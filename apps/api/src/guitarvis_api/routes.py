"""Every route. Plain `def`: the work is blocking I/O, which FastAPI runs in
its threadpool."""

import logging
import tempfile
from pathlib import Path
from typing import cast

from fastapi import APIRouter, Request, Response, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from guitarvis_core.audio import check_duration
from guitarvis_core.contracts import FailureReason, PipelineError
from guitarvis_jobs.blobs import PRESIGN_EXPIRES_SEC
from guitarvis_jobs.models import INTERNAL_FAILURE_MESSAGE, Job, JobStatus, NewJob
from guitarvis_jobs.store import TooManyActiveJobs

from guitarvis_api.errors import ApiError, HttpReason, error_body
from guitarvis_api.reconcile import reconcile
from guitarvis_api.schemas import JobView
from guitarvis_api.services import Services
from guitarvis_api.uploads import receive, title_of, upload_key

log = logging.getLogger(__name__)

router = APIRouter()


def services_of(request: Request) -> Services:
    return cast(Services, request.app.state.services)


def _load(services: Services, job_id: str) -> Job:
    job = services.store.get(job_id)
    if job is None:
        raise ApiError(404, HttpReason.NOT_FOUND, "There is no job with that id.")
    return job


def _not_ready(job: Job, what: str) -> ApiError:
    if job.status is JobStatus.FAILED:
        return ApiError(
            409, HttpReason.NOT_READY, f"That job failed, so it has no {what}."
        )
    return ApiError(
        409,
        HttpReason.NOT_READY,
        f"The {what} is not ready yet. Poll the job until it succeeds.",
    )


@router.post("/jobs", status_code=202, response_model=JobView)
def create_job(file: UploadFile, request: Request, response: Response) -> JobView:
    """Validate, dedupe, limit, store and enqueue — cheapest check first."""
    services = services_of(request)
    settings = services.settings
    client_ip = request.client.host if request.client is not None else "unknown"

    with tempfile.TemporaryDirectory(prefix="guitarvis-upload-") as tmp:
        upload = receive(
            file.file, Path(tmp) / "upload", max_bytes=settings.max_upload_bytes
        )
        duration = _probe(services, upload.path)

        live = _live_job(services, upload.content_hash)
        if live is not None:  # starts no work, so it is not counted below
            response.status_code = 200
            return JobView.of(live)

        # Counted before the blob is stored, so a refused upload costs no
        # storage. Uploads that race past it are refused by `create`.
        active = services.store.count_active(client_ip)
        if active >= settings.max_active_jobs_per_ip:
            raise _too_many_jobs(active)

        key = upload_key(upload.content_hash, file.filename)
        if not services.blobs.exists(key):
            services.blobs.put_file(key, upload.path)

    try:
        job, created = services.store.create(
            NewJob(
                content_hash=upload.content_hash,
                title=title_of(file.filename),
                duration_sec=duration,
                upload_key=key,
                client_ip=client_ip,
            ),
            max_active=settings.max_active_jobs_per_ip,
        )
    except TooManyActiveJobs as error:
        raise _too_many_jobs(error.active) from error
    if not created:  # the same file, uploaded at the same moment, got there first
        response.status_code = 200
        return JobView.of(job)

    try:
        services.queue.enqueue(job.id)
    except Exception as exc:
        log.exception("could not enqueue job %s", job.id)
        services.store.fail(
            job.id,
            reason=FailureReason.INTERNAL,
            message=INTERNAL_FAILURE_MESSAGE,
            stage=None,
            expect=JobStatus.QUEUED,
        )
        raise ApiError(
            503,
            FailureReason.INTERNAL,
            "We could not queue that song. Try again in a minute.",
        ) from exc

    response.headers["Location"] = f"/jobs/{job.id}"
    return JobView.of(job)


def _too_many_jobs(active: int) -> ApiError:
    songs = "song" if active == 1 else "songs"
    return ApiError(
        429,
        HttpReason.TOO_MANY_JOBS,
        f"You already have {active} {songs} processing. Wait for one to "
        "finish, then try again.",
    )


def _probe(services: Services, path: Path) -> float:
    """ffprobe now, so a bad file is refused in a second, not after a queue wait."""
    try:
        duration = services.probe(path)
        check_duration(duration)
    except PipelineError as error:
        if error.reason is FailureReason.INTERNAL:  # ffprobe missing: ours, not theirs
            raise ApiError(503, error.reason, str(error)) from error
        raise ApiError(422, error.reason, str(error)) from error
    return duration


def _live_job(services: Services, content_hash: str) -> Job | None:
    """The live job for this upload, repaired first if the queue lost it.

    A lookup is a read like any other, so it reconciles: a dead job must not
    be handed back as though it were still coming.
    """
    job = services.store.find_live(content_hash)
    if job is None:
        return None
    job = reconcile(job, services)
    return None if job.status is JobStatus.FAILED else job


@router.get("/jobs/{job_id}", response_model=JobView)
def get_job(job_id: str, request: Request) -> JobView:
    services = services_of(request)
    return JobView.of(reconcile(_load(services, job_id), services))


@router.get("/jobs/{job_id}/document")
def get_document(job_id: str, request: Request) -> JSONResponse:
    job = _load(services_of(request), job_id)
    if job.status is not JobStatus.SUCCEEDED or job.document is None:
        raise _not_ready(job, "tab document")
    return JSONResponse(job.document)


@router.get("/jobs/{job_id}/audio/mix")
def get_mix(job_id: str, request: Request) -> RedirectResponse:
    # A redirect, not bytes through the api: storage answers Range requests,
    # which seeking needs, and the api stays thin.
    services = services_of(request)
    job = _load(services, job_id)
    url = services.blobs.presign_get(job.upload_key, expires_sec=PRESIGN_EXPIRES_SEC)
    return RedirectResponse(url, status_code=307)


@router.get("/jobs/{job_id}/audio/guitar")
def get_guitar(job_id: str, request: Request) -> RedirectResponse:
    services = services_of(request)
    job = _load(services, job_id)
    if job.stem_key is None:
        raise _not_ready(job, "isolated guitar")
    url = services.blobs.presign_get(job.stem_key, expires_sec=PRESIGN_EXPIRES_SEC)
    return RedirectResponse(url, status_code=307)


@router.get("/health")
def health(request: Request) -> JSONResponse:
    services = services_of(request)
    checks = {
        "postgres": services.store.ping,
        "redis": services.queue.ping,
        "storage": services.blobs.ping,
    }
    answers: dict[str, str] = {}
    for name, ping in checks.items():
        try:
            ping()
        except Exception:
            log.warning("health: %s did not answer", name, exc_info=True)
            answers[name] = "unreachable"
        else:
            answers[name] = "ok"

    down = [name for name, answer in answers.items() if answer != "ok"]
    if not down:
        return JSONResponse({"status": "ok", "services": answers})
    body = error_body(FailureReason.INTERNAL, f"Not answering: {', '.join(down)}.")
    return JSONResponse({**body, "services": answers}, status_code=503)
