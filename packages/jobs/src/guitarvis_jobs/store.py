"""The jobs table's contract, and an in-memory twin of it.

Every write after creation is conditional: it names the status it expects to
find and changes nothing when the row has moved on. That is what lets the
worker, the api's reconciliation and a duplicate RQ delivery race without
corrupting a row. One contract suite (packages/jobs/tests/test_job_store.py)
runs against this and against PostgresJobStore.
"""

import copy
import threading
import uuid
from collections.abc import Callable, Collection
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

from guitarvis_core.contracts import FailureReason

from guitarvis_jobs.models import ACTIVE_STATUSES, Job, JobStatus, NewJob, canonical_id

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


class TooManyActiveJobs(Exception):
    """`create` refused: this address already has `active` jobs going."""

    def __init__(self, active: int) -> None:
        super().__init__(f"{active} active jobs")
        self.active = active


class JobStore(Protocol):
    def create(self, new: NewJob, *, max_active: int | None = None) -> tuple[Job, bool]:
        """Insert a queued row, or return the live row for this hash.

        Returns the job and whether this call created it. "Live" is any
        status but failed: a failed job never blocks a fresh attempt.

        With `max_active`, raise TooManyActiveJobs instead of inserting when
        the address already has that many queued or running. The count and
        the insert are one step, so simultaneous uploads cannot all pass it.
        The live row for the hash is returned whatever the count: it starts
        no work.
        """
        ...

    def get(self, job_id: str) -> Job | None: ...

    def find_live(self, content_hash: str) -> Job | None: ...

    def count_active(self, client_ip: str) -> int:
        """Jobs from this address that are queued or running."""
        ...

    def mark_running(self, job_id: str) -> Job | None:
        """Start an attempt: running, attempts + 1, stage and percent reset.

        Accepts a row already running: a worker killed outright never ran its
        except, and RQ's retry finds the row as that worker left it. Returns
        None, changing nothing, for a finished or missing row.
        """
        ...

    def set_progress(self, job_id: str, stage: str, percent: int) -> bool: ...

    def succeed(
        self, job_id: str, *, document: dict[str, Any], stem_key: str
    ) -> bool: ...

    def fail(
        self,
        job_id: str,
        *,
        reason: FailureReason,
        message: str,
        stage: str | None,
        expect: JobStatus,
        expect_updated_at: datetime | None = None,
    ) -> bool:
        """Fail the row if it is still `expect` — and, when given, still
        carries `expect_updated_at`, so a writer that got there first wins."""
        ...

    def requeue(self, job_id: str) -> bool:
        """Running back to queued for RQ's retry; attempts are kept."""
        ...

    def ping(self) -> None:
        """Raise if the store cannot be reached."""
        ...


class InMemoryJobStore:
    """Implements JobStore in a dict.

    Locked, because TestClient runs plain-def routes in a threadpool.
    """

    def __init__(self, clock: Clock = utc_now) -> None:
        self._clock = clock
        self._rows: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, new: NewJob, *, max_active: int | None = None) -> tuple[Job, bool]:
        with self._lock:
            live = self._find_live(new.content_hash)
            if live is not None:
                return live, False
            if max_active is not None:
                active = self._count_active(new.client_ip)
                if active >= max_active:
                    raise TooManyActiveJobs(active)
            now = self._clock()
            job = Job(
                id=str(uuid.uuid4()),
                content_hash=new.content_hash,
                status=JobStatus.QUEUED,
                stage=None,
                percent=0,
                attempts=0,
                failure_reason=None,
                failure_message=None,
                failed_stage=None,
                title=new.title,
                duration_sec=new.duration_sec,
                upload_key=new.upload_key,
                stem_key=None,
                client_ip=new.client_ip,
                document=None,
                created_at=now,
                updated_at=now,
            )
            self._rows[job.id] = job
            return job, True

    def get(self, job_id: str) -> Job | None:
        key = canonical_id(job_id)
        with self._lock:
            row = None if key is None else self._rows.get(key)
            # A copy, as a database read would be.
            return (
                None
                if row is None
                else replace(row, document=copy.deepcopy(row.document))
            )

    def find_live(self, content_hash: str) -> Job | None:
        with self._lock:
            return self._find_live(content_hash)

    def count_active(self, client_ip: str) -> int:
        with self._lock:
            return self._count_active(client_ip)

    def mark_running(self, job_id: str) -> Job | None:
        return self._transition(
            job_id,
            ACTIVE_STATUSES,
            lambda row: replace(
                row,
                status=JobStatus.RUNNING,
                attempts=row.attempts + 1,
                stage=None,
                percent=0,
            ),
        )

    def set_progress(self, job_id: str, stage: str, percent: int) -> bool:
        changed = self._transition(
            job_id,
            {JobStatus.RUNNING},
            lambda row: replace(row, stage=stage, percent=percent),
        )
        return changed is not None

    def succeed(self, job_id: str, *, document: dict[str, Any], stem_key: str) -> bool:
        stored = copy.deepcopy(document)
        changed = self._transition(
            job_id,
            {JobStatus.RUNNING},
            lambda row: replace(
                row,
                status=JobStatus.SUCCEEDED,
                stage=None,
                percent=100,
                document=stored,
                stem_key=stem_key,
            ),
        )
        return changed is not None

    def fail(
        self,
        job_id: str,
        *,
        reason: FailureReason,
        message: str,
        stage: str | None,
        expect: JobStatus,
        expect_updated_at: datetime | None = None,
    ) -> bool:
        changed = self._transition(
            job_id,
            {expect},
            lambda row: replace(
                row,
                status=JobStatus.FAILED,
                stage=None,
                failure_reason=reason,
                failure_message=message,
                failed_stage=stage,
            ),
            expect_updated_at=expect_updated_at,
        )
        return changed is not None

    def requeue(self, job_id: str) -> bool:
        changed = self._transition(
            job_id,
            {JobStatus.RUNNING},
            lambda row: replace(row, status=JobStatus.QUEUED, stage=None, percent=0),
        )
        return changed is not None

    def ping(self) -> None:
        return None

    def _count_active(self, client_ip: str) -> int:
        """Caller holds the lock."""
        return sum(
            1
            for row in self._rows.values()
            if row.client_ip == client_ip and row.status in ACTIVE_STATUSES
        )

    def _find_live(self, content_hash: str) -> Job | None:
        """Caller holds the lock."""
        return next(
            (
                row
                for row in self._rows.values()
                if row.content_hash == content_hash
                and row.status is not JobStatus.FAILED
            ),
            None,
        )

    def _transition(
        self,
        job_id: str,
        allowed: Collection[JobStatus],
        change: Callable[[Job], Job],
        *,
        expect_updated_at: datetime | None = None,
    ) -> Job | None:
        key = canonical_id(job_id)
        with self._lock:
            row = None if key is None else self._rows.get(key)
            if row is None or row.status not in allowed:
                return None
            if expect_updated_at is not None and row.updated_at != expect_updated_at:
                return None
            updated = replace(change(row), updated_at=self._clock())
            self._rows[row.id] = updated
            return updated


if TYPE_CHECKING:  # Static conformance: the typed assignment is what mypy checks.
    _conforms: JobStore = InMemoryJobStore()
