"""Replace the legacy dynamic map with the author-reviewed AI map atlas.

Revision ID: 20260812_ai_map_atlas
Revises: 20260805_task_novel_id
"""

from __future__ import annotations

import os
import re

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260812_ai_map_atlas"
down_revision = "20260805_task_novel_id"
branch_labels = None
depends_on = None

_OLD_TABLES = (
    "map_facts",
    "map_observations",
    "map_visual_revisions",
    "map_territory_tiles",
    "map_markers",
    "map_terrain_bindings",
    "map_terrain_patches",
    "map_terrain_regions",
    "map_path_nodes",
    "map_paths",
    "map_layer_nodes",
    "map_path_layers",
    "map_terrain_layers",
    "map_location_layouts",
    "map_location_bindings",
    "map_tiles",
    "map_configs",
)
_DESTRUCTIVE_CONFIRMATION = "DROP_LEGACY_MAP_DATA_20260812"
_SAFE_ENVIRONMENTS = {"dev", "development", "test", "testing", "ci"}


def _require_destructive_confirmation(bind: sa.Connection) -> None:
    if os.getenv("APP_ENV", "development").strip().lower() in _SAFE_ENVIRONMENTS:
        return
    has_projects = bind.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM projects LIMIT 1)")
    ).scalar_one()
    if not has_projects:
        return

    confirmation = os.getenv("MAP_ATLAS_DESTRUCTIVE_MIGRATION_CONFIRMATION", "")
    backup_name = os.getenv("MAP_ATLAS_DESTRUCTIVE_MIGRATION_BACKUP_NAME", "")
    backup_sha256 = os.getenv(
        "MAP_ATLAS_DESTRUCTIVE_MIGRATION_BACKUP_SHA256", ""
    )
    if (
        confirmation != _DESTRUCTIVE_CONFIRMATION
        or re.fullmatch(r"\d{8}T\d{6}Z\.dump", backup_name) is None
        or len(backup_sha256) != 64
        or any(character not in "0123456789abcdef" for character in backup_sha256)
    ):
        raise RuntimeError(
            "20260812_ai_map_atlas requires a verified pre-migration backup and "
            "one-time destructive confirmation; use deploy/scripts/release.sh"
        )


def _uuid() -> sa.TypeEngine:
    return sa.CHAR(36).with_variant(postgresql.UUID(as_uuid=True), "postgresql")


def _json() -> sa.TypeEngine:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _timestamps() -> list[sa.Column]:
    default = (
        sa.text("CURRENT_TIMESTAMP")
        if op.get_bind().dialect.name == "sqlite"
        else sa.text("timezone('utc', now())")
    )
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=default,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=default,
        ),
    ]


def _identity() -> list[sa.Column]:
    return [sa.Column("id", _uuid(), nullable=False), *_timestamps()]


def upgrade() -> None:
    bind = op.get_bind()
    _require_destructive_confirmation(bind)
    existing = set(sa.inspect(bind).get_table_names())
    for table in _OLD_TABLES:
        if table in existing:
            op.drop_table(table)

    op.create_table(
        "map_atlas_runs",
        *_identity(),
        sa.Column("novel_id", _uuid(), nullable=False),
        sa.Column("task_id", _uuid(), nullable=True),
        sa.Column("run_kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("style_note", sa.Text(), nullable=True),
        sa.Column("include_working_drafts", sa.Boolean(), nullable=False),
        sa.Column("include_interiors", sa.Boolean(), nullable=False),
        sa.Column("layout", sa.String(16), nullable=False),
        sa.Column("quality", sa.String(16), nullable=False),
        sa.Column("page_limit", sa.Integer(), nullable=False),
        sa.Column("planned_page_count", sa.Integer(), nullable=False),
        sa.Column("completed_page_count", sa.Integer(), nullable=False),
        sa.Column("stop_requested", sa.Boolean(), nullable=False),
        sa.Column("context_hash", sa.String(64), nullable=True),
        sa.Column("context_snapshot", _json(), nullable=False),
        sa.Column("source_manifest", _json(), nullable=False),
        sa.Column("atlas_plan", _json(), nullable=False),
        sa.Column("llm_execution_snapshot", _json(), nullable=False),
        sa.Column("image_execution_snapshot", _json(), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "run_kind IN ('initial','update','rebuild','edit','regenerate')",
            name="ck_map_atlas_runs_kind",
        ),
        sa.CheckConstraint(
            "status IN ('planning','generating','review_ready','partial',"
            "'paused','failed','completed')",
            name="ck_map_atlas_runs_status",
        ),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["async_tasks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_map_atlas_runs_novel_id", "map_atlas_runs", ["novel_id"])
    op.create_index("ix_map_atlas_runs_task_id", "map_atlas_runs", ["task_id"])
    op.create_index("ix_map_atlas_runs_status", "map_atlas_runs", ["status"])
    op.create_index(
        "ix_map_atlas_runs_novel_created",
        "map_atlas_runs",
        ["novel_id", "created_at"],
    )

    op.create_table(
        "map_atlas_nodes",
        *_identity(),
        sa.Column("novel_id", _uuid(), nullable=False),
        sa.Column("created_by_run_id", _uuid(), nullable=False),
        sa.Column("parent_id", _uuid(), nullable=True),
        sa.Column("location_entity_id", _uuid(), nullable=True),
        sa.Column("semantic_key", sa.String(255), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "level IN ('cover','world','region','city','district','street','interior')",
            name="ck_map_atlas_nodes_level",
        ),
        sa.CheckConstraint(
            "status IN ('provisional','adopted')",
            name="ck_map_atlas_nodes_status",
        ),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_run_id"], ["map_atlas_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["map_atlas_nodes.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["location_entity_id"], ["core_entities.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "novel_id", "semantic_key", name="uq_map_atlas_nodes_novel_semantic"
        ),
    )
    for column in (
        "novel_id",
        "created_by_run_id",
        "parent_id",
        "location_entity_id",
        "level",
        "status",
    ):
        op.create_index(f"ix_map_atlas_nodes_{column}", "map_atlas_nodes", [column])
    op.create_index(
        "ix_map_atlas_nodes_novel_parent_order",
        "map_atlas_nodes",
        ["novel_id", "parent_id", "sort_order"],
    )

    op.create_table(
        "map_atlas_pages",
        *_identity(),
        sa.Column("novel_id", _uuid(), nullable=False),
        sa.Column("run_id", _uuid(), nullable=False),
        sa.Column("node_id", _uuid(), nullable=False),
        sa.Column("derived_from_page_id", _uuid(), nullable=True),
        sa.Column("generation_status", sa.String(32), nullable=False),
        sa.Column("review_status", sa.String(16), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("visual_brief", sa.Text(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("edit_instruction", sa.Text(), nullable=True),
        sa.Column("node_proposal", _json(), nullable=False),
        sa.Column("evidence", _json(), nullable=False),
        sa.Column("source_manifest", _json(), nullable=False),
        sa.Column("reference_page_ids", _json(), nullable=False),
        sa.Column("object_key", sa.String(1024), nullable=True),
        sa.Column("mask_object_key", sa.String(1024), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("media_type", sa.String(64), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("provider_request_id", sa.String(255), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("adopted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deprecated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "generation_status IN ('prepared','provider_in_flight','uploaded',"
            "'review_ready','failed','retry_requires_confirmation')",
            name="ck_map_atlas_pages_generation_status",
        ),
        sa.CheckConstraint(
            "review_status IN ('candidate','adopted','rejected','deprecated')",
            name="ck_map_atlas_pages_review_status",
        ),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["map_atlas_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["node_id"], ["map_atlas_nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["derived_from_page_id"], ["map_atlas_pages.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "novel_id",
        "run_id",
        "node_id",
        "derived_from_page_id",
        "generation_status",
        "review_status",
    ):
        op.create_index(f"ix_map_atlas_pages_{column}", "map_atlas_pages", [column])
    op.create_index(
        "ix_map_atlas_pages_novel_node_review",
        "map_atlas_pages",
        ["novel_id", "node_id", "review_status"],
    )
    op.create_index(
        "ix_map_atlas_pages_run_order",
        "map_atlas_pages",
        ["run_id", "sort_order", "created_at"],
    )

    op.create_table(
        "map_atlas_annotations",
        *_identity(),
        sa.Column("novel_id", _uuid(), nullable=False),
        sa.Column("page_id", _uuid(), nullable=False),
        sa.Column("target_node_id", _uuid(), nullable=True),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("position_x", sa.Float(), nullable=False),
        sa.Column("position_y", sa.Float(), nullable=False),
        sa.Column("source_ref", _json(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "position_x >= 0 AND position_x <= 1 AND position_y >= 0 AND position_y <= 1",
            name="ck_map_atlas_annotations_position",
        ),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["page_id"], ["map_atlas_pages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["target_node_id"], ["map_atlas_nodes.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("novel_id", "page_id", "target_node_id"):
        op.create_index(
            f"ix_map_atlas_annotations_{column}", "map_atlas_annotations", [column]
        )
    op.create_index(
        "ix_map_atlas_annotations_page_order",
        "map_atlas_annotations",
        ["page_id", "sort_order"],
    )


def downgrade() -> None:
    raise RuntimeError(
        "20260812_ai_map_atlas is destructive; restore the pre-migration backup instead"
    )
