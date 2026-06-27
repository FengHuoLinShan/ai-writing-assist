"""scope chapter card uniqueness by novel

Revision ID: aed774d964fe
Revises: aed774d964fd
"""

from collections.abc import Sequence

from alembic import op

revision: str = "aed774d964fe"
down_revision: str | None = "aed774d964fd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_chapter_cards_chapter", table_name="chapter_cards")
    op.create_unique_constraint(
        "uq_chapter_cards_novel_chapter",
        "chapter_cards",
        ["novel_id", "chapter_index"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_chapter_cards_novel_chapter",
        "chapter_cards",
        type_="unique",
    )
    op.create_index(
        "ix_chapter_cards_chapter",
        "chapter_cards",
        ["chapter_index"],
        unique=True,
    )
