"""The hard invariant: pitch(string, fret, tuning) == the note's MIDI pitch.

The parent spec makes fretboard assignment deterministic precisely so that
tablature correctness does not depend on model accuracy. This is the assertion
that keeps that promise true.
"""

import pytest
from guitarvis_core.fretboard import (
    InvariantViolation,
    check_invariant,
    parse_pitch,
    pitch_of,
)
from guitarvis_core.tabdoc import STANDARD_TUNING, Note

MAX_FRET = 24


@pytest.mark.parametrize(
    ("name", "midi"),
    [
        ("C-1", 0),
        ("E2", 40),
        ("A2", 45),
        ("D3", 50),
        ("C4", 60),
        ("A4", 69),
        ("E4", 64),
        ("Eb3", 51),
        ("F#2", 42),
    ],
)
def test_parse_pitch(name: str, midi: int) -> None:
    assert parse_pitch(name) == midi


def test_parse_pitch_rejects_nonsense() -> None:
    with pytest.raises(ValueError):
        parse_pitch("H7")


def test_open_low_e_is_midi_40() -> None:
    assert pitch_of(0, 0, STANDARD_TUNING) == 40


def test_spec_example_d_string_second_fret_is_e3() -> None:
    """The worked example in the parent spec's tab document section."""
    assert pitch_of(2, 2, STANDARD_TUNING) == 52


def test_invariant_holds_across_the_whole_neck() -> None:
    """Exhaustive rather than randomised: 6 x 25 cases is cheap and total.

    Hypothesis would add a dependency to generate a strictly smaller space.
    """
    for string_index, open_name in enumerate(STANDARD_TUNING):
        open_midi = parse_pitch(open_name)
        for fret in range(MAX_FRET + 1):
            assert pitch_of(string_index, fret, STANDARD_TUNING) == open_midi + fret


def test_pitch_of_rejects_an_out_of_range_string() -> None:
    with pytest.raises(IndexError):
        pitch_of(6, 0, STANDARD_TUNING)


def test_pitch_of_rejects_a_negative_fret() -> None:
    with pytest.raises(ValueError):
        pitch_of(0, -1, STANDARD_TUNING)


def test_pitch_of_rejects_a_negative_string_index() -> None:
    """Python would otherwise index from the end and return a real pitch
    for the wrong string."""
    with pytest.raises(IndexError):
        pitch_of(-1, 0, STANDARD_TUNING)


def test_check_invariant_accepts_a_consistent_note() -> None:
    note = Note(id="n_0", t=0.0, dur=0.5, midi=52, string=2, fret=2, confidence=1.0)

    check_invariant(note, STANDARD_TUNING)  # must not raise


def test_check_invariant_rejects_an_inconsistent_note() -> None:
    note = Note(id="n_0", t=0.0, dur=0.5, midi=53, string=2, fret=2, confidence=1.0)

    with pytest.raises(InvariantViolation) as excinfo:
        check_invariant(note, STANDARD_TUNING)

    assert "n_0" in str(excinfo.value)
