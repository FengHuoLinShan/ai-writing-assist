"""add author-confirmed map node merge receipts

Revision ID: 20261015_map_node_merge
Revises: 20261015_map_auto_drafts
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261015_map_node_merge"
down_revision: str | None = "20261015_map_auto_drafts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "map_atlas_nodes",
        sa.Column("merged_into_node_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "map_atlas_nodes",
        sa.Column("merge_metadata", sa.JSON(), nullable=True),
    )
    op.create_foreign_key(
        "fk_map_atlas_node_merged_into_same_novel",
        "map_atlas_nodes",
        "map_atlas_nodes",
        ["novel_id", "merged_into_node_id"],
        ["novel_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_map_atlas_node_not_merged_into_self",
        "map_atlas_nodes",
        "merged_into_node_id IS NULL OR merged_into_node_id <> id",
    )
    op.create_index(
        "ix_map_atlas_nodes_merge_target",
        "map_atlas_nodes",
        ["novel_id", "merged_into_node_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_map_atlas_nodes_merge_target", table_name="map_atlas_nodes")
    op.drop_constraint(
        "ck_map_atlas_node_not_merged_into_self",
        "map_atlas_nodes",
        type_="check",
    )
    op.drop_constraint(
        "fk_map_atlas_node_merged_into_same_novel",
        "map_atlas_nodes",
        type_="foreignkey",
    )
    op.drop_column("map_atlas_nodes", "merge_metadata")
    op.drop_column("map_atlas_nodes", "merged_into_node_id")
