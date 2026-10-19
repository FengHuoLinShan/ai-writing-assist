"""Align the frozen review scope project index with the ORM.

Revision ID: 20261018_review_scope_index
Revises: 20261018_world_review_scope
"""

from alembic import op

revision = "20261018_review_scope_index"
down_revision = "20261018_world_review_scope"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_world_entity_review_scopes_novel_id",
        "world_entity_review_scopes",
        ["novel_id"],
    )


def downgrade():
    op.drop_index(
        "ix_world_entity_review_scopes_novel_id", table_name="world_entity_review_scopes"
    )
