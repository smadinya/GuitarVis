"""Every route. Plain `def`: the work is blocking I/O, which FastAPI runs in
its threadpool."""

import logging
from typing import cast

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from guitarvis_core.contracts import FailureReason
from guitarvis_jobs.blobs import PRESIGN_EXPIRES_SEC
from guitarvis_jobs.models import Job, JobStatus

from guitarvis_api.errors import ApiError, HttpReason, error_body
from guitarvis_api.reconcile import reconcile
from guitarvis_api.schemas import JobView
from guitarvis_api.services import Services

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
