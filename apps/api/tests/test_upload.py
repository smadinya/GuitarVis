"""POST /jobs: validate, dedupe, limit, store, enqueue — cheapest check first."""

import asyncio
import errno
import hashlib
import json
import logging
import shutil
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace

import httpx2
import pytest
from api_fixture import CLIENT_IP, make_api
from fastapi.testclient import TestClient
from guitarvis_api.errors import UNREADABLE_UPLOAD_MESSAGE, ApiError
from guitarvis_api.uploads import (
    MAX_TITLE_CHARS,
    MULTIPART_ALLOWANCE,
    UploadSizeLimit,
    extension_of,
    title_of,
)
from guitarvis_core.audio import probe_duration
from guitarvis_core.contracts import FailureReason, PipelineError
from guitarvis_jobs.models import INTERNAL_FAILURE_MESSAGE, Job, JobStatus, NewJob
from starlette.datastructures import UploadFile
from starlette.types import Message, Receive, Scope, Send

SONG = b"ID3 pretend these are mp3 bytes"
SONG_HASH = hashlib.sha256(SONG).hexdigest()
MIB = 1024 * 1024

requires_ffprobe = pytest.mark.skipif(
    shutil.which("ffprobe") is None,
    reason="ffprobe not installed; install ffmpeg",
)


def post(
    client: TestClient, data: bytes = SONG, filename: str = "song.mp3"
) -> httpx2.Response:
    return client.post("/jobs", files={"file": (filename, data, "audio/mpeg")})


def refuse(error: PipelineError) -> Callable[[Path], float]:
    """A probe that rejects every file the way ffprobe would."""

    def probe(path: Path) -> float:
        raise error

    return probe


def test_a_new_upload_is_stored_queued_and_accepted() -> None:
    api = make_api()

    response = post(api.client)

    assert response.status_code == 202
    body = response.json()
    assert response.headers["location"] == f"/jobs/{body['id']}"
    assert (body["status"], body["percent"], body["title"], body["duration_sec"]) == (
        "queued",
        0,
        "song",
        30.0,
    )
    assert api.queue.enqueued == [body["id"]]
    job = api.job(body["id"])
    assert job.content_hash == SONG_HASH
    assert job.upload_key == f"uploads/{SONG_HASH}.mp3"
    assert job.client_ip == CLIENT_IP
    assert api.blobs.get_bytes(job.upload_key) == SONG


def test_the_same_file_again_is_the_same_job_and_no_new_work() -> None:
    api = make_api()
    first = post(api.client).json()

    again = post(api.client, filename="renamed.wav")

    assert again.status_code == 200
    assert again.json()["id"] == first["id"]
    assert api.queue.enqueued == [first["id"]]


def test_the_same_file_after_success_returns_the_finished_job() -> None:
    api = make_api()
    job_id = post(api.client).json()["id"]
    api.store.mark_running(job_id)
    api.store.succeed(job_id, document={}, stem_key="k")

    again = post(api.client)

    assert again.status_code == 200
    assert again.json()["status"] == "succeeded"


def test_the_same_file_after_a_failure_starts_over() -> None:
    api = make_api()
    first = post(api.client).json()["id"]
    api.store.mark_running(first)
    api.store.fail(
        first,
        reason=FailureReason.INTERNAL,
        message="m",
        stage=None,
        expect=JobStatus.RUNNING,
    )

    again = post(api.client)

    assert again.status_code == 202
    assert again.json()["id"] != first


def test_reupload_of_a_lost_job_starts_a_fresh_one() -> None:
    """Review Focus 5: the dedupe lookup is a read, so it reconciles."""
    api = make_api()
    first = post(api.client).json()["id"]
    api.queue.lose(first)
    api.clock.advance(seconds=61)

    again = post(api.client)

    assert again.status_code == 202
    assert again.json()["id"] != first
    assert api.job(first).status is JobStatus.FAILED


def test_reupload_of_a_job_the_queue_failed_for_good_starts_a_fresh_one() -> None:
    api = make_api()
    first = post(api.client).json()["id"]
    api.queue.fail_terminally(first)
    api.clock.advance(seconds=61)

    again = post(api.client)

    assert again.status_code == 202
    assert again.json()["id"] != first
    assert api.job(first).status is JobStatus.FAILED


def test_a_duplicate_does_not_count_against_the_limit() -> None:
    api = make_api(max_active_jobs_per_ip=1)
    post(api.client)

    assert post(api.client).status_code == 200


def test_too_many_active_jobs_from_one_address() -> None:
    api = make_api(max_active_jobs_per_ip=2)
    assert post(api.client, b"one").status_code == 202
    assert post(api.client, b"two").status_code == 202

    third = post(api.client, b"three")

    assert third.status_code == 429
    assert third.json()["error"]["reason"] == "too_many_jobs"
    assert post(api.client_from("198.51.100.9"), b"three").status_code == 202
    assert len(api.queue.enqueued) == 3


def test_a_finished_job_frees_its_slot() -> None:
    api = make_api(max_active_jobs_per_ip=1)
    job_id = post(api.client, b"one").json()["id"]
    api.store.mark_running(job_id)
    api.store.succeed(job_id, document={}, stem_key="k")

    assert post(api.client, b"two").status_code == 202


def test_a_file_exactly_at_the_limit_is_accepted() -> None:
    api = make_api(max_upload_mb=1)

    assert post(api.client, b"x" * MIB).status_code == 202


def test_a_file_one_byte_over_the_limit_is_refused() -> None:
    api = make_api(max_upload_mb=1)

    response = post(api.client, b"x" * (MIB + 1))

    assert response.status_code == 413
    assert response.json()["error"]["reason"] == "too_large"
    assert "1 MB" in response.json()["error"]["message"]
    assert api.queue.enqueued == []


def test_a_body_far_over_the_limit_is_refused_by_its_declared_length() -> None:
    api = make_api(max_upload_mb=1)

    response = post(api.client, b"x" * (MIB + 100 * 1024))

    assert response.status_code == 413
    assert response.json()["error"]["reason"] == "too_large"


def test_an_oversized_body_with_no_declared_length_is_abandoned() -> None:
    api = make_api(max_upload_mb=1)

    def chunked() -> Iterator[bytes]:
        yield (
            b'--zzz\r\nContent-Disposition: form-data; name="file"; '
            b'filename="big.mp3"\r\nContent-Type: audio/mpeg\r\n\r\n'
        )
        for _ in range(20):
            yield b"x" * (64 * 1024)
        yield b"\r\n--zzz--\r\n"

    response = api.client.post(
        "/jobs",
        content=chunked(),
        headers={"content-type": "multipart/form-data; boundary=zzz"},
    )

    assert response.status_code == 413
    assert response.json()["error"]["reason"] == "too_large"


def _upload_scope(max_upload_mb: int, content_length: int | None) -> Scope:
    """The scope of a POST /jobs, with the settings the middleware reads."""
    settings = make_api(max_upload_mb=max_upload_mb).settings
    headers = [(b"content-type", b"multipart/form-data; boundary=zzz")]
    if content_length is not None:
        headers.append((b"content-length", str(content_length).encode()))
    return {
        "type": "http",
        "method": "POST",
        "path": "/jobs",
        "headers": headers,
        "app": SimpleNamespace(
            state=SimpleNamespace(services=SimpleNamespace(settings=settings))
        ),
    }


def test_the_middleware_refuses_a_declared_length_before_reading_a_byte() -> None:
    """Without it the route would still say 413, but only after Starlette had
    spooled the whole body to disk."""
    reads = 0
    reached_app = False
    sent: list[Message] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal reached_app
        reached_app = True

    async def receive() -> Message:
        nonlocal reads
        reads += 1
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        sent.append(message)

    scope = _upload_scope(1, content_length=MIB + MULTIPART_ALLOWANCE + 1)
    asyncio.run(UploadSizeLimit(app)(scope, receive, send))

    assert (reads, reached_app) == (0, False)
    assert sent[0]["status"] == 413
    assert json.loads(sent[1]["body"])["error"]["reason"] == "too_large"


def test_the_middleware_abandons_a_chunked_body_as_soon_as_it_passes_the_limit() -> (
    None
):
    chunk = 64 * 1024
    reads = 0

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        while True:  # what Starlette's multipart parser does: read to the end
            message = await receive()
            if not message.get("more_body"):
                return

    async def receive() -> Message:
        nonlocal reads
        reads += 1
        # 2.5 MiB in all, so a middleware that never stops it still ends
        return {"type": "http.request", "body": b"x" * chunk, "more_body": reads < 40}

    async def send(message: Message) -> None:
        raise AssertionError("the middleware must raise, not respond")

    scope = _upload_scope(1, content_length=None)
    with pytest.raises(ApiError) as refused:
        asyncio.run(UploadSizeLimit(app)(scope, receive, send))

    assert refused.value.status_code == 413
    assert reads == (MIB + MULTIPART_ALLOWANCE) // chunk + 1  # not a byte more


def test_an_empty_file_is_refused() -> None:
    response = post(make_api().client, b"")

    assert response.status_code == 422
    assert response.json()["error"]["reason"] == "unsupported_format"


def test_a_file_that_is_not_audio_is_refused_before_it_is_stored() -> None:
    api = make_api(
        probe=refuse(
            PipelineError(
                FailureReason.UNSUPPORTED_FORMAT, "That file could not be read."
            )
        )
    )

    response = post(api.client)

    assert response.status_code == 422
    assert response.json()["error"] == {
        "reason": "unsupported_format",
        "message": "That file could not be read.",
    }
    assert not api.blobs.exists(f"uploads/{SONG_HASH}.mp3")
    assert api.queue.enqueued == []


def test_a_recording_over_ten_minutes_is_refused() -> None:
    response = post(make_api(probe=lambda path: 600.5).client)

    assert response.status_code == 422
    assert response.json()["error"]["reason"] == "too_long"
    assert "single song" in response.json()["error"]["message"]


def test_missing_ffprobe_is_our_problem_not_the_files() -> None:
    api = make_api(
        probe=refuse(PipelineError(FailureReason.INTERNAL, "ffprobe is not installed."))
    )

    response = post(api.client)

    assert response.status_code == 503
    assert response.json()["error"]["reason"] == "internal"


def test_a_request_without_a_file_field() -> None:
    response = make_api().client.post("/jobs", data={"song": "x"})

    assert response.status_code == 422
    assert response.json()["error"]["reason"] == "unsupported_format"
    assert "`file`" in response.json()["error"]["message"]


@pytest.mark.parametrize(
    ("body", "content_type"),
    [
        pytest.param(
            b"not multipart at all",
            "multipart/form-data; boundary=zzz",
            id="garbage-with-a-boundary",
        ),
        pytest.param(b"x", "multipart/form-data", id="no-boundary"),
        pytest.param(
            b"--zzz\r\nContent-Disposition form-data\r\n\r\nabc\r\n--zzz--\r\n",
            "multipart/form-data; boundary=zzz",
            id="malformed-part-header",
        ),
    ],
)
def test_a_body_that_is_not_readable_multipart_is_the_clients_mistake(
    body: bytes, content_type: str
) -> None:
    """Starlette answers these with a bare 400, which would read as our fault."""
    api = make_api()

    response = api.client.post(
        "/jobs", content=body, headers={"content-type": content_type}
    )

    assert response.status_code == 422
    assert response.json() == {
        "error": {"reason": "unsupported_format", "message": UNREADABLE_UPLOAD_MESSAGE}
    }
    assert api.queue.enqueued == []


def test_a_disk_that_fills_while_spooling_the_upload_is_our_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """FastAPI wraps any exception from reading the body in a bare 400. Only
    Starlette's own multipart failures are the client's; this one is ours."""
    full = OSError(errno.ENOSPC, "No space left on device")

    async def write(self: UploadFile, data: bytes) -> None:
        raise full

    monkeypatch.setattr(UploadFile, "write", write)
    api = make_api()

    with caplog.at_level(logging.ERROR, logger="guitarvis_api.errors"):
        response = post(api.client)

    assert response.status_code == 500
    assert response.json() == {
        "error": {"reason": "internal", "message": INTERNAL_FAILURE_MESSAGE}
    }
    logged = [record.exc_info[1] for record in caplog.records if record.exc_info]
    assert logged == [full]
    assert api.queue.enqueued == []


def test_a_queue_that_refuses_the_job() -> None:
    api = make_api()
    api.queue.fail_next = True

    response = post(api.client)

    assert response.status_code == 503
    assert response.json()["error"]["reason"] == "internal"
    assert api.store.find_live(SONG_HASH) is None  # the row was failed, not left queued
    retried = post(api.client)
    assert retried.status_code == 202


def test_a_failed_enqueue_leaves_the_generic_message_on_the_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = make_api()
    api.queue.fail_next = True
    created: list[str] = []
    create = api.store.create

    def recording(new: NewJob) -> tuple[Job, bool]:
        job, was_created = create(new)
        created.append(job.id)
        return job, was_created

    monkeypatch.setattr(api.store, "create", recording)

    post(api.client)

    row = api.job(created[0])
    assert row.status is JobStatus.FAILED
    assert row.failure_reason is FailureReason.INTERNAL
    assert row.failure_message == INTERNAL_FAILURE_MESSAGE


@requires_ffprobe
def test_the_real_probe_refuses_bytes_that_are_not_audio() -> None:
    response = post(make_api(probe=probe_duration).client, b"this is not audio")

    assert response.status_code == 422
    assert response.json()["error"]["reason"] == "unsupported_format"


@pytest.mark.parametrize(
    ("filename", "title", "extension"),
    [
        ("song.mp3", "song", ".mp3"),
        ("Song.MP3", "Song", ".mp3"),
        ("C:\\Users\\me\\Song.MP3", "Song", ".mp3"),
        ("/home/me/riff.wav", "riff", ".wav"),
        ("live.at.wembley.flac", "live.at.wembley", ".flac"),
        ("no-extension", "no-extension", ""),
        ("odd.extension-too-long", "odd", ""),
        ("spaced.m p3", "spaced", ""),
        ("", "Untitled", ""),
        (None, "Untitled", ""),
        ("x" * 300 + ".mp3", "x" * MAX_TITLE_CHARS, ".mp3"),
        ("a\x00b.mp3", "ab", ".mp3"),
        ("\x00", "Untitled", ""),
    ],
)
def test_title_and_extension_from_awkward_filenames(
    filename: str | None, title: str, extension: str
) -> None:
    """Review Focus 1: whatever a browser or curl sends, never a crash."""
    assert title_of(filename) == title
    assert extension_of(filename) == extension


def test_a_windows_path_filename_is_reduced_to_its_basename() -> None:
    api = make_api()

    body = post(api.client, filename="C:\\Users\\me\\Song.MP3").json()

    assert body["title"] == "Song"
    assert api.job(body["id"]).upload_key == f"uploads/{SONG_HASH}.mp3"


def test_a_nul_byte_in_the_filename_is_dropped_not_stored() -> None:
    """Postgres refuses NUL in text, and the in-memory twin does not, so the
    title is checked for it directly."""
    api = make_api()
    body = (
        b'--zzz\r\nContent-Disposition: form-data; name="file"; '
        b'filename="a\x00b.mp3"\r\nContent-Type: audio/mpeg\r\n\r\n'
        + SONG
        + b"\r\n--zzz--\r\n"
    )

    response = api.client.post(
        "/jobs",
        content=body,
        headers={"content-type": "multipart/form-data; boundary=zzz"},
    )

    assert response.status_code == 202
    assert response.json()["title"] == "ab"
    assert "\x00" not in api.job(response.json()["id"]).title
