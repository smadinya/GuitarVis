"""Reading jobs: status, document, audio redirects, errors and reconciliation."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone

import pytest
from api_fixture import Api, make_api
from fastapi.testclient import TestClient
from guitarvis_api import app as app_module
from guitarvis_api.errors import HttpReason
from guitarvis_api.reconcile import reconcile
from guitarvis_core.contracts import FailureReason
from guitarvis_core.tabdoc import Instrument, Source, TabDocument, Timing
from guitarvis_jobs.blobs import PRESIGN_EXPIRES_SEC
from guitarvis_jobs.models import INTERNAL_FAILURE_MESSAGE, JobStatus
from guitarvis_jobs.store import InMemoryJobStore
from guitarvis_jobs.testing import FakeClock, sample_new_job

MISSING_ID = "5f0c6c2e-0000-4000-8000-0000000000ff"
STEM_KEY = "cache/v1/" + "a" * 64 + "/separation/stem.wav"
DOCUMENT = TabDocument(
    source=Source(title="song", duration_sec=30.0, audio_url="/jobs/x/audio/mix"),
    instrument=Instrument(),
    timing=Timing(),
).model_dump(mode="json")


def queued(api: Api) -> str:
    job, _ = api.store.create(sample_new_job())
    return job.id


def running(api: Api) -> str:
    job_id = queued(api)
    api.store.mark_running(job_id)
    return job_id


def succeeded(api: Api) -> str:
    job_id = running(api)
    api.store.succeed(job_id, document=DOCUMENT, stem_key=STEM_KEY)
    return job_id


def failed(api: Api) -> str:
    job_id = running(api)
    api.store.set_progress(job_id, "separation", 12)
    api.store.fail(
        job_id,
        reason=FailureReason.NO_GUITAR_DETECTED,
        message="No clear guitar part was found in this recording.",
        stage="separation",
        expect=JobStatus.RUNNING,
    )
    return job_id


def test_an_unknown_job_is_not_found() -> None:
    response = make_api().client.get(f"/jobs/{MISSING_ID}")

    assert response.status_code == 404
    assert response.json() == {
        "error": {"reason": "not_found", "message": "There is no job with that id."}
    }


@pytest.mark.parametrize(
    "path", ["/jobs/not-a-uuid", "/jobs/not-a-uuid/document", "/jobs/x/audio/mix"]
)
def test_a_malformed_id_is_not_found_rather_than_invalid(path: str) -> None:
    response = make_api().client.get(path)

    assert response.status_code == 404
    assert response.json()["error"]["reason"] == "not_found"


def test_a_queued_job() -> None:
    api = make_api()
    job_id = queued(api)

    assert api.client.get(f"/jobs/{job_id}").json() == {
        "id": job_id,
        "status": "queued",
        "stage": None,
        "percent": 0,
        "attempts": 0,
        "title": "song",
        "duration_sec": 30.0,
        "failure": None,
        "created_at": "2026-10-08T12:00:00Z",
        "updated_at": "2026-10-08T12:00:00Z",
    }


def test_timestamps_are_utc_whatever_offset_the_store_returns() -> None:
    """Postgres answers in its session's time zone; the body must not."""
    plus_two = FakeClock(
        start=datetime(2026, 10, 8, 12, 0, tzinfo=UTC).astimezone(
            timezone(timedelta(hours=2))
        )
    )
    api = make_api(store=InMemoryJobStore(clock=plus_two))
    job_id = queued(api)
    assert api.job(job_id).updated_at.utcoffset() == timedelta(hours=2)  # the setup

    body = api.client.get(f"/jobs/{job_id}").json()

    assert body["created_at"] == "2026-10-08T12:00:00Z"
    assert body["updated_at"] == "2026-10-08T12:00:00Z"


def test_a_running_job_reports_its_stage_and_percent() -> None:
    api = make_api()
    job_id = running(api)
    api.store.set_progress(job_id, "separation", 23)

    body = api.client.get(f"/jobs/{job_id}").json()

    assert (body["status"], body["stage"], body["percent"], body["attempts"]) == (
        "running",
        "separation",
        23,
        1,
    )


def test_a_failed_job_says_why_and_where() -> None:
    api = make_api()
    job_id = failed(api)

    body = api.client.get(f"/jobs/{job_id}").json()

    assert body["status"] == "failed"
    assert body["stage"] is None
    assert body["failure"] == {
        "reason": "no_guitar_detected",
        "message": "No clear guitar part was found in this recording.",
        "stage": "separation",
    }


def test_the_document_of_a_finished_job_is_a_tab_document() -> None:
    api = make_api()
    job_id = succeeded(api)

    response = api.client.get(f"/jobs/{job_id}/document")

    assert response.status_code == 200
    assert (
        TabDocument.model_validate(response.json()).model_dump(mode="json") == DOCUMENT
    )


@pytest.mark.parametrize(
    ("make", "says"),
    [(queued, "not ready"), (running, "not ready"), (failed, "failed")],
)
def test_a_document_that_is_not_ready(make: Callable[[Api], str], says: str) -> None:
    api = make_api()
    job_id = make(api)

    response = api.client.get(f"/jobs/{job_id}/document")

    assert response.status_code == 409
    assert response.json()["error"]["reason"] == "not_ready"
    assert says in response.json()["error"]["message"]


def test_the_mix_redirects_to_a_presigned_url() -> None:
    api = make_api()
    job_id = queued(api)

    response = api.client.get(f"/jobs/{job_id}/audio/mix", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == api.blobs.presign_get(
        api.job(job_id).upload_key, expires_sec=PRESIGN_EXPIRES_SEC
    )


def test_the_guitar_redirects_once_the_stem_exists() -> None:
    api = make_api()
    job_id = succeeded(api)

    response = api.client.get(f"/jobs/{job_id}/audio/guitar", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == api.blobs.presign_get(
        STEM_KEY, expires_sec=PRESIGN_EXPIRES_SEC
    )


def test_the_guitar_is_not_ready_before_separation_finishes() -> None:
    api = make_api()
    job_id = running(api)

    response = api.client.get(f"/jobs/{job_id}/audio/guitar", follow_redirects=False)

    assert response.status_code == 409
    assert response.json()["error"]["reason"] == "not_ready"


def test_an_unknown_route_uses_the_error_body() -> None:
    response = make_api().client.get("/nope")

    assert response.status_code == 404
    assert response.json()["error"]["reason"] == "not_found"


def test_an_unexpected_error_uses_the_error_body_and_hides_the_detail() -> None:
    class OnFire(InMemoryJobStore):
        def get(self, job_id: str) -> None:
            raise RuntimeError("the database is on fire")

    api = make_api(store=OnFire(), raise_server_exceptions=False)

    response = api.client.get(f"/jobs/{MISSING_ID}")

    assert response.status_code == 500
    assert response.json() == {
        "error": {"reason": "internal", "message": INTERNAL_FAILURE_MESSAGE}
    }


def test_the_http_layer_adds_exactly_four_reasons() -> None:
    http = {reason.value for reason in HttpReason}

    assert http == {"too_large", "too_many_jobs", "not_found", "not_ready"}
    assert not http & {reason.value for reason in FailureReason}


def test_the_module_app_connects_to_nothing_until_it_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert not hasattr(app_module.app.state, "services")
    built: list[object] = []

    def fake_build(settings: object) -> object:
        built.append(settings)
        return make_api().services

    monkeypatch.setattr(app_module, "build_services", fake_build)

    with TestClient(app_module.create_app()) as client:
        assert client.get("/health").status_code == 200
    assert len(built) == 1


# Reconciliation: the two ways Postgres and Redis can disagree, repaired on read.


def test_a_queued_job_the_queue_lost_is_failed_on_read() -> None:
    api = make_api()
    job_id = queued(api)  # never enqueued: as if the api died in between
    api.clock.advance(seconds=61)

    body = api.client.get(f"/jobs/{job_id}").json()

    assert body["status"] == "failed"
    assert body["failure"] == {
        "reason": "internal",
        "message": INTERNAL_FAILURE_MESSAGE,
        "stage": None,
    }


def test_a_queued_job_inside_its_grace_period_is_left_alone() -> None:
    api = make_api()
    job_id = queued(api)
    api.clock.advance(seconds=60)

    assert api.client.get(f"/jobs/{job_id}").json()["status"] == "queued"


def test_a_queued_job_the_queue_still_holds_is_left_alone() -> None:
    api = make_api()
    job_id = queued(api)
    api.queue.enqueue(job_id)
    api.clock.advance(hours=1)

    assert api.client.get(f"/jobs/{job_id}").json()["status"] == "queued"


def test_redis_down_while_polling_answers_from_postgres() -> None:
    """Review Focus 3: a queue that cannot be asked is not a lost job."""
    api = make_api()
    job_id = queued(api)
    api.queue.down = True
    api.clock.advance(seconds=61)

    response = api.client.get(f"/jobs/{job_id}")

    assert response.status_code == 200
    assert response.json()["status"] == "queued"


def test_a_running_job_long_past_its_timeout_is_failed_on_read() -> None:
    api = make_api(job_timeout_sec=60)
    job_id = running(api)
    api.store.set_progress(job_id, "separation", 12)
    api.clock.advance(seconds=60 + 5 * 60 + 1)

    body = api.client.get(f"/jobs/{job_id}").json()

    assert body["status"] == "failed"
    assert body["failure"]["stage"] == "separation"


def test_a_running_job_inside_timeout_plus_grace_is_left_alone() -> None:
    api = make_api(job_timeout_sec=60)
    job_id = running(api)
    api.clock.advance(seconds=60 + 5 * 60)

    assert api.client.get(f"/jobs/{job_id}").json()["status"] == "running"


def test_a_worker_that_writes_first_wins() -> None:
    api = make_api(job_timeout_sec=60)
    job_id = running(api)
    api.clock.advance(seconds=400)
    stale = api.job(job_id)  # what a slow GET read...
    api.store.set_progress(job_id, "transcription", 40)  # ...before the worker wrote

    assert reconcile(stale, api.services).status is JobStatus.RUNNING
