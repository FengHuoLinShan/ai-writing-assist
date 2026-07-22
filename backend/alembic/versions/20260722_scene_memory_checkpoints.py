"""Add Scene-anchored memory events, checkpoints, and sparse snapshots.

Revision ID: 20260722_scene_memory
Revises: 20260722_map_visual_history
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260722_scene_memory"
down_revision = "20260722_map_visual_history"
branch_labels = None
depends_on = None


def _uuid_type():
    return sa.CHAR(36).with_variant(postgresql.UUID(as_uuid=True), "postgresql")


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("memory_scene_checkpoints") and inspector.has_table(
        "memory_scene_snapshots"
    ):
        return
    guid = _uuid_type()
    op.add_column("memory_events", sa.Column("scene_id", guid, nullable=True))
    op.add_column("memory_events", sa.Column("scene_index", sa.Integer(), nullable=True))
    op.add_column(
        "memory_events", sa.Column("scene_sequence", sa.Integer(), nullable=True)
    )
    op.add_column("memory_events", sa.Column("dimension", sa.String(32), nullable=True))
    op.create_index("ix_memory_events_scene_id", "memory_events", ["scene_id"])
    op.create_index("ix_memory_events_scene_index", "memory_events", ["scene_index"])
    op.create_index("ix_memory_events_dimension", "memory_events", ["dimension"])
    op.create_unique_constraint(
        "uq_memory_events_novel_scene_sequence",
        "memory_events",
        ["novel_id", "scene_id", "scene_sequence"],
    )

    op.create_table(
        "memory_scene_checkpoints",
        sa.Column("id", guid, nullable=False),
        sa.Column("novel_id", guid, nullable=False),
        sa.Column("scene_id", guid, nullable=False),
        sa.Column("scene_index", sa.Integer(), nullable=False),
        sa.Column("stage_index", sa.Integer(), nullable=False),
        sa.Column("dimension", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("confirmed", sa.Boolean(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("state_json", sa.JSON(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("display_summary", sa.Text(), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("gap_reason", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("decision_summary", sa.Text(), nullable=True),
        sa.Column("supersedes_id", guid, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        comment="Scene 分维度轻量状态与覆盖缺口",
    )
    op.create_index(
        "uq_memory_scene_checkpoint_current",
        "memory_scene_checkpoints",
        ["novel_id", "scene_id", "dimension"],
        unique=True,
        postgresql_where=sa.text("is_current"),
        sqlite_where=sa.text("is_current = 1"),
    )
    op.create_index(
        "ix_memory_scene_checkpoint_order",
        "memory_scene_checkpoints",
        ["novel_id", "scene_index", "dimension"],
    )
    op.create_index(
        "ix_memory_scene_checkpoints_novel_id",
        "memory_scene_checkpoints",
        ["novel_id"],
    )
    op.create_index(
        "ix_memory_scene_checkpoints_scene_id",
        "memory_scene_checkpoints",
        ["scene_id"],
    )

    op.create_table(
        "memory_scene_snapshots",
        sa.Column("id", guid, nullable=False),
        sa.Column("novel_id", guid, nullable=False),
        sa.Column("scene_id", guid, nullable=True),
        sa.Column("scene_index", sa.Integer(), nullable=True),
        sa.Column("stage_index", sa.Integer(), nullable=False),
        sa.Column("snapshot_reasons", sa.JSON(), nullable=False),
        sa.Column("full_state", sa.JSON(), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("is_latest", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        comment="Scene 时间轴稀疏全量快照",
    )
    op.create_index(
        "uq_memory_scene_snapshot_current_stage",
        "memory_scene_snapshots",
        ["novel_id", "stage_index"],
        unique=True,
        postgresql_where=sa.text("is_current"),
        sqlite_where=sa.text("is_current = 1"),
    )
    op.create_index(
        "ix_memory_scene_snapshot_latest",
        "memory_scene_snapshots",
        ["novel_id", "is_latest"],
    )
    op.create_index(
        "ix_memory_scene_snapshots_novel_id",
        "memory_scene_snapshots",
        ["novel_id"],
    )


def downgrade() -> None:
    op.drop_table("memory_scene_snapshots")
    op.drop_table("memory_scene_checkpoints")
    op.drop_constraint(
        "uq_memory_events_novel_scene_sequence", "memory_events", type_="unique"
    )
    op.drop_index("ix_memory_events_dimension", table_name="memory_events")
    op.drop_index("ix_memory_events_scene_index", table_name="memory_events")
    op.drop_index("ix_memory_events_scene_id", table_name="memory_events")
    op.drop_column("memory_events", "dimension")
    op.drop_column("memory_events", "scene_sequence")
    op.drop_column("memory_events", "scene_index")
    op.drop_column("memory_events", "scene_id")
