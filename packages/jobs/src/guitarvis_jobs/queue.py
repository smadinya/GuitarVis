"""The queue. Postgres is the record (ADR 0007); Redis carries job ids only.

The api enqueues the worker's entry point by its dotted path, so it never
imports the function it schedules — the worker is reachable only through the
queue. The RQ job id is the GuitarVis job id.
"""

import threading
from typing import TYPE_CHECKING, Protocol

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


if TYPE_CHECKING:  # Static conformance: the typed assignment is what mypy checks.
    _conforms: JobQueue = InMemoryJobQueue()
