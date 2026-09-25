"""Pitch arithmetic and the one invariant tablature correctness rests on.

This lives in core, not in the worker, because the mapper, its tests, and any
future editing feature must all ask the same question of the same code.
"""

import re
from collections.abc import Sequence

from guitarvis_core.tabdoc import Note

_SEMITONES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_PITCH_RE = re.compile(r"^([A-G])([#b]?)(-?\d+)$")


class InvariantViolation(Exception):
    """A note's (string, fret, tuning) does not produce its MIDI pitch."""


def parse_pitch(name: str) -> int:
    """Convert a scientific pitch name to a MIDI number. C-1 is 0, A4 is 69."""
    match = _PITCH_RE.match(name)
    if match is None:
        raise ValueError(f"not a scientific pitch name: {name!r}")

    letter, accidental, octave = match.groups()
    semitone = _SEMITONES[letter]
    if accidental == "#":
        semitone += 1
    elif accidental == "b":
        semitone -= 1

    return 12 * (int(octave) + 1) + semitone


def pitch_of(string_index: int, fret: int, tuning: Sequence[str]) -> int:
    """The MIDI pitch produced by fretting `string_index` at `fret`.

    string_index is 0 for the lowest string, matching Note.string.
    """
    if fret < 0:
        raise ValueError(f"fret must not be negative: {fret}")
    if not 0 <= string_index < len(tuning):
        raise IndexError(
            f"string {string_index} does not exist on a {len(tuning)}-string instrument"
        )

    return parse_pitch(tuning[string_index]) + fret


def check_invariant(note: Note, tuning: Sequence[str]) -> None:
    """Raise if a note's fingering does not produce its pitch.

    Call this on every note leaving stage 4. A tab that renders the wrong fret
    is worse than no tab: a beginner cannot tell it from a hard passage.

    `note.fret` is always measured from the nut, never from the capo. v1
    only ever produces capo 0 (see Instrument.capo), so this distinction is
    currently invisible, but it is the single most likely thing to make a
    future client render every fret wrong once capo detection lands.
    """
    produced = pitch_of(note.string, note.fret, tuning)
    if produced != note.midi:
        raise InvariantViolation(
            f"note {note.id}: string {note.string} fret {note.fret} produces "
            f"MIDI {produced}, but the note claims MIDI {note.midi}"
        )
