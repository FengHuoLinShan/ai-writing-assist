"""add foreshadowing payoff scene

Revision ID: f20260629d
Revises: f20260629c
Create Date: 2026-06-29 15:43:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "f20260629d"
down_revision = "f20260629c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "foreshadowing_plans",
        sa.Column("planned_payoff_scene", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("foreshadowing_plans", "planned_payoff_scene")
