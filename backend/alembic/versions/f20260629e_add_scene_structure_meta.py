"""add scene structure meta

Revision ID: f20260629e
Revises: f20260629d
Create Date: 2026-06-29 18:20:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "f20260629e"
down_revision = "f20260629d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scenes",
        sa.Column("structure_meta", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scenes", "structure_meta")
