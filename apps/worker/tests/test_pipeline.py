"""The orchestrator and the degradation ladder.

Every stage is stubbed. What is under test is what happens when one of them
fails: the design's promise is that only "no usable guitar audio" fails a job.
"""

import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from guitarvis_core.contracts import (
    FailureReason,
    FretboardResult,
    IngestedAudio,
    NoteEvent,
    PipelineError,
    SeparationProgress,
    SeparationResult,
    StructureResult,
    TabNote,
)
from guitarvis_core.tabdoc import Beat, Chord, TabDocument, Timing
from guitarvis_worker.pipeline import PipelineResult, StageProgress, run_pipeline


class StubSeparator:
    def __init__(
        self, warnings: list[str] | None = None, fractions: Sequence[float] = ()
    ) -> None:
        self.warnings = warnings or []
        self.fractions = list(fractions)

    def isolate(
        self, audio_path: Path, *, progress: SeparationProgress | None = None
    ) -> SeparationResult:
        if progress is not None:
            for fraction in self.fractions:
                progress(fraction)
        return SeparationResult(stem_path=audio_path, warnings=list(self.warnings))


class FailingSeparator:
    def isolate(
        self, audio_path: Path, *, progress: SeparationProgress | None = None
    ) -> SeparationResult:
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
    def __init__(
        self, notes: Sequence[TabNote] = (), warnings: Sequence[str] = ()
    ) -> None:
        self.notes = list(notes)
        self.warnings = list(warnings)

    def assign(
        self, notes: Sequence[NoteEvent], tuning: Sequence[str]
    ) -> FretboardResult:
        return FretboardResult(notes=list(self.notes), warnings=list(self.warnings))


class FailingMapper:
    def assign(
        self, notes: Sequence[NoteEvent], tuning: Sequence[str]
    ) -> FretboardResult:
        raise RuntimeError("no fingering search today")


def audio(tmp_path: Path) -> IngestedAudio:
    path = tmp_path / "song.wav"
    path.write_bytes(b"")
    return IngestedAudio(path=path, title="song", duration_sec=10.0)


def run(tmp_path: Path, **overrides: Any) -> TabDocument:
    return run_result(tmp_path, **overrides).document


def run_result(tmp_path: Path, **overrides: Any) -> PipelineResult:
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


EVERY_STAGE_STARTS = [
    ("separation", 0),
    ("transcription", 40),
    ("structure", 65),
    ("fretboard", 80),
    ("fretboard", 100),
]


def test_reports_each_stage_as_it_starts_then_100(tmp_path: Path) -> None:
    seen: list[StageProgress] = []
    run(tmp_path, progress=seen.append)

    assert [(p.stage, p.percent) for p in seen] == EVERY_STAGE_STARTS


def test_progress_still_reports_when_stages_degrade(tmp_path: Path) -> None:
    seen: list[StageProgress] = []
    run(
        tmp_path,
        analyzer=FailingAnalyzer(),
        mapper=FailingMapper(),
        progress=seen.append,
    )

    assert [(p.stage, p.percent) for p in seen] == EVERY_STAGE_STARTS


def test_separation_progress_moves_within_its_band(tmp_path: Path) -> None:
    seen: list[StageProgress] = []
    run(
        tmp_path,
        separator=StubSeparator(fractions=[0.25, 0.5, 1.0]),
        progress=seen.append,
    )

    assert [(p.stage, p.percent) for p in seen if p.stage == "separation"] == [
        ("separation", 0),
        ("separation", 10),
        ("separation", 20),
        ("separation", 40),
    ]
    assert seen[-1] == StageProgress(stage="fretboard", percent=100)


def test_progress_is_monotonic_whatever_the_separator_reports(tmp_path: Path) -> None:
    seen: list[StageProgress] = []
    run(
        tmp_path,
        separator=StubSeparator(fractions=[0.5, 0.2, 0.5, 1.7, math.nan, -1.0, 0.9]),
        progress=seen.append,
    )

    percents = [p.percent for p in seen]
    assert percents == sorted(percents)
    # 0.2 and the second 0.5 would not raise the percent; 1.7 is clamped to
    # the band's top; NaN and -1 are ignored; 0.9 arrives after 40 already has.
    assert [p.percent for p in seen if p.stage == "separation"] == [0, 20, 40]


def test_a_separator_that_reports_nothing_still_reaches_100(tmp_path: Path) -> None:
    seen: list[StageProgress] = []
    run(tmp_path, separator=StubSeparator(fractions=[]), progress=seen.append)

    assert seen[-1].percent == 100


def test_audio_url_replaces_the_file_uri(tmp_path: Path) -> None:
    result = run_pipeline(
        audio(tmp_path),
        separator=StubSeparator(),
        transcriber=StubTranscriber(),
        analyzer=StubAnalyzer(),
        mapper=StubMapper(),
        audio_url="/jobs/abc/audio/mix",
    )

    assert result.document.source.audio_url == "/jobs/abc/audio/mix"


def test_an_invariant_failure_never_reports_100(tmp_path: Path) -> None:
    seen: list[StageProgress] = []
    with pytest.raises(PipelineError):
        run(
            tmp_path,
            transcriber=StubTranscriber([NoteEvent(1.0, 0.5, 53, 0.8)]),
            mapper=StubMapper([TabNote(1.0, 0.5, 53, 2, 2, 0.8)]),
            progress=seen.append,
        )

    assert seen[-1] == StageProgress(stage="fretboard", percent=80)


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


def test_fretboard_failure_degrades_instead_of_failing(tmp_path: Path) -> None:
    doc = run(
        tmp_path,
        transcriber=StubTranscriber([NoteEvent(1.0, 0.5, 52, 0.8)]),
        mapper=FailingMapper(),
    )

    assert doc.notes == []
    assert any("fretboard assignment failed" in w.lower() for w in doc.warnings)
    # The fretboard warning must speak only about notes: stage 4 failing
    # says nothing about whether stage 3 (timing, chords) succeeded.
    assert not any("unaffected" in w.lower() for w in doc.warnings)


def test_a_mapper_raising_not_implemented_degrades_like_any_other_failure(
    tmp_path: Path,
) -> None:
    # 003's review notes: a real mapper may raise NotImplementedError for a
    # genuinely unsupported case. It must degrade, not be mistaken for a stub.
    class Unsupported:
        def assign(
            self, notes: Sequence[NoteEvent], tuning: Sequence[str]
        ) -> FretboardResult:
            raise NotImplementedError("exotic tuning")

    doc = run(
        tmp_path,
        transcriber=StubTranscriber([NoteEvent(1.0, 0.5, 52, 0.8)]),
        mapper=Unsupported(),
    )
    assert doc.notes == []
    assert any("NotImplementedError" in w for w in doc.warnings)


def test_fretboard_warnings_reach_the_document(tmp_path: Path) -> None:
    doc = run(
        tmp_path,
        transcriber=StubTranscriber([NoteEvent(1.0, 0.5, 52, 0.8)]),
        mapper=StubMapper(
            [TabNote(1.0, 0.5, 52, 2, 2, 0.8)],
            warnings=["1 note outside the guitar's range was dropped."],
        ),
    )

    assert len(doc.notes) == 1
    assert "1 note outside the guitar's range was dropped." in doc.warnings


def test_transcribed_note_count_survives_a_fretboard_failure(
    tmp_path: Path,
) -> None:
    result = run_result(
        tmp_path,
        transcriber=StubTranscriber(
            [NoteEvent(1.0, 0.5, 52, 0.8), NoteEvent(2.0, 0.5, 55, 0.7)]
        ),
        mapper=FailingMapper(),
    )

    assert result.transcribed_note_count == 2
    assert result.document.notes == []


def test_transcribed_note_count_is_zero_on_transcription_failure(
    tmp_path: Path,
) -> None:
    result = run_result(tmp_path, transcriber=FailingTranscriber())
    assert result.transcribed_note_count == 0


def test_structure_warnings_reach_the_document(tmp_path: Path) -> None:
    # Each half of stage 3 fails independently and produces its own
    # document warning, distinct from the analyze()-raised-entirely backstop.
    doc = run(
        tmp_path,
        analyzer=StubAnalyzer(
            StructureResult(
                timing=Timing(),
                chords=[],
                sections=[],
                warnings=[
                    "Beat tracking failed (RuntimeError), so bar lines are "
                    "unavailable.",
                    "Chord detection failed (RuntimeError), so the chord "
                    "track is unavailable.",
                ],
            )
        ),
    )

    assert any("beat tracking failed" in w.lower() for w in doc.warnings)
    assert any("chord detection failed" in w.lower() for w in doc.warnings)


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


def test_a_note_violating_the_invariant_is_rejected(tmp_path: Path) -> None:
    # String 2 (D3=50) fret 2 sounds 52, so a mapper claiming 53 is broken
    with pytest.raises(PipelineError) as excinfo:
        run(
            tmp_path,
            transcriber=StubTranscriber([NoteEvent(1.0, 0.5, 53, 0.8)]),
            mapper=StubMapper([TabNote(1.0, 0.5, 53, 2, 2, 0.8)]),
        )
    assert excinfo.value.reason is FailureReason.INTERNAL


@pytest.mark.parametrize(
    "tab",
    [
        TabNote(1.0, 0.5, 52, 9, 2, 0.8),  # no string 9 on a six-string
        TabNote(1.0, 0.5, 52, 2, -1, 0.8),  # no fret below the nut
    ],
)
def test_a_note_off_the_neck_is_rejected(tmp_path: Path, tab: TabNote) -> None:
    with pytest.raises(PipelineError) as excinfo:
        run(
            tmp_path,
            transcriber=StubTranscriber([NoteEvent(1.0, 0.5, 52, 0.8)]),
            mapper=StubMapper([tab]),
        )
    assert excinfo.value.reason is FailureReason.INTERNAL
