"""Keep author grant renewal history separate from goals and execution."""

import sqlalchemy as sa

from alembic import op

revision = "20260920_creative_recovery"
down_revision = "20260920_interaction_input"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "collaboration_cases",
        sa.Column(
            "grant_history_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )

    op.add_column(
        "creative_workspaces",
        sa.Column("request_hash", sa.String(64), nullable=False, server_default=""),
    )


def downgrade():
    op.drop_column("creative_workspaces", "request_hash")
    op.drop_column("collaboration_cases", "grant_history_json")
