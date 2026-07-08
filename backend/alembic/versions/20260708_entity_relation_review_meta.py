"""add relation review metadata

Revision ID: 20260708_entity_relation_review_meta
Revises: 20260707_core_entities_auto_ingested_recent_index
"""

import sqlalchemy as sa

from alembic import op

revision = "20260708_entity_relation_review_meta"
down_revision = "20260707_core_entities_auto_ingested_recent_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "entity_relations",
        sa.Column("review_meta", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("entity_relations", "review_meta")
