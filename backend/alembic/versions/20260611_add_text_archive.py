"""add text_archive table

Revision ID: 20260611_add_text_archive
Revises: 20260610_add_delta_log
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260611_add_text_archive"
down_revision: str | None = "20260610_add_delta_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "text_archive",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("novel_id", sa.UUID(),
                  sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=True,
                  comment="关联实体 ID"),
        sa.Column("field_name", sa.String(64), nullable=False,
                  comment="字段名（summary/public_info/hidden_truth 等）"),
        sa.Column("text_content", sa.Text(), nullable=True,
                  comment="该字段在本次变更后的文本内容"),
        sa.Column("scene_index", sa.Integer(), nullable=True,
                  comment="变更发生时的 Scene 索引锚点"),
        sa.Column("source", sa.String(32), nullable=False,
                  server_default="manual_edit", comment="来源"),
        sa.Column("meta", sa.JSON(), nullable=True, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        comment="文本归档 — 记录长文本字段每次变更的快照，用于版本回滚",
    )
    op.create_index("ix_text_archive_novel_id", "text_archive", ["novel_id"])
    op.create_index("ix_text_archive_entity_id", "text_archive", ["entity_id"])
    op.create_index(
        "ix_text_archive_scene", "text_archive",
        ["novel_id", "entity_id", "scene_index"],
    )


def downgrade() -> None:
    op.drop_table("text_archive")
