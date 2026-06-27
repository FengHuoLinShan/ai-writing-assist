"""add map_configs/tiles/bindings/markers tables

动态地图功能 P0 数据层（PRD docs/PRD-动态地图功能.md §4）：
- map_configs: 地图配置（自引用树）
- map_tiles: 六边形地形网格
- map_location_bindings: 地点绑定
- map_markers: 动态标记（P1 数据层预留，P0 不实现 service/API）

注：down_revision 指向 20260613_add_draft_status（当前最新逻辑 head）。
若仓库存在多 head（aed774d96500 / 20260609_pinyin_string 未合并），
需先 `alembic merge heads` 再应用本迁移，或手工调整 down_revision。

Revision ID: 20260614_add_map_tables
Revises: 20260613_add_draft_status
Create Date: 2026-06-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260614_add_map_tables"
down_revision: str | None = "20260613_add_draft_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # map_configs
    op.create_table(
        "map_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("map_type", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("default_center_x", sa.Float(), nullable=False),
        sa.Column("default_center_y", sa.Float(), nullable=False),
        sa.Column("default_zoom", sa.Float(), nullable=False),
        sa.Column("grid_width", sa.Integer(), nullable=False),
        sa.Column("grid_height", sa.Integer(), nullable=False),
        sa.Column("hex_size", sa.Integer(), nullable=False),
        sa.Column("parent_map_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("parent_entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
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
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["parent_map_id"], ["map_configs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["parent_entity_id"], ["core_entities.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="动态地图配置",
    )
    op.create_index(
        "uq_map_config_novel_parent_name",
        "map_configs",
        ["novel_id", "parent_map_id", "name"],
        unique=True,
    )
    op.create_index("ix_map_configs_map_type", "map_configs", ["map_type"], unique=False)
    op.create_index(
        "ix_map_configs_parent_map_id", "map_configs", ["parent_map_id"], unique=False
    )
    op.create_index(
        "ix_map_configs_parent_entity_id",
        "map_configs",
        ["parent_entity_id"],
        unique=False,
    )
    op.create_index("ix_map_configs_novel_id", "map_configs", ["novel_id"], unique=False)

    # map_tiles
    op.create_table(
        "map_tiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("map_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hex_q", sa.Integer(), nullable=False),
        sa.Column("hex_r", sa.Integer(), nullable=False),
        sa.Column("terrain_type", sa.String(length=32), nullable=False),
        sa.Column("elevation", sa.Integer(), nullable=False),
        sa.Column("style_override", sa.JSON(), nullable=True),
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
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["map_id"], ["map_configs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        comment="六边形地形网格",
    )
    op.create_index(
        "uq_map_tile_map_qr", "map_tiles", ["map_id", "hex_q", "hex_r"], unique=True
    )
    op.create_index("ix_map_tiles_map_id", "map_tiles", ["map_id"], unique=False)
    op.create_index("ix_map_tiles_novel_id", "map_tiles", ["novel_id"], unique=False)

    # map_location_bindings
    op.create_table(
        "map_location_bindings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("map_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("location_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hex_q", sa.Integer(), nullable=False),
        sa.Column("hex_r", sa.Integer(), nullable=False),
        sa.Column("is_center", sa.Boolean(), nullable=False),
        sa.Column("label_override", sa.String(length=255), nullable=True),
        sa.Column("style_override", sa.JSON(), nullable=True),
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
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["map_id"], ["map_configs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["location_entity_id"], ["core_entities.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="地点绑定",
    )
    op.create_index(
        "uq_map_binding_map_entity_qr",
        "map_location_bindings",
        ["map_id", "location_entity_id", "hex_q", "hex_r"],
        unique=True,
    )
    # PG 部分唯一索引：同一地点在同一地图最多一个中心点（SQLite 无此语法，测试靠业务层）
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_map_binding_center "
        "ON map_location_bindings (map_id, location_entity_id) WHERE is_center"
    )
    op.create_index(
        "ix_map_location_bindings_map_id",
        "map_location_bindings",
        ["map_id"],
        unique=False,
    )
    op.create_index(
        "ix_map_location_bindings_location_entity_id",
        "map_location_bindings",
        ["location_entity_id"],
        unique=False,
    )
    op.create_index(
        "ix_map_location_bindings_novel_id",
        "map_location_bindings",
        ["novel_id"],
        unique=False,
    )

    # map_markers（P1 数据层预留）
    op.create_table(
        "map_markers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("map_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("marker_type", sa.String(length=16), nullable=False),
        sa.Column("hex_q", sa.Integer(), nullable=False),
        sa.Column("hex_r", sa.Integer(), nullable=False),
        sa.Column("offset_x", sa.Float(), nullable=False),
        sa.Column("offset_y", sa.Float(), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.Column("style_json", sa.JSON(), nullable=True),
        sa.Column("start_scene_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("start_scene_index", sa.Integer(), nullable=True),
        sa.Column("end_scene_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("end_scene_index", sa.Integer(), nullable=True),
        sa.Column("visible", sa.Boolean(), nullable=False),
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
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["map_id"], ["map_configs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entity_id"], ["core_entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        comment="动态标记（P1 预留）",
    )
    op.create_index(
        "ix_map_marker_map_scene", "map_markers", ["map_id", "marker_type"], unique=False
    )
    op.create_index("ix_map_markers_map_id", "map_markers", ["map_id"], unique=False)
    op.create_index(
        "ix_map_markers_entity_id", "map_markers", ["entity_id"], unique=False
    )
    op.create_index("ix_map_markers_novel_id", "map_markers", ["novel_id"], unique=False)


def downgrade() -> None:
    op.drop_table("map_markers")
    op.execute("DROP INDEX IF EXISTS ix_map_binding_center")
    op.drop_table("map_location_bindings")
    op.drop_table("map_tiles")
    op.drop_table("map_configs")
