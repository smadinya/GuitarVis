"""Stage 2 — transcription. Was planned to start as basic-pitch: polyphonic,
CPU-runnable, and it emits per-note activation strength that maps to
confidence. basic-pitch 0.4.0 cannot install on this project's Python 3.12
(it requires tensorflow<2.15.1, and no cp312 wheel of that tensorflow
exists), so the actual backend is an open choice for 003-pipeline-skeleton —
see the comment in apps/worker/pyproject.toml. The class name
`BasicPitchTranscriber` below is therefore provisional, kept only because
Task 7's tests and the plan already reference it; it does not commit this
stage to the basic-pitch backend.

Returns NoteEvent and deliberately not string/fret, so a guitar-specific model
can implement the same interface later. This is the single upgrade point the
staged architecture exists to protect.
"""

from pathlib import Path
from typing import TYPE_CHECKING

from guitarvis_core.contracts import NoteEvent


class BasicPitchTranscriber:
    """Implements guitarvis_core.contracts.Transcriber.

    Name is provisional pending the backend choice described in the module
    docstring above.
    """

    def transcribe(self, stem_path: Path) -> list[NoteEvent]:
        raise NotImplementedError(
            "Stage 2 lands in 003-pipeline-skeleton; see "
            "docs/specs/001-guitarvis-design/spec.md"
        )


if TYPE_CHECKING:  # Static conformance: isinstance compares method names
    from guitarvis_core.contracts import Transcriber  # only, so this

    _conforms: Transcriber = BasicPitchTranscriber()  # assignment is what
    # actually checks the signature.
