"""The api's response schema: generated, committed, and true to what the
routes send. The web client's types are generated from it."""

import subprocess
import sys
from pathlib import Path

from api_fixture import make_api
from guitarvis_api.errors import ErrorBody, HttpReason
from guitarvis_api.schema_export import api_schema
from guitarvis_api.schemas import JobView
from guitarvis_core.contracts import FailureReason
from guitarvis_jobs.models import JobStatus
from guitarvis_jobs.store import InMemoryJobStore
from guitarvis_jobs.testing import sample_new_job

REPO_ROOT = Path(__file__).resolve().parents[3]
COMMITTED = REPO_ROOT / "schema" / "api.schema.json"
MISSING_ID = "5f0c6c2e-0000-4000-8000-0000000000ff"
MIB = 1024 * 1024


def upload(data: bytes) -> dict[str, tuple[str, bytes, str]]:
    return {"file": ("song.mp3", data, "audio/mpeg")}


def test_the_export_writes_exactly_the_committed_file(tmp_path: Path) -> None:
    """Byte for byte, since schema-check compares bytes through git."""
    fresh = tmp_path / "api.schema.json"
    subprocess.run(
        [sys.executable, "-m", "guitarvis_api.schema_export", str(fresh)],
        check=True,
    )

    assert COMMITTED.exists(), "run `make schema` and commit the output"
    assert fresh.read_text() == COMMITTED.read_text(), (
        "schema/api.schema.json is stale; run `make schema`"
    )


def test_the_schema_names_all_nine_reasons() -> None:
    definitions = api_schema()["$defs"]
    named = set(definitions["FailureReason"]["enum"]) | set(
        definitions["HttpReason"]["enum"]
    )

    assert named == {r.value for r in FailureReason} | {r.value for r in HttpReason}
    assert len(named) == 9


def test_a_failed_job_can_carry_only_a_failure_reason() -> None:
    """The four HttpReason values describe a request, never a job."""
    reason = api_schema()["$defs"]["FailureView"]["properties"]["reason"]

    assert reason == {"$ref": "#/$defs/FailureReason"}


def test_the_errors_the_routes_send_are_error_bodies() -> None:
    api = make_api(max_active_jobs_per_ip=1, max_upload_mb=1)
    job_id = api.client.post("/jobs", files=upload(b"one")).json()["id"]

    responses = [
        api.client.get(f"/jobs/{MISSING_ID}"),
        api.client.get("/nowhere"),
        api.client.get(f"/jobs/{job_id}/document"),
        api.client.post("/jobs", files=upload(b"two")),
        api.client.post("/jobs", files=upload(b"x" * (MIB + 1))),
        api.client.post("/jobs", data={"nothing": "here"}),
    ]

    assert [r.status_code for r in responses] == [404, 404, 409, 429, 413, 422]
    for response in responses:
        ErrorBody.model_validate(response.json())


def test_an_internal_error_is_an_error_body() -> None:
    class OnFire(InMemoryJobStore):
        def get(self, job_id: str) -> None:
            raise RuntimeError("the database is on fire")

    api = make_api(store=OnFire(), raise_server_exceptions=False)

    response = api.client.get(f"/jobs/{MISSING_ID}")

    assert response.status_code == 500
    ErrorBody.model_validate(response.json())


def test_a_failed_job_is_a_job_view_with_a_typed_reason() -> None:
    api = make_api()
    job, _ = api.store.create(sample_new_job())
    api.store.fail(
        job.id,
        reason=FailureReason.TOO_LONG,
        message="m",
        stage=None,
        expect=JobStatus.QUEUED,
    )

    view = JobView.model_validate(api.client.get(f"/jobs/{job.id}").json())

    assert view.failure is not None
    assert view.failure.reason is FailureReason.TOO_LONG
