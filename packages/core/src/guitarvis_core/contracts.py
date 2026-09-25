"""What the pipeline stages promise each other.

Each stage takes and returns plain data, and no stage knows what runs before or
after it. The worker orchestrates. Keeping these declarations in core — rather
than in the worker that implements them — is what lets tests, the api, and a
future desktop build reason about the pipeline without importing torch.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable

from guitarvis_core.tabdoc import Chord, Section, Timing


class FailureReason(StrEnum):
    """Why a job failed, in terms the UI can turn into actionable text.

    The user needs to know whether to try a different file, a different song,
    or come back later.
    """

    UNSUPPORTED_FORMAT = "unsupported_format"
    NO_GUITAR_DETECTED = "no_guitar_detected"
    TOO_LONG = "too_long"
    FETCH_FAILED = "fetch_failed"
    INTERNAL = "internal"


class PipelineError(Exception):
    """A job failure carrying a typed reason."""

    def __init__(self, reason: FailureReason, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class NoteEvent:
    """Stage 2 output: a pitch in time, with no opinion about fingering.

    Deliberately not string/fret, so a guitar-specific transcription model can
    later implement Transcriber without changing anything downstream.
    """

    onset: float
    duration: float
    midi: int
    confidence: float


@dataclass(frozen=True)
class TabNote:
    """Stage 4 output: a NoteEvent placed on the neck."""

    onset: float
    duration: float
    midi: int
    string: int
    fret: int
    confidence: float


@dataclass(frozen=True)
class StructureResult:
    """Stage 3 output. Any field may be empty; the UI omits what is missing."""

    timing: Timing
    chords: list[Chord]
    sections: list[Section]


@dataclass(frozen=True)
class IngestedAudio:
    """What every way of getting audio into the system produces.

    URL fetching is another implementation of AudioSource and changes nothing
    downstream — the isolation the design spec asks for, expressed as a type.
    """

    path: Path
    title: str
    duration_sec: float


@dataclass(frozen=True)
class SeparationResult:
    """Stage 1 output. `warnings` carries degradation the client must show.

    A bare Path cannot say "this came from the 4-stem fallback and may contain
    other instruments", and putting that on the separator instance would make a
    stateless stage stateful.
    """

    stem_path: Path
    warnings: list[str] = field(default_factory=list)


@runtime_checkable
class AudioSource(Protocol):
    """Ingestion: produce a local audio file and its metadata."""

    def fetch(self) -> IngestedAudio: ...


@runtime_checkable
class Separator(Protocol):
    """Stage 1: isolate the guitar from a mix."""

    def isolate(self, audio_path: Path) -> SeparationResult: ...


@runtime_checkable
class Transcriber(Protocol):
    """Stage 2: turn an isolated stem into pitched events."""

    def transcribe(self, stem_path: Path) -> list[NoteEvent]: ...


@runtime_checkable
class StructureAnalyzer(Protocol):
    """Stage 3: beats and chords.

    Takes both the stem and the original mix: drums are the strongest beat cue,
    and the stem has them removed.
    """

    def analyze(self, stem_path: Path, mix_path: Path) -> StructureResult: ...


@runtime_checkable
class FretboardMapper(Protocol):
    """Stage 4: place pitches on the neck. Deterministic, never learned."""

    def assign(
        self, notes: Sequence[NoteEvent], tuning: Sequence[str]
    ) -> list[TabNote]: ...
