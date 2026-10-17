"""pin map node level types to immutable project vocabulary revisions

Revision ID: 20261015_map_spatial_v2
Revises: 20261015_project_vocabulary
"""

import sqlalchemy as sa

from alembic import op

revision = "20261015_map_spatial_v2"
down_revision = "20261015_project_vocabulary"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("map_atlas_nodes", sa.Column("level_type_ref", sa.UUID()))
    op.add_column("map_atlas_nodes", sa.Column("level_type_revision_id", sa.UUID()))
    op.create_check_constraint(
        "ck_map_node_level_type_pair",
        "map_atlas_nodes",
        "(level_type_ref IS NULL) = (level_type_revision_id IS NULL)",
    )
    op.create_foreign_key(
        "fk_map_node_level_type_revision",
        "map_atlas_nodes",
        "project_vocabulary_revisions",
        ["novel_id", "level_type_ref", "level_type_revision_id"],
        ["novel_id", "term_id", "id"],
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM map_atlas_nodes "
                "WHERE level_type_ref IS NOT NULL OR level_type_revision_id IS NOT NULL)"
            )
        )
        .scalar()
    ):
        raise RuntimeError(
            "Map level type references exist; downgrade would discard author data"
        )
    op.drop_constraint(
        "fk_map_node_level_type_revision", "map_atlas_nodes", type_="foreignkey"
    )
    op.drop_constraint("ck_map_node_level_type_pair", "map_atlas_nodes", type_="check")
    op.drop_column("map_atlas_nodes", "level_type_revision_id")
    op.drop_column("map_atlas_nodes", "level_type_ref")
