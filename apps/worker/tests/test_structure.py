"""Stage 3's pure logic: bar numbering, chord templates, and run merging.

The independent-degradation tests below stub `_track_beats`/`_detect_chords`
rather than monkeypatching librosa itself: librosa is not installed under the
default `uv sync` (it lives behind the worker's `ml` extra), so patching its
module-level functions is not a seam available here. Overriding the private
method is the same seam `test_transcription.py` already uses for
`BasicPitchTranscriber._predict`.
"""

import math
from collections.abc import Sequence
from pathlib import Path

from guitarvis_core.tabdoc import Beat, Chord, Timing
from guitarvis_worker.stages.structure import (
    MIN_CHORD_CONFIDENCE,
    LibrosaStructureAnalyzer,
    beats_to_events,
    chord_templates,
    merge_chords,
)


def test_beats_are_numbered_into_bars() -> None:
    beats = beats_to_events([0.0, 0.5, 1.0, 1.5, 2.0], beats_per_bar=4)
    assert [(b.bar, b.beat) for b in beats] == [(1, 1), (1, 2), (1, 3), (1, 4), (2, 1)]
    assert beats[0].t == 0.0


def test_no_beats_yields_no_events() -> None:
    assert beats_to_events([]) == []


def test_templates_cover_every_major_and_minor_triad() -> None:
    names = [name for name, _ in chord_templates()]
    assert len(names) == 24
    assert "C" in names and "Am" in names and "F#m" in names


def test_templates_are_unit_vectors() -> None:
    for _, vector in chord_templates():
        assert math.isclose(math.sqrt(sum(v * v for v in vector)), 1.0, abs_tol=1e-9)


def test_c_major_template_is_c_e_g() -> None:
    template = dict(chord_templates())["C"]
    assert {i for i, v in enumerate(template) if v > 0} == {0, 4, 7}


def test_a_minor_template_is_a_c_e() -> None:
    template = dict(chord_templates())["Am"]
    assert {i for i, v in enumerate(template) if v > 0} == {9, 0, 4}


def test_repeated_labels_collapse_into_one_chord() -> None:
    chords = merge_chords(
        symbols=["Am", "Am", "G", "G", "G"],
        times=[0.0, 1.0, 2.0, 3.0, 4.0],
        confidences=[0.9, 0.8, 0.7, 0.9, 0.8],
        end_time=5.0,
    )
    assert [(c.symbol, c.t, c.dur) for c in chords] == [
        ("Am", 0.0, 2.0),
        ("G", 2.0, 3.0),
    ]


def test_merged_confidence_is_the_mean() -> None:
    chords = merge_chords(["Am", "Am"], [0.0, 1.0], [0.6, 0.8], end_time=2.0)
    assert math.isclose(chords[0].confidence, 0.7, abs_tol=1e-9)


def test_unlabelled_segments_are_skipped() -> None:
    chords = merge_chords(["Am", None, "G"], [0.0, 1.0, 2.0], [0.9, 0.0, 0.8], 3.0)
    assert [c.symbol for c in chords] == ["Am", "G"]


def test_confidence_threshold_is_a_real_threshold() -> None:
    assert 0.0 < MIN_CHORD_CONFIDENCE < 1.0


def test_a_beat_time_past_the_decoded_duration_does_not_raise() -> None:
    # A librosa beat time that overshoots the decoded duration by a frame
    # would otherwise make `dur` negative and fail Chord's `ge=0`.
    chords = merge_chords(
        symbols=["Am"],
        times=[9.9],
        confidences=[0.9],
        end_time=9.8,  # earlier than the chord's own start
    )
    assert chords[0].dur == 0.0


class BeatsFailAnalyzer(LibrosaStructureAnalyzer):
    """Beat tracking always raises; chord detection is stubbed to prove it
    still ran."""

    def _track_beats(self, mix_path: Path) -> tuple[Timing, list[float]]:
        raise RuntimeError("beat tracker exploded")

    def _detect_chords(
        self, stem_path: Path, beat_times: Sequence[float]
    ) -> list[Chord]:
        return [Chord(t=0.0, dur=1.0, symbol="Am", confidence=0.9)]


class ChordsFailAnalyzer(LibrosaStructureAnalyzer):
    """Chord detection always raises; beat tracking is stubbed to prove it
    still ran."""

    def _track_beats(self, mix_path: Path) -> tuple[Timing, list[float]]:
        return (
            Timing(beats=[Beat(t=0.0, bar=1, beat=1)], tempo_bpm_avg=120.0),
            [0.0, 0.5],
        )

    def _detect_chords(
        self, stem_path: Path, beat_times: Sequence[float]
    ) -> list[Chord]:
        raise RuntimeError("chord detector exploded")


def test_beat_tracking_failure_still_yields_chords(tmp_path: Path) -> None:
    result = BeatsFailAnalyzer().analyze(tmp_path / "stem.wav", tmp_path / "mix.wav")

    assert result.timing.beats == []
    assert result.timing.tempo_bpm_avg is None
    assert [c.symbol for c in result.chords] == ["Am"]
    assert len(result.warnings) == 1
    assert "beat tracking failed" in result.warnings[0].lower()
    assert "RuntimeError" in result.warnings[0]


def test_chord_detection_failure_still_yields_beats(tmp_path: Path) -> None:
    result = ChordsFailAnalyzer().analyze(tmp_path / "stem.wav", tmp_path / "mix.wav")

    assert result.chords == []
    assert result.timing.tempo_bpm_avg == 120.0
    assert [b.bar for b in result.timing.beats] == [1]
    assert len(result.warnings) == 1
    assert "chord detection failed" in result.warnings[0].lower()
    assert "RuntimeError" in result.warnings[0]


class BothFailAnalyzer(LibrosaStructureAnalyzer):
    """Both halves raise independently: each must produce its own warning."""

    def _track_beats(self, mix_path: Path) -> tuple[Timing, list[float]]:
        raise RuntimeError("beat tracker exploded")

    def _detect_chords(
        self, stem_path: Path, beat_times: Sequence[float]
    ) -> list[Chord]:
        raise ValueError("chord detector exploded")


def test_both_halves_failing_produce_two_distinct_warnings(tmp_path: Path) -> None:
    result = BothFailAnalyzer().analyze(tmp_path / "stem.wav", tmp_path / "mix.wav")

    assert len(result.warnings) == 2
    assert any("beat tracking failed" in w.lower() for w in result.warnings)
    assert any("chord detection failed" in w.lower() for w in result.warnings)
