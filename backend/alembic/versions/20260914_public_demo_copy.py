"""Persist idempotent owner copies of configured public demo revisions.

Revision ID: 20260914_public_demo_copy
Revises: 20260913_schema_parity_repair
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260914_public_demo_copy"
down_revision = "20260913_schema_parity_repair"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "demo_project_copies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_version", sa.String(length=128), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_project_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id",
            "source_project_id",
            "source_version",
            name="uq_demo_project_copies_owner_source_version",
        ),
        sa.UniqueConstraint("project_id", name="uq_demo_project_copies_project"),
        comment="登录作者从公开演示创建的可编辑项目副本",
    )
    op.create_index(
        "ix_demo_project_copies_owner_id", "demo_project_copies", ["owner_id"]
    )
    op.create_index(
        "ix_demo_project_copies_source",
        "demo_project_copies",
        ["source_project_id", "source_version"],
    )


def downgrade() -> None:
    op.drop_table("demo_project_copies")
