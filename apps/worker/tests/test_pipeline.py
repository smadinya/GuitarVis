"""The orchestrator and the degradation ladder.

Every stage is stubbed. What is under test is what happens when one of them
fails: the design's promise is that only "no usable guitar audio" fails a job.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from guitarvis_core.contracts import (
    FailureReason,
    IngestedAudio,
    NoteEvent,
    PipelineError,
    SeparationResult,
    StructureResult,
    TabNote,
)
from guitarvis_core.tabdoc import Beat, Chord, TabDocument, Timing
from guitarvis_worker.pipeline import StageProgress, run_pipeline


class StubSeparator:
    def __init__(self, warnings: list[str] | None = None) -> None:
        self.warnings = warnings or []

    def isolate(self, audio_path: Path) -> SeparationResult:
        return SeparationResult(stem_path=audio_path, warnings=list(self.warnings))


class FailingSeparator:
    def isolate(self, audio_path: Path) -> SeparationResult:
        raise PipelineError(FailureReason.NO_GUITAR_DETECTED, "No clear guitar part")


class StubTranscriber:
    def __init__(self, events: Sequence[NoteEvent] = ()) -> None:
        self.events = list(events)

    def transcribe(self, stem_path: Path) -> list[NoteEvent]:
        return list(self.events)


class FailingTranscriber:
    def transcribe(self, stem_path: Path) -> list[NoteEvent]:
        raise RuntimeError("model failed to load")


class StubAnalyzer:
    def __init__(self, result: StructureResult | None = None) -> None:
        self.result = result or StructureResult(timing=Timing(), chords=[], sections=[])

    def analyze(self, stem_path: Path, mix_path: Path) -> StructureResult:
        return self.result


class FailingAnalyzer:
    def analyze(self, stem_path: Path, mix_path: Path) -> StructureResult:
        raise RuntimeError("beat tracker exploded")


class StubMapper:
    def __init__(self, notes: Sequence[TabNote] = ()) -> None:
        self.notes = list(notes)

    def assign(
        self, notes: Sequence[NoteEvent], tuning: Sequence[str]
    ) -> list[TabNote]:
        return list(self.notes)


class UnimplementedMapper:
    """Stage 4 as it stands until 004-fretboard-mapper lands."""

    def assign(
        self, notes: Sequence[NoteEvent], tuning: Sequence[str]
    ) -> list[TabNote]:
        raise NotImplementedError("Stage 4 lands in 004-fretboard-mapper")


def audio(tmp_path: Path) -> IngestedAudio:
    path = tmp_path / "song.wav"
    path.write_bytes(b"")
    return IngestedAudio(path=path, title="song", duration_sec=10.0)


def run(tmp_path: Path, **overrides: Any) -> TabDocument:
    kwargs: dict[str, Any] = {
        "separator": StubSeparator(),
        "transcriber": StubTranscriber(),
        "analyzer": StubAnalyzer(),
        "mapper": StubMapper(),
    }
    kwargs.update(overrides)
    return run_pipeline(audio(tmp_path), **kwargs)


def test_produces_a_valid_document(tmp_path: Path) -> None:
    doc = run(
        tmp_path,
        transcriber=StubTranscriber([NoteEvent(1.0, 0.5, 52, 0.8)]),
        # D3 open is 50, so fret 2 is 52 — the invariant holds
        mapper=StubMapper([TabNote(1.0, 0.5, 52, 2, 2, 0.8)]),
        analyzer=StubAnalyzer(
            StructureResult(
                timing=Timing(beats=[Beat(t=0.0, bar=1, beat=1)], tempo_bpm_avg=120.0),
                chords=[Chord(t=0.0, dur=2.0, symbol="Am", confidence=0.9)],
                sections=[],
            )
        ),
    )

    assert doc.source.title == "song"
    assert doc.source.audio_url.startswith("file://")
    assert [(n.string, n.fret) for n in doc.notes] == [(2, 2)]
    assert doc.notes[0].id == "n_0000"
    assert doc.chords[0].symbol == "Am"
    assert doc.timing.tempo_bpm_avg == 120.0


def test_reports_progress_for_every_stage(tmp_path: Path) -> None:
    seen: list[StageProgress] = []
    run(tmp_path, progress=seen.append)

    assert [p.stage for p in seen] == [
        "separation",
        "transcription",
        "structure",
        "fretboard",
    ]
    assert [p.percent for p in seen] == [40, 65, 80, 100]


def test_no_guitar_is_the_only_hard_failure(tmp_path: Path) -> None:
    with pytest.raises(PipelineError) as excinfo:
        run(tmp_path, separator=FailingSeparator())
    assert excinfo.value.reason is FailureReason.NO_GUITAR_DETECTED


def test_structure_failure_degrades_instead_of_failing(tmp_path: Path) -> None:
    doc = run(
        tmp_path,
        transcriber=StubTranscriber([NoteEvent(1.0, 0.5, 52, 0.8)]),
        mapper=StubMapper([TabNote(1.0, 0.5, 52, 2, 2, 0.8)]),
        analyzer=FailingAnalyzer(),
    )

    assert len(doc.notes) == 1  # notes keep their own onsets and survive
    assert doc.timing.beats == []
    assert doc.chords == []
    assert any("bar lines" in w for w in doc.warnings)


def test_unimplemented_fretboard_stage_degrades(tmp_path: Path) -> None:
    doc = run(
        tmp_path,
        transcriber=StubTranscriber([NoteEvent(1.0, 0.5, 52, 0.8)]),
        mapper=UnimplementedMapper(),
    )

    assert doc.notes == []
    assert any("fretboard" in w.lower() for w in doc.warnings)


def test_separation_warnings_reach_the_document(tmp_path: Path) -> None:
    doc = run(tmp_path, separator=StubSeparator(["used the 4-stem track"]))
    assert "used the 4-stem track" in doc.warnings


def test_empty_transcription_warns_but_still_returns_a_document(tmp_path: Path) -> None:
    doc = run(tmp_path, transcriber=StubTranscriber([]))
    assert doc.notes == []
    assert any("no notes" in w.lower() for w in doc.warnings)


def test_transcription_failure_degrades_instead_of_failing(tmp_path: Path) -> None:
    doc = run(tmp_path, transcriber=FailingTranscriber())
    assert doc.notes == []
    assert any("transcription failed" in w.lower() for w in doc.warnings)
    # A raised exception is distinguishable from a genuinely empty result: the
    # empty-result warning is worded differently and must not also appear.
    assert "No notes were detected in the isolated guitar part." not in doc.warnings


def test_progress_still_reports_when_stages_degrade(tmp_path: Path) -> None:
    seen: list[StageProgress] = []
    run(
        tmp_path,
        analyzer=FailingAnalyzer(),
        mapper=UnimplementedMapper(),
        progress=seen.append,
    )

    assert [p.stage for p in seen] == [
        "separation",
        "transcription",
        "structure",
        "fretboard",
    ]
    assert [p.percent for p in seen] == [40, 65, 80, 100]


def test_a_note_violating_the_invariant_is_rejected(tmp_path: Path) -> None:
    # String 2 (D3=50) fret 2 sounds 52, so a mapper claiming 53 is broken
    with pytest.raises(PipelineError) as excinfo:
        run(
            tmp_path,
            transcriber=StubTranscriber([NoteEvent(1.0, 0.5, 53, 0.8)]),
            mapper=StubMapper([TabNote(1.0, 0.5, 53, 2, 2, 0.8)]),
        )
    assert excinfo.value.reason is FailureReason.INTERNAL
