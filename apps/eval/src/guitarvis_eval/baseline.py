"""The number the mapper has to beat.

Every note at its lowest playable fret: no voicings, no search, no memory of
where the hand just was. It lives in the harness, never in the worker — it
is a reference point, and a plausible-looking wrong tab is exactly what the
pipeline must not ship.
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING

from guitarvis_core.contracts import FretboardResult, NoteEvent, TabNote
from guitarvis_core.fretboard import parse_pitch

MAX_FRET = 20


class LowestFretMapper:
    """Implements guitarvis_core.contracts.FretboardMapper, naively."""

    def assign(
        self, notes: Sequence[NoteEvent], tuning: Sequence[str]
    ) -> FretboardResult:
        open_pitches = [parse_pitch(name) for name in tuning]
        placed = []
        for note in notes:
            options = [
                (note.midi - open_pitch, string)
                for string, open_pitch in enumerate(open_pitches)
                if 0 <= note.midi - open_pitch <= MAX_FRET
            ]
            if not options:
                continue
            fret, string = min(options)
            placed.append(
                TabNote(
                    onset=note.onset,
                    duration=note.duration,
                    midi=note.midi,
                    string=string,
                    fret=fret,
                    confidence=note.confidence,
                )
            )
        dropped = len(notes) - len(placed)
        warnings = [f"{dropped} out-of-range notes dropped."] if dropped else []
        return FretboardResult(notes=placed, warnings=warnings)


if TYPE_CHECKING:
    from guitarvis_core.contracts import FretboardMapper

    _conforms: FretboardMapper = LowestFretMapper()
