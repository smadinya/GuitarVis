"""The three numbers, and nothing that decides whether they are good enough.

Everything here counts rather than averages, so excerpts add up before
anything is divided: a 4-note excerpt must not weigh as much as a 400-note
one.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from guitarvis_core.contracts import TabNote

from guitarvis_eval.dataset import TruthNote


@dataclass(frozen=True)
class Tally:
    correct: int = 0
    total: int = 0

    def __add__(self, other: "Tally") -> "Tally":
        return Tally(self.correct + other.correct, self.total + other.total)

    @property
    def rate(self) -> float | None:
        return self.correct / self.total if self.total else None


@dataclass(frozen=True)
class NoteCounts:
    matched: int = 0
    truth: int = 0
    estimated: int = 0

    def __add__(self, other: "NoteCounts") -> "NoteCounts":
        return NoteCounts(
            self.matched + other.matched,
            self.truth + other.truth,
            self.estimated + other.estimated,
        )

    @property
    def precision(self) -> float | None:
        return self.matched / self.estimated if self.estimated else None

    @property
    def recall(self) -> float | None:
        return self.matched / self.truth if self.truth else None

    @property
    def f1(self) -> float | None:
        if not self.truth and not self.estimated:
            return None
        return 2 * self.matched / (self.truth + self.estimated)


def oracle_string_tally(truth: Sequence[TruthNote], placed: Sequence[TabNote]) -> Tally:
    """Oracle mode: the mapper saw exactly the truth's onsets and pitches.

    Pair by (onset, pitch). A truth note the mapper dropped has no partner
    and counts as wrong: dropping a note is not a way to score better.
    """
    strings: dict[tuple[float, int], list[int]] = defaultdict(list)
    for tab in placed:
        strings[(tab.onset, tab.midi)].append(tab.string)

    correct = 0
    for note in truth:
        candidates = strings.get((note.onset, note.midi), [])
        if note.string in candidates:
            candidates.remove(note.string)
            correct += 1
    return Tally(correct, len(truth))
