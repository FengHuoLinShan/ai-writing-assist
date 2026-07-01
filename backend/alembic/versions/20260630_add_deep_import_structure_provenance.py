"""add deep import structure provenance

Revision ID: 20260630_structure_provenance
Revises: 20260630_merge_map_heads
Create Date: 2026-06-30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260630_structure_provenance"
down_revision: str | None = "20260630_merge_map_heads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "plot_threads",
        sa.Column("provenance_meta", sa.JSON(), nullable=True),
    )
    op.add_column(
        "outline_arcs",
        sa.Column("provenance_meta", sa.JSON(), nullable=True),
    )
    op.add_column(
        "foreshadowing_plans",
        sa.Column("provenance_meta", sa.JSON(), nullable=True),
    )
    op.add_column(
        "reveal_plans",
        sa.Column("provenance_meta", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("reveal_plans", "provenance_meta")
    op.drop_column("foreshadowing_plans", "provenance_meta")
    op.drop_column("outline_arcs", "provenance_meta")
    op.drop_column("plot_threads", "provenance_meta")
