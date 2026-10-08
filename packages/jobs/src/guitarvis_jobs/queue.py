"""The queue. Postgres is the record (ADR 0007); Redis carries job ids only.

The api enqueues the worker's entry point by its dotted path, so it never
imports the function it schedules — the worker is reachable only through the
queue. The RQ job id is the GuitarVis job id.
"""

import threading
from typing import TYPE_CHECKING, Protocol

from redis import Redis
from rq import Queue, Retry
from rq.exceptions import InvalidJobOperation
from rq.job import Job as RQJob
from rq.job import JobStatus as RQJobStatus

from guitarvis_jobs.settings import Settings

RUN_JOB = "guitarvis_worker.runner.run_job"
QUEUE_NAME = "jobs"
MAX_RETRIES = 2  # three attempts in all, as spec 001 asks
RETRY_INTERVALS_SEC = (10, 60)

# Statuses RQ never runs a job from again. A retry goes back through SCHEDULED
# or QUEUED, so FAILED is final.
_RQ_TERMINAL = frozenset(
    {
        RQJobStatus.FINISHED,
        RQJobStatus.FAILED,
        RQJobStatus.STOPPED,
        RQJobStatus.CANCELED,
    }
)


class JobQueue(Protocol):
    def enqueue(self, job_id: str) -> None: ...

    def exists(self, job_id: str) -> bool:
        """Whether the queue knows this job and can still run it.

        False for a job it never had or has forgotten, and for one it will
        never run again: finished, or failed, stopped or canceled for good.
        Reconciliation treats either as lost.
        """
        ...

    def ping(self) -> None:
        """Raise if the queue cannot be reached."""
        ...


class InMemoryJobQueue:
    """Implements JobQueue by recording what was enqueued.

    `fail_next` makes the next enqueue raise; `down` makes `exists` and
    `ping` raise; `lose` forgets a job, as a flushed Redis would;
    `fail_terminally` keeps a job but never runs it again, as RQ does once
    its last attempt has failed.
    """

    def __init__(self) -> None:
        self.enqueued: list[str] = []
        self.fail_next = False
        self.down = False
        self._known: set[str] = set()
        self._terminal: set[str] = set()
        self._lock = threading.Lock()

    def enqueue(self, job_id: str) -> None:
        with self._lock:
            if self.fail_next:
                self.fail_next = False
                raise ConnectionError("queue unavailable")
            self.enqueued.append(job_id)
            self._known.add(job_id)

    def exists(self, job_id: str) -> bool:
        self.ping()
        with self._lock:
            return job_id in self._known and job_id not in self._terminal

    def lose(self, job_id: str) -> None:
        with self._lock:
            self._known.discard(job_id)

    def fail_terminally(self, job_id: str) -> None:
        with self._lock:
            self._terminal.add(job_id)

    def ping(self) -> None:
        if self.down:
            raise ConnectionError("queue unavailable")


class RQJobQueue:
    """Implements JobQueue on RQ."""

    def __init__(self, connection: Redis, *, job_timeout_sec: int) -> None:
        self.connection = connection
        self.job_timeout_sec = job_timeout_sec
        self._queue = Queue(QUEUE_NAME, connection=connection)

    @classmethod
    def from_settings(cls, settings: Settings) -> "RQJobQueue":
        # The api-side connection: a dead or silent Redis must raise quickly,
        # so reads can answer from Postgres. The worker builds its own
        # connection, which waits for work without a socket timeout.
        connection = Redis.from_url(
            settings.redis_url, socket_connect_timeout=5, socket_timeout=5
        )
        return cls(connection, job_timeout_sec=settings.job_timeout_sec)

    def enqueue(self, job_id: str) -> None:
        self._queue.enqueue(
            RUN_JOB,
            job_id,
            job_id=job_id,
            retry=Retry(max=MAX_RETRIES, interval=list(RETRY_INTERVALS_SEC)),
            job_timeout=self.job_timeout_sec,
            description=f"guitarvis job {job_id}",
        )

    def exists(self, job_id: str) -> bool:
        try:
            status = RQJob(job_id, connection=self.connection).get_status()
        except InvalidJobOperation:  # no such job
            return False
        return status not in _RQ_TERMINAL

    def ping(self) -> None:
        self.connection.ping()


if TYPE_CHECKING:  # Static conformance: the typed assignment is what mypy checks.
    _conforms: JobQueue = InMemoryJobQueue()
    _rq: JobQueue = RQJobQueue(Redis(), job_timeout_sec=1)
