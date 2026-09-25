"""Every stage stub satisfies its protocol and refuses to pretend it works.

The classes exist before their bodies so that the shape of the pipeline is
reviewable, and type-checked, before any model is installed. The
NotImplementedError assertions are what stop a stub from being mistaken for a
working stage during phase 1.
"""

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


def test_separation_is_not_implemented_yet() -> None:
    with pytest.raises(NotImplementedError, match="003-pipeline-skeleton"):
        DemucsSeparator().isolate(Path("song.wav"))


def test_transcription_is_not_implemented_yet() -> None:
    with pytest.raises(NotImplementedError, match="003-pipeline-skeleton"):
        BasicPitchTranscriber().transcribe(Path("stem.wav"))


def test_structure_is_not_implemented_yet() -> None:
    with pytest.raises(NotImplementedError, match="003-pipeline-skeleton"):
        LibrosaStructureAnalyzer().analyze(Path("stem.wav"), Path("mix.wav"))


def test_fretboard_is_not_implemented_yet() -> None:
    """Stage 4 names a different spec: the parent spec's build phase 2 pairs the
    mapper with the evaluation harness that measures it."""
    with pytest.raises(NotImplementedError, match="004-fretboard-mapper"):
        ViterbiFretboardMapper().assign([], STANDARD_TUNING)


def test_stage_modules_do_not_import_the_ml_stack_at_module_level() -> None:
    """Heavy imports belong inside the methods that use them.

    uv sync installs the worker without its ml extra, so a module-level
    `import torch` would break collection of this very test file.
    """
    import guitarvis_worker.stages.separation as separation

    assert separation is not None
