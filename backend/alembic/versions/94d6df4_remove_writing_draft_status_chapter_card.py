"""删除 writing_drafts.status 和 chapter_card_id 列

Writing 模块瘦身：手工编辑不再需要状态流转和章节卡关联。

Revision ID: 94d6df4
Revises: e31ca9d12321
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "94d6df4"
down_revision: str | None = "e31ca9d12321"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("writing_drafts", "status")
    op.drop_column("writing_drafts", "chapter_card_id")


def downgrade() -> None:
    op.add_column(
        "writing_drafts",
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="draft",
            comment="状态：draft / candidate / canonical / deprecated",
        ),
    )
    op.add_column(
        "writing_drafts",
        sa.Column(
            "chapter_card_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="关联的章节卡 ID",
        ),
    )
