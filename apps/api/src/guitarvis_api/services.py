"""What a request handler needs, bundled so tests can hand in the twins."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from guitarvis_core.audio import probe_duration
from guitarvis_jobs.blobs import BlobStore, S3BlobStore
from guitarvis_jobs.postgres import PostgresJobStore
from guitarvis_jobs.queue import JobQueue, RQJobQueue
from guitarvis_jobs.settings import Settings
from guitarvis_jobs.store import Clock, JobStore, utc_now


@dataclass(frozen=True)
class Services:
    store: JobStore
    blobs: BlobStore
    queue: JobQueue
    settings: Settings
    probe: Callable[[Path], float] = probe_duration
    clock: Clock = utc_now


def build_services(settings: Settings) -> Services:
    """The real stores. Nothing here connects until first use."""
    return Services(
        store=PostgresJobStore.from_url(settings.database_url),
        blobs=S3BlobStore.from_settings(settings),
        queue=RQJobQueue.from_settings(settings),
        settings=settings,
    )
