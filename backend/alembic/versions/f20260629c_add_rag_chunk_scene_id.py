"""add rag chunk scene id

Revision ID: f20260629c
Revises: f20260629b
Create Date: 2026-06-29 15:40:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "f20260629c"
down_revision = "f20260629b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rag_chunks", sa.Column("scene_id", sa.UUID(), nullable=True))
    op.create_index("ix_rag_chunks_scene_id", "rag_chunks", ["scene_id"])


def downgrade() -> None:
    op.drop_index("ix_rag_chunks_scene_id", table_name="rag_chunks")
    op.drop_column("rag_chunks", "scene_id")
