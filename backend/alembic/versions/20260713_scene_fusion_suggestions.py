"""generalize Scene fusion suggestions for deep-import Phase 1c

Revision ID: 20260713_scene_fusion_suggestions
Revises: 20260712_llm_max_12000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op
from core.base import UUIDType

revision = "20260713_scene_fusion_suggestions"
down_revision = "20260712_llm_max_12000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "scene_fusion_suggestions" in tables:
        return
    if "scene_cross_chapter_suggestions" not in tables:
        return

    op.rename_table("scene_cross_chapter_suggestions", "scene_fusion_suggestions")
    op.alter_column(
        "scene_fusion_suggestions",
        "source_task_id",
        new_column_name="source_workflow_id",
        existing_type=UUIDType,
        type_=sa.String(64),
        postgresql_using="source_task_id::text",
    )
    op.add_column(
        "scene_fusion_suggestions",
        sa.Column(
            "suggestion_kind",
            sa.String(32),
            nullable=False,
            server_default="cross_chapter",
        ),
    )
    op.alter_column(
        "scene_fusion_suggestions",
        "suggestion_kind",
        server_default=None,
    )
    op.create_table_comment(
        "scene_fusion_suggestions",
        "Phase 1c 产生的持久 Scene 融合建议",
        existing_comment="跨章 Scene 识别产生的持久待处理建议",
    )
    op.add_column(
        "scene_fusion_suggestions",
        sa.Column(
            "proposed_action",
            sa.String(32),
            nullable=False,
            server_default="needs_review",
        ),
    )
    op.alter_column(
        "scene_fusion_suggestions",
        "proposed_action",
        server_default=None,
    )
    op.drop_index(
        "ix_scene_cross_chapter_suggestions_queue",
        table_name="scene_fusion_suggestions",
    )
    op.drop_index(
        "ix_scene_cross_chapter_suggestions_novel_id",
        table_name="scene_fusion_suggestions",
    )
    op.drop_constraint(
        "uq_scene_cross_chapter_suggestion_key",
        "scene_fusion_suggestions",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_scene_fusion_suggestion_key",
        "scene_fusion_suggestions",
        ["novel_id", "suggestion_key"],
    )
    op.create_index(
        "ix_scene_fusion_suggestions_novel_id",
        "scene_fusion_suggestions",
        ["novel_id"],
    )
    op.create_index(
        "ix_scene_fusion_suggestions_queue",
        "scene_fusion_suggestions",
        ["novel_id", "status", "created_at"],
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "scene_fusion_suggestions" not in set(inspector.get_table_names()):
        return
    op.drop_index(
        "ix_scene_fusion_suggestions_queue",
        table_name="scene_fusion_suggestions",
    )
    op.create_table_comment(
        "scene_fusion_suggestions",
        "跨章 Scene 识别产生的持久待处理建议",
        existing_comment="Phase 1c 产生的持久 Scene 融合建议",
    )
    op.drop_index(
        "ix_scene_fusion_suggestions_novel_id",
        table_name="scene_fusion_suggestions",
    )
    op.drop_constraint(
        "uq_scene_fusion_suggestion_key",
        "scene_fusion_suggestions",
        type_="unique",
    )
    op.drop_column("scene_fusion_suggestions", "proposed_action")
    op.drop_column("scene_fusion_suggestions", "suggestion_kind")
    op.alter_column(
        "scene_fusion_suggestions",
        "source_workflow_id",
        new_column_name="source_task_id",
        existing_type=sa.String(64),
        type_=UUIDType,
        postgresql_using="source_workflow_id::uuid",
    )
    op.rename_table("scene_fusion_suggestions", "scene_cross_chapter_suggestions")
    op.create_unique_constraint(
        "uq_scene_cross_chapter_suggestion_key",
        "scene_cross_chapter_suggestions",
        ["novel_id", "suggestion_key"],
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
