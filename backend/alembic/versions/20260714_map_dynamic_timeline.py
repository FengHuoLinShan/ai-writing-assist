"""map dynamic timeline projection indexes

Revision ID: 20260714_map_dynamic_timeline
Revises: 20260714_map_floor_paths
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260714_map_dynamic_timeline"
down_revision = "20260714_map_floor_paths"
branch_labels = None
depends_on = None


def _ensure_index(table_name: str, index_name: str, columns: list[str]) -> None:
    bind = op.get_bind()
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes(table_name)}
    if index_name not in indexes:
        op.create_index(index_name, table_name, columns)


def upgrade() -> None:
    _ensure_index(
        "map_observations",
        "ix_map_observation_novel_map_review_scene_id",
        ["novel_id", "map_id", "review_state", "scene_index", "id"],
    )
    _ensure_index(
        "map_facts",
        "ix_map_fact_novel_map_status_scene_id",
        ["novel_id", "map_id", "fact_status", "scene_index", "id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    for table_name, index_name in (
        (
            "map_observations",
            "ix_map_observation_novel_map_review_scene_id",
        ),
        ("map_facts", "ix_map_fact_novel_map_status_scene_id"),
    ):
        indexes = {
            item["name"] for item in sa.inspect(bind).get_indexes(table_name)
        }
        if index_name in indexes:
            op.drop_index(index_name, table_name=table_name)
