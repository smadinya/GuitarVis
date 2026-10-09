"""The jobs table in Postgres, through SQLAlchemy Core and psycopg 3.

Alembic owns the schema (guitarvis_jobs/migrations). The table below
describes it for queries, and test_migrations.py fails if the two disagree.
Status and reason values go in as plain strings: psycopg would write an
Enum's *name*, not its value.
"""

import uuid
from collections.abc import Collection
from datetime import datetime
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from guitarvis_core.contracts import FailureReason
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.dialects.postgresql import insert as pg_insert

from guitarvis_jobs.models import ACTIVE_STATUSES, Job, JobStatus, NewJob, canonical_id
from guitarvis_jobs.store import Clock, TooManyActiveJobs, utc_now

metadata = sa.MetaData()

# The partial unique index's predicate, as literal SQL. ON CONFLICT names it
# too, and must do so with a constant: a bound parameter matches the index
# only while Postgres plans with its value, and once psycopg prepares the
# statement Postgres may switch to a generic plan that cannot prove it.
_LIVE_INDEX_PREDICATE = "status <> 'failed'"

jobs = sa.Table(
    "jobs",
    metadata,
    sa.Column("id", UUID(as_uuid=False), primary_key=True),
    sa.Column("content_hash", sa.Text(), nullable=False),
    sa.Column("status", sa.Text(), nullable=False),
    sa.Column("stage", sa.Text(), nullable=True),
    sa.Column("percent", sa.Integer(), nullable=False),
    sa.Column("attempts", sa.Integer(), nullable=False),
    sa.Column("failure_reason", sa.Text(), nullable=True),
    sa.Column("failure_message", sa.Text(), nullable=True),
    sa.Column("failed_stage", sa.Text(), nullable=True),
    sa.Column("title", sa.Text(), nullable=False),
    sa.Column("duration_sec", sa.Float(), nullable=False),
    sa.Column("upload_key", sa.Text(), nullable=False),
    sa.Column("stem_key", sa.Text(), nullable=True),
    sa.Column("client_ip", sa.Text(), nullable=False),
    sa.Column("document", JSONB(), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint(
        "status IN ('queued', 'running', 'succeeded', 'failed')",
        name="jobs_status_valid",
    ),
    sa.CheckConstraint("percent BETWEEN 0 AND 100", name="jobs_percent_range"),
    # The dedupe rule: one live job per upload; a failed one never blocks.
    sa.Index(
        "jobs_content_hash_live",
        "content_hash",
        unique=True,
        postgresql_where=sa.text(_LIVE_INDEX_PREDICATE),
    ),
    sa.Index("jobs_client_ip_status", "client_ip", "status"),
)

_LIVE = jobs.c.status != JobStatus.FAILED.value


class PostgresJobStore:
    """Implements JobStore."""

    def __init__(self, engine: sa.Engine, clock: Clock = utc_now) -> None:
        self.engine = engine
        self._clock = clock

    @classmethod
    def from_url(cls, url: str, clock: Clock = utc_now) -> "PostgresJobStore":
        engine = sa.create_engine(
            url, pool_pre_ping=True, connect_args={"connect_timeout": 5}
        )
        return cls(engine, clock)

    def create(self, new: NewJob, *, max_active: int | None = None) -> tuple[Job, bool]:
        # Retried because the live row this insert collided with can fail
        # between the insert and the read; the next insert then succeeds.
        for _ in range(3):
            now = self._clock()
            insert = (
                pg_insert(jobs)
                .values(
                    id=str(uuid.uuid4()),
                    content_hash=new.content_hash,
                    status=JobStatus.QUEUED.value,
                    stage=None,
                    percent=0,
                    attempts=0,
                    title=new.title,
                    duration_sec=new.duration_sec,
                    upload_key=new.upload_key,
                    client_ip=new.client_ip,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_nothing(
                    index_elements=[jobs.c.content_hash],
                    index_where=sa.text(_LIVE_INDEX_PREDICATE),
                )
                .returning(*jobs.c)
            )
            with self.engine.begin() as connection:
                if max_active is not None:
                    already = _check_limit(connection, new, max_active)
                    if already is not None:
                        return already, False
                row = connection.execute(insert).mappings().one_or_none()
                if row is not None:
                    return _to_job(row), True
                live = (
                    connection.execute(_live_for(new.content_hash))
                    .mappings()
                    .one_or_none()
                )
            if live is not None:
                return _to_job(live), False
        raise RuntimeError(
            f"could neither create nor find a live job for {new.content_hash}"
        )

    def get(self, job_id: str) -> Job | None:
        key = canonical_id(job_id)
        if key is None:
            return None
        return self._one(sa.select(jobs).where(jobs.c.id == key))

    def find_live(self, content_hash: str) -> Job | None:
        return self._one(_live_for(content_hash))

    def count_active(self, client_ip: str) -> int:
        with self.engine.connect() as connection:
            return int(connection.execute(_active_from(client_ip)).scalar_one())

    def active_jobs(self, client_ip: str) -> list[Job]:
        statement = (
            sa.select(jobs)
            .where(*_is_active_from(client_ip))
            .order_by(jobs.c.created_at, jobs.c.id)
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [_to_job(row) for row in rows]

    def mark_running(self, job_id: str) -> Job | None:
        return self._update(
            job_id,
            ACTIVE_STATUSES,
            {
                "status": JobStatus.RUNNING.value,
                "attempts": jobs.c.attempts + 1,
                "stage": None,
                "percent": 0,
            },
        )

    def set_progress(self, job_id: str, stage: str, percent: int) -> bool:
        changed = self._update(
            job_id, {JobStatus.RUNNING}, {"stage": stage, "percent": percent}
        )
        return changed is not None

    def succeed(self, job_id: str, *, document: dict[str, Any], stem_key: str) -> bool:
        changed = self._update(
            job_id,
            {JobStatus.RUNNING},
            {
                "status": JobStatus.SUCCEEDED.value,
                "stage": None,
                "percent": 100,
                "document": document,
                "stem_key": stem_key,
            },
        )
        return changed is not None

    def fail(
        self,
        job_id: str,
        *,
        reason: FailureReason,
        message: str,
        stage: str | None,
        expect: JobStatus,
        expect_updated_at: datetime | None = None,
    ) -> bool:
        changed = self._update(
            job_id,
            {expect},
            {
                "status": JobStatus.FAILED.value,
                "stage": None,
                "failure_reason": reason.value,
                "failure_message": message,
                "failed_stage": stage,
            },
            expect_updated_at=expect_updated_at,
        )
        return changed is not None

    def requeue(self, job_id: str) -> bool:
        changed = self._update(
            job_id,
            {JobStatus.RUNNING},
            {"status": JobStatus.QUEUED.value, "stage": None, "percent": 0},
        )
        return changed is not None

    def ping(self) -> None:
        with self.engine.connect() as connection:
            connection.execute(sa.text("SELECT 1"))

    def _one(self, statement: sa.Select[Any]) -> Job | None:
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().one_or_none()
        return None if row is None else _to_job(row)

    def _update(
        self,
        job_id: str,
        allowed: Collection[JobStatus],
        values: dict[str, Any],
        *,
        expect_updated_at: datetime | None = None,
    ) -> Job | None:
        key = canonical_id(job_id)
        if key is None:
            return None
        conditions = [
            jobs.c.id == key,
            jobs.c.status.in_([status.value for status in allowed]),
        ]
        if expect_updated_at is not None:
            conditions.append(jobs.c.updated_at == expect_updated_at)
        statement = (
            sa.update(jobs)
            .where(*conditions)
            .values(updated_at=self._clock(), **values)
            .returning(*jobs.c)
        )
        with self.engine.begin() as connection:
            row = connection.execute(statement).mappings().one_or_none()
        return None if row is None else _to_job(row)


def _live_for(content_hash: str) -> sa.Select[Any]:
    return sa.select(jobs).where(jobs.c.content_hash == content_hash, _LIVE)


def _is_active_from(client_ip: str) -> tuple[sa.ColumnElement[bool], ...]:
    return (
        jobs.c.client_ip == client_ip,
        jobs.c.status.in_([status.value for status in ACTIVE_STATUSES]),
    )


def _active_from(client_ip: str) -> sa.Select[Any]:
    return (
        sa.select(sa.func.count()).select_from(jobs).where(*_is_active_from(client_ip))
    )


def _check_limit(connection: sa.Connection, new: NewJob, max_active: int) -> Job | None:
    """Raise TooManyActiveJobs if the address is at its limit; return the
    live row for the hash, which the limit never refuses.

    The advisory lock serialises creates from one address until the
    transaction ends, so the next one counts this one's row rather than
    racing it. An address hashing alike to another only waits its turn.
    """
    connection.execute(
        sa.select(
            sa.func.pg_advisory_xact_lock(sa.func.hashtextextended(new.client_ip, 0))
        )
    )
    live = connection.execute(_live_for(new.content_hash)).mappings().one_or_none()
    if live is not None:
        return _to_job(live)
    active = int(connection.execute(_active_from(new.client_ip)).scalar_one())
    if active >= max_active:
        raise TooManyActiveJobs(active)
    return None


def _to_job(row: sa.RowMapping) -> Job:
    reason = row["failure_reason"]
    return Job(
        id=str(row["id"]),
        content_hash=row["content_hash"],
        status=JobStatus(row["status"]),
        stage=row["stage"],
        percent=row["percent"],
        attempts=row["attempts"],
        failure_reason=None if reason is None else FailureReason(reason),
        failure_message=row["failure_message"],
        failed_stage=row["failed_stage"],
        title=row["title"],
        duration_sec=row["duration_sec"],
        upload_key=row["upload_key"],
        stem_key=row["stem_key"],
        client_ip=row["client_ip"],
        document=row["document"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


if TYPE_CHECKING:  # Static conformance: the typed assignment is what mypy checks.
    from guitarvis_jobs.store import JobStore

    _conforms: JobStore = PostgresJobStore(sa.create_engine("postgresql://"))
