"""Stage interfaces and the failure taxonomy.

The interfaces are narrow on purpose: stage 2 returns (onset, duration, pitch,
confidence) and NOT string/fret, so a guitar-specific model can later implement
the same interface. That is the single upgrade point the staged architecture
exists to protect.
"""

from collections.abc import Sequence
from pathlib import Path

import pytest
from guitarvis_core.contracts import (
    FailureReason,
    FretboardMapper,
    NoteEvent,
    PipelineError,
    Separator,
    StructureAnalyzer,
    StructureResult,
    TabNote,
    Transcriber,
)
from guitarvis_core.tabdoc import Timing


def test_failure_reasons_match_the_spec_exactly() -> None:
    """The UI maps these to actionable text; the strings are a contract."""
    assert {reason.value for reason in FailureReason} == {
        "unsupported_format",
        "no_guitar_detected",
        "too_long",
        "fetch_failed",
        "internal",
    }


def test_pipeline_error_carries_a_typed_reason() -> None:
    error = PipelineError(FailureReason.NO_GUITAR_DETECTED, "stem was silent")

    assert error.reason is FailureReason.NO_GUITAR_DETECTED
    assert "stem was silent" in str(error)


def test_note_event_is_immutable() -> None:
    event = NoteEvent(onset=1.0, duration=0.5, midi=52, confidence=0.8)

    with pytest.raises(AttributeError):
        event.onset = 2.0  # type: ignore[misc]


def test_note_event_carries_no_fingering() -> None:
    """Stage 2 must not know about strings. Stage 4 decides fingering."""
    event = NoteEvent(onset=0.0, duration=0.1, midi=40, confidence=1.0)

    assert not hasattr(event, "string")
    assert not hasattr(event, "fret")


def test_a_fake_separator_satisfies_the_protocol() -> None:
    class FakeSeparator:
        def isolate(self, audio_path: Path) -> Path:
            return audio_path

    assert isinstance(FakeSeparator(), Separator)


def test_a_fake_transcriber_satisfies_the_protocol() -> None:
    class FakeTranscriber:
        def transcribe(self, stem_path: Path) -> list[NoteEvent]:
            return []

    assert isinstance(FakeTranscriber(), Transcriber)


def test_a_fake_structure_analyzer_satisfies_the_protocol() -> None:
    class FakeStructureAnalyzer:
        def analyze(self, stem_path: Path, mix_path: Path) -> StructureResult:
            return StructureResult(timing=Timing(), chords=[], sections=[])

    assert isinstance(FakeStructureAnalyzer(), StructureAnalyzer)


def test_a_fake_mapper_satisfies_the_protocol() -> None:
    class FakeMapper:
        def assign(
            self, notes: Sequence[NoteEvent], tuning: Sequence[str]
        ) -> list[TabNote]:
            return []

    assert isinstance(FakeMapper(), FretboardMapper)


def test_an_unrelated_object_does_not_satisfy_the_protocol() -> None:
    assert not isinstance(object(), Separator)
