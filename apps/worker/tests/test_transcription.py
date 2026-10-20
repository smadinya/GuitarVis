"""Stage 2's conversion from raw model output to NoteEvent.

_predict is stubbed: what is under test is the clamping, filtering, and
ordering, none of which should require the ml extra to verify.
"""

import math
import sys
import types
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from guitarvis_core.contracts import NoteEvent
from guitarvis_worker.stages.transcription import (
    MIN_CONFIDENCE,
    BasicPitchTranscriber,
    TranscriptionSettings,
    drop_ghosts,
)


class StubTranscriber(BasicPitchTranscriber):
    def __init__(self, raw: Sequence[tuple], **kwargs: Any) -> None:
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


def test_default_settings_are_010s_tuned_values() -> None:
    # Tuned on GuitarSet's dev split: docs/specs/010-tab-accuracy/tuning.md.
    assert TranscriptionSettings() == TranscriptionSettings(
        onset_threshold=0.5,
        frame_threshold=0.4,
        minimum_note_length_ms=93.0,
        melodia_trick=False,
        ghost_ratio=0.8,
        ghost_alone_only=True,
    )
    assert BasicPitchTranscriber().settings == TranscriptionSettings()


def test_settings_reach_predict(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def predict(path: str, model: str, **kwargs: object) -> tuple:
        seen.update(path=path, model=model, **kwargs)
        return {}, None, []

    package = types.ModuleType("basic_pitch")
    package.ICASSP_2022_MODEL_PATH = "nmp.onnx"  # type: ignore[attr-defined]
    inference = types.ModuleType("basic_pitch.inference")
    inference.predict = predict  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "basic_pitch", package)
    monkeypatch.setitem(sys.modules, "basic_pitch.inference", inference)

    settings = TranscriptionSettings(
        onset_threshold=0.6,
        frame_threshold=0.4,
        minimum_note_length_ms=58.0,
        melodia_trick=False,
    )
    BasicPitchTranscriber(settings=settings).transcribe(Path("x.wav"))

    assert seen == {
        "path": "x.wav",
        "model": "nmp.onnx",
        "onset_threshold": 0.6,
        "frame_threshold": 0.4,
        "minimum_note_length": 58.0,
        "melodia_trick": False,
    }


@pytest.mark.parametrize(
    "bad",
    [
        {"frame_threshold": 0},
        {"onset_threshold": 1.5},
        {"minimum_note_length_ms": -1},
        {"minimum_note_length_ms": math.inf},
        {"minimum_note_length_ms": math.nan},
        {"ghost_ratio": 0},
        {"ghost_ratio": 1.5},
    ],
)
def test_settings_refuse_impossible_values(bad: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        TranscriptionSettings(**bad)


# The ghost rule. Every test has a base, E3 (52) at 1.0 s for half a second at
# confidence 0.8, so a ghost needs to be under 0.6 x 0.8 = 0.48 to go.
E3 = 52
BASE = NoteEvent(onset=1.0, duration=0.5, midi=E3, confidence=0.8)


def ghost(midi: int = 64, onset: float = 1.0, confidence: float = 0.4) -> NoteEvent:
    return NoteEvent(onset=onset, duration=0.5, midi=midi, confidence=confidence)


def test_a_weak_octave_above_a_sounding_note_is_dropped() -> None:
    assert drop_ghosts([BASE, ghost()], 0.6, alone_only=False) == [BASE]


def test_twelfths_and_double_octaves_are_ghosts_but_fifths_are_not() -> None:
    events = [BASE, ghost(71), ghost(76), ghost(59)]
    assert drop_ghosts(events, 0.6, alone_only=False) == [BASE, ghost(59)]


def test_a_strong_octave_is_kept() -> None:
    events = [BASE, ghost(confidence=0.6)]
    assert drop_ghosts(events, 0.6, alone_only=False) == events


def test_a_ghost_may_lead_its_base_by_50ms() -> None:
    early = ghost(onset=0.96)
    too_early = ghost(onset=0.94)
    assert drop_ghosts([early, BASE], 0.6, alone_only=False) == [BASE]
    assert drop_ghosts([too_early, BASE], 0.6, alone_only=False) == [too_early, BASE]


def test_a_ghost_needs_its_base_still_sounding() -> None:
    late = ghost(onset=1.6)
    assert drop_ghosts([BASE, late], 0.6, alone_only=False) == [BASE, late]


def test_alone_only_spares_a_chord() -> None:
    g3 = NoteEvent(onset=1.0, duration=0.5, midi=55, confidence=0.8)
    events = [BASE, g3, ghost()]
    assert drop_ghosts(events, 0.6, alone_only=True) == events
    assert drop_ghosts(events, 0.6, alone_only=False) == [BASE, g3]


def test_alone_only_drops_a_ghost_whose_neighbours_are_all_its_bases() -> None:
    e2 = NoteEvent(onset=1.0, duration=0.5, midi=40, confidence=0.8)
    assert drop_ghosts([e2, BASE, ghost()], 0.6, alone_only=True) == [e2, BASE]


def test_alone_only_counts_a_neighbour_that_is_too_weak_to_be_a_base() -> None:
    # E3 is 12 below the E4 and sounding, but 0.4 is not under 0.6 x 0.6. Only
    # E2 makes the E4 a ghost, and E3, a real note, stands beside it.
    e2 = NoteEvent(onset=1.0, duration=0.5, midi=40, confidence=0.9)
    e3 = NoteEvent(onset=1.0, duration=0.5, midi=E3, confidence=0.6)
    events = [e2, e3, ghost()]
    assert drop_ghosts(events, 0.6, alone_only=False) == [e2, e3]
    assert drop_ghosts(events, 0.6, alone_only=True) == events


def test_alone_only_needs_the_base_to_start_with_the_ghost() -> None:
    # A melody note over a held bass: E3 starts while E2 is still sounding,
    # but nothing starts with it. The ghost and its base are not "the only
    # notes starting at that onset", because the base started two seconds
    # earlier, so E3 stays. The plain rule still drops it.
    e2 = NoteEvent(onset=0.0, duration=3.0, midi=40, confidence=0.8)
    e3 = NoteEvent(onset=2.0, duration=0.5, midi=E3, confidence=0.6)
    assert drop_ghosts([e2, e3], 0.8, alone_only=True) == [e2, e3]
    assert drop_ghosts([e2, e3], 0.8, alone_only=False) == [e2]

    # A base starting with the ghost still makes it one, held bass or not.
    e3_base = NoteEvent(onset=2.0, duration=0.5, midi=E3, confidence=0.8)
    e4 = NoteEvent(onset=2.0, duration=0.5, midi=64, confidence=0.4)
    events = [e2, e3_base, e4]
    assert drop_ghosts(events, 0.8, alone_only=True) == [e2, e3_base]


def test_ghost_rule_judges_against_decoded_notes() -> None:
    # Review Focus 4. A ghost is a base too: the E4 is judged against the E3
    # even though the E3 is itself about to go.
    def stack(e2: float, e3: float, e4: float) -> list[NoteEvent]:
        return [
            NoteEvent(onset=1.0, duration=0.5, midi=40, confidence=e2),
            NoteEvent(onset=1.0, duration=0.5, midi=52, confidence=e3),
            NoteEvent(onset=1.0, duration=0.5, midi=64, confidence=e4),
        ]

    weak = stack(0.9, 0.5, 0.25)
    assert drop_ghosts(weak, 0.6, alone_only=False) == weak[:1]
    equal = stack(0.8, 0.8, 0.8)
    assert drop_ghosts(equal, 0.6, alone_only=False) == equal


def test_a_ghost_may_be_judged_by_another_ghost() -> None:
    # The E4 starts 80 ms before the E2, too early to be its ghost, but only
    # 40 ms before the E3, which is itself a ghost of the E2. Judged against
    # the survivors the E4 would stay.
    e2 = NoteEvent(onset=1.0, duration=0.5, midi=40, confidence=0.9)
    e3 = NoteEvent(onset=0.96, duration=0.5, midi=52, confidence=0.5)
    e4 = NoteEvent(onset=0.92, duration=0.5, midi=64, confidence=0.25)
    assert drop_ghosts([e4, e3, e2], 0.6, alone_only=False) == [e2]


def test_survivors_keep_their_order() -> None:
    later = NoteEvent(onset=3.0, duration=0.5, midi=60, confidence=0.7)
    events = [later, ghost(), BASE]
    assert drop_ghosts(events, 0.6, alone_only=False) == [later, BASE]


def test_ghosts_are_kept_when_the_rule_is_off() -> None:
    raw = [(1.0, 1.5, 52, 0.8, None), (1.0, 1.5, 64, 0.4, None)]
    settings = TranscriptionSettings(ghost_ratio=None)
    events = StubTranscriber(raw, settings=settings).transcribe(Path("x.wav"))
    assert [event.midi for event in events] == [52, 64]


def test_transcribe_drops_ghosts_when_asked() -> None:
    raw = [(1.0, 1.5, 52, 0.8, None), (1.0, 1.5, 64, 0.4, None)]
    settings = TranscriptionSettings(ghost_ratio=0.6)
    events = StubTranscriber(raw, settings=settings).transcribe(Path("x.wav"))
    assert [event.midi for event in events] == [52]


def test_the_ghost_alone_only_setting_reaches_the_rule() -> None:
    raw = [
        (1.0, 1.5, 52, 0.8, None),
        (1.0, 1.5, 55, 0.8, None),
        (1.0, 1.5, 64, 0.4, None),
    ]
    settings = TranscriptionSettings(ghost_ratio=0.6, ghost_alone_only=True)
    events = StubTranscriber(raw, settings=settings).transcribe(Path("x.wav"))
    assert [event.midi for event in events] == [52, 55, 64]
