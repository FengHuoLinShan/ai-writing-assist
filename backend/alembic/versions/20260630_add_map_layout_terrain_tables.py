"""add map layout and terrain tables

Revision ID: 20260630_map_layout_terrain
Revises: 20260629_map_dynamic_facts
Create Date: 2026-06-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260630_map_layout_terrain"
down_revision: str | None = "20260629_map_dynamic_facts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('utc', now())"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('utc', now())"),
            nullable=True,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "map_location_layouts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("map_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("location_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("center_hex_q", sa.Integer(), nullable=False),
        sa.Column("center_hex_r", sa.Integer(), nullable=False),
        sa.Column("occupy_radius", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "layout_source",
            sa.String(length=32),
            nullable=False,
            server_default="quick_create",
        ),
        sa.Column("layout_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "sync_geo_setting",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("meta", sa.JSON(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["map_id"], ["map_configs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["location_entity_id"], ["core_entities.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="地图地点布局节点",
    )
    op.create_index(
        "uq_map_location_layout_map_entity",
        "map_location_layouts",
        ["map_id", "location_entity_id"],
        unique=True,
    )
    op.create_index(
        "ix_map_location_layouts_novel_id",
        "map_location_layouts",
        ["novel_id"],
    )
    op.create_index("ix_map_location_layouts_map_id", "map_location_layouts", ["map_id"])

    op.create_table(
        "map_terrain_layers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("map_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("terrain_asset_key", sa.String(length=64), nullable=False),
        sa.Column("opacity", sa.Float(), nullable=False, server_default="0.45"),
        sa.Column("z_index", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("visible", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("meta", sa.JSON(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["map_id"], ["map_configs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        comment="地图手绘地形图层",
    )
    op.create_index("ix_map_terrain_layers_novel_id", "map_terrain_layers", ["novel_id"])
    op.create_index("ix_map_terrain_layers_map_id", "map_terrain_layers", ["map_id"])

    op.create_table(
        "map_terrain_regions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("map_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("layer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "region_status",
            sa.String(length=32),
            nullable=False,
            server_default="active",
        ),
        sa.Column("meta", sa.JSON(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["map_id"], ["map_configs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["layer_id"], ["map_terrain_layers.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="地图手绘地形区域",
    )
    op.create_index(
        "ix_map_terrain_regions_novel_id",
        "map_terrain_regions",
        ["novel_id"],
    )
    op.create_index("ix_map_terrain_regions_map_id", "map_terrain_regions", ["map_id"])
    op.create_index(
        "ix_map_terrain_regions_layer_id",
        "map_terrain_regions",
        ["layer_id"],
    )

    op.create_table(
        "map_terrain_patches",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("map_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("layer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("region_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hex_q", sa.Integer(), nullable=False),
        sa.Column("hex_r", sa.Integer(), nullable=False),
        sa.Column("strength", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column(
            "brush_source",
            sa.String(length=32),
            nullable=False,
            server_default="brush",
        ),
        *_timestamps(),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["map_id"], ["map_configs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["layer_id"], ["map_terrain_layers.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["region_id"], ["map_terrain_regions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="地图手绘地形 patch",
    )
    op.create_index(
        "uq_map_terrain_patch_map_layer_region_qr",
        "map_terrain_patches",
        ["map_id", "layer_id", "region_id", "hex_q", "hex_r"],
        unique=True,
    )
    op.create_index(
        "ix_map_terrain_patches_novel_id",
        "map_terrain_patches",
        ["novel_id"],
    )
    op.create_index("ix_map_terrain_patches_map_id", "map_terrain_patches", ["map_id"])
    op.create_index(
        "ix_map_terrain_patches_layer_id",
        "map_terrain_patches",
        ["layer_id"],
    )
    op.create_index(
        "ix_map_terrain_patches_region_id",
        "map_terrain_patches",
        ["region_id"],
    )

    op.create_table(
        "map_terrain_bindings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("map_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("region_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("location_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("binding_type", sa.String(length=32), nullable=False),
        sa.Column(
            "review_state",
            sa.String(length=32),
            nullable=False,
            server_default="confirmed",
        ),
        sa.Column(
            "source",
            sa.String(length=64),
            nullable=False,
            server_default="user_confirmed",
        ),
        sa.Column("meta", sa.JSON(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["map_id"], ["map_configs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["region_id"], ["map_terrain_regions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["location_entity_id"], ["core_entities.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="地图手绘地形绑定",
    )
    op.create_index(
        "uq_map_terrain_binding_region_location_type",
        "map_terrain_bindings",
        ["region_id", "location_entity_id", "binding_type"],
        unique=True,
    )
    op.create_index(
        "ix_map_terrain_bindings_novel_id",
        "map_terrain_bindings",
        ["novel_id"],
    )
    op.create_index("ix_map_terrain_bindings_map_id", "map_terrain_bindings", ["map_id"])
    op.create_index(
        "ix_map_terrain_bindings_region_id",
        "map_terrain_bindings",
        ["region_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_map_terrain_bindings_region_id", table_name="map_terrain_bindings")
    op.drop_index("ix_map_terrain_bindings_map_id", table_name="map_terrain_bindings")
    op.drop_index("ix_map_terrain_bindings_novel_id", table_name="map_terrain_bindings")
    op.drop_index(
        "uq_map_terrain_binding_region_location_type",
        table_name="map_terrain_bindings",
    )
    op.drop_table("map_terrain_bindings")
    op.drop_index("ix_map_terrain_patches_region_id", table_name="map_terrain_patches")
    op.drop_index("ix_map_terrain_patches_layer_id", table_name="map_terrain_patches")
    op.drop_index("ix_map_terrain_patches_map_id", table_name="map_terrain_patches")
    op.drop_index("ix_map_terrain_patches_novel_id", table_name="map_terrain_patches")
    op.drop_index(
        "uq_map_terrain_patch_map_layer_region_qr",
        table_name="map_terrain_patches",
    )
    op.drop_table("map_terrain_patches")
    op.drop_index("ix_map_terrain_regions_layer_id", table_name="map_terrain_regions")
    op.drop_index("ix_map_terrain_regions_map_id", table_name="map_terrain_regions")
    op.drop_index("ix_map_terrain_regions_novel_id", table_name="map_terrain_regions")
    op.drop_table("map_terrain_regions")
    op.drop_index("ix_map_terrain_layers_map_id", table_name="map_terrain_layers")
    op.drop_index("ix_map_terrain_layers_novel_id", table_name="map_terrain_layers")
    op.drop_table("map_terrain_layers")
    op.drop_index("ix_map_location_layouts_map_id", table_name="map_location_layouts")
    op.drop_index("ix_map_location_layouts_novel_id", table_name="map_location_layouts")
    op.drop_index(
        "uq_map_location_layout_map_entity",
        table_name="map_location_layouts",
    )
    op.drop_table("map_location_layouts")
