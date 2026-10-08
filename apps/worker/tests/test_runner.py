"""One delivery of one job: the runner's contract with RQ and the job row.

process_job is driven directly, with in-memory stores and stub stages; the
end-to-end test (test_end_to_end.py) runs it under a real RQ worker.
"""

import importlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from guitarvis_core.contracts import (
    FailureReason,
    IngestedAudio,
    NoteEvent,
    PipelineError,
    SeparationProgress,
    SeparationResult,
    StructureResult,
)
from guitarvis_core.tabdoc import TabDocument, Timing
from guitarvis_jobs.blobs import InMemoryBlobStore
from guitarvis_jobs.models import INTERNAL_FAILURE_MESSAGE, Job, JobStatus
from guitarvis_jobs.queue import RUN_JOB
from guitarvis_jobs.store import InMemoryJobStore
from guitarvis_jobs.testing import sample_new_job
from guitarvis_worker import runner
from guitarvis_worker.caching import CacheKeys
from guitarvis_worker.runner import Stages, WorkerDeps, process_job
from guitarvis_worker.stages.fretboard import ViterbiFretboardMapper


class StubSeparator:
    def __init__(self) -> None:
        self.calls = 0
        self.error: Exception | None = None

    def isolate(
        self, audio_path: Path, *, progress: SeparationProgress | None = None
    ) -> SeparationResult:
        self.calls += 1
        if self.error is not None:
            raise self.error
        if progress is not None:
            progress(0.5)
        return SeparationResult(stem_path=audio_path)


class StubTranscriber:
    def __init__(self) -> None:
        self.during: Callable[[], None] | None = None

    def transcribe(self, stem_path: Path) -> list[NoteEvent]:
        if self.during is not None:
            self.during()
        return [NoteEvent(onset=1.0, duration=0.5, midi=52, confidence=0.8)]


class StubAnalyzer:
    def analyze(self, stem_path: Path, mix_path: Path) -> StructureResult:
        return StructureResult(timing=Timing(), chords=[], sections=[])


class StubAudioSource:
    """Stands in for UploadSource, so these tests need no ffprobe."""

    def __init__(self, path: Path | str, **kwargs: object) -> None:
        self._path = Path(path)

    def fetch(self) -> IngestedAudio:
        return IngestedAudio(path=self._path, title=self._path.stem, duration_sec=30.0)


@dataclass
class Harness:
    store: InMemoryJobStore
    blobs: InMemoryBlobStore
    separator: StubSeparator
    transcriber: StubTranscriber
    job_id: str

    def deps(self) -> WorkerDeps:
        return WorkerDeps(
            store=self.store,
            blobs=self.blobs,
            stages=lambda work_dir: Stages(
                separator=self.separator,
                transcriber=self.transcriber,
                analyzer=StubAnalyzer(),
                mapper=ViterbiFretboardMapper(),
            ),
        )

    def run(self, retries_left: int = 2) -> None:
        process_job(self.job_id, self.deps(), retries_left=retries_left)

    def row(self) -> Job:
        row = self.store.get(self.job_id)
        assert row is not None
        return row


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    monkeypatch.setattr(runner, "UploadSource", StubAudioSource)
    store = InMemoryJobStore()
    blobs = InMemoryBlobStore()
    job, _ = store.create(sample_new_job(title="My Song"))
    blobs.put_bytes(job.upload_key, b"pretend mp3 bytes")
    return Harness(store, blobs, StubSeparator(), StubTranscriber(), job.id)


def test_a_job_runs_to_a_stored_document(harness: Harness) -> None:
    harness.run()

    row = harness.row()
    assert row.status is JobStatus.SUCCEEDED
    assert (row.stage, row.percent, row.attempts) == (None, 100, 1)
    document = TabDocument.model_validate(row.document)
    assert document.source.title == "My Song"  # the row's, not the temp file's
    assert document.source.audio_url == f"/jobs/{row.id}/audio/mix"
    assert len(document.notes) == 1
    assert row.stem_key == CacheKeys(row.content_hash).stem
    assert harness.blobs.get_bytes(row.stem_key) == b"pretend mp3 bytes"


def test_progress_reaches_the_row_while_the_job_runs(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[str, int]] = []
    write = harness.store.set_progress

    def recording(job_id: str, stage: str, percent: int) -> bool:
        seen.append((stage, percent))
        return write(job_id, stage, percent)

    monkeypatch.setattr(harness.store, "set_progress", recording)
    harness.run()

    assert seen == [
        ("separation", 0),
        ("separation", 20),
        ("transcription", 40),
        ("structure", 65),
        ("fretboard", 80),
        ("fretboard", 100),
    ]


def test_a_pipeline_error_fails_the_job_without_a_retry(harness: Harness) -> None:
    harness.separator.error = PipelineError(
        FailureReason.NO_GUITAR_DETECTED,
        "No clear guitar part was found in this recording.",
    )

    harness.run()  # returns normally, which tells RQ not to retry

    row = harness.row()
    assert row.status is JobStatus.FAILED
    assert row.failure_reason is FailureReason.NO_GUITAR_DETECTED
    assert row.failure_message == "No clear guitar part was found in this recording."
    assert row.failed_stage == "separation"
    assert row.stage is None


def test_a_file_the_worker_rejects_fails_before_any_stage(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    class TooLong(StubAudioSource):
        def fetch(self) -> IngestedAudio:
            raise PipelineError(FailureReason.TOO_LONG, "Try a single song.")

    monkeypatch.setattr(runner, "UploadSource", TooLong)

    harness.run()

    row = harness.row()
    assert row.failure_reason is FailureReason.TOO_LONG
    assert row.failed_stage is None
    assert harness.separator.calls == 0


def test_another_exception_with_retries_left_requeues_and_reraises(
    harness: Harness,
) -> None:
    harness.separator.error = RuntimeError("storage blinked")

    with pytest.raises(RuntimeError):
        harness.run(retries_left=1)

    row = harness.row()
    assert row.status is JobStatus.QUEUED
    assert (row.stage, row.percent, row.attempts) == (None, 0, 1)


def test_the_last_attempt_fails_internal_and_reraises(harness: Harness) -> None:
    harness.separator.error = RuntimeError("still broken")

    with pytest.raises(RuntimeError):  # RQ files it in FailedJobRegistry
        harness.run(retries_left=0)

    row = harness.row()
    assert row.status is JobStatus.FAILED
    assert row.failure_reason is FailureReason.INTERNAL
    assert row.failure_message == INTERNAL_FAILURE_MESSAGE
    assert row.failed_stage == "separation"


def test_a_finished_job_delivered_again_is_left_alone(harness: Harness) -> None:
    harness.run()
    before = harness.row()

    harness.run()

    assert harness.row() == before
    assert harness.separator.calls == 1


def test_a_retry_resumes_from_the_cached_separation(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec success condition 3: a worker that crashes after separation, then
    succeeds on retry, does not run separation twice."""
    write = harness.store.set_progress
    crashed: list[bool] = []

    def crash_once_when_transcription_starts(
        job_id: str, stage: str, percent: int
    ) -> bool:
        if stage == "transcription" and not crashed:
            crashed.append(True)
            raise ConnectionError("postgres went away")
        return write(job_id, stage, percent)

    monkeypatch.setattr(
        harness.store, "set_progress", crash_once_when_transcription_starts
    )

    with pytest.raises(ConnectionError):
        harness.run(retries_left=2)
    assert harness.row().status is JobStatus.QUEUED

    harness.run(retries_left=1)

    row = harness.row()
    assert row.status is JobStatus.SUCCEEDED
    assert row.attempts == 2
    assert harness.separator.calls == 1


def test_a_row_left_running_by_a_killed_worker_is_resumed(harness: Harness) -> None:
    """Review Focus 4: SIGKILL means no except ran; RQ redelivers anyway."""
    harness.store.mark_running(harness.job_id)

    harness.run(retries_left=1)

    row = harness.row()
    assert row.status is JobStatus.SUCCEEDED
    assert row.attempts == 2


def test_a_result_after_the_row_was_failed_is_dropped(harness: Harness) -> None:
    def reconciled_behind_our_back() -> None:
        harness.store.fail(
            harness.job_id,
            reason=FailureReason.INTERNAL,
            message="lost",
            stage="transcription",
            expect=JobStatus.RUNNING,
        )

    harness.transcriber.during = reconciled_behind_our_back

    harness.run()  # no exception: the late result is logged and dropped

    row = harness.row()
    assert row.status is JobStatus.FAILED
    assert row.failure_message == "lost"
    assert row.document is None


def test_an_unknown_job_is_dropped(harness: Harness) -> None:
    process_job("5f0c6c2e-0000-4000-8000-0000000000ff", harness.deps(), retries_left=2)

    assert harness.separator.calls == 0


def test_the_dotted_path_the_api_enqueues_is_run_job() -> None:
    # Renaming or moving run_job must fail here, not in every queued job.
    module_name, _, function_name = RUN_JOB.rpartition(".")

    assert (
        getattr(importlib.import_module(module_name), function_name) is runner.run_job
    )


@pytest.mark.parametrize(
    ("current", "expected"), [(SimpleNamespace(retries_left=1), 1), (None, 0)]
)
def test_run_job_hands_rq_retries_left_to_process_job(
    monkeypatch: pytest.MonkeyPatch, current: object, expected: int
) -> None:
    seen: dict[str, object] = {}

    @contextmanager
    def fake_deps(settings: object) -> Iterator[str]:
        yield "deps"

    def fake_process(job_id: str, deps: object, *, retries_left: int) -> None:
        seen.update(job_id=job_id, deps=deps, retries_left=retries_left)

    monkeypatch.setattr(runner, "get_current_job", lambda: current)
    monkeypatch.setattr(runner, "open_deps", fake_deps)
    monkeypatch.setattr(runner, "process_job", fake_process)

    runner.run_job("abc")

    # Outside RQ (no current job) the attempt is treated as the last one.
    assert seen == {"job_id": "abc", "deps": "deps", "retries_left": expected}
