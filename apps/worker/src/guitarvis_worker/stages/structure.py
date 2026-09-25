"""Stage 3 — musical structure.

Beat and downbeat tracking run on the original mix, not the guitar stem: drums
are the strongest beat cue and the stem has them removed. Chord detection runs
on the stem via chroma template matching. Section labels are optional; when
unreliable the field stays empty and the UI omits them.
"""

from pathlib import Path
from typing import TYPE_CHECKING

from guitarvis_core.contracts import StructureResult


class LibrosaStructureAnalyzer:
    """Implements guitarvis_core.contracts.StructureAnalyzer."""

    def analyze(self, stem_path: Path, mix_path: Path) -> StructureResult:
        raise NotImplementedError(
            "Stage 3 lands in 003-pipeline-skeleton; see "
            "docs/specs/001-guitarvis-design/spec.md"
        )


if TYPE_CHECKING:  # Static conformance: isinstance compares method names
    from guitarvis_core.contracts import StructureAnalyzer  # only, so this

    _conforms: StructureAnalyzer = LibrosaStructureAnalyzer()  # assignment is
    # what actually checks the signature.
