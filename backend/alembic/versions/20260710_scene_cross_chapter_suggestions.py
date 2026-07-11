"""persist outline cross-chapter Scene suggestions

Revision ID: 20260710_scene_cross_suggestions
Revises: 20260710_asset_state_simple
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op
from core.base import UUIDType

revision = "20260710_scene_cross_suggestions"
down_revision = "20260710_asset_state_simple"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "scene_cross_chapter_suggestions" in set(inspector.get_table_names()):
        return
    op.create_table(
        "scene_cross_chapter_suggestions",
        sa.Column("id", UUIDType, primary_key=True),
        sa.Column(
            "novel_id",
            UUIDType,
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_task_id", UUIDType, nullable=False),
        sa.Column("suggestion_key", sa.String(64), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("source_scene_ids", sa.JSON(), nullable=False),
        sa.Column("chapter_span", sa.JSON(), nullable=False),
        sa.Column("proposed_scene", sa.JSON(), nullable=False),
        sa.Column("scan_trace", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "result_scene_id",
            UUIDType,
            sa.ForeignKey("scenes.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
        sa.UniqueConstraint(
            "novel_id",
            "suggestion_key",
            name="uq_scene_cross_chapter_suggestion_key",
        ),
        comment="跨章 Scene 识别产生的持久待处理建议",
    )
    op.create_index(
        "ix_scene_cross_chapter_suggestions_novel_id",
        "scene_cross_chapter_suggestions",
        ["novel_id"],
    )
    op.create_index(
        "ix_scene_cross_chapter_suggestions_queue",
        "scene_cross_chapter_suggestions",
        ["novel_id", "status", "created_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "scene_cross_chapter_suggestions" not in set(inspector.get_table_names()):
        return
    op.drop_table("scene_cross_chapter_suggestions")
