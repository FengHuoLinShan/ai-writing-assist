"""Explicit RP consent for the self-hosted public research channel."""

import sqlalchemy as sa

from alembic import op

revision = "20260912_web_search_consent"
down_revision = "20260911_assistant_runtime"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "interaction_journeys",
        sa.Column(
            "web_search_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade():
    op.drop_column("interaction_journeys", "web_search_enabled")
