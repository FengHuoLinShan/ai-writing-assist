"""Persist the authorized source plan independently of queue retention."""

import sqlalchemy as sa

from alembic import op

revision = "20260922_evolution_reading"
down_revision = "20260922_evolution_model"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "evolution_runs", sa.Column("reading_plan_json", sa.JSON(), nullable=True)
    )


def downgrade():
    op.drop_column("evolution_runs", "reading_plan_json")
