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

import hashlib
import logging
import re
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any

from guitarvis_core.audio import probe_duration
from guitarvis_core.contracts import (
    FailureReason,
    FretboardMapper,
    IngestedAudio,
    PipelineError,
    Separator,
    StructureAnalyzer,
    Transcriber,
)
from guitarvis_fetch.catalog import LINKS_OFF_IN_QUEUE_MESSAGE
from guitarvis_fetch.fetcher import ChildFetcher, UrlFetcher, log_links_at_start
from guitarvis_fetch.links import Link, LinkRefused, parse
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
from guitarvis_worker.ingest import UploadSource, UrlSource
from guitarvis_worker.pipeline import ProgressCallback, StageProgress, run_pipeline
from guitarvis_worker.stages.fretboard import ViterbiFretboardMapper
from guitarvis_worker.stages.separation import DemucsSeparator
from guitarvis_worker.stages.structure import LibrosaStructureAnalyzer
from guitarvis_worker.stages.transcription import BasicPitchTranscriber
from guitarvis_worker.timeouts import JobTimedOut, JobTimeoutDeathPenalty

log = logging.getLogger(__name__)

# A link job's download fills its first 5%, and the pipeline's 0-100 is
# scaled onto the rest: a ten-minute song downloads in seconds and separates
# in minutes (spec 012).
DOWNLOAD_PERCENT = 5
_EXTENSION = re.compile(r"\.[a-z0-9]{1,5}")


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
    # None when links are off: a link job whose audio is not stored fails.
    fetcher: UrlFetcher | None = None
    max_download_bytes: int = Settings().max_upload_bytes
    probe: Callable[[Path], float] = probe_duration


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


class _LinkProgress:
    """A link job's percent: `download` fills 0-5, then the pipeline's 0-100
    is scaled onto 5-100. As for uploads, an update reaches the row only
    when the stage changes or the whole percent rises."""

    def __init__(self, writer: _ProgressWriter) -> None:
        self._writer = writer
        self._last: StageProgress | None = None

    def download(self, fraction: float) -> None:
        clamped = min(max(fraction, 0.0), 1.0)
        self._emit(StageProgress("download", int(clamped * DOWNLOAD_PERCENT)))

    def pipeline(self, update: StageProgress) -> None:
        share = update.percent * (100 - DOWNLOAD_PERCENT) // 100
        self._emit(StageProgress(update.stage, DOWNLOAD_PERCENT + share))

    def _emit(self, update: StageProgress) -> None:
        last = self._last
        if last is not None and (last.stage, last.percent) == (
            update.stage,
            max(last.percent, update.percent),
        ):
            return  # the same stage, and no whole percent gained
        self._last = update
        self._writer(update)


def process_job(job_id: str, deps: WorkerDeps, *, retries_left: int) -> None:
    """Run one delivery of a job. `retries_left` is RQ's count; 0 means last."""
    job = deps.store.get(job_id)
    if job is None:
        log.warning("job %s does not exist; dropping it", job_id)
        return
    if job.status in FINISHED_STATUSES:
        log.info("job %s is already %s; ignoring a repeat delivery", job_id, job.status)
        return
    started = deps.store.mark_running(job_id)
    if started is None:
        log.info("job %s finished elsewhere before it could start", job_id)
        return

    progress = _ProgressWriter(deps.store, job_id)
    try:
        result = _run(started, deps, progress)
        if result is None:  # S3: the row was failed while the audio was fetched
            log.warning("job %s was failed while it fetched; dropping it", job_id)
            return
        document, stem_key = result
        # Inside the try: a write that fails here is a failed attempt too,
        # not a row left running until reconciliation notices it.
        stored = deps.store.succeed(job_id, document=document, stem_key=stem_key)
    except PipelineError as error:
        if error.retryable:
            # It may pass: Demucs killed for memory, say, or a network that
            # dropped while fetching a link.
            _failed_attempt(job_id, deps, progress, retries_left, error)
            raise
        # The input's: another attempt gives the same answer. Returning
        # normally tells RQ not to retry.
        deps.store.fail(
            job_id,
            reason=error.reason,
            message=_shown(error),
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
    job_id: str,
    deps: WorkerDeps,
    progress: _ProgressWriter,
    retries_left: int,
    error: PipelineError | None = None,
) -> None:
    """Requeue the row for RQ's retry, or on the last attempt fail it.

    The caller re-raises, so RQ schedules the retry, or on the last attempt
    files the job in its FailedJobRegistry — the dead-letter queue — with the
    traceback. The row is what the user sees: the error's own reason and
    message when it has one that is not internal, so a fetch that kept
    failing ends as fetch_failed, with its own words.
    """
    if retries_left > 0:
        deps.store.requeue(job_id)
        return
    reason = FailureReason.INTERNAL if error is None else error.reason
    deps.store.fail(
        job_id,
        reason=reason,
        message=INTERNAL_FAILURE_MESSAGE if error is None else _shown(error),
        stage=progress.stage,
        expect=JobStatus.RUNNING,
    )


def _shown(error: PipelineError) -> str:
    """What the row says: an internal error's detail is for the log only."""
    if error.reason is FailureReason.INTERNAL:
        return INTERNAL_FAILURE_MESSAGE
    return str(error)


def _run(
    job: Job, deps: WorkerDeps, progress: _ProgressWriter
) -> tuple[dict[str, Any], str] | None:
    """The document and the stem's key; None when the row was failed while
    a link's audio was fetched."""
    link_progress = None if job.source_url is None else _LinkProgress(progress)
    report: ProgressCallback = (
        progress if link_progress is None else link_progress.pipeline
    )
    with tempfile.TemporaryDirectory(prefix="guitarvis-job-") as tmp:
        work_dir = Path(tmp)
        if job.upload_key is not None:
            # An upload, exactly as before links; or a link job retried after
            # its download was kept, so YouTube is not asked again and the
            # switch does not apply.
            audio = _stored_audio(job, job.upload_key, deps, work_dir)
            content_hash = (
                job.content_hash
                if job.source_url is None
                else PurePosixPath(job.upload_key).stem
            )
        else:
            fetched = _fetch(
                job, deps, work_dir, link_progress or _LinkProgress(progress)
            )
            if fetched is None:
                return None
            audio, content_hash = fetched
        # Cached by the bytes, never by the video: a stem from one download
        # must not meet the mix from another, whose encoder delay may differ.
        keys = CacheKeys(content_hash)
        stages = deps.stages(work_dir)
        result = run_pipeline(
            audio,
            separator=CachedSeparator(stages.separator, deps.blobs, keys, work_dir),
            transcriber=CachedTranscriber(stages.transcriber, deps.blobs, keys),
            analyzer=CachedAnalyzer(stages.analyzer, deps.blobs, keys),
            mapper=stages.mapper,
            progress=report,
            audio_url=f"/jobs/{job.id}/audio/mix",
        )
    return result.document.model_dump(mode="json"), keys.stem


def _stored_audio(
    job: Job, upload_key: str, deps: WorkerDeps, work_dir: Path
) -> IngestedAudio:
    upload = work_dir / f"upload{PurePosixPath(upload_key).suffix}"
    deps.blobs.get_file(upload_key, upload)
    # Probed again here: the worker must not trust its caller.
    return replace(UploadSource(upload).fetch(), title=job.title)


def _fetch(
    job: Job, deps: WorkerDeps, work_dir: Path, progress: _LinkProgress
) -> tuple[IngestedAudio, str] | None:
    """Download a link job's audio, store it as an upload is stored, and
    record its key. The audio and the hash of its bytes; None when the row
    is no longer running.

    The failure catalog's rows (spec 012), and what each does here:

    - W1, links off and nothing stored: `links_disabled`, logged at INFO, not
      retried (another attempt finds the switch as it is).
    - W2, D1-D10 and P1-P2: UrlSource's. It logs each once and raises the
      catalog's PipelineError, whose `retryable` is the catalog's rule: only
      D1, D2, D7, D8, D9 and D10 are retried by RQ.
    - P3, no ffprobe: `internal`, retried. S1, the store fails, and S2, the key
      cannot be recorded: the exception propagates, so RQ retries (S1 then
      downloads again) and logs it at ERROR, and the last attempt fails the
      row `internal`.
    - S3, the row was failed meanwhile, which `attach_upload` reports by
      returning False: None, and process_job logs "dropping" at WARNING.

    Nothing yt-dlp said is in any message: those are the catalog's.
    """
    if deps.fetcher is None:  # W1
        # The catalog's INFO line. The link is the row's, so it is not here.
        log.info(
            "job %s is a link job and links are off, and its audio was never stored",
            job.id,
        )
        raise PipelineError(FailureReason.LINKS_DISABLED, LINKS_OFF_IN_QUEUE_MESSAGE)
    progress.download(0.0)
    audio = UrlSource(
        _link_of(job),
        work_dir,
        deps.fetcher,
        max_bytes=deps.max_download_bytes,
        progress=progress.download,
        probe=deps.probe,
        job_id=job.id,
        attempt=job.attempts,
    ).fetch()
    content_hash = _sha256(audio.path)
    suffix = audio.path.suffix.lower()
    key = f"uploads/{content_hash}{suffix if _EXTENSION.fullmatch(suffix) else ''}"
    if not deps.blobs.exists(key):
        deps.blobs.put_file(key, audio.path)  # S1: a failure is retried
    if not deps.store.attach_upload(  # S2: a failure is retried
        job.id, upload_key=key, duration_sec=audio.duration_sec
    ):
        return None  # S3
    return replace(audio, title=job.title), content_hash


def _link_of(job: Job) -> Link:
    if job.source_url is None:
        raise PipelineError(FailureReason.INTERNAL, f"job {job.id} has no audio")
    try:
        return parse(job.source_url)
    except LinkRefused as error:  # the api stored it canonical: ours
        raise PipelineError(
            FailureReason.INTERNAL, f"job {job.id}'s link is {error.kind}"
        ) from error


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


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
            fetcher=ChildFetcher() if settings.url_ingestion else None,
            max_download_bytes=settings.max_upload_bytes,
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
    log_links_at_start(log, settings.url_ingestion)
    connection = Redis.from_url(settings.redis_url)
    JobWorker([QUEUE_NAME], connection=connection).work(
        with_scheduler=True, burst=burst
    )
