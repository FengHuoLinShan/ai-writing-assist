"""store author-declared validity on World relations

Revision ID: 20261016_relation_validity
Revises: 20261016_story_scene_director
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261016_relation_validity"
down_revision: str | None = "20261016_story_scene_director"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "entity_relations",
        sa.Column("validity_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("entity_relations", "validity_json")
