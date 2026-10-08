"""Repair, on read, the known ways Postgres and Redis disagree (ADR 0007).

A row queued for over a minute whose RQ job is gone, or will never run again:
the api died between insert and enqueue, Redis lost its data, or RQ failed
the job without the worker ever touching the row (a worker that cannot import
run_job, say). The grace period covers the gap between insert and enqueue in
a live request. A row running long past the job timeout whose RQ job is not
waiting to run again: the worker was killed outright, horse and all, and
never ran its except. RQ's own timeout raises inside the job, so the worker
handles every timeout it can see. When RQ kills only the horse, it schedules
the retry itself, and the row keeps saying running until the retry starts.

Either is failed as internal, conditionally on the row being exactly as read,
so a worker that was merely slow and writes first wins. Nothing runs in the
background; a job nobody asks about can stay wrong until somebody does.
"""

import logging
from collections.abc import Callable
from datetime import timedelta

from guitarvis_core.contracts import FailureReason
from guitarvis_jobs.models import INTERNAL_FAILURE_MESSAGE, Job, JobStatus

from guitarvis_api.services import Services

log = logging.getLogger(__name__)

QUEUED_GRACE = timedelta(seconds=60)
RUNNING_GRACE = timedelta(minutes=5)


def reconcile(job: Job, services: Services) -> Job:
    """The job as it now stands — failed first, if the queue lost it."""
    if not _is_lost(job, services):
        return job
    services.store.fail(
        job.id,
        reason=FailureReason.INTERNAL,
        message=INTERNAL_FAILURE_MESSAGE,
        stage=job.stage,
        expect=job.status,
        expect_updated_at=job.updated_at,
    )
    return services.store.get(job.id) or job


def _is_lost(job: Job, services: Services) -> bool:
    age = services.clock() - job.updated_at
    if job.status is JobStatus.RUNNING:
        timeout = timedelta(seconds=services.settings.job_timeout_sec)
        if age <= timeout + RUNNING_GRACE:
            return False
        return not _queue_says(services.queue.waiting, job.id)
    if job.status is not JobStatus.QUEUED or age <= QUEUED_GRACE:
        return False
    return not _queue_says(services.queue.exists, job.id)


def _queue_says(question: Callable[[str], bool], job_id: str) -> bool:
    """The queue's answer, or True when it cannot be asked: Redis is down, so
    answer from Postgres now, and repair on a later read."""
    try:
        return question(job_id)
    except Exception:
        log.warning("could not ask the queue about job %s", job_id, exc_info=True)
        return True
