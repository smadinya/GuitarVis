"""Stage 4 — fretboard assignment. The deterministic core.

Notes within 50ms of a voicing's first note group into that voicing; each
voicing has a set of playable fingerings filtered by physical constraints; a
Viterbi pass minimises total cost, dominated by hand-position movement between
consecutive voicings because real players stay put. The hand is the index
finger's fret and covers `hand_window` frets, so it moves only when a voicing
does not fit under it. An open string costs more the further up the neck the
hand sits, unless its note has no other place to be played. A chord that skips
strings between its outer two costs a little for each one it skips.

Testable without audio: feed note sequences, assert fingerings. Every note it
emits must satisfy guitarvis_core.fretboard.check_invariant — a note that
cannot be placed correctly is dropped with a warning, never approximated.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from guitarvis_core.contracts import (
    VOICING_WINDOW_SEC,
    FretboardResult,
    NoteEvent,
    TabNote,
)
from guitarvis_core.fretboard import parse_pitch

# Path totals are rounded to this many places before they are compared, so
# that two equally good paths summed in a different order tie exactly and the
# tie-break rule decides, not the last bit of a float.
COST_PLACES = 9
FINGERS_BEYOND_BARRE = 3  # the index finger holds the lowest fret; three remain


@dataclass(frozen=True)
class MapperCosts:
    """Every tunable number in the mapper. Tuned on the dev split, not by edit.

    docs/specs/010-tab-accuracy/tuning.md records the sweeps that chose them.
    Evaluation results record the values they ran with, so a change here shows
    up in the eval/results/ history next to the number it moved.

    The hand is the index finger's fret and covers `hand_window` frets; moving
    it costs `move_weight` per fret. Within a fingering, `span_weight` charges
    per fret of stretch and `height_weight` per fret of height, which pulls the
    tab toward the nut (zero: nothing does). An open string is free while the
    hand sits at or below `open_reach`, and above it costs `open_weight` per
    fret of the hand's height. A note with no other place to be played is
    exempt, so the lowest string's open note never drags a phrase down.

    Moving into a fingering costs `ring_weight` for each string it uses where
    the previous voicing's note is still sounding. A note counts as sounding
    until `ring_tolerance` seconds after the next voicing starts, because
    basic-pitch lets notes run on past the point a player moved to the next
    note. It is a cost, not a rule: a ringing string can still be reused.

    A fingering of three or more notes costs `gap_weight` per unused string
    between its lowest and highest string, because a strum hits adjacent
    strings. It is a cost, not a rule: fingerstyle chords do skip strings.
    """

    move_weight: float = 1.0
    span_weight: float = 0.5
    height_weight: float = 0.0
    open_reach: int = 4
    open_weight: float = 0.2
    ring_weight: float = 2.0
    ring_tolerance: float = 0.1  # seconds
    gap_weight: float = 0.6
    max_fret: int = 20
    max_span: int = 4
    hand_window: int = 4
    beam: int = 50

    def __post_init__(self) -> None:
        # Below these bounds a lone note can have no fingering at all, and the
        # drop loop in assign() relies on a lone note always being playable.
        if self.beam < 1:
            raise ValueError(f"beam must be at least 1, not {self.beam}")
        if self.max_span < 0 or self.max_fret < 0 or self.open_reach < 0:
            raise ValueError("max_span, max_fret and open_reach cannot be negative")
        # The hand covers at least the fret under the index finger.
        if self.hand_window < 1:
            raise ValueError(f"hand_window must be at least 1, not {self.hand_window}")
        weights = (
            self.move_weight,
            self.span_weight,
            self.height_weight,
            self.open_weight,
            self.ring_weight,
            self.gap_weight,
        )
        if any(weight < 0 for weight in weights):
            raise ValueError("cost weights cannot be negative")
        if self.ring_tolerance < 0:
            raise ValueError(
                f"ring_tolerance cannot be negative, not {self.ring_tolerance}"
            )


@dataclass(frozen=True)
class _Fingering:
    """One way to play one voicing: a (string, fret) per note, in note order."""

    places: tuple[tuple[int, int], ...]
    cost: float
    position: int | None  # lowest fretted fret; None when every string is open
    top: int | None  # highest fretted fret; None when every string is open
    # Open strings whose note could be played elsewhere. They are charged by
    # where the hand lands, so the cost waits for the transition.
    charged_opens: int

    @property
    def tie_key(self) -> tuple[int, tuple[int, ...]]:
        """Lower frets first, then lower strings: how equal paths are told
        apart, so the result is deterministic."""
        frets = sum(fret for _, fret in self.places)
        strings = tuple(string for string, _ in self.places)
        return (frets, strings)

    @property
    def order_key(self) -> tuple[float, int, tuple[int, ...]]:
        """Cheapest first, then by `tie_key`: which fingerings the beam keeps."""
        frets, strings = self.tie_key
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

        path = self._viterbi(voicings, fingerings)
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
        """The `beam` cheapest playable fingerings of one voicing, in tie order.

        The beam keeps the cheapest by `order_key`. The kept fingerings are
        then ordered by `tie_key` alone, because `cost` is only part of what
        a fingering costs (an open string is charged by where the hand
        lands), so two paths of equal total need not share a `cost`. The
        search breaks ties by index, so index order must be tie order.
        """
        if len(voicing) > len(open_pitches):
            return []  # more notes than strings: nothing to enumerate

        per_note = [self._candidates(note, open_pitches) for note in voicing]
        forced = tuple(len(candidates) == 1 for candidates in per_note)
        found: list[_Fingering] = []

        def extend(chosen: list[tuple[int, int]], used: set[int]) -> None:
            if len(chosen) == len(per_note):
                fingering = self._score(tuple(chosen), forced)
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
        kept = found[: self.costs.beam]
        kept.sort(key=lambda fingering: fingering.tie_key)
        return kept

    def _score(
        self, places: tuple[tuple[int, int], ...], forced: tuple[bool, ...]
    ) -> _Fingering | None:
        """The cost of one fingering, or None when no hand can hold it.

        `forced[i]` says note i has exactly one candidate. If that one is an
        open string every fingering plays it open, so charging for it would
        only drag the rest of the phrase toward the nut. The exemption is
        that, and not "the lowest string": E2 on a seven-string has two places.
        """
        # A hole in the middle of a chord: strings between its outer two that
        # it leaves unused. One or two notes have no middle to speak of.
        gap = 0.0
        if len(places) >= 3:
            strings = [string for string, _ in places]
            gap = self.costs.gap_weight * (
                max(strings) - min(strings) + 1 - len(places)
            )
        fretted = [fret for _, fret in places if fret > 0]
        charged_opens = sum(
            1
            for (_, fret), only in zip(places, forced, strict=True)
            if fret == 0 and not only
        )
        if not fretted:
            return _Fingering(places, gap, None, None, charged_opens)

        low, high = min(fretted), max(fretted)
        span = high - low
        if span > self.costs.max_span:
            return None
        # The index finger barres every note at the lowest fret; each other
        # fretted note needs a finger of its own.
        if sum(1 for fret in fretted if fret > low) > FINGERS_BEYOND_BARRE:
            return None

        cost = self.costs.span_weight * span + self.costs.height_weight * low + gap
        return _Fingering(places, cost, low, high, charged_opens)

    def _transition(
        self, hand: int | None, after: _Fingering
    ) -> tuple[float, int | None]:
        """The cost of moving the hand to play `after`, and where it lands.

        The hand is the index finger's fret and covers `hand_window` frets.
        A shape that fits under it costs nothing; otherwise the hand moves the
        shortest way that makes it fit. A shape wider than the box puts the
        index finger on its lowest fret. An all-open voicing needs no
        fretting, so the hand stays put. Before the first fretted voicing the
        hand is nowhere: arriving is free, and the index finger lands on the
        lowest fret, not on a lower one that would also fit.

        The fingering's charged open strings cost `open_weight` per fret that
        the landing hand sits above `open_reach`. A hand that is nowhere is
        at the nut.
        """
        if after.position is None or after.top is None:
            move, landing = 0.0, hand
        else:
            low, high = after.position, after.top
            if hand is None:
                move, landing = 0.0, low
            else:
                landing = min(
                    max(hand, min(high - (self.costs.hand_window - 1), low)), low
                )
                move = self.costs.move_weight * abs(hand - landing)
        above_reach = max(0, (landing or 0) - self.costs.open_reach)
        open_cost = self.costs.open_weight * after.charged_opens * above_reach
        return move + open_cost, landing

    def _ring(
        self,
        before: Sequence[NoteEvent],
        held: _Fingering,
        onset: float,
        after: _Fingering,
    ) -> float:
        """The cost of playing `after` while `before` may still be sounding.

        `held` is how `before` was played, a place per note in note order.
        Each string that `after` uses costs `ring_weight` when the note `held`
        put on it ends more than `ring_tolerance` after `onset`, the start of
        the voicing `after` plays. A note that rings for ever costs only this,
        once, so it can never stop a later note being placed.
        """
        ends = {
            string: note.onset + note.duration
            for note, (string, _) in zip(before, held.places, strict=True)
        }
        limit = onset + self.costs.ring_tolerance
        ringing = sum(
            1 for string, _ in after.places if string in ends and ends[string] > limit
        )
        return self.costs.ring_weight * ringing

    def _viterbi(
        self,
        voicings: Sequence[Sequence[NoteEvent]],
        fingerings: Sequence[Sequence[_Fingering]],
    ) -> list[_Fingering]:
        """The cheapest fingering per voicing, over the whole sequence.

        `voicings[k]` is the notes `fingerings[k]` plays. A transition also
        pays for any string in the new fingering that the previous voicing's
        fingering left sounding, which the predecessor state already holds.

        A state is a fingering plus where the hand lands. The hand is the
        index finger's fret and covers `hand_window` frets, so a fingering
        reached from different hand positions can land the hand in different
        places, and holds one state per landing. An all-open fingering leaves
        the hand where it was, and holds one state per hand position it can
        be reached from. Without that, an open note would forget the hand and
        make the next jump free.
        """
        if not fingerings:
            return []

        # States are (fingering index, hand landing), sorted by index and then
        # by landing, with a hand that is nowhere (None) first. A voicing's
        # fingerings are in `tie_key` order, so index order is tie order: of
        # equal (rounded) totals, the final `min` takes the first state of the
        # last voicing, which is its lowest-fret fingering and, within one
        # fingering, its lowest landing; strict `<` gives each state its first
        # predecessor, by the same order. Ties break toward lower frets, then
        # lower strings, then a lower hand, latest voicing first.
        #
        # The first voicing is reached from no hand, which costs nothing to
        # move but still charges its open strings where the hand lands.
        arrivals = [self._transition(None, fingering) for fingering in fingerings[0]]
        states: list[tuple[int, int | None]] = [
            (index, landing) for index, (_, landing) in enumerate(arrivals)
        ]
        totals = [
            round(fingering.cost + cost, COST_PLACES)
            for fingering, (cost, _) in zip(fingerings[0], arrivals, strict=True)
        ]
        history: list[list[tuple[int, int | None]]] = [states]
        back: list[list[int]] = []
        for k in range(1, len(fingerings)):
            current = fingerings[k]
            onset = voicings[k][0].onset
            best: dict[tuple[int, int | None], tuple[float, int]] = {}
            for before, (held_index, hand) in enumerate(states):
                held = fingerings[k - 1][held_index]
                for index, option in enumerate(current):
                    move, landing = self._transition(hand, option)
                    ring = self._ring(voicings[k - 1], held, onset, option)
                    total = round(
                        totals[before] + move + ring + option.cost, COST_PLACES
                    )
                    key = (index, landing)
                    if key not in best or total < best[key][0]:
                        best[key] = (total, before)
            states = sorted(best, key=lambda s: (s[0], -1 if s[1] is None else s[1]))
            totals = [best[state][0] for state in states]
            history.append(states)
            back.append([best[state][1] for state in states])

        state = min(range(len(totals)), key=lambda i: totals[i])
        path = [fingerings[-1][history[-1][state][0]]]
        for step in range(len(fingerings) - 2, -1, -1):
            state = back[step][state]
            path.append(fingerings[step][history[step][state][0]])
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
