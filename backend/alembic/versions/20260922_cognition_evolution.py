"""Keep the exact committed understanding read by retained interpretations."""

import sqlalchemy as sa

from alembic import op

revision = "20260922_cognition_evolution"
down_revision = "20260922_understanding_owner"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "cognition_records",
        sa.Column("evolution_refs_json", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade():
    op.drop_column("cognition_records", "evolution_refs_json")
