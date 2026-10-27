"""What a request handler needs, bundled so tests can hand in the twins."""

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from guitarvis_core.audio import probe_duration
from guitarvis_fetch.fetcher import ChildFetcher, UrlFetcher
from guitarvis_jobs.blobs import BlobStore, S3BlobStore
from guitarvis_jobs.postgres import PostgresJobStore
from guitarvis_jobs.queue import JobQueue, RQJobQueue
from guitarvis_jobs.settings import Settings
from guitarvis_jobs.store import Clock, JobStore, utc_now

# Spec 012: a lookup holds a thread until its child answers, so a process
# runs at most this many at once and turns the next away at once.
MAX_CONCURRENT_LOOKUPS = 4


@dataclass(frozen=True)
class Services:
    store: JobStore
    blobs: BlobStore
    queue: JobQueue
    settings: Settings
    probe: Callable[[Path], float] = probe_duration
    clock: Clock = utc_now
    # None when links are off: then nothing in the api can fetch.
    fetcher: UrlFetcher | None = None
    lookups: threading.Semaphore = field(
        default_factory=lambda: threading.BoundedSemaphore(MAX_CONCURRENT_LOOKUPS)
    )


def build_services(settings: Settings) -> Services:
    """The real stores. Nothing here connects until first use."""
    return Services(
        store=PostgresJobStore.from_url(settings.database_url),
        blobs=S3BlobStore.from_settings(settings),
        queue=RQJobQueue.from_settings(settings),
        settings=settings,
        fetcher=ChildFetcher() if settings.url_ingestion else None,
    )
