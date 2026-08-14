"""Add private images to world objects.

Revision ID: 20260814_world_object_images
Revises: 20260813_map_prompt_upload
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260814_world_object_images"
down_revision = "20260813_map_prompt_upload"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("core_entities") as batch:
        batch.add_column(
            sa.Column("image_version", postgresql.UUID(as_uuid=True), nullable=True)
        )
        batch.add_column(
            sa.Column("image_updated_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("core_entities") as batch:
        batch.drop_column("image_updated_at")
        batch.drop_column("image_version")
