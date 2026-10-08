"""Full mode: matching estimated notes to truth, chord scoring, and the
end-to-end scorer with stub stages."""

from pathlib import Path

import pytest
from guitarset_fixture import write_jams
from guitarvis_core.contracts import NoteEvent, StructureResult, TabNote
from guitarvis_core.tabdoc import Chord, Timing
from guitarvis_eval.dataset import TruthChord, TruthNote, read_jams
from guitarvis_eval.metrics import (
    NoteCounts,
    Tally,
    chord_tally,
    match_notes,
    reduce_chord,
)
from guitarvis_eval.runner import score_full, summarize
from guitarvis_worker.stages.fretboard import ViterbiFretboardMapper


@pytest.mark.parametrize(
    ("label", "reduced"),
    [
        ("D#:maj", "D#"),
        ("G#:maj6(*5)/1", "G#"),
        ("A:7", "A"),
        ("C:maj7/3", "C"),
        ("F#:min7", "F#m"),
        ("Bb:min", "A#m"),  # flats spelled as the analyzer's sharps
        ("E", "E"),  # Harte shorthand: a bare root is major
        ("N", "N"),
        ("D#:sus2(7)/1", None),  # no third: out of vocabulary
        ("B:hdim7", None),
        ("G:(1,5)/1", None),  # power chord
        ("X", None),
    ],
)
def test_reduce_chord_to_the_analyzer_vocabulary(
    label: str, reduced: str | None
) -> None:
    assert reduce_chord(label) == reduced


def test_chord_tally_is_frame_wise() -> None:
    truth = [TruthChord(0.0, 1.0, "A:min"), TruthChord(1.0, 2.0, "C:maj")]
    predicted = [Chord(t=0.0, dur=1.5, symbol="Am", confidence=0.9)]

    # 20 frames: 0.0 to 0.9 Am right, 1.0 to 1.4 predicted Am vs C wrong,
    # 1.5 to 1.9 predicted nothing vs C wrong.
    assert chord_tally(truth, predicted, duration=2.0) == Tally(correct=10, total=20)


def test_chord_tally_skips_out_of_vocabulary_frames() -> None:
    truth = [TruthChord(0.0, 1.0, "D:sus4")]
    assert chord_tally(truth, [], duration=1.0) == Tally(0, 0)
    assert Tally(0, 0).rate is None


def test_no_chord_frames_count_when_nothing_is_predicted() -> None:
    assert chord_tally([], [], duration=0.5) == Tally(correct=5, total=5)


def test_match_notes_needs_onset_within_50ms_and_the_exact_pitch() -> None:
    pytest.importorskip("mir_eval")
    truth = [TruthNote(0.0, 0.5, 60, 4), TruthNote(1.0, 0.5, 62, 4)]
    estimated = [
        TabNote(0.04, 0.3, 60, 4, 1, 0.9),  # 40ms late: a hit
        TabNote(1.0, 0.3, 63, 4, 4, 0.9),  # a semitone off: a miss
    ]
    assert match_notes(truth, estimated) == [(0, 0)]


def test_match_notes_with_nothing_to_match() -> None:
    assert match_notes([], [TabNote(0.0, 0.5, 60, 4, 1, 0.9)]) == []
    assert match_notes([TruthNote(0.0, 0.5, 60, 4)], []) == []


class EchoTranscriber:
    """Returns fixed notes, as if transcription were perfect or not."""

    def __init__(self, events: list[NoteEvent]) -> None:
        self.events = events
        self.seen: list[Path] = []

    def transcribe(self, stem_path: Path) -> list[NoteEvent]:
        self.seen.append(stem_path)
        return list(self.events)


class FixedAnalyzer:
    def __init__(self, chords: list[Chord]) -> None:
        self.chords = chords

    def analyze(self, stem_path: Path, mix_path: Path) -> StructureResult:
        assert stem_path == mix_path  # no separation: the recording is both
        return StructureResult(timing=Timing(), chords=self.chords, sections=[])


def test_score_full_with_stub_stages(tmp_path: Path) -> None:
    pytest.importorskip("mir_eval")
    excerpt = read_jams(
        write_jams(
            tmp_path,
            "05_a_comp",
            notes=[(0.0, 0.5, 40.0, 0), (1.0, 0.5, 45.0, 1)],
            performed=[(0.0, 1.0, "E:min")],
            duration=1.0,
        )
    )
    audio = tmp_path / "05_a_comp_mic.wav"
    transcriber = EchoTranscriber(
        [NoteEvent(0.01, 0.5, 40, 0.9), NoteEvent(0.5, 0.5, 70, 0.9)]
    )

    score = score_full(
        excerpt,
        audio,
        transcriber=transcriber,
        analyzer=FixedAnalyzer([Chord(t=0.0, dur=1.0, symbol="Em", confidence=0.9)]),
        mapper=ViterbiFretboardMapper(),
    )

    assert transcriber.seen == [audio]
    assert score.notes == NoteCounts(matched=1, truth=2, estimated=2)
    assert score.strings == Tally(1, 1)  # E2 on the low string
    assert score.chords == Tally(10, 10)
    assert "note" in summarize([score])["all"]  # type: ignore[operator]


def test_full_mode_without_mir_eval_says_what_to_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import builtins
    from typing import Any

    from guitarvis_eval.__main__ import main

    real_import = builtins.__import__

    def no_mir_eval(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "mir_eval":
            raise ImportError("No module named 'mir_eval'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_mir_eval)
    write_jams(tmp_path / "annotation", "05_a_comp")

    code = main(["--full", "--data-dir", str(tmp_path), "--out", str(tmp_path / "out")])

    assert code == 1
    assert "uv sync --extra eval-full" in capsys.readouterr().err


def test_note_f1_measures_the_transcriber_not_the_mapper(tmp_path: Path) -> None:
    # A perfect transcription of two notes no hand can hold together: the
    # mapper drops one, but the transcriber got both right.
    excerpt = read_jams(
        write_jams(
            tmp_path, "05_a_comp", notes=[(0.0, 0.5, 41.0, 0), (0.0, 0.5, 84.0, 5)]
        )
    )
    score = score_full(
        excerpt,
        tmp_path / "05_a_comp_mic.wav",
        transcriber=EchoTranscriber(
            [NoteEvent(0.0, 0.5, 41, 0.9), NoteEvent(0.0, 0.5, 84, 0.8)]
        ),
        analyzer=FixedAnalyzer([]),
        mapper=ViterbiFretboardMapper(),
    )

    assert score.notes == NoteCounts(matched=2, truth=2, estimated=2)
    assert score.strings == Tally(correct=1, total=1)  # only the placed note


def test_full_mode_checks_every_audio_file_before_transcribing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import guitarvis_worker.stages.structure as structure
    import guitarvis_worker.stages.transcription as transcription
    from guitarvis_eval.__main__ import main

    echo = EchoTranscriber([])
    monkeypatch.setattr(transcription, "BasicPitchTranscriber", lambda: echo)
    monkeypatch.setattr(
        structure, "LibrosaStructureAnalyzer", lambda: FixedAnalyzer([])
    )
    write_jams(tmp_path / "annotation", "05_a_comp")
    write_jams(tmp_path / "annotation", "05_b_solo")
    (tmp_path / "audio_mono-mic").mkdir()
    (tmp_path / "audio_mono-mic" / "05_a_comp_mic.wav").write_bytes(b"")

    code = main(["--full", "--data-dir", str(tmp_path), "--out", str(tmp_path / "out")])

    assert code == 1
    assert echo.seen == []  # nothing transcribed before the missing file was found
    assert "05_b_solo_mic.wav" in capsys.readouterr().err
