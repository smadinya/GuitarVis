"""How often a note at each confidence is right, and the rule that turns
that into the client's thresholds (spec 006, "Where the thresholds come
from").

A transcribed note is "right" when match_notes pairs it with the truth.
The bands are measured like every other number here, never gated.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass

from guitarvis_core.contracts import NoteEvent

BANDS = 10  # each 0.1 wide
MIN_BAND_NOTES = 50
HIDE_PRECISION = 0.5  # below HIDE, a note is more often wrong than right
FULL_PRECISION = 0.8

_EMPTY = (0,) * BANDS


@dataclass(frozen=True)
class ConfidenceBands:
    """Band i holds confidences in [i/10, (i+1)/10); the top band takes 1.0."""

    estimated: tuple[int, ...] = _EMPTY
    matched: tuple[int, ...] = _EMPTY

    def __add__(self, other: "ConfidenceBands") -> "ConfidenceBands":
        return ConfidenceBands(
            tuple(a + b for a, b in zip(self.estimated, other.estimated, strict=True)),
            tuple(a + b for a, b in zip(self.matched, other.matched, strict=True)),
        )

    def precision(self, band: int) -> float | None:
        estimated = self.estimated[band]
        return self.matched[band] / estimated if estimated else None


def band_of(confidence: float) -> int:
    return min(max(int(confidence * BANDS), 0), BANDS - 1)


def confidence_bands(
    estimated: Sequence[NoteEvent], matched: Collection[int]
) -> ConfidenceBands:
    """Tally each estimated note by band. `matched` holds the indices into
    `estimated` that match_notes paired with a true note."""
    counts = [0] * BANDS
    hits = [0] * BANDS
    for index, note in enumerate(estimated):
        band = band_of(note.confidence)
        counts[band] += 1
        hits[band] += index in matched
    return ConfidenceBands(tuple(counts), tuple(hits))


def threshold(
    bands: ConfidenceBands,
    min_precision: float,
    min_notes: int = MIN_BAND_NOTES,
) -> float | None:
    """The lower edge of the lowest band such that every band at or above
    it, among bands holding at least `min_notes` notes, has precision of at
    least `min_precision`.

    None when the measurement cannot support a threshold: no band holds
    enough notes, or the highest one that does falls short.
    """
    supported = [b for b in range(BANDS) if bands.estimated[b] >= min_notes]
    if not supported:
        return None
    failing = [b for b in supported if (bands.precision(b) or 0.0) < min_precision]
    if not failing:
        return 0.0
    lowest = max(failing) + 1
    if lowest > max(supported):
        return None
    return lowest / BANDS
