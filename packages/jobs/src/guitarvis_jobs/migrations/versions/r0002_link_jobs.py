"""Link jobs: source_url, and an upload_key that waits for the download.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("source_url", sa.Text(), nullable=True))
    op.alter_column("jobs", "upload_key", existing_type=sa.Text(), nullable=True)
    op.create_check_constraint(
        "jobs_has_audio_source",
        "jobs",
        "upload_key IS NOT NULL OR source_url IS NOT NULL",
    )


def downgrade() -> None:
    # A link job whose download was never stored has nothing a 0001 row
    # could point at. It goes: going down is for development databases.
    op.execute("DELETE FROM jobs WHERE upload_key IS NULL")
    op.drop_constraint("jobs_has_audio_source", "jobs", type_="check")
    op.alter_column("jobs", "upload_key", existing_type=sa.Text(), nullable=False)
    op.drop_column("jobs", "source_url")
