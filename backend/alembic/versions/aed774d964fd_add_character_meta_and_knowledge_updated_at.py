"""add character meta and knowledge updated_at

Revision ID: aed774d964fd
Revises: aed774d964fc
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "aed774d964fd"
down_revision: Union[str, None] = "aed774d964fc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "characters",
        sa.Column(
            "meta",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
            comment="扩展元数据（AI 抽取建议等）",
        ),
    )
    op.add_column(
        "character_knowledge",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('utc', now())"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("character_knowledge", "updated_at")
    op.drop_column("characters", "meta")
