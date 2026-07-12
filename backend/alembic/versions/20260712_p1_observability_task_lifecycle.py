"""add retrieval observability and fenced task lifecycle

Revision ID: 20260712_p1_observe_lifecycle
Revises: 20260710_scene_cross_suggestions
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op
from core.base import UUIDType

revision = "20260712_p1_observe_lifecycle"
down_revision = "20260710_scene_cross_suggestions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "context_retrieval_traces" not in tables:
        op.create_table(
            "context_retrieval_traces",
            sa.Column("id", UUIDType, primary_key=True),
            sa.Column(
                "novel_id",
                UUIDType,
                sa.ForeignKey("projects.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("content_mode", sa.String(16), nullable=False),
            sa.Column("consumer_action", sa.String(128), nullable=False),
            sa.Column("retrieval_purpose", sa.String(64), nullable=False),
            sa.Column("reveal_mode", sa.String(32), nullable=False),
            sa.Column("scene_id", sa.String(64), nullable=True),
            sa.Column("chapter_index", sa.Integer(), nullable=True),
            sa.Column("plan_version", sa.String(32), nullable=False),
            sa.Column("plan_hash", sa.String(64), nullable=False),
            sa.Column("clause_summaries", sa.JSON(), nullable=False),
            sa.Column("candidate_count", sa.Integer(), nullable=False, default=0),
            sa.Column("unique_count", sa.Integer(), nullable=False, default=0),
            sa.Column("hydrated_count", sa.Integer(), nullable=False, default=0),
            sa.Column("drop_counts", sa.JSON(), nullable=False),
            sa.Column("safe_empty_reason", sa.String(64), nullable=True),
            sa.Column("degraded", sa.Boolean(), nullable=False, default=False),
            sa.Column("warning_codes", sa.JSON(), nullable=False),
            sa.Column("latency_metadata", sa.JSON(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.timezone("utc", sa.func.now()),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.timezone("utc", sa.func.now()),
            ),
            comment="Context retrieval diagnostics without raw query or content",
        )
        op.create_index(
            "ix_context_retrieval_traces_novel_id",
            "context_retrieval_traces",
            ["novel_id"],
        )
        op.create_index(
            "ix_context_retrieval_traces_novel_mode_created",
            "context_retrieval_traces",
            ["novel_id", "content_mode", "created_at"],
        )

    if "async_tasks" in tables:
        columns = {column["name"] for column in inspector.get_columns("async_tasks")}
        additions = {
            "attempt": sa.Column(
                "attempt", sa.Integer(), nullable=False, server_default="0"
            ),
            "max_attempts": sa.Column(
                "max_attempts", sa.Integer(), nullable=False, server_default="1"
            ),
            "recovery_policy": sa.Column(
                "recovery_policy",
                sa.String(32),
                nullable=False,
                server_default="restart_origin",
            ),
            "lease_id": sa.Column("lease_id", sa.String(36), nullable=True),
            "stale_detected_at": sa.Column(
                "stale_detected_at", sa.DateTime(timezone=True), nullable=True
            ),
            "transition_reason": sa.Column(
                "transition_reason", sa.String(64), nullable=True
            ),
        }
        for name, column in additions.items():
            if name not in columns:
                op.add_column("async_tasks", column)
        indexes = {index["name"] for index in sa.inspect(bind).get_indexes("async_tasks")}
        if "ix_async_tasks_lease_id" not in indexes:
            op.create_index("ix_async_tasks_lease_id", "async_tasks", ["lease_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "async_tasks" in tables:
        columns = {column["name"] for column in inspector.get_columns("async_tasks")}
        indexes = {index["name"] for index in inspector.get_indexes("async_tasks")}
        if "ix_async_tasks_lease_id" in indexes:
            op.drop_index("ix_async_tasks_lease_id", table_name="async_tasks")
        for name in (
            "transition_reason",
            "stale_detected_at",
            "lease_id",
            "recovery_policy",
            "max_attempts",
            "attempt",
        ):
            if name in columns:
                op.drop_column("async_tasks", name)
    if "context_retrieval_traces" in tables:
        op.drop_table("context_retrieval_traces")
