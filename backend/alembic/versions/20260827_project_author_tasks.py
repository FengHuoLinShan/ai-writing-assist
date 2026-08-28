"""Add project-owned lightweight author tasks.

Revision ID: 20260827_project_author_tasks
Revises: 20260827_world_authority_phase0
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260827_project_author_tasks"
down_revision = "20260827_world_authority_phase0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_author_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("source_kind", sa.String(32), nullable=True),
        sa.Column("source_id", sa.String(64), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "status IN ('open', 'completed', 'archived')",
            name="ck_project_author_tasks_status",
        ),
        sa.CheckConstraint(
            "length(trim(title)) > 0",
            name="ck_project_author_tasks_title_not_blank",
        ),
        sa.CheckConstraint(
            "note IS NULL OR length(note) <= 4000",
            name="ck_project_author_tasks_note_length",
        ),
        sa.CheckConstraint(
            "(source_kind IS NULL) = (source_id IS NULL)",
            name="ck_project_author_tasks_source_pair",
        ),
        sa.CheckConstraint(
            "source_kind IS NULL OR source_kind IN "
            "('world_page', 'world_entity', 'writing_chapter', 'outline_scene')",
            name="ck_project_author_tasks_source_kind",
        ),
        sa.CheckConstraint(
            "(status = 'completed' AND completed_at IS NOT NULL) OR "
            "(status <> 'completed' AND completed_at IS NULL)",
            name="ck_project_author_tasks_completed_at",
        ),
        sa.ForeignKeyConstraint(
            ["novel_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="作者个人轻量待办；不承载领域决定或后台任务",
    )
    op.create_index(
        "ix_project_author_tasks_novel_id",
        "project_author_tasks",
        ["novel_id"],
    )
    op.create_index(
        "ix_project_author_tasks_status",
        "project_author_tasks",
        ["status"],
    )
    op.create_index(
        "ix_project_author_tasks_due_date",
        "project_author_tasks",
        ["due_date"],
    )
    op.create_index(
        "ix_project_author_tasks_scope",
        "project_author_tasks",
        ["novel_id", "status", "due_date", "updated_at"],
    )


def downgrade() -> None:
    op.drop_table("project_author_tasks")
