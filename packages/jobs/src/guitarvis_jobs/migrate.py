"""`make migrate`: bring the database up to date.

There is no alembic.ini. The database URL comes from Settings like every
other address, and the migrations ship inside the package.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

from guitarvis_jobs.settings import Settings

MIGRATIONS = Path(__file__).resolve().parent / "migrations"


def alembic_config(database_url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    # ConfigParser interpolates %, which a URL-encoded password can contain.
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def upgrade(database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "head")


def main() -> int:
    settings = Settings.from_env()
    upgrade(settings.database_url)
    shown = make_url(settings.database_url).render_as_string(hide_password=True)
    print(f"database up to date: {shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
