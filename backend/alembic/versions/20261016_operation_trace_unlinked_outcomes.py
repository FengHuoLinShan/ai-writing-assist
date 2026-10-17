"""track lifecycle outcomes that lack call-level correlation

Revision ID: 20261016_operation_trace_unlinked_outcomes
Revises: 20261016_operation_trace_reports
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261016_operation_trace_unlinked_outcomes"
down_revision: str | None = "20261016_operation_trace_reports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "assistant_operation_trace_lifecycle_aggregates",
        sa.Column(
            "unlinked_execution_events",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.alter_column(
        "assistant_operation_trace_lifecycle_aggregates",
        "unlinked_execution_events",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column(
        "assistant_operation_trace_lifecycle_aggregates",
        "unlinked_execution_events",
    )
