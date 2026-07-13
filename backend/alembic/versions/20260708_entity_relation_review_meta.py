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
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("entity_relations")
    }
    if "review_meta" not in columns:
        op.add_column(
            "entity_relations",
            sa.Column("review_meta", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("entity_relations")
    }
    if "review_meta" in columns:
        op.drop_column("entity_relations", "review_meta")
