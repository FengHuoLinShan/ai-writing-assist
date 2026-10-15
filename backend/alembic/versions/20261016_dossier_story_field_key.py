"""bind a dossier entry to an exact Story status field

Revision ID: 20261016_dossier_story_field_key
Revises: 20261016_relation_validity
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261016_dossier_story_field_key"
down_revision: str | None = "20261016_relation_validity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "world_object_dossier_entries",
        sa.Column("story_field_key", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("world_object_dossier_entries", "story_field_key")
