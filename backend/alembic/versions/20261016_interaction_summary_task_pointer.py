"""pin exact summary task on its interaction journey

Revision ID: 20261016_interaction_summary_task_pointer
Revises: 20261016_assistant_goal_runs
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261016_interaction_summary_task_pointer"
down_revision: str | None = "20261016_assistant_goal_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "interaction_journeys",
        sa.Column("summary_refresh_task_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_interaction_journey_summary_task",
        "interaction_journeys",
        "async_tasks",
        ["summary_refresh_task_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_interaction_journeys_summary_refresh_task_id",
        "interaction_journeys",
        ["summary_refresh_task_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_interaction_journeys_summary_refresh_task_id",
        table_name="interaction_journeys",
    )
    op.drop_constraint(
        "fk_interaction_journey_summary_task",
        "interaction_journeys",
        type_="foreignkey",
    )
    op.drop_column("interaction_journeys", "summary_refresh_task_id")
