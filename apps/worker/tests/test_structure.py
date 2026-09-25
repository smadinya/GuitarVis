"""Stage 3's pure logic: bar numbering, chord templates, and run merging."""

import math

from guitarvis_worker.stages.structure import (
    MIN_CHORD_CONFIDENCE,
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
