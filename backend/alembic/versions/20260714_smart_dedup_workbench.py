"""add smart dedup workbench decisions

Revision ID: 20260714_smart_dedup_workbench
Revises: 20260714_world_bible_synopsis
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "20260714_smart_dedup_workbench"
down_revision = "20260714_world_bible_synopsis"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Databases first initialized by the old dynamic baseline may already have
    # this table.  Keep that upgrade path, while the frozen baseline now leaves
    # creation to this revision on truly fresh databases.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "smart_dedup_workbench_decisions" not in inspector.get_table_names():
        op.create_table(
            "smart_dedup_workbench_decisions",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "novel_id",
                UUID(as_uuid=True),
                sa.ForeignKey("projects.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("asset_type", sa.String(64), nullable=False),
            sa.Column("left_asset_id", sa.String(36), nullable=False),
            sa.Column("right_asset_id", sa.String(36), nullable=False),
            sa.Column("left_semantic_fingerprint", sa.String(64), nullable=False),
            sa.Column("right_semantic_fingerprint", sa.String(64), nullable=False),
            sa.Column("decision", sa.String(32), nullable=False),
            sa.Column("source_scan_task_id", sa.String(36), nullable=False),
            sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=True,
            ),
            sa.CheckConstraint(
                "left_asset_id < right_asset_id",
                name="ck_smart_dedup_decision_sorted_pair",
            ),
            sa.CheckConstraint(
                "decision = 'keep_separate'",
                name="ck_smart_dedup_decision_value",
            ),
        )

    indexes = {
        index["name"]
        for index in sa.inspect(bind).get_indexes(
            "smart_dedup_workbench_decisions"
        )
    }
    if "ix_smart_dedup_workbench_decisions_novel_id" not in indexes:
        op.create_index(
            "ix_smart_dedup_workbench_decisions_novel_id",
            "smart_dedup_workbench_decisions",
            ["novel_id"],
        )
    if "ix_smart_dedup_decision_lookup" not in indexes:
        op.create_index(
            "ix_smart_dedup_decision_lookup",
            "smart_dedup_workbench_decisions",
            [
                "novel_id",
                "asset_type",
                "left_asset_id",
                "right_asset_id",
                "superseded_at",
            ],
        )
    if "uq_smart_dedup_active_disposition" not in indexes:
        op.create_index(
            "uq_smart_dedup_active_disposition",
            "smart_dedup_workbench_decisions",
            [
                "novel_id",
                "asset_type",
                "left_asset_id",
                "right_asset_id",
                "left_semantic_fingerprint",
                "right_semantic_fingerprint",
            ],
            unique=True,
            postgresql_where=sa.text("superseded_at IS NULL"),
            sqlite_where=sa.text("superseded_at IS NULL"),
        )


def downgrade() -> None:
    if "smart_dedup_workbench_decisions" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("smart_dedup_workbench_decisions")
