"""Loudness from the stem: a stdlib measurement, so no audio stack needed."""

import wave
from dataclasses import replace
from pathlib import Path

import pytest
from guitarvis_core.contracts import NoteEvent
from guitarvis_worker.loudness import measure_loudness
from stem_fixture import write_stem


def event(onset: float, midi: int = 52) -> NoteEvent:
    return NoteEvent(onset=onset, duration=0.3, midi=midi, confidence=0.9)


def level(note: NoteEvent) -> float:
    assert note.loudness is not None
    return note.loudness


def test_a_loud_pluck_reads_louder_than_a_quiet_one(tmp_path: Path) -> None:
    stem = write_stem(tmp_path / "stem.wav", [(1.0, 0.3, 16000), (2.0, 0.3, 2000)])

    loud, quiet = measure_loudness(stem, [event(1.0), event(2.0)])

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
        stem, [event(1.0, 40), event(1.02, 45), event(1.04, 50), event(3.0)]
    )

    assert measured[0].loudness == measured[1].loudness == measured[2].loudness
    assert level(measured[0]) < level(measured[3])


def test_notes_more_than_50ms_apart_are_measured_apart(tmp_path: Path) -> None:
    stem = write_stem(tmp_path / "stem.wav", [(1.0, 0.1, 2000), (1.1, 0.3, 16000)])

    first, second = measure_loudness(stem, [event(1.0), event(1.1)])

    assert level(first) < level(second)


def test_the_notes_come_back_in_order_with_nothing_else_changed(tmp_path: Path) -> None:
    stem = write_stem(tmp_path / "stem.wav", [(1.0, 0.3, 16000), (2.0, 0.3, 2000)])
    events = [event(2.0, 60), event(1.0, 40)]

    measured = measure_loudness(stem, events)

    assert [replace(m, loudness=None) for m in measured] == events
    assert level(measured[0]) < level(measured[1])


def test_a_note_past_the_end_of_the_stem_reads_silent(tmp_path: Path) -> None:
    stem = write_stem(tmp_path / "stem.wav", [(1.0, 0.3, 16000)], seconds=2.0)

    inside, past = measure_loudness(stem, [event(1.0), event(5.0)])

    assert (inside.loudness, past.loudness) == (1.0, 0.0)


def test_a_stem_silent_under_every_note_cannot_be_measured(tmp_path: Path) -> None:
    stem = write_stem(tmp_path / "stem.wav", [(3.0, 0.5, 16000)])

    with pytest.raises(ValueError):
        measure_loudness(stem, [event(1.0), event(2.0)])


def test_an_unreadable_stem_raises(tmp_path: Path) -> None:
    empty = tmp_path / "empty.wav"
    empty.write_bytes(b"")

    with pytest.raises((EOFError, wave.Error)):
        measure_loudness(empty, [event(1.0)])


def test_a_stem_that_is_not_16_bit_raises(tmp_path: Path) -> None:
    stem = tmp_path / "24bit.wav"
    with wave.open(str(stem), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(3)
        handle.setframerate(8000)
        handle.writeframes(b"\0" * 3 * 8000)

    with pytest.raises(ValueError):
        measure_loudness(stem, [event(0.5)])


def test_no_notes_need_no_stem(tmp_path: Path) -> None:
    assert measure_loudness(tmp_path / "missing.wav", []) == []
