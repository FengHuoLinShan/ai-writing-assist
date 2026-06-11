"""废弃旧 memory 卡片表，新建事件溯源型 memory_events + memory_snapshots

Revision ID: d967c0547257
Revises: d967c0547256
Create Date: 2026-06-01 21:28:33.370518
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d967c0547257"
down_revision: str | None = "d967c0547256"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -----------------------------------------------------------
    # 1. 废弃旧 memory 卡片表
    # -----------------------------------------------------------
    op.drop_table("memory_update_proposals", if_exists=True)
    op.drop_table("memory_records", if_exists=True)

    # -----------------------------------------------------------
    # 2. memory_events — 每章的变化事件（真相源）
    # -----------------------------------------------------------
    op.create_table(
        "memory_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "novel_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chapter_index", sa.Integer(), nullable=False, comment="所属章节"),
        sa.Column("sequence", sa.Integer(), nullable=False, comment="章内事件顺序"),
        sa.Column(
            "event_type",
            sa.String(64),
            nullable=False,
            comment="entity_created | entity_updated | entity_removed | entity_moved | relation_established | relation_ended | knowledge_changed | manual_correction",
        ),
        sa.Column(
            "entity_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="影响的实体 ID",
        ),
        sa.Column(
            "entity_type",
            sa.String(32),
            nullable=True,
            comment="character | location | faction | item | event",
        ),
        sa.Column(
            "snapshot_before",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="变化前状态（创建事件为 null）",
        ),
        sa.Column(
            "snapshot_after",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="变化后状态",
        ),
        sa.Column(
            "source",
            sa.String(32),
            nullable=False,
            server_default="ai_extraction",
            comment="ai_extraction | manual_edit",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="记忆变化事件 — 每章写入时记录，重放可得任意章的世界全景",
    )
    op.create_index("ix_memory_events_novel_id", "memory_events", ["novel_id"])
    op.create_index(
        "ix_memory_events_novel_chapter",
        "memory_events",
        ["novel_id", "chapter_index", "sequence"],
    )
    op.create_index("ix_memory_events_entity", "memory_events", ["entity_id"])
    op.create_index("ix_memory_events_type", "memory_events", ["event_type"])

    # -----------------------------------------------------------
    # 3. memory_snapshots — 每 10 章物化节点（查询加速）
    # -----------------------------------------------------------
    op.create_table(
        "memory_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "novel_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chapter_index", sa.Integer(), nullable=False, comment="快照对应章节"),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="current",
            comment="current | stale",
        ),
        sa.Column(
            "full_state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="完整世界状态（entities + relations + locations + knowledge）",
        ),
        sa.Column(
            "events_until",
            sa.Integer(),
            nullable=True,
            comment="覆盖到第几个事件序号",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="记忆阶段性快照 — 每 10 章物化，加速全景查询",
    )
    op.create_index("ix_memory_snapshots_novel_id", "memory_snapshots", ["novel_id"])
    op.create_index(
        "ix_memory_snapshots_novel_chapter",
        "memory_snapshots",
        ["novel_id", "chapter_index"],
    )


def downgrade() -> None:
    op.drop_table("memory_snapshots", if_exists=True)
    op.drop_table("memory_events", if_exists=True)
    # 旧表不再恢复——此迁移不可逆（旧表已在 upgrade 中丢弃）
