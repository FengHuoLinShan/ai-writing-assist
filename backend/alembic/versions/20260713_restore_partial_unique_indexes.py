"""restore migration-managed partial uniqueness indexes

Revision ID: 20260713_restore_partial_unique_indexes
Revises: 20260713_drop_legacy_entity_aliases
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260713_restore_partial_unique_indexes"
down_revision = "20260713_drop_legacy_entity_aliases"
branch_labels = None
depends_on = None


def _index_names(table_name: str) -> set[str]:
    return {
        index["name"]
        for index in sa.inspect(op.get_bind()).get_indexes(table_name)
    }


def upgrade() -> None:
    if "uq_entity_relations_canonical_edge" not in _index_names(
        "entity_relations"
    ):
        duplicates = op.get_bind().execute(
            sa.text(
                "SELECT 1 FROM entity_relations "
                "WHERE status = 'canonical' "
                "GROUP BY novel_id, source_id, target_id, relation_type "
                "HAVING COUNT(*) > 1 LIMIT 1"
            )
        ).first()
        if duplicates:
            raise RuntimeError(
                "duplicate canonical entity relations block partial unique index"
            )
        op.execute(
            "CREATE UNIQUE INDEX uq_entity_relations_canonical_edge "
            "ON entity_relations (novel_id, source_id, target_id, relation_type) "
            "WHERE status = 'canonical'"
        )

    if "uq_map_config_top_level_name" not in _index_names("map_configs"):
        duplicates = op.get_bind().execute(
            sa.text(
                "SELECT 1 FROM map_configs WHERE parent_map_id IS NULL "
                "GROUP BY novel_id, name HAVING COUNT(*) > 1 LIMIT 1"
            )
        ).first()
        if duplicates:
            raise RuntimeError(
                "duplicate top-level map names block partial unique index"
            )
        op.execute(
            "CREATE UNIQUE INDEX uq_map_config_top_level_name "
            "ON map_configs (novel_id, name) WHERE parent_map_id IS NULL"
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_map_config_top_level_name")
    op.execute("DROP INDEX IF EXISTS uq_entity_relations_canonical_edge")
