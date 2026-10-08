"""The JobStore contract. Task 6 adds a "postgres" param, so these same
tests run against the database the system actually uses, and the in-memory
twin cannot quietly drift from it."""

from collections.abc import Iterator

import pytest
from guitarvis_core.contracts import FailureReason
from guitarvis_jobs.models import JobStatus
from guitarvis_jobs.store import InMemoryJobStore, JobStore
from guitarvis_jobs.testing import FakeClock, sample_new_job

HASH_B = "b" * 64


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture(params=["memory"])
def store(request: pytest.FixtureRequest, clock: FakeClock) -> Iterator[JobStore]:
    yield InMemoryJobStore(clock=clock)


def running(store: JobStore, content_hash: str = "a" * 64) -> str:
    job, _ = store.create(sample_new_job(content_hash=content_hash))
    assert store.mark_running(job.id) is not None
    return job.id


def test_create_returns_a_queued_job(store: JobStore, clock: FakeClock) -> None:
    job, created = store.create(sample_new_job())

    assert created
    assert job.status is JobStatus.QUEUED
    assert (job.stage, job.percent, job.attempts) == (None, 0, 0)
    assert (job.title, job.duration_sec, job.client_ip) == ("song", 30.0, "203.0.113.7")
    assert job.failure_reason is None and job.document is None
    assert job.created_at == job.updated_at == clock.now
    assert store.get(job.id) == job


def test_create_dedupes_a_live_job_with_the_same_hash(store: JobStore) -> None:
    first, _ = store.create(sample_new_job())
    second, created = store.create(sample_new_job(client_ip="198.51.100.1"))

    assert not created
    assert second.id == first.id


def test_a_failed_job_does_not_block_a_new_one(store: JobStore) -> None:
    first, _ = store.create(sample_new_job())
    store.fail(
        first.id,
        reason=FailureReason.INTERNAL,
        message="m",
        stage=None,
        expect=JobStatus.QUEUED,
    )

    second, created = store.create(sample_new_job())

    assert created
    assert second.id != first.id


def test_a_succeeded_job_is_returned_rather_than_redone(store: JobStore) -> None:
    job_id = running(store)
    store.succeed(job_id, document={"notes": []}, stem_key="cache/stem.wav")

    again, created = store.create(sample_new_job())

    assert not created
    assert again.id == job_id
    assert again.status is JobStatus.SUCCEEDED


def test_get_returns_none_for_unknown_and_malformed_ids(store: JobStore) -> None:
    assert store.get("5f0c6c2e-0000-4000-8000-000000000000") is None
    assert store.get("not-a-uuid") is None
    assert store.get("") is None


def test_get_accepts_an_uppercase_id(store: JobStore) -> None:
    job, _ = store.create(sample_new_job())

    found = store.get(job.id.upper())

    assert found is not None and found.id == job.id


def test_find_live_ignores_failed_jobs(store: JobStore) -> None:
    job, _ = store.create(sample_new_job())
    assert store.find_live(job.content_hash) == job

    store.fail(
        job.id,
        reason=FailureReason.INTERNAL,
        message="m",
        stage=None,
        expect=JobStatus.QUEUED,
    )

    assert store.find_live(job.content_hash) is None


def test_count_active_counts_queued_and_running_for_one_ip(store: JobStore) -> None:
    store.create(sample_new_job())
    running(store, content_hash=HASH_B)
    done = running(store, content_hash="c" * 64)
    store.succeed(done, document={}, stem_key="k")
    store.create(sample_new_job(content_hash="d" * 64, client_ip="198.51.100.1"))

    assert store.count_active("203.0.113.7") == 2
    assert store.count_active("198.51.100.1") == 1
    assert store.count_active("192.0.2.1") == 0


def test_mark_running_starts_an_attempt(store: JobStore, clock: FakeClock) -> None:
    job, _ = store.create(sample_new_job())
    clock.advance(seconds=5)

    started = store.mark_running(job.id)

    assert started is not None
    assert started.status is JobStatus.RUNNING
    assert started.attempts == 1
    assert started.updated_at == clock.now


def test_mark_running_accepts_a_row_already_running(store: JobStore) -> None:
    # A worker killed outright never ran its except; RQ's retry finds the
    # row still running and must be allowed to start again.
    job_id = running(store)

    again = store.mark_running(job_id)

    assert again is not None and again.attempts == 2


def test_mark_running_refuses_a_finished_row(store: JobStore) -> None:
    job_id = running(store)
    store.succeed(job_id, document={}, stem_key="k")

    assert store.mark_running(job_id) is None
    assert store.mark_running("not-a-uuid") is None


def test_set_progress_only_while_running(store: JobStore) -> None:
    job, _ = store.create(sample_new_job())
    assert not store.set_progress(job.id, "separation", 5)

    store.mark_running(job.id)
    assert store.set_progress(job.id, "separation", 12)

    row = store.get(job.id)
    assert row is not None and (row.stage, row.percent) == ("separation", 12)


def test_succeed_stores_the_document_and_stem(store: JobStore) -> None:
    job_id = running(store)
    store.set_progress(job_id, "fretboard", 80)
    document = {"notes": [{"id": "n_0000", "t": 1.5}], "warnings": ["w"]}

    assert store.succeed(job_id, document=document, stem_key="cache/v1/x/stem.wav")

    row = store.get(job_id)
    assert row is not None
    assert row.status is JobStatus.SUCCEEDED
    assert (row.stage, row.percent) == (None, 100)
    assert row.document == document
    assert row.stem_key == "cache/v1/x/stem.wav"


def test_the_stored_document_is_a_copy(store: JobStore) -> None:
    job_id = running(store)
    document: dict[str, object] = {"warnings": []}
    store.succeed(job_id, document=document, stem_key="k")

    document["warnings"] = ["changed after the fact"]

    row = store.get(job_id)
    assert row is not None and row.document == {"warnings": []}


def test_a_late_success_after_the_row_was_failed_changes_nothing(
    store: JobStore,
) -> None:
    job_id = running(store)
    store.fail(
        job_id,
        reason=FailureReason.INTERNAL,
        message="lost",
        stage="separation",
        expect=JobStatus.RUNNING,
    )

    assert not store.succeed(job_id, document={}, stem_key="k")
    row = store.get(job_id)
    assert row is not None and row.status is JobStatus.FAILED


def test_fail_records_reason_message_and_stage(store: JobStore) -> None:
    job_id = running(store)
    store.set_progress(job_id, "separation", 20)

    assert store.fail(
        job_id,
        reason=FailureReason.NO_GUITAR_DETECTED,
        message="No clear guitar part was found in this recording.",
        stage="separation",
        expect=JobStatus.RUNNING,
    )

    row = store.get(job_id)
    assert row is not None
    assert row.status is JobStatus.FAILED
    assert row.failure_reason is FailureReason.NO_GUITAR_DETECTED
    assert row.failure_message == "No clear guitar part was found in this recording."
    assert row.failed_stage == "separation"
    assert row.stage is None


def test_fail_with_the_wrong_expected_status_changes_nothing(store: JobStore) -> None:
    job, _ = store.create(sample_new_job())

    assert not store.fail(
        job.id,
        reason=FailureReason.INTERNAL,
        message="m",
        stage=None,
        expect=JobStatus.RUNNING,
    )
    assert store.get(job.id) == job


def test_fail_with_a_stale_updated_at_changes_nothing(
    store: JobStore, clock: FakeClock
) -> None:
    job_id = running(store)
    seen = store.get(job_id)
    assert seen is not None
    clock.advance(seconds=1)
    store.set_progress(job_id, "separation", 3)  # the worker wrote first

    assert not store.fail(
        job_id,
        reason=FailureReason.INTERNAL,
        message="m",
        stage=None,
        expect=JobStatus.RUNNING,
        expect_updated_at=seen.updated_at,
    )
    row = store.get(job_id)
    assert row is not None and row.status is JobStatus.RUNNING


def test_requeue_resets_stage_and_percent_but_keeps_attempts(store: JobStore) -> None:
    job_id = running(store)
    store.set_progress(job_id, "transcription", 40)

    assert store.requeue(job_id)

    row = store.get(job_id)
    assert row is not None
    assert row.status is JobStatus.QUEUED
    assert (row.stage, row.percent, row.attempts) == (None, 0, 1)
    assert not store.requeue(job_id)  # only a running row goes back


def test_ping_answers(store: JobStore) -> None:
    store.ping()
