"""Keep invalidated evolution inputs and Story events as non-current history."""

import sqlalchemy as sa

from alembic import op

revision = "20260922_evolution_invalidation"
down_revision = "20260921_evolution_single_writer"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "memory_events",
        sa.Column(
            "source_stale", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "evolution_runs", sa.Column("invalidation_json", sa.JSON(), nullable=True)
    )


def downgrade():
    op.drop_column("evolution_runs", "invalidation_json")
    op.drop_column("memory_events", "source_stale")
