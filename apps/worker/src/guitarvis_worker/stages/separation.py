"""Stage 1 — separation. Demucs htdemucs_6s, which has a dedicated guitar stem.

Output is normalised to 44.1kHz mono. When the guitar stem comes back empty or
near-silent — common when a heavily distorted guitar is attributed elsewhere —
the implementation falls back to the 4-stem `other` track and marks the
document with a quality warning. This stage dominates job time.
"""

from pathlib import Path
from typing import TYPE_CHECKING


class DemucsSeparator:
    """Implements guitarvis_core.contracts.Separator."""

    def isolate(self, audio_path: Path) -> Path:
        raise NotImplementedError(
            "Stage 1 lands in 003-pipeline-skeleton; see "
            "docs/specs/001-guitarvis-design/spec.md"
        )


if TYPE_CHECKING:  # Static conformance: isinstance compares method names
    from guitarvis_core.contracts import Separator  # only, so this

    _conforms: Separator = DemucsSeparator()  # assignment is what
    # actually checks the signature.
