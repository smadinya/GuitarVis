"""Test support shared by every package's tests.

Imported by tests only — never by the api or the worker. It lives in the
package rather than in a conftest.py because a second conftest.py anywhere in
PY_SOURCES collides in mypy (see the Makefile).
"""

from datetime import UTC, datetime, timedelta

from guitarvis_jobs.models import NewJob


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
