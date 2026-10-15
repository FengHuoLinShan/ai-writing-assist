"""Persist explicit Director-to-World candidate receipts.

Revision ID: 20261016_story_director_candidate_transfer
Revises: 20261016_operation_trace_archive_days
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261016_story_director_candidate_transfer"
down_revision: str | None = "20261016_operation_trace_archive_days"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "story_scene_director_candidate_transfers",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("novel_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.timezone("utc", sa.func.now()),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.timezone("utc", sa.func.now()),
            nullable=True,
        ),
        sa.Column("round_id", sa.UUID(), nullable=False),
        sa.Column("candidate_ref", sa.String(length=120), nullable=False),
        sa.Column("scene_id", sa.UUID(), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("output_hash", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("world_candidate_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "novel_id",
            "round_id",
            "candidate_ref",
            name="uq_story_director_candidate_transfer_source",
        ),
        sa.UniqueConstraint(
            "novel_id",
            "world_candidate_id",
            name="uq_story_director_candidate_transfer_world",
        ),
    )
    op.create_index(
        "ix_story_scene_director_candidate_transfers_novel_id",
        "story_scene_director_candidate_transfers",
        ["novel_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_story_scene_director_candidate_transfers_novel_id",
        table_name="story_scene_director_candidate_transfers",
    )
    op.drop_table("story_scene_director_candidate_transfers")
