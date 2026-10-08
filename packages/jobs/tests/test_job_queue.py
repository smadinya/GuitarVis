"""The JobQueue contract, run against the in-memory twin and against RQ."""

from collections.abc import Iterator

import pytest
from guitarvis_jobs.queue import (
    MAX_RETRIES,
    QUEUE_NAME,
    RETRY_INTERVALS_SEC,
    RUN_JOB,
    InMemoryJobQueue,
    JobQueue,
    RQJobQueue,
)
from guitarvis_jobs.settings import Settings
from guitarvis_jobs.testing import redis_connection
from rq.job import Job as RQJob
from rq.job import JobStatus as RQJobStatus

JOB_ID = "5f0c6c2e-0000-4000-8000-000000000001"


@pytest.fixture(params=["memory", "rq"])
def queue(request: pytest.FixtureRequest) -> Iterator[JobQueue]:
    if request.param == "memory":
        yield InMemoryJobQueue()
        return
    with redis_connection() as connection:
        yield RQJobQueue(connection, job_timeout_sec=1800)


def test_an_enqueued_job_exists(queue: JobQueue) -> None:
    queue.enqueue(JOB_ID)

    assert queue.exists(JOB_ID)


def test_an_unknown_job_does_not_exist(queue: JobQueue) -> None:
    assert not queue.exists("5f0c6c2e-0000-4000-8000-0000000000ff")


def test_ping_answers(queue: JobQueue) -> None:
    queue.ping()


def fail_terminally(queue: JobQueue, job_id: str) -> None:
    """Fail a job for good: RQ's last retry failed, or the worker could not
    even import run_job."""
    if isinstance(queue, InMemoryJobQueue):
        queue.fail_terminally(job_id)
        return
    assert isinstance(queue, RQJobQueue)
    RQJob.fetch(job_id, connection=queue.connection).set_status(RQJobStatus.FAILED)


def test_a_job_the_queue_will_never_run_again_does_not_exist(queue: JobQueue) -> None:
    # Reconciliation treats it as lost, so its row cannot stay queued forever.
    queue.enqueue(JOB_ID)

    fail_terminally(queue, JOB_ID)

    assert not queue.exists(JOB_ID)


@pytest.mark.parametrize(
    "status",
    [
        RQJobStatus.FINISHED,
        RQJobStatus.FAILED,
        RQJobStatus.STOPPED,
        RQJobStatus.CANCELED,
    ],
)
def test_an_rq_job_in_a_terminal_status_does_not_exist(status: RQJobStatus) -> None:
    with redis_connection() as connection:
        queue = RQJobQueue(connection, job_timeout_sec=1800)
        queue.enqueue(JOB_ID)

        RQJob.fetch(JOB_ID, connection=connection).set_status(status)

        assert not queue.exists(JOB_ID)


@pytest.mark.parametrize(
    "status",
    [
        RQJobStatus.CREATED,
        RQJobStatus.QUEUED,
        RQJobStatus.SCHEDULED,  # a retry waiting out its interval
        RQJobStatus.STARTED,
        RQJobStatus.DEFERRED,
    ],
)
def test_an_rq_job_that_can_still_run_exists(status: RQJobStatus) -> None:
    with redis_connection() as connection:
        queue = RQJobQueue(connection, job_timeout_sec=1800)
        queue.enqueue(JOB_ID)

        RQJob.fetch(JOB_ID, connection=connection).set_status(status)

        assert queue.exists(JOB_ID)


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


def test_an_rq_job_carries_the_retry_policy_and_the_timeout() -> None:
    with redis_connection() as connection:
        RQJobQueue(connection, job_timeout_sec=1800).enqueue(JOB_ID)
        job = RQJob.fetch(JOB_ID, connection=connection)

        assert job.func_name == RUN_JOB
        assert job.args == (JOB_ID,)
        assert job.origin == QUEUE_NAME
        assert job.retries_left == MAX_RETRIES
        assert job.retry_intervals == list(RETRY_INTERVALS_SEC)
        assert job.timeout == 1800


def test_the_api_side_connection_times_out_instead_of_hanging() -> None:
    """A Redis that goes silent must raise, so reads can answer from Postgres.

    Constructing a client does not connect, so this needs no live Redis.
    """
    queue = RQJobQueue.from_settings(Settings())

    kwargs = queue.connection.connection_pool.connection_kwargs
    assert kwargs["socket_connect_timeout"] == 5
    assert kwargs["socket_timeout"] == 5
