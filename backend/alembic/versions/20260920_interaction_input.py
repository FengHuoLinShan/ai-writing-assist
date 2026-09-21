"""Preserve typed player stimuli with each immutable branch input."""

import sqlalchemy as sa

from alembic import op

revision = "20260920_interaction_input"
down_revision = "20260920_assistant_forecast"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "interaction_message_nodes",
        sa.Column("input_json", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade():
    op.drop_column("interaction_message_nodes", "input_json")
