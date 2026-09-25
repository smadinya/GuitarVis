"""Stage 2 — transcription. Starts as basic-pitch: polyphonic, CPU-runnable,
and it emits per-note activation strength that maps to confidence.

Returns NoteEvent and deliberately not string/fret, so a guitar-specific model
can implement the same interface later. This is the single upgrade point the
staged architecture exists to protect.
"""

from pathlib import Path

from guitarvis_core.contracts import NoteEvent


class BasicPitchTranscriber:
    """Implements guitarvis_core.contracts.Transcriber."""

    def transcribe(self, stem_path: Path) -> list[NoteEvent]:
        raise NotImplementedError(
            "Stage 2 lands in 003-pipeline-skeleton; see "
            "docs/specs/001-guitarvis-design/spec.md"
        )
