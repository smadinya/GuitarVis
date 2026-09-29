"""Stage 4 — fretboard assignment. The deterministic core.

Notes within 50ms of a voicing's first note group into that voicing; each
voicing has a set of playable fingerings filtered by physical constraints; a
Viterbi pass minimises total cost, dominated by hand-position movement between
consecutive voicings because real players stay put.

Testable without audio: feed note sequences, assert fingerings. Every note it
emits must satisfy guitarvis_core.fretboard.check_invariant — a note that
cannot be placed correctly is dropped with a warning, never approximated.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING

from guitarvis_core.contracts import FretboardResult, NoteEvent, TabNote
from guitarvis_core.fretboard import parse_pitch

VOICING_WINDOW_SEC = 0.05
FINGERS_BEYOND_BARRE = 3  # the index finger holds the lowest fret; three remain


@dataclass(frozen=True)
class MapperCosts:
    """Every tunable number in the mapper. Tuned on the dev split, not by edit.

    Evaluation results record the values they ran with, so a change here shows
    up in the eval/results/ history next to the number it moved.
    """

    move_weight: float = 1.0
    span_weight: float = 0.5
    height_weight: float = 0.1
    open_bonus: float = 0.3
    max_fret: int = 20
    max_span: int = 4
    beam: int = 50


@dataclass(frozen=True)
class _Fingering:
    """One way to play one voicing: a (string, fret) per note, in note order."""

    places: tuple[tuple[int, int], ...]
    cost: float
    position: int | None  # lowest fretted fret; None when every string is open

    @property
    def order_key(self) -> tuple[float, int, tuple[int, ...]]:
        """Cheapest first, then lower frets, then lower strings: determinism."""
        frets = sum(fret for _, fret in self.places)
        strings = tuple(string for string, _ in self.places)
        return (self.cost, frets, strings)


class ViterbiFretboardMapper:
    """Implements guitarvis_core.contracts.FretboardMapper."""

    def __init__(self, costs: MapperCosts | None = None) -> None:
        self.costs = costs or MapperCosts()

    def assign(
        self, notes: Sequence[NoteEvent], tuning: Sequence[str]
    ) -> FretboardResult:
        open_pitches = [parse_pitch(name) for name in tuning]

        placeable = [n for n in notes if self._candidates(n, open_pitches)]
        out_of_range = len(notes) - len(placeable)

        voicings: list[list[NoteEvent]] = []
        fingerings: list[list[_Fingering]] = []
        unplayable = 0
        for voicing in _group(placeable):
            options = self._fingerings(voicing, open_pitches)
            while not options:
                # Drop the least confident note (the latest, among equals)
                # until a fingering exists. A single placeable note is always
                # playable, so this ends.
                weakest = min(
                    range(len(voicing)), key=lambda i: (voicing[i].confidence, -i)
                )
                voicing = voicing[:weakest] + voicing[weakest + 1 :]
                unplayable += 1
                options = self._fingerings(voicing, open_pitches)
            voicings.append(voicing)
            fingerings.append(options)

        path = self._viterbi(fingerings)
        placed = [
            TabNote(
                onset=note.onset,
                duration=note.duration,
                midi=note.midi,
                string=string,
                fret=fret,
                confidence=note.confidence,
            )
            for voicing, choice in zip(voicings, path, strict=True)
            for note, (string, fret) in zip(voicing, choice.places, strict=True)
        ]
        placed.sort(key=lambda tab: (tab.onset, tab.string))

        warnings = []
        if out_of_range:
            warnings.append(
                f"{_notes(out_of_range)} outside the guitar's range "
                f"{_were(out_of_range)} dropped."
            )
        if unplayable:
            warnings.append(
                f"{_notes(unplayable)} in chords no hand could play "
                f"{_were(unplayable)} dropped."
            )
        return FretboardResult(notes=placed, warnings=warnings)

    def _candidates(
        self, note: NoteEvent, open_pitches: Sequence[int]
    ) -> list[tuple[int, int]]:
        """Every (string, fret) that sounds this note's pitch."""
        return [
            (string, note.midi - open_pitch)
            for string, open_pitch in enumerate(open_pitches)
            if 0 <= note.midi - open_pitch <= self.costs.max_fret
        ]

    def _fingerings(
        self, voicing: Sequence[NoteEvent], open_pitches: Sequence[int]
    ) -> list[_Fingering]:
        """The `beam` cheapest playable fingerings of one voicing."""
        if len(voicing) > len(open_pitches):
            return []  # more notes than strings: nothing to enumerate

        per_note = [self._candidates(note, open_pitches) for note in voicing]
        found: list[_Fingering] = []

        def extend(chosen: list[tuple[int, int]], used: set[int]) -> None:
            if len(chosen) == len(per_note):
                fingering = self._score(tuple(chosen))
                if fingering is not None:
                    found.append(fingering)
                return
            for string, fret in per_note[len(chosen)]:
                if string not in used:
                    chosen.append((string, fret))
                    used.add(string)
                    extend(chosen, used)
                    used.discard(string)
                    chosen.pop()

        extend([], set())
        found.sort(key=lambda fingering: fingering.order_key)
        return found[: self.costs.beam]

    def _score(self, places: tuple[tuple[int, int], ...]) -> _Fingering | None:
        """The cost of one fingering, or None when no hand can hold it."""
        fretted = [fret for _, fret in places if fret > 0]
        open_strings = len(places) - len(fretted)
        if not fretted:
            return _Fingering(places, -self.costs.open_bonus * open_strings, None)

        low, high = min(fretted), max(fretted)
        span = high - low
        if span > self.costs.max_span:
            return None
        # The index finger barres every note at the lowest fret; each other
        # fretted note needs a finger of its own.
        if sum(1 for fret in fretted if fret > low) > FINGERS_BEYOND_BARRE:
            return None

        cost = (
            self.costs.span_weight * span
            + self.costs.height_weight * low
            - self.costs.open_bonus * open_strings
        )
        return _Fingering(places, cost, low)

    def _move(self, before: _Fingering, after: _Fingering) -> float:
        """Hand movement. Open strings free the fretting hand, so moving into
        or out of an all-open voicing is free."""
        if before.position is None or after.position is None:
            return 0.0
        return self.costs.move_weight * abs(before.position - after.position)

    def _viterbi(self, fingerings: Sequence[Sequence[_Fingering]]) -> list[_Fingering]:
        """The cheapest fingering per voicing, over the whole sequence."""
        if not fingerings:
            return []

        totals = [fingering.cost for fingering in fingerings[0]]
        back: list[list[int]] = []
        for previous, current in pairwise(fingerings):
            step_totals: list[float] = []
            step_back: list[int] = []
            for option in current:
                # `previous` is sorted by order_key, so strict `<` keeps the
                # first — lowest-fret — predecessor among equal costs.
                best, best_index = totals[0] + self._move(previous[0], option), 0
                for index in range(1, len(previous)):
                    total = totals[index] + self._move(previous[index], option)
                    if total < best:
                        best, best_index = total, index
                step_totals.append(best + option.cost)
                step_back.append(best_index)
            totals = step_totals
            back.append(step_back)

        index = min(range(len(totals)), key=lambda i: totals[i])
        path = [fingerings[-1][index]]
        for step in range(len(fingerings) - 2, -1, -1):
            index = back[step][index]
            path.append(fingerings[step][index])
        path.reverse()
        return path


def _group(notes: Sequence[NoteEvent]) -> list[list[NoteEvent]]:
    """Voicings: notes within VOICING_WINDOW_SEC of a voicing's first note.

    Anchored to the first note, not the latest, so a fast run cannot chain
    into one many-note chord.
    """
    voicings: list[list[NoteEvent]] = []
    for note in sorted(notes, key=lambda n: (n.onset, n.midi)):
        if voicings and note.onset - voicings[-1][0].onset <= VOICING_WINDOW_SEC:
            voicings[-1].append(note)
        else:
            voicings.append([note])
    return voicings


def _notes(count: int) -> str:
    return f"{count} note" if count == 1 else f"{count} notes"


def _were(count: int) -> str:
    return "was" if count == 1 else "were"


if TYPE_CHECKING:  # Static conformance: isinstance compares method names
    from guitarvis_core.contracts import FretboardMapper  # only, so this

    _conforms: FretboardMapper = ViterbiFretboardMapper()  # assignment is
    # what actually checks the signature.
