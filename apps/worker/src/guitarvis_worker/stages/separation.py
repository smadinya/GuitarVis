"""Stage 1 — separation. Demucs htdemucs_6s, which has a dedicated guitar stem.

Output is normalised to 44.1kHz mono. When the guitar stem comes back empty or
near-silent — common when a heavily distorted guitar is attributed elsewhere —
the implementation falls back to the 4-stem `other` track and marks the
document with a quality warning. This stage dominates job time.
"""

from pathlib import Path


class DemucsSeparator:
    """Implements guitarvis_core.contracts.Separator."""

    def isolate(self, audio_path: Path) -> Path:
        raise NotImplementedError(
            "Stage 1 lands in 003-pipeline-skeleton; see "
            "docs/specs/001-guitarvis-design/spec.md"
        )
