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


def _column_exists(table_name: str, column_name: str) -> bool:
    return column_name in {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def upgrade() -> None:
    if _column_exists("writing_drafts", "chapter_card_id"):
        op.drop_column("writing_drafts", "chapter_card_id")


def downgrade() -> None:
    if not _column_exists("writing_drafts", "chapter_card_id"):
        op.add_column(
            "writing_drafts",
            sa.Column(
                "chapter_card_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                nullable=True,
                comment="关联的章节卡 ID",
            ),
        )
