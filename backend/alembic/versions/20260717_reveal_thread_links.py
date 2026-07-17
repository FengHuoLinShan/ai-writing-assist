"""add PlotThread links to reveal plans

Revision ID: 20260717_reveal_thread_links
Revises: 20260716_rag_entity_appearances
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260717_reveal_thread_links"
down_revision = "20260716_rag_entity_appearances"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("reveal_plans")
    }
    if "related_thread_ids" not in columns:
        op.add_column(
            "reveal_plans",
            sa.Column(
                "related_thread_ids",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            ),
        )


def downgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("reveal_plans")
    }
    if "related_thread_ids" in columns:
        op.drop_column("reveal_plans", "related_thread_ids")
