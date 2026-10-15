"""Record complete UTC-day snapshots without retaining trace identifiers.

Revision ID: 20261016_operation_trace_archive_days
Revises: 20261016_operation_trace_unlinked_outcomes
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261016_operation_trace_archive_days"
down_revision: str | None = "20261016_operation_trace_unlinked_outcomes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assistant_operation_trace_archive_days",
        sa.Column("novel_id", sa.UUID(), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("complete", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("novel_id", "occurred_on"),
    )


def downgrade() -> None:
    op.drop_table("assistant_operation_trace_archive_days")
