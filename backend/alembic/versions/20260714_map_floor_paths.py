"""map floor modes and continuous path assets

Revision ID: 20260714_map_floor_paths
Revises: 20260714_map_editor_layer_tree
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260714_map_floor_paths"
down_revision = "20260714_map_editor_layer_tree"
branch_labels = None
depends_on = None


def _utc_now_default() -> sa.TextClause:
    if op.get_bind().dialect.name == "sqlite":
        return sa.text("CURRENT_TIMESTAMP")
    return sa.text("timezone('utc', now())")


def _identity_columns() -> list[sa.Column]:
    return [
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
    ]


def _ensure_index(
    table_name: str,
    index_name: str,
    columns: list[str],
    *,
    unique: bool = False,
) -> None:
    bind = op.get_bind()
    names = {item["name"] for item in sa.inspect(bind).get_indexes(table_name)}
    if index_name not in names:
        op.create_index(index_name, table_name, columns, unique=unique)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    layer_columns = {
        column["name"] for column in inspector.get_columns("map_layer_nodes")
    }
    if "selection_mode" not in layer_columns:
        op.add_column(
            "map_layer_nodes",
            sa.Column(
                "selection_mode",
                sa.String(length=16),
                nullable=False,
                server_default="normal",
            ),
        )
    if "floor_level" not in layer_columns:
        op.add_column(
            "map_layer_nodes",
            sa.Column("floor_level", sa.Integer(), nullable=True),
        )

    tables = set(inspector.get_table_names())
    if "map_path_layers" not in tables:
        op.create_table(
            "map_path_layers",
            sa.Column("map_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("category", sa.String(length=16), nullable=False),
            sa.Column("meta", sa.JSON(), nullable=True),
            *_identity_columns(),
            sa.ForeignKeyConstraint(
                ["map_id"], ["map_configs.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["novel_id"], ["projects.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
    _ensure_index("map_path_layers", "ix_map_path_layers_map_id", ["map_id"])
    _ensure_index("map_path_layers", "ix_map_path_layers_novel_id", ["novel_id"])
    _ensure_index(
        "map_path_layers",
        "ix_map_path_layer_map_category",
        ["map_id", "category"],
    )

    layer_columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("map_layer_nodes")
    }
    if "path_layer_id" not in layer_columns:
        op.add_column(
            "map_layer_nodes",
            sa.Column("path_layer_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
    layer_foreign_keys = sa.inspect(bind).get_foreign_keys("map_layer_nodes")
    if not any(
        item.get("constrained_columns") == ["path_layer_id"]
        for item in layer_foreign_keys
    ):
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("map_layer_nodes") as batch_op:
                batch_op.create_foreign_key(
                    "fk_map_layer_nodes_path_layer_id",
                    "map_path_layers",
                    ["path_layer_id"],
                    ["id"],
                    ondelete="CASCADE",
                )
        else:
            op.create_foreign_key(
                "fk_map_layer_nodes_path_layer_id",
                "map_layer_nodes",
                "map_path_layers",
                ["path_layer_id"],
                ["id"],
                ondelete="CASCADE",
            )
    _ensure_index(
        "map_layer_nodes",
        "ix_map_layer_nodes_path_layer_id",
        ["path_layer_id"],
    )
    _ensure_index(
        "map_layer_nodes",
        "uq_map_layer_node_path_layer",
        ["path_layer_id"],
        unique=True,
    )

    tables = set(sa.inspect(bind).get_table_names())
    if "map_paths" not in tables:
        op.create_table(
            "map_paths",
            sa.Column("map_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("path_layer_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("path_type", sa.String(length=32), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "visible", sa.Boolean(), nullable=False, server_default=sa.true()
            ),
            sa.Column(
                "locked", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
            sa.Column("opacity", sa.Float(), nullable=False, server_default="1"),
            sa.Column("min_zoom", sa.Integer(), nullable=True),
            sa.Column("max_zoom", sa.Integer(), nullable=True),
            sa.Column("style_json", sa.JSON(), nullable=True),
            sa.Column(
                "start_location_entity_id",
                postgresql.UUID(as_uuid=True),
                nullable=True,
            ),
            sa.Column(
                "end_location_entity_id",
                postgresql.UUID(as_uuid=True),
                nullable=True,
            ),
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default="active",
            ),
            sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "content_revision", sa.Integer(), nullable=False, server_default="1"
            ),
            sa.Column("meta", sa.JSON(), nullable=True),
            *_identity_columns(),
            sa.ForeignKeyConstraint(
                ["map_id"], ["map_configs.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["path_layer_id"], ["map_path_layers.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["start_location_entity_id"],
                ["core_entities.id"],
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["end_location_entity_id"],
                ["core_entities.id"],
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["novel_id"], ["projects.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
    for column in (
        "map_id",
        "path_layer_id",
        "start_location_entity_id",
        "end_location_entity_id",
        "status",
        "novel_id",
    ):
        _ensure_index("map_paths", f"ix_map_paths_{column}", [column])
    _ensure_index("map_paths", "ix_map_path_map_status", ["map_id", "status"])
    _ensure_index(
        "map_paths",
        "ix_map_path_layer_order",
        ["path_layer_id", "sort_order", "id"],
    )

    tables = set(sa.inspect(bind).get_table_names())
    if "map_path_nodes" not in tables:
        op.create_table(
            "map_path_nodes",
            sa.Column("map_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("path_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.Column("q", sa.Float(), nullable=False),
            sa.Column("r", sa.Float(), nullable=False),
            sa.Column("width_scale", sa.Float(), nullable=False, server_default="1"),
            sa.Column("tension", sa.Float(), nullable=False, server_default="0.5"),
            sa.Column("segment_type", sa.String(length=32), nullable=True),
            *_identity_columns(),
            sa.ForeignKeyConstraint(
                ["map_id"], ["map_configs.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["path_id"], ["map_paths.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["novel_id"], ["projects.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "path_id", "sort_order", name="uq_map_path_node_path_order"
            ),
        )
    unique_names = {
        item["name"]
        for item in sa.inspect(bind).get_unique_constraints("map_path_nodes")
    }
    if "uq_map_path_node_path_order" not in unique_names:
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("map_path_nodes") as batch_op:
                batch_op.create_unique_constraint(
                    "uq_map_path_node_path_order",
                    ["path_id", "sort_order"],
                )
        else:
            op.create_unique_constraint(
                "uq_map_path_node_path_order",
                "map_path_nodes",
                ["path_id", "sort_order"],
            )
    _ensure_index("map_path_nodes", "ix_map_path_nodes_map_id", ["map_id"])
    _ensure_index("map_path_nodes", "ix_map_path_nodes_path_id", ["path_id"])
    _ensure_index("map_path_nodes", "ix_map_path_nodes_novel_id", ["novel_id"])
    _ensure_index(
        "map_path_nodes",
        "ix_map_path_node_map_path",
        ["map_id", "path_id", "sort_order"],
    )

    if bind.dialect.name == "sqlite":
        configs = bind.execute(
            sa.text("SELECT id, novel_id FROM map_configs")
        ).mappings()
        for config in configs:
            exists = bind.execute(
                sa.text(
                    "SELECT 1 FROM map_layer_nodes "
                    "WHERE map_id = :map_id AND layer_key = 'path' LIMIT 1"
                ),
                {"map_id": config["id"]},
            ).first()
            if exists:
                continue
            sort_order = bind.execute(
                sa.text(
                    "SELECT COALESCE(MAX(sort_order) + 1, 0) "
                    "FROM map_layer_nodes "
                    "WHERE map_id = :map_id AND parent_id IS NULL"
                ),
                {"map_id": config["id"]},
            ).scalar_one()
            bind.execute(
                sa.text(
                    "INSERT INTO map_layer_nodes "
                    "(id, novel_id, map_id, node_type, layer_key, name, visible, "
                    "locked, opacity, sort_order, selection_mode, meta) VALUES "
                    "(:id, :novel_id, :map_id, 'group', 'path', :name, 1, 0, "
                    "1, :sort_order, 'normal', '{}')"
                ),
                {
                    "id": str(
                        uuid.uuid5(
                            uuid.NAMESPACE_URL,
                            f"map-path:{config['id']}",
                        )
                    ),
                    "novel_id": config["novel_id"],
                    "map_id": config["id"],
                    "name": "线路",
                    "sort_order": sort_order,
                },
            )
    else:
        op.execute(
            sa.text(
                "INSERT INTO map_layer_nodes "
                "(id, novel_id, map_id, node_type, layer_key, name, visible, locked, "
                "opacity, sort_order, selection_mode, meta) "
                "SELECT CAST(md5(CAST(config.id AS text) || :salt) AS uuid), "
                "config.novel_id, config.id, 'group', 'path', :name, true, false, 1, "
                "COALESCE((SELECT MAX(node.sort_order) + 1 "
                "FROM map_layer_nodes AS node WHERE node.map_id = config.id "
                "AND node.parent_id IS NULL), 0), 'normal', '{}' "
                "FROM map_configs AS config WHERE true ON CONFLICT DO NOTHING"
            ).bindparams(salt=":path", name="线路")
        )


def downgrade() -> None:
    op.drop_table("map_path_nodes")
    op.drop_table("map_paths")
    op.drop_index(
        "uq_map_layer_node_path_layer", table_name="map_layer_nodes"
    )
    op.drop_index(
        "ix_map_layer_nodes_path_layer_id", table_name="map_layer_nodes"
    )
    op.drop_constraint(
        "fk_map_layer_nodes_path_layer_id",
        "map_layer_nodes",
        type_="foreignkey",
    )
    op.drop_column("map_layer_nodes", "path_layer_id")
    op.execute("DELETE FROM map_layer_nodes WHERE layer_key = 'path'")
    op.drop_table("map_path_layers")
    op.drop_column("map_layer_nodes", "floor_level")
    op.drop_column("map_layer_nodes", "selection_mode")
