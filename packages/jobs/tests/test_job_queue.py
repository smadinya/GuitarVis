"""The JobQueue contract. Task 7 adds an "rq" param against Redis."""

from collections.abc import Iterator

import pytest
from guitarvis_jobs.queue import (
    MAX_RETRIES,
    RETRY_INTERVALS_SEC,
    RUN_JOB,
    InMemoryJobQueue,
    JobQueue,
)

JOB_ID = "5f0c6c2e-0000-4000-8000-000000000001"


@pytest.fixture(params=["memory"])
def queue(request: pytest.FixtureRequest) -> Iterator[JobQueue]:
    yield InMemoryJobQueue()


def test_an_enqueued_job_exists(queue: JobQueue) -> None:
    queue.enqueue(JOB_ID)

    assert queue.exists(JOB_ID)


def test_an_unknown_job_does_not_exist(queue: JobQueue) -> None:
    assert not queue.exists("5f0c6c2e-0000-4000-8000-0000000000ff")


def test_ping_answers(queue: JobQueue) -> None:
    queue.ping()


def test_the_job_function_is_named_not_imported() -> None:
    # The api enqueues by this string and never imports the worker. A worker
    # test (Task 9) imports it, so renaming run_job fails CI, not every job.
    assert RUN_JOB == "guitarvis_worker.runner.run_job"


def test_three_attempts_in_all() -> None:
    assert MAX_RETRIES == 2
    assert RETRY_INTERVALS_SEC == (10, 60)


def test_the_twin_can_fail_lose_and_go_down() -> None:
    queue = InMemoryJobQueue()

    queue.fail_next = True
    with pytest.raises(ConnectionError):
        queue.enqueue(JOB_ID)
    queue.enqueue(JOB_ID)  # only the next one failed
    assert queue.enqueued == [JOB_ID]

    queue.lose(JOB_ID)
    assert not queue.exists(JOB_ID)

    queue.down = True
    with pytest.raises(ConnectionError):
        queue.exists(JOB_ID)
    with pytest.raises(ConnectionError):
        queue.ping()
