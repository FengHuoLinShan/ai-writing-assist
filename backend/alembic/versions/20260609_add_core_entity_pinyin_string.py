"""add pinyin_string column to core_entities

Revision ID: 20260609_pinyin_string
Revises: 20260608_project_settings
Create Date: 2026-06-09
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260609_pinyin_string"
down_revision: str | None = "20260608_project_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "core_entities",
        sa.Column(
            "pinyin_string",
            sa.String(length=1024),
            nullable=True,
            comment="name 的拼音字符串缓存（用于去重音似特征）",
        ),
    )


def downgrade() -> None:
    op.drop_column("core_entities", "pinyin_string")
