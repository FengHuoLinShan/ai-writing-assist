"""Persist World Bible draft source metadata.

Revision ID: 20260821_world_bible_draft_meta
Revises: 20260815_story_scene_assets
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260821_world_bible_draft_meta"
down_revision = "20260815_story_scene_assets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "world_bible_page_drafts",
        sa.Column(
            "page_meta_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("world_bible_page_drafts", "page_meta_json")
