"""The job as clients see it."""

from datetime import datetime

from guitarvis_core.contracts import FailureReason
from guitarvis_jobs.models import INTERNAL_FAILURE_MESSAGE, Job, JobStatus
from pydantic import BaseModel


class FailureView(BaseModel):
    reason: str
    message: str
    stage: str | None


class JobView(BaseModel):
    """`failure` is set only when `status` is failed; `stage` only while running."""

    id: str
    status: JobStatus
    stage: str | None
    percent: int
    attempts: int
    title: str
    duration_sec: float
    failure: FailureView | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, job: Job) -> "JobView":
        failure = None
        if job.status is JobStatus.FAILED:
            failure = FailureView(
                reason=(job.failure_reason or FailureReason.INTERNAL).value,
                message=job.failure_message or INTERNAL_FAILURE_MESSAGE,
                stage=job.failed_stage,
            )
        return cls(
            id=job.id,
            status=job.status,
            stage=job.stage,
            percent=job.percent,
            attempts=job.attempts,
            title=job.title,
            duration_sec=job.duration_sec,
            failure=failure,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )
