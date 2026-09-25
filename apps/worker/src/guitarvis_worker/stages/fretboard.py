"""Stage 4 — fretboard assignment. The deterministic core.

Notes within roughly 50ms group into a voicing; each voicing has a set of
playable combinations filtered by physical constraints; a Viterbi pass
minimises total cost, dominated by hand-position movement between consecutive
voicings because real players stay put.

Testable without audio: feed note sequences, assert fingerings. Every note it
emits must satisfy guitarvis_core.fretboard.check_invariant.
"""

from collections.abc import Sequence

from guitarvis_core.contracts import NoteEvent, TabNote


class ViterbiFretboardMapper:
    """Implements guitarvis_core.contracts.FretboardMapper."""

    def assign(
        self, notes: Sequence[NoteEvent], tuning: Sequence[str]
    ) -> list[TabNote]:
        raise NotImplementedError(
            "Stage 4 lands in 004-fretboard-mapper; see "
            "docs/specs/001-guitarvis-design/spec.md"
        )
