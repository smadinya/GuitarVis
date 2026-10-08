"""Test support shared by every package's tests.

Imported by tests only — never by the api or the worker. It is test-only code
that needs pytest (the dev dependency group), which is why nothing outside
tests may import it. It lives in the package rather than in a conftest.py
because a second conftest.py anywhere in PY_SOURCES collides in mypy (see the
Makefile).
"""

import functools
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit, urlunsplit

import pytest
import sqlalchemy as sa
from redis import Redis
from sqlalchemy.engine import make_url

from guitarvis_jobs.blobs import S3BlobStore, s3_client
from guitarvis_jobs.migrate import upgrade
from guitarvis_jobs.models import NewJob
from guitarvis_jobs.postgres import PostgresJobStore
from guitarvis_jobs.settings import Settings
from guitarvis_jobs.store import Clock, utc_now


class FakeClock:
    """A clock a test moves by hand.

    It never ticks on its own, so two writes in one test carry the same
    `updated_at` unless the test advances it between them. Postgres keeps
    microseconds; advance by at least that much.
    """

    def __init__(
        self, start: datetime = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    ) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


def sample_new_job(
    *,
    content_hash: str = "a" * 64,
    title: str = "song",
    duration_sec: float = 30.0,
    upload_key: str | None = None,
    client_ip: str = "203.0.113.7",
) -> NewJob:
    return NewJob(
        content_hash=content_hash,
        title=title,
        duration_sec=duration_sec,
        upload_key=upload_key or f"uploads/{content_hash}.mp3",
        client_ip=client_ip,
    )


REQUIRE_SERVICES_ENV = "GUITARVIS_REQUIRE_SERVICES"
TEST_DATABASE = "guitarvis_test"
TEST_REDIS_DB = 15
TEST_BUCKET = "guitarvis-test"


def integration_settings() -> Settings:
    """The environment's settings, pointed at the test database, Redis db 15
    and the test bucket — never at the stores `make api` uses."""
    base = Settings.from_env()
    return replace(
        base,
        database_url=make_url(base.database_url)
        .set(database=TEST_DATABASE)
        .render_as_string(hide_password=False),
        redis_url=urlunsplit(
            urlsplit(base.redis_url)._replace(path=f"/{TEST_REDIS_DB}")
        ),
        s3_bucket=TEST_BUCKET,
    )


def settings_env(settings: Settings) -> dict[str, str]:
    """`settings` as the GUITARVIS_* variables Settings.from_env reads back.

    The end-to-end test sets these, because run_job builds its own stores
    from the environment exactly as it does under a real worker.
    """
    values = {field.name: getattr(settings, field.name) for field in fields(settings)}
    return {
        f"GUITARVIS_{name.upper()}": str(value)
        for name, value in values.items()
        if value is not None
    }


def require(service: str) -> None:
    """Skip the calling test when `service` is down — or fail it, when
    GUITARVIS_REQUIRE_SERVICES=1 says every service must be up, as in CI."""
    problem = _probe(service)
    if problem is None:
        return
    message = f"{service} is not reachable ({problem}). Run `make services`."
    if os.environ.get(REQUIRE_SERVICES_ENV) == "1":
        pytest.fail(message, pytrace=False)
    pytest.skip(message)


def _ping_postgres(settings: Settings) -> None:
    engine = sa.create_engine(
        settings.database_url, connect_args={"connect_timeout": 2}
    )
    try:
        with engine.connect() as connection:
            connection.execute(sa.text("SELECT 1"))
    finally:
        engine.dispose()


def _ping_redis(settings: Settings) -> None:
    connection = Redis.from_url(settings.redis_url, socket_connect_timeout=1)
    try:
        connection.ping()
    finally:
        connection.close()


def _ping_storage(settings: Settings) -> None:
    client = s3_client(
        settings, settings.s3_endpoint, connect_timeout=1, max_attempts=1
    )
    client.list_buckets()


_PINGS: dict[str, Callable[[Settings], None]] = {
    "postgres": _ping_postgres,
    "redis": _ping_redis,
    "storage": _ping_storage,
}


@functools.cache
def _probe(service: str) -> str | None:
    """None when `service` answers, else why not. Asked once per process."""
    ping = _PINGS[service]  # a typo is a KeyError, never a silent skip
    try:
        ping(integration_settings())
    except Exception as exc:
        return f"{exc.__class__.__name__}: {exc}"
    return None


@contextmanager
def postgres_store(clock: Clock = utc_now) -> Iterator[PostgresJobStore]:
    """A PostgresJobStore on the migrated test database, empty before and after."""
    require("postgres")
    url = integration_settings().database_url
    _migrate_once(url)
    store = PostgresJobStore.from_url(url, clock=clock)
    _truncate(store)
    try:
        yield store
    finally:
        _truncate(store)
        store.engine.dispose()


@functools.cache
def _migrate_once(database_url: str) -> None:
    upgrade(database_url)


def _truncate(store: PostgresJobStore) -> None:
    with store.engine.begin() as connection:
        connection.execute(sa.text("TRUNCATE jobs"))


@contextmanager
def redis_connection() -> Iterator[Redis]:
    """Redis database 15, flushed before and after."""
    require("redis")
    connection = Redis.from_url(integration_settings().redis_url)
    connection.flushdb()
    try:
        yield connection
    finally:
        connection.flushdb()
        connection.close()


@contextmanager
def s3_blob_store() -> Iterator[S3BlobStore]:
    """The test bucket, created if missing, emptied before and after."""
    require("storage")
    settings = integration_settings()
    store = S3BlobStore.from_settings(settings)
    store.ensure_bucket()
    _empty_bucket(settings)
    try:
        yield store
    finally:
        _empty_bucket(settings)


def _empty_bucket(settings: Settings) -> None:
    client = s3_client(settings, settings.s3_endpoint)
    for page in client.get_paginator("list_objects_v2").paginate(
        Bucket=settings.s3_bucket
    ):
        for item in page.get("Contents", []):
            client.delete_object(Bucket=settings.s3_bucket, Key=item["Key"])
