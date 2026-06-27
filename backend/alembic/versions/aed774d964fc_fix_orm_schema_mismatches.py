"""fix ORM/DB schema mismatches

- rag_chunks: RENAME COLUMN metadata -> meta
- review_reports: ADD COLUMN status
- memory_update_proposals: ADD COLUMN updated_at

Revision ID: aed774d964fc
Revises: aed774d964fb
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "aed774d964fc"
down_revision: str | None = "aed774d964fb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. rag_chunks: rename metadata -> meta
    op.alter_column("rag_chunks", "metadata", new_column_name="meta")

    # 2. review_reports: add status column
    op.add_column(
        "review_reports",
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="canonical",
            comment="报告状态：draft/canonical/deprecated",
        ),
    )

    # 3. review_reports: add updated_at column (from TimestampMixin)
    op.add_column(
        "review_reports",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('utc', now())"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("review_reports", "updated_at")
    op.drop_column("review_reports", "status")
    op.alter_column("rag_chunks", "meta", new_column_name="metadata")
