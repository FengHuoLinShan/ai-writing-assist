"""Keep reusable object image bytes independent of candidate retention.

Revision ID: 20261003_image_reuse_payload
Revises: 20261002_candidate_request_hash
"""

import sqlalchemy as sa

from alembic import op

revision = "20261003_image_reuse_payload"
down_revision = "20261002_candidate_request_hash"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "image_request_reuse", sa.Column("asset_data", sa.LargeBinary(), nullable=True)
    )
    op.execute(
        "UPDATE image_request_reuse AS r SET asset_data = c.image_data "
        "FROM world_object_image_candidates AS c "
        "WHERE r.source_type = 'world_object' AND r.created_from_id = c.id "
        "AND r.novel_id = c.novel_id AND r.owner_id = c.owner_id"
    )


def downgrade() -> None:
    op.drop_column("image_request_reuse", "asset_data")
