"""Add transient binary staging table for local CLI image jobs.

Revision ID: 20260929_local_agent_files
Revises: 20260928_schema_drift_repair
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260929_local_agent_files"
down_revision = "20260928_schema_drift_repair"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "local_agent_files",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "invocation_id",
            uuid,
            sa.ForeignKey("local_agent_invocations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "novel_id",
            uuid,
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(8), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("media_type", sa.String(32), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.UniqueConstraint(
            "invocation_id", "role", "ordinal", name="uq_local_agent_file_slot"
        ),
    )
    op.create_index(
        "ix_local_agent_file_invocation_id",
        "local_agent_files",
        ["invocation_id"],
    )
    op.create_index(
        "ix_local_agent_file_novel_id",
        "local_agent_files",
        ["novel_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_local_agent_file_novel_id", table_name="local_agent_files")
    op.drop_index("ix_local_agent_file_invocation_id", table_name="local_agent_files")
    op.drop_table("local_agent_files")
