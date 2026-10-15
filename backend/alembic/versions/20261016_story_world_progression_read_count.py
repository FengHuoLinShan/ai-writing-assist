"""Count only proven whole new chapter reads for standing progression.

Revision ID: 20261016_wp_read_count
Revises: 20261016_wp_cascade_guard
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261016_wp_read_count"
down_revision: str | None = "20261016_wp_cascade_guard"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "story_world_progression_authorizations",
        sa.Column(
            "counted_read_chapters_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.add_column(
        "story_world_progression_authorizations",
        sa.Column(
            "last_triggered_read_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "story_world_progression_authorizations",
        sa.Column(
            "read_count_initialized",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    for name in (
        "counted_read_chapters_json",
        "last_triggered_read_count",
        "read_count_initialized",
    ):
        op.alter_column(
            "story_world_progression_authorizations", name, server_default=None
        )


def downgrade() -> None:
    op.drop_column("story_world_progression_authorizations", "read_count_initialized")
    op.drop_column("story_world_progression_authorizations", "last_triggered_read_count")
    op.drop_column("story_world_progression_authorizations", "counted_read_chapters_json")
