"""add delta log table

Revision ID: 20260610_add_delta_log
Revises: 20260610_add_scenes_table
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260610_add_delta_log"
down_revision: str | None = "20260610_add_scenes_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "delta_log",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "novel_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entity_id", sa.UUID(), nullable=True, comment="关联实体 ID"),
        sa.Column("character_id", sa.UUID(), nullable=True, comment="关联网格人物 ID"),
        sa.Column("scene_index", sa.Integer(), nullable=True, comment="变更发生的 Scene"),
        sa.Column("category", sa.String(32), nullable=False, comment="变更类别"),
        sa.Column("field_path", sa.String(255), nullable=True, comment="变更字段路径"),
        sa.Column(
            "old_value", sa.Text(), nullable=True, comment="变更前的 JSON 序列化值"
        ),
        sa.Column(
            "new_value", sa.Text(), nullable=True, comment="变更后的 JSON 序列化值"
        ),
        sa.Column(
            "source",
            sa.String(32),
            nullable=False,
            server_default="ai_extraction",
            comment="来源",
        ),
        sa.Column("meta", sa.JSON(), nullable=True, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="实体变更日志 — 记录每次结构化字段变更的 before/after",
    )
    op.create_index("ix_delta_log_novel_id", "delta_log", ["novel_id"])
    op.create_index("ix_delta_log_entity_id", "delta_log", ["entity_id"])
    op.create_index("ix_delta_log_scene_index", "delta_log", ["novel_id", "scene_index"])


def downgrade() -> None:
    op.drop_table("delta_log")
