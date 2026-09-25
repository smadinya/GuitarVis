"""Every stage stub satisfies its protocol and refuses to pretend it works.

The classes exist before their bodies so that the shape of the pipeline is
reviewable, and type-checked, before any model is installed. The
NotImplementedError assertions are what stop a stub from being mistaken for a
working stage during phase 1.
"""

import ast
from pathlib import Path

import pytest
from guitarvis_core.contracts import (
    FretboardMapper,
    Separator,
    StructureAnalyzer,
    Transcriber,
)
from guitarvis_core.tabdoc import STANDARD_TUNING
from guitarvis_worker.stages.fretboard import ViterbiFretboardMapper
from guitarvis_worker.stages.separation import DemucsSeparator
from guitarvis_worker.stages.structure import LibrosaStructureAnalyzer
from guitarvis_worker.stages.transcription import BasicPitchTranscriber

FORBIDDEN_ROOTS = {"torch", "demucs", "basic_pitch", "librosa", "numpy"}
STAGES_DIR = Path(__file__).resolve().parents[1] / "src" / "guitarvis_worker" / "stages"
STAGE_MODULES = [
    STAGES_DIR / "separation.py",
    STAGES_DIR / "transcription.py",
    STAGES_DIR / "structure.py",
    STAGES_DIR / "fretboard.py",
]


def module_level_imported_roots(source_file: Path) -> set[str]:
    """Top-level import roots only — mirrors apps/api/tests/test_boundaries.py,
    but deliberately does NOT `ast.walk` into nested scopes. A heavy import
    inside a method body (e.g. `def isolate(self, ...): import torch`) is the
    convention this repo wants — CONVENTIONS.md requires heavy imports to be
    deferred into the method that uses them — so only `tree.body`, the
    statements that execute at import time, are scanned.
    """
    tree = ast.parse(source_file.read_text(), filename=str(source_file))
    roots: set[str] = set()

    for node in tree.body:
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])

    return roots


# Static conformance: isinstance compares method names only, so these typed
# assignments are what actually make mypy check the stage signatures.
_separator: Separator = DemucsSeparator()
_transcriber: Transcriber = BasicPitchTranscriber()
_analyzer: StructureAnalyzer = LibrosaStructureAnalyzer()
_mapper: FretboardMapper = ViterbiFretboardMapper()


def test_stages_satisfy_their_protocols() -> None:
    assert isinstance(DemucsSeparator(), Separator)
    assert isinstance(BasicPitchTranscriber(), Transcriber)
    assert isinstance(LibrosaStructureAnalyzer(), StructureAnalyzer)
    assert isinstance(ViterbiFretboardMapper(), FretboardMapper)


def test_fretboard_is_not_implemented_yet() -> None:
    """Stage 4 names a different spec: the parent spec's build phase 2 pairs the
    mapper with the evaluation harness that measures it."""
    with pytest.raises(NotImplementedError, match="004-fretboard-mapper"):
        ViterbiFretboardMapper().assign([], STANDARD_TUNING)


def test_stage_modules_do_not_import_the_ml_stack_at_module_level() -> None:
    """Heavy imports belong inside the methods that use them.

    uv sync installs the worker without its ml extra, so a module-level
    `import torch` would break collection of this very test file.

    This is an AST scan rather than an import-and-check: once phase 1
    installs the `ml` extra, `import torch` at module level would import
    successfully and a "does it import cleanly" check would pass right past
    the violation it exists to catch. The scan is environment-independent —
    it fails whether or not torch is installed.
    """
    offenders: dict[str, set[str]] = {}

    for source_file in STAGE_MODULES:
        forbidden = module_level_imported_roots(source_file) & FORBIDDEN_ROOTS
        if forbidden:
            offenders[str(source_file)] = forbidden

    assert offenders == {}, (
        f"stage modules must defer ML imports into their methods, but found "
        f"module-level imports: {offenders}"
    )
