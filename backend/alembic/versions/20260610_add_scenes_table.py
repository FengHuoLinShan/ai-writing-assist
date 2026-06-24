"""add scenes table

Revision ID: 20260610_add_scenes_table
Revises: e31ca9d12321
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260610_add_scenes_table"
down_revision: str | None = "e31ca9d12321"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scenes",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "novel_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "scene_index",
            sa.Integer(),
            nullable=False,
            index=True,
        ),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("goal", sa.Text(), nullable=True),
        sa.Column("core_conflict", sa.Text(), nullable=True),
        sa.Column("emotional_beat", sa.Text(), nullable=True),
        sa.Column("must_happen", sa.Text(), nullable=True),
        sa.Column("must_not_happen", sa.Text(), nullable=True),
        sa.Column(
            "narrative_tag",
            sa.String(32),
            nullable=False,
            server_default="draft",
        ),
        sa.Column(
            "source",
            sa.String(32),
            nullable=False,
            server_default="manual",
        ),
        sa.Column("scene_chunks", sa.JSON(), nullable=True),
        sa.Column("chapter_ids", sa.JSON(), nullable=True),
        sa.Column("pov_character_id", sa.String(36), nullable=True),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="draft",
            index=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.timezone("utc", sa.func.now()),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.timezone("utc", sa.func.now()),
        ),
        comment="Scene 卡",
    )


def downgrade() -> None:
    op.drop_table("scenes")
