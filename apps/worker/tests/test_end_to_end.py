"""The whole service, on real Postgres, Redis and object storage.

Upload through the api, process under a real RQ worker, fetch the results.
The stages are stubbed, so no model loads; ffprobe, the stores, the queue and
the job runner are all real. It lives with the worker because it drives
run_job; the api's own tests never import the worker.
"""

import hashlib
import shutil
import urllib.request
import wave
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from guitarvis_api.app import create_app
from guitarvis_api.services import Services
from guitarvis_core.contracts import (
    NoteEvent,
    SeparationProgress,
    SeparationResult,
    StructureResult,
)
from guitarvis_core.tabdoc import TabDocument, Timing
from guitarvis_fetch.testing import FakeFetcher
from guitarvis_jobs.queue import QUEUE_NAME, RQJobQueue
from guitarvis_jobs.testing import (
    integration_settings,
    postgres_store,
    redis_connection,
    s3_blob_store,
    settings_env,
)
from guitarvis_worker import runner
from guitarvis_worker.runner import Stages
from guitarvis_worker.stages.fretboard import ViterbiFretboardMapper
from redis import Redis
from rq import Queue, SimpleWorker

requires_ffprobe = pytest.mark.skipif(
    shutil.which("ffprobe") is None,
    reason="ffprobe not installed; install ffmpeg",
)


class StubSeparator:
    def isolate(
        self, audio_path: Path, *, progress: SeparationProgress | None = None
    ) -> SeparationResult:
        if progress is not None:
            progress(1.0)
        return SeparationResult(stem_path=audio_path)


class StubTranscriber:
    def transcribe(self, stem_path: Path) -> list[NoteEvent]:
        return [NoteEvent(onset=0.25, duration=0.5, midi=52, confidence=0.8)]


class StubAnalyzer:
    def analyze(self, stem_path: Path, mix_path: Path) -> StructureResult:
        return StructureResult(timing=Timing(), chords=[], sections=[])


def stub_stages(work_dir: Path, device: str | None = None) -> Stages:
    return Stages(
        separator=StubSeparator(),
        transcriber=StubTranscriber(),
        analyzer=StubAnalyzer(),
        mapper=ViterbiFretboardMapper(),
    )


def write_wav(path: Path, seconds: float = 1.0, rate: int = 8000) -> Path:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x01\x00" * int(rate * seconds))
    return path


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, Redis]]:
    with (
        postgres_store() as store,
        s3_blob_store() as blobs,
        redis_connection() as redis,
    ):
        settings = integration_settings()
        # run_job builds its stores from the environment, in this process.
        for name, value in settings_env(settings).items():
            monkeypatch.setenv(name, value)
        monkeypatch.setattr(runner, "build_stages", stub_stages)
        services = Services(
            store=store,
            blobs=blobs,
            queue=RQJobQueue(redis, job_timeout_sec=settings.job_timeout_sec),
            settings=settings,
        )
        yield TestClient(create_app(services)), redis


@requires_ffprobe
def test_upload_process_and_fetch(
    service: tuple[TestClient, Redis], tmp_path: Path
) -> None:
    client, redis = service
    song = write_wav(tmp_path / "song.wav").read_bytes()

    created = client.post("/jobs", files={"file": ("song.wav", song, "audio/wav")})
    assert created.status_code == 202, created.text
    job_id = created.json()["id"]

    again = client.post("/jobs", files={"file": ("again.wav", song, "audio/wav")})
    assert (again.status_code, again.json()["id"]) == (200, job_id)

    SimpleWorker([Queue(QUEUE_NAME, connection=redis)], connection=redis).work(
        burst=True
    )

    job = client.get(f"/jobs/{job_id}").json()
    assert (job["status"], job["percent"], job["attempts"]) == ("succeeded", 100, 1), (
        job
    )

    document = TabDocument.model_validate(client.get(f"/jobs/{job_id}/document").json())
    assert document.source.title == "song"
    assert document.source.audio_url == f"/jobs/{job_id}/audio/mix"
    assert len(document.notes) == 1

    mix = client.get(f"/jobs/{job_id}/audio/mix", follow_redirects=False)
    assert mix.status_code == 307
    request = urllib.request.Request(
        mix.headers["location"], headers={"Range": "bytes=0-3"}
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.status == 206
        assert response.read() == song[:4]

    guitar = client.get(f"/jobs/{job_id}/audio/guitar", follow_redirects=False)
    assert guitar.status_code == 307


@pytest.fixture
def link_service(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[tuple[TestClient, Redis, FakeFetcher]]:
    """The same service with links on, and a fake fetcher at both ends: the
    api's lookup and, through open_deps, the worker's download."""
    content = write_wav(tmp_path / "fetched.wav", seconds=2.0).read_bytes()
    fetcher = FakeFetcher(content=content)
    with (
        postgres_store() as store,
        s3_blob_store() as blobs,
        redis_connection() as redis,
    ):
        settings = replace(integration_settings(), url_ingestion=True)
        for name, value in settings_env(settings).items():
            monkeypatch.setenv(name, value)
        monkeypatch.setattr(runner, "build_stages", stub_stages)
        monkeypatch.setattr(runner, "ChildFetcher", lambda: fetcher)
        services = Services(
            store=store,
            blobs=blobs,
            queue=RQJobQueue(redis, job_timeout_sec=settings.job_timeout_sec),
            settings=settings,
            fetcher=fetcher,
        )
        yield TestClient(create_app(services)), redis, fetcher


@requires_ffprobe
def test_a_link_job_end_to_end(
    link_service: tuple[TestClient, Redis, FakeFetcher],
) -> None:
    client, redis, fetcher = link_service
    assert client.get("/features").json() == {"url_ingestion": True}

    created = client.post(
        "/jobs/from-url", json={"url": "https://youtu.be/kPdv44HtEoA"}
    )
    assert created.status_code == 202, created.text
    job_id = created.json()["id"]
    assert created.json()["source_url"] == "https://www.youtube.com/watch?v=kPdv44HtEoA"
    again = client.post(
        "/jobs/from-url", json={"url": "https://www.youtube.com/shorts/kPdv44HtEoA"}
    )
    assert (again.status_code, again.json()["id"]) == (200, job_id)
    assert len(fetcher.lookups) == 1  # the repeat asked YouTube nothing
    not_yet = client.get(f"/jobs/{job_id}/audio/mix", follow_redirects=False)
    assert not_yet.status_code == 409

    SimpleWorker([Queue(QUEUE_NAME, connection=redis)], connection=redis).work(
        burst=True
    )

    job = client.get(f"/jobs/{job_id}").json()
    assert (job["status"], job["percent"], job["attempts"]) == ("succeeded", 100, 1), (
        job
    )
    assert job["title"] == "Elephants Dream - 10 years of open movies"
    assert job["duration_sec"] == pytest.approx(2.0, abs=0.05)  # ffprobe's
    document = TabDocument.model_validate(client.get(f"/jobs/{job_id}/document").json())
    assert document.source.audio_url == f"/jobs/{job_id}/audio/mix"

    mix = client.get(f"/jobs/{job_id}/audio/mix", follow_redirects=False)
    assert mix.status_code == 307
    assert hashlib.sha256(fetcher.content or b"").hexdigest() in mix.headers["location"]
    with urllib.request.urlopen(mix.headers["location"], timeout=10) as response:
        assert response.read() == fetcher.content
