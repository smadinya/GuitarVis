"""Stage 2's conversion from raw model output to NoteEvent.

_predict is stubbed: what is under test is the clamping, filtering, and
ordering, none of which should require the ml extra to verify.
"""

from collections.abc import Sequence
from pathlib import Path

import pytest
from guitarvis_worker.stages.transcription import (
    MIN_CONFIDENCE,
    BasicPitchTranscriber,
)


class StubTranscriber(BasicPitchTranscriber):
    def __init__(self, raw: Sequence[tuple], **kwargs: float) -> None:
        super().__init__(**kwargs)
        self.raw = raw

    def _predict(self, stem_path: Path) -> Sequence[tuple]:
        return self.raw


def test_builds_note_events_from_model_tuples() -> None:
    # (start, end, midi, amplitude, pitch_bends) — basic-pitch's shape
    events = StubTranscriber([(1.0, 1.5, 52, 0.8, None)]).transcribe(Path("x.wav"))

    assert len(events) == 1
    assert events[0].onset == 1.0
    assert events[0].duration == pytest.approx(0.5)
    assert events[0].midi == 52
    assert events[0].confidence == pytest.approx(0.8)


def test_confidence_is_clamped_into_range() -> None:
    # Note.confidence is bounded 0..1 by the schema; amplitude is not
    events = StubTranscriber([(1.0, 1.5, 52, 1.4, None)]).transcribe(Path("x.wav"))
    assert events[0].confidence == 1.0


def test_near_noise_is_dropped() -> None:
    events = StubTranscriber([(1.0, 1.5, 52, 0.01, None)]).transcribe(Path("x.wav"))
    assert events == []


def test_pitches_outside_midi_range_are_dropped() -> None:
    events = StubTranscriber([(1.0, 1.5, 200, 0.9, None)]).transcribe(Path("x.wav"))
    assert events == []


def test_events_are_sorted_by_onset() -> None:
    raw = [(2.0, 2.5, 52, 0.8, None), (1.0, 1.5, 55, 0.8, None)]
    events = StubTranscriber(raw).transcribe(Path("x.wav"))
    assert [event.onset for event in events] == [1.0, 2.0]


def test_empty_prediction_is_not_an_error() -> None:
    assert StubTranscriber([]).transcribe(Path("x.wav")) == []


def test_midi_is_a_plain_int() -> None:
    # basic-pitch returns numpy integers; they must not reach the document,
    # where they would serialise as something a strict client may reject.
    events = StubTranscriber([(1.0, 1.5, 52, 0.8, None)]).transcribe(Path("x.wav"))
    assert type(events[0].midi) is int


def test_min_confidence_stays_conservative() -> None:
    # The degradation ladder needs faint notes to survive and render faintly;
    # this floor removes near-noise only.
    assert MIN_CONFIDENCE <= 0.2
