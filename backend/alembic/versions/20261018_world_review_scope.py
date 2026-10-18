"""Persist bounded frozen world review membership.

Revision ID: 20261018_world_review_scope
Revises: 20261018_assistant_approval
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261018_world_review_scope"
down_revision = "20261018_assistant_approval"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "world_entity_review_scopes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation_id", sa.String(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("filters_json", sa.JSON(), nullable=False),
        sa.Column("members_json", sa.JSON(), nullable=False),
        sa.Column("decisions_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("novel_id", "operation_id"),
    )


def downgrade():
    op.drop_table("world_entity_review_scopes")
