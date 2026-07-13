"""store all result Scenes for replacement suggestions

Revision ID: 20260713_scene_replacement_results
Revises: 20260713_restore_partial_unique_indexes
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260713_scene_replacement_results"
down_revision = "20260713_restore_partial_unique_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns(
            "scene_fusion_suggestions"
        )
    }
    if "result_scene_ids" not in columns:
        op.add_column(
            "scene_fusion_suggestions",
            sa.Column(
                "result_scene_ids",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'::json"),
            ),
        )
        op.alter_column(
            "scene_fusion_suggestions",
            "result_scene_ids",
            server_default=None,
        )


def downgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns(
            "scene_fusion_suggestions"
        )
    }
    if "result_scene_ids" in columns:
        op.drop_column("scene_fusion_suggestions", "result_scene_ids")
