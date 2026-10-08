"""The queue's entry point: one job, end to end, against the shared stores.

`run_job` is what RQ calls, found by the dotted path in
guitarvis_jobs.queue.RUN_JOB. It is a thin adapter: it reads how many
retries RQ has left and hands off to `process_job`, which tests drive
directly with in-memory stores and stub stages.

RQ delivers at least once, so a second delivery of a finished job must be
harmless. The api's reconciliation can fail a row behind the worker's back,
so every write after the job starts is conditional on the row still being
running; when one changes nothing, the worker logs and drops its result.
"""

import logging
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any

from guitarvis_core.contracts import (
    FailureReason,
    FretboardMapper,
    PipelineError,
    Separator,
    StructureAnalyzer,
    Transcriber,
)
from guitarvis_jobs.blobs import BlobStore, S3BlobStore
from guitarvis_jobs.models import (
    FINISHED_STATUSES,
    INTERNAL_FAILURE_MESSAGE,
    Job,
    JobStatus,
)
from guitarvis_jobs.postgres import PostgresJobStore
from guitarvis_jobs.queue import QUEUE_NAME
from guitarvis_jobs.settings import Settings
from guitarvis_jobs.store import JobStore
from redis import Redis
from rq import Worker, get_current_job

from guitarvis_worker.caching import (
    CachedAnalyzer,
    CachedSeparator,
    CachedTranscriber,
    CacheKeys,
)
from guitarvis_worker.ingest import UploadSource
from guitarvis_worker.pipeline import StageProgress, run_pipeline
from guitarvis_worker.stages.fretboard import ViterbiFretboardMapper
from guitarvis_worker.stages.separation import DemucsSeparator
from guitarvis_worker.stages.structure import LibrosaStructureAnalyzer
from guitarvis_worker.stages.transcription import BasicPitchTranscriber
from guitarvis_worker.timeouts import JobTimedOut, JobTimeoutDeathPenalty

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Stages:
    separator: Separator
    transcriber: Transcriber
    analyzer: StructureAnalyzer
    mapper: FretboardMapper


def build_stages(work_dir: Path, device: str | None = None) -> Stages:
    """The real stages. Tests patch this name, as test_cli patches cli's."""
    return Stages(
        separator=DemucsSeparator(work_dir=work_dir, device=device),
        transcriber=BasicPitchTranscriber(),
        analyzer=LibrosaStructureAnalyzer(),
        mapper=ViterbiFretboardMapper(),
    )


@dataclass(frozen=True)
class WorkerDeps:
    store: JobStore
    blobs: BlobStore
    stages: Callable[[Path], Stages]


class _ProgressWriter:
    """Writes each progress update to the row and remembers the stage running.

    All but 100, which `succeed` writes together with the status: a write
    that fails between the two would show 100% and then a retry.
    """

    def __init__(self, store: JobStore, job_id: str) -> None:
        self._store = store
        self._job_id = job_id
        self._warned = False
        self.stage: str | None = None

    def __call__(self, update: StageProgress) -> None:
        self.stage = update.stage
        if update.percent >= 100:
            return
        if self._store.set_progress(self._job_id, update.stage, update.percent):
            return
        if not self._warned:
            self._warned = True
            log.warning(
                "job %s is no longer running; its progress is not recorded",
                self._job_id,
            )


def process_job(job_id: str, deps: WorkerDeps, *, retries_left: int) -> None:
    """Run one delivery of a job. `retries_left` is RQ's count; 0 means last."""
    job = deps.store.get(job_id)
    if job is None:
        log.warning("job %s does not exist; dropping it", job_id)
        return
    if job.status in FINISHED_STATUSES:
        log.info("job %s is already %s; ignoring a repeat delivery", job_id, job.status)
        return
    if deps.store.mark_running(job_id) is None:
        log.info("job %s finished elsewhere before it could start", job_id)
        return

    progress = _ProgressWriter(deps.store, job_id)
    try:
        document, stem_key = _run(job, deps, progress)
        # Inside the try: a write that fails here is a failed attempt too,
        # not a row left running until reconciliation notices it.
        stored = deps.store.succeed(job_id, document=document, stem_key=stem_key)
    except PipelineError as error:
        if error.reason is FailureReason.INTERNAL:
            # Ours, not the file's — Demucs killed for memory, say — so it
            # may pass, and its detail is for the log, not the user.
            _failed_attempt(job_id, deps, progress, retries_left)
            raise
        # The file's: another attempt gives the same answer. Returning
        # normally tells RQ not to retry.
        deps.store.fail(
            job_id,
            reason=error.reason,
            message=str(error),
            stage=progress.stage,
            expect=JobStatus.RUNNING,
        )
        return
    except (Exception, JobTimedOut):
        # JobTimedOut is the job timeout. It is not an Exception, so no stage
        # degraded it into a warning, but here it is one more failed attempt.
        _failed_attempt(job_id, deps, progress, retries_left)
        raise

    if not stored:
        log.warning("job %s was failed while it ran; dropping its result", job_id)


def _failed_attempt(
    job_id: str, deps: WorkerDeps, progress: _ProgressWriter, retries_left: int
) -> None:
    """Requeue the row for RQ's retry, or on the last attempt fail it.

    The caller re-raises, so RQ schedules the retry, or on the last attempt
    files the job in its FailedJobRegistry — the dead-letter queue — with the
    traceback. The row is what the user sees.
    """
    if retries_left > 0:
        deps.store.requeue(job_id)
        return
    deps.store.fail(
        job_id,
        reason=FailureReason.INTERNAL,
        message=INTERNAL_FAILURE_MESSAGE,
        stage=progress.stage,
        expect=JobStatus.RUNNING,
    )


def _run(
    job: Job, deps: WorkerDeps, progress: _ProgressWriter
) -> tuple[dict[str, Any], str]:
    keys = CacheKeys(job.content_hash)
    with tempfile.TemporaryDirectory(prefix="guitarvis-job-") as tmp:
        work_dir = Path(tmp)
        upload = work_dir / f"upload{PurePosixPath(job.upload_key).suffix}"
        deps.blobs.get_file(job.upload_key, upload)
        # Probed again here: the worker must not trust its caller.
        audio = replace(UploadSource(upload).fetch(), title=job.title)
        stages = deps.stages(work_dir)
        result = run_pipeline(
            audio,
            separator=CachedSeparator(stages.separator, deps.blobs, keys, work_dir),
            transcriber=CachedTranscriber(stages.transcriber, deps.blobs, keys),
            analyzer=CachedAnalyzer(stages.analyzer, deps.blobs, keys),
            mapper=stages.mapper,
            progress=progress,
            audio_url=f"/jobs/{job.id}/audio/mix",
        )
    return result.document.model_dump(mode="json"), keys.stem


def run_job(job_id: str) -> None:
    """RQ's entry point, enqueued by name (guitarvis_jobs.queue.RUN_JOB)."""
    current = get_current_job()
    retries_left = (
        current.retries_left
        if current is not None and current.retries_left is not None
        else 0
    )
    with open_deps(Settings.from_env()) as deps:
        process_job(job_id, deps, retries_left=retries_left)


@contextmanager
def open_deps(settings: Settings) -> Iterator[WorkerDeps]:
    """Real stores for one job.

    Built per job: each job runs in a forked work horse, and a database
    engine must not cross a fork with connections in its pool.
    """
    store = PostgresJobStore.from_url(settings.database_url)
    try:
        yield WorkerDeps(
            store=store,
            blobs=S3BlobStore.from_settings(settings),
            stages=lambda work_dir: build_stages(work_dir, settings.device),
        )
    finally:
        store.engine.dispose()


class JobWorker(Worker):
    """RQ's forking worker, whose job timeout no stage's handler can catch."""

    death_penalty_class = JobTimeoutDeathPenalty


def serve(settings: Settings, *, burst: bool = False) -> None:
    """Run jobs from the queue until stopped (or, with `burst`, until empty).

    The scheduler is on because RQ needs it to run retries after their
    intervals.
    """
    connection = Redis.from_url(settings.redis_url)
    JobWorker([QUEUE_NAME], connection=connection).work(
        with_scheduler=True, burst=burst
    )
