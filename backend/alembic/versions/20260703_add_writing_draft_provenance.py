"""add writing draft provenance

Revision ID: 20260703_draft_provenance
Revises: 20260630_structure_provenance
Create Date: 2026-07-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260703_draft_provenance"
down_revision: str | None = "20260630_structure_provenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "writing_drafts",
        sa.Column("provenance_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("writing_drafts", "provenance_json")
