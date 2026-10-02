"""Add image request reuse registry (B9 idempotent image generation).

Revision ID: 20261002_image_request_reuse
Revises: 20260929_world_object_image_candidates
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261002_image_request_reuse"
down_revision = "20260929_world_object_image_candidates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "image_request_reuse",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "novel_id",
            uuid,
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "owner_id",
            uuid,
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("object_key", sa.String(1024), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False, server_default=""),
        sa.Column("model", sa.String(64), nullable=False, server_default=""),
        sa.Column("asset_sha256", sa.String(64), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("created_from_id", uuid, nullable=True),
        sa.Column("reused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reuse_count", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint(
            "source_type IN ('map_atlas', 'world_object')",
            name="ck_image_request_reuse_source_type",
        ),
    )
    op.create_index(
        "uq_image_request_reuse_novel_hash",
        "image_request_reuse",
        ["novel_id", "request_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_image_request_reuse_novel_hash", table_name="image_request_reuse"
    )
    op.drop_table("image_request_reuse")
