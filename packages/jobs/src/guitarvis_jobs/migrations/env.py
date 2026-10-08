"""Alembic's entry point, run by `python -m guitarvis_jobs.migrate`.

There is no alembic.ini: migrate.py supplies the script location and the
database URL. To add a migration, copy versions/r0001_create_jobs.py to the
next number, set `revision` and `down_revision`, and keep the file name a
valid identifier (test_migrations.py checks).
"""

from alembic import context
from guitarvis_jobs.postgres import metadata
from sqlalchemy import create_engine


def run_migrations() -> None:
    url = context.config.get_main_option("sqlalchemy.url")
    if url is None:
        raise RuntimeError("no database URL; run `python -m guitarvis_jobs.migrate`")
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Offline migrations are not supported.")
run_migrations()
