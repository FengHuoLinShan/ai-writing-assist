"""map archive, editor revision, and recursive layer tree

Revision ID: 20260714_map_editor_layer_tree
Revises: 20260714_smart_dedup_workbench
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260714_map_editor_layer_tree"
down_revision = "20260714_smart_dedup_workbench"
branch_labels = None
depends_on = None


def _utc_now_default() -> sa.TextClause:
    if op.get_bind().dialect.name == "sqlite":
        return sa.text("CURRENT_TIMESTAMP")
    return sa.text("timezone('utc', now())")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    map_config_columns = {
        column["name"] for column in inspector.get_columns("map_configs")
    }
    if "status" not in map_config_columns:
        op.add_column(
            "map_configs",
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default="active",
            ),
        )
    if "archived_at" not in map_config_columns:
        op.add_column(
            "map_configs",
            sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "editor_revision" not in map_config_columns:
        op.add_column(
            "map_configs",
            sa.Column(
                "editor_revision",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )

    map_config_indexes = {
        index["name"] for index in sa.inspect(bind).get_indexes("map_configs")
    }
    if "ix_map_configs_status" not in map_config_indexes:
        op.create_index("ix_map_configs_status", "map_configs", ["status"])
    if "uq_map_config_novel_parent_name" in map_config_indexes:
        op.execute("DROP INDEX IF EXISTS uq_map_config_novel_parent_name")
    if "uq_map_config_top_level_name" in map_config_indexes:
        op.execute("DROP INDEX IF EXISTS uq_map_config_top_level_name")
    if "ix_map_config_novel_parent_name" not in map_config_indexes:
        op.create_index(
            "ix_map_config_novel_parent_name",
            "map_configs",
            ["novel_id", "parent_map_id", "name"],
        )
    if "uq_map_config_active_child_name" not in map_config_indexes:
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_map_config_active_child_name "
            "ON map_configs (novel_id, parent_map_id, name) "
            "WHERE status = 'active' AND parent_map_id IS NOT NULL"
        )
    if "uq_map_config_active_root_name" not in map_config_indexes:
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_map_config_active_root_name "
            "ON map_configs (novel_id, name) "
            "WHERE status = 'active' AND parent_map_id IS NULL"
        )

    if "map_layer_nodes" not in inspector.get_table_names():
        _create_layer_nodes_table()
    _ensure_layer_node_indexes()
    _backfill_layer_nodes()


def _create_layer_nodes_table() -> None:
    op.create_table(
        "map_layer_nodes",
        sa.Column("map_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("terrain_layer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("node_type", sa.String(length=16), nullable=False),
        sa.Column("layer_key", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("visible", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("opacity", sa.Float(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "sort_order",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("min_zoom", sa.Integer(), nullable=True),
        sa.Column("max_zoom", sa.Integer(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=_utc_now_default(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=_utc_now_default(),
        ),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["map_id"], ["map_configs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["novel_id"], ["projects.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["map_layer_nodes.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["terrain_layer_id"],
            ["map_terrain_layers.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def _ensure_layer_node_indexes() -> None:
    bind = op.get_bind()
    indexes = {
        index["name"]
        for index in sa.inspect(bind).get_indexes("map_layer_nodes")
    }
    definitions = (
        ("ix_map_layer_nodes_map_id", ("map_id",), False),
        ("ix_map_layer_nodes_novel_id", ("novel_id",), False),
        ("ix_map_layer_nodes_parent_id", ("parent_id",), False),
        (
            "ix_map_layer_nodes_terrain_layer_id",
            ("terrain_layer_id",),
            False,
        ),
        (
            "ix_map_layer_node_map_parent",
            ("map_id", "parent_id", "sort_order"),
            False,
        ),
        (
            "uq_map_layer_node_map_layer_key",
            ("map_id", "layer_key"),
            True,
        ),
        ("uq_map_layer_node_terrain_layer", ("terrain_layer_id",), True),
    )
    for index_name, columns, unique in definitions:
        if index_name not in indexes:
            op.create_index(
                index_name,
                "map_layer_nodes",
                list(columns),
                unique=unique,
            )


def _backfill_layer_nodes() -> None:
    # UUIDs are deterministic so interrupted demo migrations can be inspected safely.
    for key, name, node_type, sort_order in (
        ("baseTerrain", "底图", "leaf", 0),
        ("location", "地点", "leaf", 1),
        ("marker", "标记", "group", 2),
        ("territory", "领地", "leaf", 3),
        ("terrainOverlay", "覆盖素材", "group", 4),
        ("pending", "待处理", "leaf", 5),
    ):
        op.execute(
            sa.text(
                "INSERT INTO map_layer_nodes "
                "(id, novel_id, map_id, node_type, layer_key, name, visible, "
                "locked, opacity, sort_order, meta) "
                "SELECT CAST(md5(CAST(id AS text) || :salt) AS uuid), novel_id, id, "
                ":node_type, :layer_key, :name, true, false, 1, :sort_order, '{}' "
                "FROM map_configs WHERE true ON CONFLICT DO NOTHING"
            ).bindparams(
                salt=f":{key}",
                node_type=node_type,
                layer_key=key,
                name=name,
                sort_order=sort_order,
            )
        )

    for key, name, sort_order in (
        ("marker.character", "人物", 0),
        ("marker.event", "事件", 1),
        ("marker.item", "物品", 2),
    ):
        op.execute(
            sa.text(
                "INSERT INTO map_layer_nodes "
                "(id, novel_id, map_id, parent_id, node_type, layer_key, name, "
                "visible, locked, opacity, sort_order, meta) "
                "SELECT CAST(md5(CAST(id AS text) || :salt) AS uuid), novel_id, id, "
                "CAST(md5(CAST(id AS text) || :parent_salt) AS uuid), 'leaf', "
                ":layer_key, :name, true, false, 1, :sort_order, '{}' "
                "FROM map_configs WHERE true ON CONFLICT DO NOTHING"
            ).bindparams(
                salt=f":{key}",
                parent_salt=":marker",
                layer_key=key,
                name=name,
                sort_order=sort_order,
            )
        )

    op.execute(
        sa.text(
            "INSERT INTO map_layer_nodes "
            "(id, novel_id, map_id, parent_id, terrain_layer_id, node_type, name, "
            "visible, locked, opacity, sort_order, meta) "
            "SELECT CAST(md5(CAST(layer.id AS text) || :terrain_salt) AS uuid), "
            "layer.novel_id, layer.map_id, "
            "CAST(md5(CAST(layer.map_id AS text) || :overlay_salt) AS uuid), "
            "layer.id, 'leaf', layer.name, layer.visible, layer.locked, layer.opacity, "
            "ROW_NUMBER() OVER (PARTITION BY layer.map_id "
            "ORDER BY layer.z_index, layer.created_at, layer.id) - 1, '{}' "
            "FROM map_terrain_layers AS layer WHERE true ON CONFLICT DO NOTHING"
        ).bindparams(terrain_salt=":terrain", overlay_salt=":terrainOverlay")
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "map_layer_nodes" in inspector.get_table_names():
        op.drop_table("map_layer_nodes")
    op.execute("DROP INDEX IF EXISTS uq_map_config_active_child_name")
    op.execute("DROP INDEX IF EXISTS uq_map_config_active_root_name")
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("map_configs")}
    if "ix_map_config_novel_parent_name" in indexes:
        op.drop_index("ix_map_config_novel_parent_name", table_name="map_configs")
    op.create_index(
        "uq_map_config_novel_parent_name",
        "map_configs",
        ["novel_id", "parent_map_id", "name"],
        unique=True,
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_map_config_top_level_name "
        "ON map_configs (novel_id, name) WHERE parent_map_id IS NULL"
    )
    op.drop_index("ix_map_configs_status", table_name="map_configs")
    op.drop_column("map_configs", "editor_revision")
    op.drop_column("map_configs", "archived_at")
    op.drop_column("map_configs", "status")
