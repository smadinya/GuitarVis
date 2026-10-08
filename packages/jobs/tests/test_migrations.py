"""The Alembic migration and the table the code queries must agree."""

import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from guitarvis_jobs.migrate import MIGRATIONS, alembic_config, upgrade
from guitarvis_jobs.postgres import metadata
from guitarvis_jobs.testing import integration_settings, postgres_store


def test_the_migrations_build_exactly_the_table_the_code_queries() -> None:
    with postgres_store() as store, store.engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), metadata)

    assert diff == [], f"migrations and postgres.py disagree: {diff}"


def test_upgrading_twice_is_harmless() -> None:
    url = integration_settings().database_url
    head = ScriptDirectory.from_config(alembic_config(url)).get_current_head()

    with postgres_store() as store:
        upgrade(url)

        with store.engine.connect() as connection:
            current = MigrationContext.configure(connection).get_current_revision()
            assert sa.inspect(connection).has_table("jobs")
    assert current == head


def test_migration_files_have_importable_names() -> None:
    # mypy scans packages/jobs/src and derives a module name from each file;
    # Alembic's usual "0001_x.py" is not a valid one.
    versions = sorted((MIGRATIONS / "versions").glob("*.py"))

    assert versions, "no migrations found"
    assert all(path.stem.isidentifier() for path in versions)
