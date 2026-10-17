"""Loudness from the stem: a stdlib measurement, so no audio stack needed."""

import wave
from dataclasses import replace
from pathlib import Path

import pytest
from guitarvis_core.contracts import TabNote
from guitarvis_worker.loudness import measure_loudness
from stem_fixture import write_stem


def note(onset: float, midi: int = 52) -> TabNote:
    """A note on the low E string, which plays every pitch these tests use."""
    return TabNote(
        onset=onset, duration=0.3, midi=midi, string=0, fret=midi - 40, confidence=0.9
    )


def level(tab: TabNote) -> float:
    assert tab.loudness is not None
    return tab.loudness


def test_a_loud_pluck_reads_louder_than_a_quiet_one(tmp_path: Path) -> None:
    stem = write_stem(tmp_path / "stem.wav", [(1.0, 0.3, 16000), (2.0, 0.3, 2000)])

    loud, quiet = measure_loudness(stem, [note(1.0), note(2.0)])

    assert loud.loudness == 1.0
    # 2000 / 16000 is -18.06 dB, so (30 - 18.06) / 30.
    assert quiet.loudness == pytest.approx(0.398, abs=0.001)


def test_a_strums_notes_share_one_level(tmp_path: Path) -> None:
    # Quiet under the first string, loud from the third: measured note by
    # note, the later strings would read louder.
    stem = write_stem(
        tmp_path / "stem.wav",
        [(1.0, 0.04, 1000), (1.04, 0.3, 16000), (3.0, 0.3, 16000)],
    )

    measured = measure_loudness(
        stem, [note(1.0, 40), note(1.02, 45), note(1.04, 50), note(3.0)]
    )

    assert measured[0].loudness == measured[1].loudness == measured[2].loudness
    assert level(measured[0]) < level(measured[3])


def test_a_strum_is_anchored_to_its_first_onset(tmp_path: Path) -> None:
    # Each onset is within 50 ms of the one before, but 1.08 is not within
    # 50 ms of 1.00. Chained, a fast passage would become one strum.
    stem = write_stem(tmp_path / "stem.wav", [(1.0, 0.08, 2000), (1.08, 0.3, 16000)])

    measured = measure_loudness(stem, [note(1.0), note(1.04), note(1.08)])

    assert measured[0].loudness == measured[1].loudness
    assert level(measured[1]) < level(measured[2])


def test_notes_more_than_50ms_apart_are_measured_apart(tmp_path: Path) -> None:
    stem = write_stem(tmp_path / "stem.wav", [(1.0, 0.1, 2000), (1.1, 0.3, 16000)])

    first, second = measure_loudness(stem, [note(1.0), note(1.1)])

    assert level(first) < level(second)


def test_the_notes_come_back_in_order_with_nothing_else_changed(tmp_path: Path) -> None:
    stem = write_stem(tmp_path / "stem.wav", [(1.0, 0.3, 16000), (2.0, 0.3, 2000)])
    notes = [note(2.0, 60), note(1.0, 40)]

    measured = measure_loudness(stem, notes)

    assert [replace(m, loudness=None) for m in measured] == notes
    assert level(measured[0]) < level(measured[1])


def test_a_note_past_the_end_of_the_stem_reads_silent(tmp_path: Path) -> None:
    stem = write_stem(tmp_path / "stem.wav", [(1.0, 0.3, 16000)], seconds=2.0)

    inside, past = measure_loudness(stem, [note(1.0), note(5.0)])

    assert (inside.loudness, past.loudness) == (1.0, 0.0)


def test_a_stem_silent_under_every_note_cannot_be_measured(tmp_path: Path) -> None:
    stem = write_stem(tmp_path / "stem.wav", [(3.0, 0.5, 16000)])

    with pytest.raises(ValueError):
        measure_loudness(stem, [note(1.0), note(2.0)])


def test_an_unreadable_stem_raises(tmp_path: Path) -> None:
    empty = tmp_path / "empty.wav"
    empty.write_bytes(b"")

    with pytest.raises((EOFError, wave.Error)):
        measure_loudness(empty, [note(1.0)])


def test_a_stem_that_is_not_16_bit_raises(tmp_path: Path) -> None:
    stem = tmp_path / "24bit.wav"
    with wave.open(str(stem), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(3)
        handle.setframerate(8000)
        handle.writeframes(b"\0" * 3 * 8000)

    with pytest.raises(ValueError):
        measure_loudness(stem, [note(0.5)])


def test_no_notes_need_no_stem(tmp_path: Path) -> None:
    assert measure_loudness(tmp_path / "missing.wav", []) == []
