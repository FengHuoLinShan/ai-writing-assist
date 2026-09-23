"""Freeze one secret-free model connection for an Evolution run."""

import sqlalchemy as sa

from alembic import op

revision = "20260922_evolution_model"
down_revision = "20260922_cognition_evolution"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "evolution_runs", sa.Column("llm_snapshot_json", sa.JSON(), nullable=True)
    )


def downgrade():
    op.drop_column("evolution_runs", "llm_snapshot_json")
