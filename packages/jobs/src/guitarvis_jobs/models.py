"""The job record, as the api and the worker both see it."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from guitarvis_core.contracts import FailureReason

# What a user is told when the failure is ours, not their file's.
INTERNAL_FAILURE_MESSAGE = "Something went wrong on our side. Try again later."


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


ACTIVE_STATUSES = frozenset({JobStatus.QUEUED, JobStatus.RUNNING})
FINISHED_STATUSES = frozenset({JobStatus.SUCCEEDED, JobStatus.FAILED})


def canonical_id(raw: str) -> str | None:
    """A job id in canonical form, or None when `raw` is not a UUID.

    Ids are UUIDs because they are public and must be unguessable. A
    malformed id is simply a job that does not exist.
    """
    try:
        return str(uuid.UUID(raw))
    except (ValueError, AttributeError, TypeError):
        return None


@dataclass(frozen=True)
class NewJob:
    """What an upload or a link contributes to a fresh row.

    An upload has its `upload_key` already. A link job has `source_url`, and
    its key arrives when the worker has stored the download (spec 012).
    """

    content_hash: str
    title: str
    duration_sec: float
    upload_key: str | None
    client_ip: str
    source_url: str | None = None

    def __post_init__(self) -> None:
        if self.upload_key is None and self.source_url is None:
            raise ValueError("a job needs an upload_key or a source_url")


@dataclass(frozen=True)
class Job:
    """One row of the jobs table; spec 005 describes each column.

    `content_hash` is the dedupe key: the hash of an upload's bytes, or for a
    link job the video's identity, sha256("youtube:" + id). The hash of a
    link job's bytes is in its `upload_key`, once the worker sets it.
    """

    id: str
    content_hash: str
    status: JobStatus
    stage: str | None
    percent: int
    attempts: int
    failure_reason: FailureReason | None
    failure_message: str | None
    failed_stage: str | None
    title: str
    duration_sec: float
    upload_key: str | None
    stem_key: str | None
    client_ip: str
    document: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    source_url: str | None = None
