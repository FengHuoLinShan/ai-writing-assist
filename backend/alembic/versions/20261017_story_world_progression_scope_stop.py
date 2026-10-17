"""Record why standing world progression stopped.

Revision ID: 20261017_wp_scope_stop
Revises: 20261016_chapter_order
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261017_wp_scope_stop"
down_revision: str | None = "20261016_chapter_order"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "story_world_progression_authorizations",
        sa.Column("stop_reason", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("story_world_progression_authorizations", "stop_reason")
