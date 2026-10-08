"""The queue. Postgres is the record (ADR 0007); Redis carries job ids only.

The api enqueues the worker's entry point by its dotted path, so it never
imports the function it schedules — the worker is reachable only through the
queue. The RQ job id is the GuitarVis job id.
"""

import threading
from typing import TYPE_CHECKING, Protocol

from redis import Redis
from rq import Queue, Retry
from rq.job import Job as RQJob

from guitarvis_jobs.settings import Settings

RUN_JOB = "guitarvis_worker.runner.run_job"
QUEUE_NAME = "jobs"
MAX_RETRIES = 2  # three attempts in all, as spec 001 asks
RETRY_INTERVALS_SEC = (10, 60)


class JobQueue(Protocol):
    def enqueue(self, job_id: str) -> None: ...

    def exists(self, job_id: str) -> bool:
        """Whether the queue still knows this job, in any state."""
        ...

    def ping(self) -> None:
        """Raise if the queue cannot be reached."""
        ...


class InMemoryJobQueue:
    """Implements JobQueue by recording what was enqueued.

    `fail_next` makes the next enqueue raise; `down` makes `exists` and
    `ping` raise; `lose` forgets a job, as a flushed Redis would.
    """

    def __init__(self) -> None:
        self.enqueued: list[str] = []
        self.fail_next = False
        self.down = False
        self._known: set[str] = set()
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
            return job_id in self._known

    def lose(self, job_id: str) -> None:
        with self._lock:
            self._known.discard(job_id)

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
        # No socket timeout: a worker blocks on this connection for minutes
        # while it waits for work, and RQ manages that wait itself.
        connection = Redis.from_url(settings.redis_url, socket_connect_timeout=5)
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
        return RQJob.exists(job_id, connection=self.connection)

    def ping(self) -> None:
        self.connection.ping()


if TYPE_CHECKING:  # Static conformance: the typed assignment is what mypy checks.
    _conforms: JobQueue = InMemoryJobQueue()
    _rq: JobQueue = RQJobQueue(Redis(), job_timeout_sec=1)
