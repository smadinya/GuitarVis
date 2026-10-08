"""Create the jobs table.

Revision ID: 0001
Revises: (none)
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
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
        sa.Column("document", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="jobs_status_valid",
        ),
        sa.CheckConstraint("percent BETWEEN 0 AND 100", name="jobs_percent_range"),
    )
    op.create_index(
        "jobs_content_hash_live",
        "jobs",
        ["content_hash"],
        unique=True,
        postgresql_where=sa.text("status <> 'failed'"),
    )
    op.create_index("jobs_client_ip_status", "jobs", ["client_ip", "status"])


def downgrade() -> None:
    op.drop_table("jobs")
