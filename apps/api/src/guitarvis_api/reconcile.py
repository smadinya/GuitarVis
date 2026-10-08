"""Repair, on read, the two ways Postgres and Redis can disagree (ADR 0007).

A row queued for over a minute whose RQ job is gone: the api died between
insert and enqueue, or Redis lost its data. The grace period covers the gap
between those two steps in a live request. A row running long past the job
timeout: the worker was killed outright and never ran its except. RQ's own
timeout raises inside the job, so the worker handles every timeout it can see.

Either is failed as internal, conditionally on the row being exactly as read,
so a worker that was merely slow and writes first wins. Nothing runs in the
background; a job nobody asks about can stay wrong until somebody does.
"""

import logging
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
        return age > timeout + RUNNING_GRACE
    if job.status is not JobStatus.QUEUED or age <= QUEUED_GRACE:
        return False
    try:
        return not services.queue.exists(job.id)
    except Exception:
        # Redis is down: answer from Postgres now, and repair on a later read.
        log.warning("could not ask the queue about job %s", job.id, exc_info=True)
        return False
