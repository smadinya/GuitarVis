"""The api on in-memory twins, for route tests.

Imported by bare name, as apps/eval/tests imports guitarset_fixture; there is
no conftest.py anywhere in this repo (see the Makefile's mypy note).
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from guitarvis_api.app import create_app
from guitarvis_api.services import Services
from guitarvis_jobs.blobs import InMemoryBlobStore
from guitarvis_jobs.models import Job
from guitarvis_jobs.queue import InMemoryJobQueue
from guitarvis_jobs.settings import Settings
from guitarvis_jobs.store import InMemoryJobStore
from guitarvis_jobs.testing import FakeClock

CLIENT_IP = "203.0.113.7"


def thirty_seconds(path: Path) -> float:
    return 30.0


@dataclass
class Api:
    client: TestClient
    store: InMemoryJobStore
    blobs: InMemoryBlobStore
    queue: InMemoryJobQueue
    clock: FakeClock
    settings: Settings
    services: Services

    def job(self, job_id: str) -> Job:
        job = self.store.get(job_id)
        assert job is not None, f"no job {job_id}"
        return job

    def client_from(self, ip: str) -> TestClient:
        """Another client of the same app, from another address."""
        return TestClient(self.client.app, client=(ip, 50000))


def make_api(
    *,
    probe: Callable[[Path], float] = thirty_seconds,
    store: InMemoryJobStore | None = None,
    blobs: InMemoryBlobStore | None = None,
    raise_server_exceptions: bool = True,
    **settings: Any,  # Settings fields to override, e.g. max_upload_mb=1
) -> Api:
    clock = FakeClock()
    store = store if store is not None else InMemoryJobStore(clock=clock)
    blobs = blobs if blobs is not None else InMemoryBlobStore()
    queue = InMemoryJobQueue()
    resolved = replace(Settings(), **settings)
    services = Services(
        store=store,
        blobs=blobs,
        queue=queue,
        settings=resolved,
        probe=probe,
        clock=clock,
    )
    client = TestClient(
        create_app(services),
        client=(CLIENT_IP, 50000),
        raise_server_exceptions=raise_server_exceptions,
    )
    return Api(client, store, blobs, queue, clock, resolved, services)
