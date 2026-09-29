"""Add world object image generation candidates (local CLI, ADR-0029).

Revision ID: 20260929_world_object_image_candidates
Revises: 20260929_local_agent_files
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260929_world_object_image_candidates"
down_revision = "20260929_local_agent_files"
branch_labels = None
depends_on = None

_STATUSES = (
    "queued",
    "generating",
    "review_ready",
    "adopted",
    "discarded",
    "failed",
    "cancelled",
)


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "world_object_image_candidates",
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
            "entity_id",
            uuid,
            sa.ForeignKey("core_entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "owner_id",
            uuid,
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("task_id", uuid, nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("executor_json", sa.JSON(), nullable=False),
        sa.Column("image_data", sa.LargeBinary(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("adopted_image_version", uuid, nullable=True),
        sa.CheckConstraint(
            "status IN ('" + "', '".join(_STATUSES) + "')",
            name="ck_world_object_image_candidates_status",
        ),
    )
    op.create_index(
        "ix_world_object_image_candidates_novel_id",
        "world_object_image_candidates",
        ["novel_id"],
    )
    op.create_index(
        "ix_world_object_image_candidates_entity_id",
        "world_object_image_candidates",
        ["entity_id"],
    )
    op.create_index(
        "ix_world_object_image_candidates_status",
        "world_object_image_candidates",
        ["status"],
    )
    op.create_index(
        "ix_world_object_image_candidates_novel_entity_created",
        "world_object_image_candidates",
        ["novel_id", "entity_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_world_object_image_candidates_novel_entity_created",
        table_name="world_object_image_candidates",
    )
    op.drop_index(
        "ix_world_object_image_candidates_status",
        table_name="world_object_image_candidates",
    )
    op.drop_index(
        "ix_world_object_image_candidates_entity_id",
        table_name="world_object_image_candidates",
    )
    op.drop_index(
        "ix_world_object_image_candidates_novel_id",
        table_name="world_object_image_candidates",
    )
    op.drop_table("world_object_image_candidates")
