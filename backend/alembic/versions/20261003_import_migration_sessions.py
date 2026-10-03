"""Add import migration sessions for spreadsheet migration (ADR-0030).

Revision ID: 20261003_import_migration_sessions
Revises: 20260929_world_object_image_candidates
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261003_import_migration_sessions"
down_revision = "20260929_world_object_image_candidates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "import_migration_sessions",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "novel_id",
            uuid,
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("owner_id", uuid, nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("file_manifest", sa.JSON(), nullable=False),
        sa.Column("rows_json", sa.JSON(), nullable=False),
        sa.Column("mapping_json", sa.JSON(), nullable=False),
        sa.Column("decisions_json", sa.JSON(), nullable=False),
        sa.Column("plan_json", sa.JSON(), nullable=False),
        sa.Column("preview_hash", sa.String(64), nullable=True),
        sa.Column(
            "ai_task_id",
            uuid,
            sa.ForeignKey("async_tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("ai_status", sa.String(16), nullable=False),
        sa.Column("ai_scope_hash", sa.String(64), nullable=True),
        sa.Column("ai_authorization", sa.JSON(), nullable=False),
        sa.Column("ai_result_json", sa.JSON(), nullable=False),
        sa.Column("receipt_json", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('draft', 'applied', 'rolled_back', 'partially_rolled_back')",
            name="ck_import_migration_sessions_status",
        ),
    )
    op.create_index(
        "ix_import_migration_sessions_novel_created",
        "import_migration_sessions",
        ["novel_id", "created_at"],
    )
    op.create_index(
        op.f("ix_import_migration_sessions_novel_id"),
        "import_migration_sessions",
        ["novel_id"],
    )
    op.create_index(
        op.f("ix_import_migration_sessions_owner_id"),
        "import_migration_sessions",
        ["owner_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_import_migration_sessions_owner_id"),
        table_name="import_migration_sessions",
    )
    op.drop_index(
        op.f("ix_import_migration_sessions_novel_id"),
        table_name="import_migration_sessions",
    )
    op.drop_index(
        "ix_import_migration_sessions_novel_created",
        table_name="import_migration_sessions",
    )
    op.drop_table("import_migration_sessions")
