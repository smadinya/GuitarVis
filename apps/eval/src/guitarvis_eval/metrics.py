"""The three numbers, and nothing that decides whether they are good enough.

Everything here counts rather than averages, so excerpts add up before
anything is divided: a 4-note excerpt must not weigh as much as a 400-note
one.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from guitarvis_core.contracts import NoteEvent, TabNote
from guitarvis_core.tabdoc import Chord

from guitarvis_eval.dataset import TruthChord, TruthNote

ONSET_TOLERANCE_SEC = 0.05
CHORD_HOP_SEC = 0.1
NO_CHORD = "N"

_PITCH_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
_LETTERS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
# Harte qualities whose third is major or minor. Everything else — sus,
# diminished, augmented, power chords, bare interval lists — has no answer in
# the analyzer's major/minor vocabulary and is left out of the score.
_MAJOR = frozenset({"maj", "maj6", "maj7", "maj9", "7", "9", "11", "13"})
_MINOR = frozenset({"min", "min6", "min7", "min9", "min11", "minmaj7"})


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


def match_notes(
    truth: Sequence[TruthNote], estimated: Sequence[TabNote] | Sequence[NoteEvent]
) -> list[tuple[int, int]]:
    """(truth index, estimate index) pairs: onset within 50ms, exact pitch,
    each note matched at most once, offsets ignored.

    mir_eval does the matching so the number is comparable with published
    transcription results. Imported here, not at module level: it is in the
    `full` extra, and oracle mode must run without it.
    """
    if not truth or not estimated:
        return []

    import mir_eval
    import numpy as np

    def intervals(
        notes: Sequence[TruthNote] | Sequence[TabNote] | Sequence[NoteEvent],
    ) -> object:
        # mir_eval rejects zero-length intervals; offsets are ignored anyway.
        return np.array([[n.onset, n.onset + max(n.duration, 1e-3)] for n in notes])

    def hertz(
        notes: Sequence[TruthNote] | Sequence[TabNote] | Sequence[NoteEvent],
    ) -> object:
        return 440.0 * 2.0 ** ((np.array([n.midi for n in notes]) - 69) / 12)

    pairs = mir_eval.transcription.match_notes(
        intervals(truth),
        hertz(truth),
        intervals(estimated),
        hertz(estimated),
        onset_tolerance=ONSET_TOLERANCE_SEC,
        pitch_tolerance=50.0,  # cents: under a semitone, so pitch must be exact
        offset_ratio=None,
    )
    return [(int(t), int(e)) for t, e in pairs]


def reduce_chord(label: str) -> str | None:
    """A Harte label in the analyzer's vocabulary — "C#", "C#m", or NO_CHORD.

    None means the chord has no major/minor reading and is excluded from the
    score, rather than counted against an analyzer that cannot express it.
    """
    if label == NO_CHORD:
        return NO_CHORD
    if label == "X":
        return None
    root, _, rest = label.partition(":")
    quality = rest.split("(")[0].split("/")[0] if rest else "maj"
    if quality in _MAJOR:
        suffix = ""
    elif quality in _MINOR:
        suffix = "m"
    else:
        return None

    pitch_class = _LETTERS[root[0]] + root[1:].count("#") - root[1:].count("b")
    return _PITCH_NAMES[pitch_class % 12] + suffix


def chord_tally(
    truth: Sequence[TruthChord],
    predicted: Sequence[Chord],
    duration: float,
    hop: float = CHORD_HOP_SEC,
) -> Tally:
    """Frame-wise agreement on a `hop` grid, over the frames whose truth is in
    the analyzer's vocabulary. Frames with no chord on either side agree."""
    correct = total = 0
    for frame in range(round(duration / hop)):
        t = frame * hop
        expected = reduce_chord(_label_at(truth, t))
        if expected is None:
            continue
        actual = next((c.symbol for c in predicted if c.t <= t < c.t + c.dur), NO_CHORD)
        total += 1
        correct += actual == expected
    return Tally(correct, total)


def _label_at(chords: Sequence[TruthChord], t: float) -> str:
    return next((c.label for c in chords if c.start <= t < c.end), NO_CHORD)
