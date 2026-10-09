"""Confidence bands and the threshold rule, from hand-built tallies: no
audio, no mir_eval."""

import pytest
from guitarvis_core.contracts import NoteEvent
from guitarvis_eval.calibration import (
    BANDS,
    ConfidenceBands,
    band_of,
    confidence_bands,
    threshold,
)
from guitarvis_eval.metrics import Tally
from guitarvis_eval.runner import ExcerptScore, score_to_dict, summarize


def bands(*rows: tuple[int, int]) -> ConfidenceBands:
    """(estimated, matched) for bands 0, 1, 2, ...; the rest are empty."""
    padded = list(rows) + [(0, 0)] * (BANDS - len(rows))
    return ConfidenceBands(tuple(e for e, _ in padded), tuple(m for _, m in padded))


def note(confidence: float) -> NoteEvent:
    return NoteEvent(onset=0.0, duration=0.5, midi=60, confidence=confidence)


@pytest.mark.parametrize(
    ("confidence", "band"),
    [(0.0, 0), (0.09, 0), (0.1, 1), (0.3, 3), (0.45, 4), (0.99, 9), (1.0, 9)],
)
def test_band_of(confidence: float, band: int) -> None:
    assert band_of(confidence) == band


def test_confidence_bands_tally_estimates_and_matches() -> None:
    estimated = [note(0.31), note(0.35), note(0.72), note(0.95)]

    tally = confidence_bands(estimated, matched={1, 3})

    assert tally.estimated == (0, 0, 0, 2, 0, 0, 0, 1, 0, 1)
    assert tally.matched == (0, 0, 0, 1, 0, 0, 0, 0, 0, 1)
    assert tally.precision(3) == 0.5
    assert tally.precision(0) is None


def test_bands_add_up() -> None:
    total = bands((2, 1)) + bands((4, 3), (1, 1))

    assert total.estimated[:2] == (6, 1)
    assert total.matched[:2] == (4, 1)


def test_threshold_is_the_lowest_edge_with_everything_above_it_precise() -> None:
    # Precision by band: 0.2, 0.3, 0.45, 0.55, 0.6, 0.7, 0.85, 0.9, 0.95.
    tally = bands(
        (100, 20), (100, 30), (100, 45), (100, 55), (100, 60),
        (100, 70), (100, 85), (100, 90), (100, 95),
    )  # fmt: skip

    assert threshold(tally, 0.5) == 0.3
    assert threshold(tally, 0.8) == 0.6


def test_a_dip_above_a_good_band_raises_the_threshold() -> None:
    tally = bands((100, 10), (100, 60), (100, 40), (100, 70))

    assert threshold(tally, 0.5) == 0.3


def test_bands_with_too_few_notes_are_ignored() -> None:
    # Band 1 is bad but holds only 10 notes; band 2 holds 49.
    tally = bands((100, 10), (10, 0), (49, 0), (100, 60))

    assert threshold(tally, 0.5) == 0.1


def test_every_band_precise_means_nothing_is_below_the_threshold() -> None:
    assert threshold(bands((100, 90), (100, 95)), 0.5) == 0.0


def test_no_supporting_measurement_gives_no_threshold() -> None:
    assert threshold(bands((100, 10), (100, 40)), 0.5) is None
    assert threshold(bands((10, 10)), 0.5) is None
    assert threshold(ConfidenceBands(), 0.5) is None


def test_the_summary_carries_bands_and_each_excerpt_does_not() -> None:
    score = ExcerptScore(
        name="05_a_comp",
        style="comp",
        strings=Tally(),
        confidence=bands((0, 0), (0, 0), (0, 0), (4, 1)),
    )

    summary = summarize([score])["all"]
    excerpt = score_to_dict(score)

    assert isinstance(summary, dict)
    by_band = summary["precision_by_confidence"]
    assert list(by_band) == [f"0.{n}" for n in range(10)]
    assert by_band["0.3"] == {"estimated": 4, "matched": 1, "precision": 0.25}
    assert by_band["0.0"] == {"estimated": 0, "matched": 0, "precision": None}
    assert "precision_by_confidence" not in excerpt
