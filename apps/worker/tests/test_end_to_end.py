"""The whole service, on real Postgres, Redis and RustFS.

Upload through the api, process under a real RQ worker, fetch the results.
The stages are stubbed, so no model loads; ffprobe, the stores, the queue and
the job runner are all real. It lives with the worker because it drives
run_job; the api's own tests never import the worker.
"""

import shutil
import urllib.request
import wave
from collections.abc import Iterator
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
