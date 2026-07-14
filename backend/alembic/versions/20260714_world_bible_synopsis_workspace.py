"""add World Bible drafts, categories, and author synopsis revisions

Revision ID: 20260714_world_bible_synopsis
Revises: 20260713_scene_replacement_results
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "20260714_world_bible_synopsis"
down_revision = "20260713_scene_replacement_results"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    ]


def _create_workspace_tables(tables: set[str]) -> None:
    if "world_bible_categories" not in tables:
        op.create_table(
            "world_bible_categories",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "novel_id",
                UUID(as_uuid=True),
                sa.ForeignKey("projects.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("category_key", sa.String(64), nullable=False),
            sa.Column("name", sa.String(80), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("color", sa.String(7), nullable=False),
            sa.Column("icon", sa.String(16), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            *_timestamps(),
            sa.UniqueConstraint(
                "novel_id",
                "category_key",
                name="uq_world_bible_category_key",
            ),
        )
        op.create_index(
            "ix_world_bible_categories_novel_id",
            "world_bible_categories",
            ["novel_id"],
        )
        op.create_index(
            "ix_world_bible_categories_status",
            "world_bible_categories",
            ["status"],
        )

    if "world_bible_page_drafts" not in tables:
        op.create_table(
            "world_bible_page_drafts",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "novel_id",
                UUID(as_uuid=True),
                sa.ForeignKey("projects.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "page_id",
                UUID(as_uuid=True),
                sa.ForeignKey("world_bible_pages.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("base_version_number", sa.Integer(), nullable=True),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("page_type", sa.String(64), nullable=False),
            sa.Column("free_text", sa.Text(), nullable=True),
            sa.Column("linked_asset_refs_json", sa.JSON(), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.Column("created_by", sa.String(64), nullable=True),
            sa.Column("updated_by", sa.String(64), nullable=True),
            *_timestamps(),
            sa.UniqueConstraint(
                "novel_id",
                "page_id",
                name="uq_world_bible_page_active_draft",
            ),
        )
        op.create_index(
            "ix_world_bible_page_drafts_novel_id",
            "world_bible_page_drafts",
            ["novel_id"],
        )
        op.create_index(
            "ix_world_bible_page_drafts_page_id",
            "world_bible_page_drafts",
            ["page_id"],
        )
        op.create_index(
            "ix_world_bible_page_drafts_page_type",
            "world_bible_page_drafts",
            ["page_type"],
        )


def _create_synopsis_tables(tables: set[str]) -> None:
    if "world_bible_synopsis_revisions" not in tables:
        op.create_table(
            "world_bible_synopsis_revisions",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "novel_id",
                UUID(as_uuid=True),
                sa.ForeignKey("projects.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("rendered_text", sa.Text(), nullable=False),
            sa.Column("claims_json", sa.JSON(), nullable=False),
            sa.Column("source_manifest_json", sa.JSON(), nullable=False),
            sa.Column("source_hash", sa.String(64), nullable=False),
            sa.Column("token_estimate", sa.Integer(), nullable=False),
            sa.Column("coverage_json", sa.JSON(), nullable=False),
            sa.Column("omitted_reasons_json", sa.JSON(), nullable=False),
            sa.Column("generation_meta_json", sa.JSON(), nullable=False),
            *_timestamps(),
            sa.UniqueConstraint(
                "novel_id",
                "version_number",
                name="uq_world_bible_synopsis_revision_version",
            ),
        )
        op.create_index(
            "ix_world_bible_synopsis_revisions_novel_id",
            "world_bible_synopsis_revisions",
            ["novel_id"],
        )
        op.create_index(
            "ix_world_bible_synopsis_revisions_source_hash",
            "world_bible_synopsis_revisions",
            ["source_hash"],
        )

    if "world_bible_synopsis_heads" not in tables:
        op.create_table(
            "world_bible_synopsis_heads",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "novel_id",
                UUID(as_uuid=True),
                sa.ForeignKey("projects.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("desired_source_hash", sa.String(64), nullable=False),
            sa.Column(
                "current_revision_id",
                UUID(as_uuid=True),
                sa.ForeignKey(
                    "world_bible_synopsis_revisions.id",
                    ondelete="SET NULL",
                ),
                nullable=True,
            ),
            sa.Column(
                "pinned_revision_id",
                UUID(as_uuid=True),
                sa.ForeignKey(
                    "world_bible_synopsis_revisions.id",
                    ondelete="SET NULL",
                ),
                nullable=True,
            ),
            sa.Column(
                "active_task_id",
                UUID(as_uuid=True),
                sa.ForeignKey("async_tasks.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("stale", sa.Boolean(), nullable=False),
            sa.Column("auto_refresh_enabled", sa.Boolean(), nullable=False),
            sa.Column("authorization_json", sa.JSON(), nullable=False),
            sa.Column("enabled_by", sa.String(64), nullable=True),
            sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error_kind", sa.String(64), nullable=True),
            sa.Column("last_error_summary", sa.Text(), nullable=True),
            sa.Column("status", sa.String(32), nullable=False),
            *_timestamps(),
            sa.UniqueConstraint(
                "novel_id",
                name="uq_world_bible_synopsis_head_novel",
            ),
        )
        op.create_index(
            "ix_world_bible_synopsis_heads_novel_id",
            "world_bible_synopsis_heads",
            ["novel_id"],
        )
        op.create_index(
            "ix_world_bible_synopsis_heads_status",
            "world_bible_synopsis_heads",
            ["status"],
        )


def _repair_page_revisions(bind: sa.Connection) -> None:
    inspector = sa.inspect(bind)
    if not {
        "world_bible_pages",
        "world_bible_page_revisions",
    }.issubset(inspector.get_table_names()):
        return
    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text(
                """
                WITH conflicted_pages AS (
                    SELECT novel_id, page_id
                    FROM world_bible_page_revisions
                    GROUP BY novel_id, page_id, version_number
                    HAVING count(*) > 1
                ),
                ranked AS (
                    SELECT revision.id,
                           row_number() OVER (
                               PARTITION BY revision.novel_id, revision.page_id
                               ORDER BY revision.version_number,
                                        revision.created_at,
                                        revision.id
                           ) AS repaired_version
                    FROM world_bible_page_revisions AS revision
                    WHERE EXISTS (
                        SELECT 1
                        FROM conflicted_pages AS conflict
                        WHERE conflict.novel_id = revision.novel_id
                          AND conflict.page_id = revision.page_id
                    )
                )
                UPDATE world_bible_page_revisions AS revision
                SET version_number = ranked.repaired_version
                FROM ranked
                WHERE revision.id = ranked.id
                  AND revision.version_number <> ranked.repaired_version
                """
            )
        )
    page_table = sa.Table(
        "world_bible_pages",
        sa.MetaData(),
        autoload_with=bind,
    )
    revision_table = sa.Table(
        "world_bible_page_revisions",
        sa.MetaData(),
        autoload_with=bind,
    )
    max_versions = dict(
        bind.execute(
            sa.select(
                revision_table.c.page_id,
                sa.func.max(revision_table.c.version_number),
            ).group_by(revision_table.c.page_id)
        ).all()
    )
    pages = bind.execute(sa.select(page_table)).mappings().all()
    for page in pages:
        current = max(
            int(page["version_number"] or 1),
            int(max_versions.get(page["id"], 0)),
        )
        if current != page["version_number"]:
            bind.execute(
                sa.update(page_table)
                .where(page_table.c.id == page["id"])
                .values(version_number=current)
            )
        exists = bind.scalar(
            sa.select(revision_table.c.id).where(
                revision_table.c.novel_id == page["novel_id"],
                revision_table.c.page_id == page["id"],
                revision_table.c.version_number == current,
            )
        )
        if exists is not None:
            continue
        snapshot = {
            "page_type": page["page_type"],
            "page_key": page["page_key"],
            "title": page["title"],
            "status": page["status"],
            "page_meta_json": page["page_meta_json"] or {},
            "free_text": page["free_text"],
            "linked_asset_refs_json": page["linked_asset_refs_json"] or [],
            "activation_defaults_json": page["activation_defaults_json"] or {},
            "template_key": page["template_key"],
            "template_version": page["template_version"],
            "sort_order": page["sort_order"],
        }
        bind.execute(
            sa.insert(revision_table).values(
                id=uuid.uuid4(),
                novel_id=page["novel_id"],
                page_id=page["id"],
                version_number=current,
                snapshot_json=snapshot,
                revision_reason="migration_baseline",
            )
        )


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    _create_workspace_tables(tables)
    _create_synopsis_tables(tables)

    projection_columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("world_bible_page_projections")
    }
    if "source_page_version" not in projection_columns:
        op.add_column(
            "world_bible_page_projections",
            sa.Column(
                "source_page_version",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )
        op.alter_column(
            "world_bible_page_projections",
            "source_page_version",
            server_default=None,
        )
    if "source_hash" not in projection_columns:
        op.add_column(
            "world_bible_page_projections",
            sa.Column(
                "source_hash",
                sa.String(64),
                nullable=False,
                server_default="",
            ),
        )
        op.alter_column(
            "world_bible_page_projections",
            "source_hash",
            server_default=None,
        )

    _repair_page_revisions(bind)
    constraints = {
        item["name"]
        for item in sa.inspect(bind).get_unique_constraints(
            "world_bible_page_revisions"
        )
    }
    if "uq_world_bible_page_revision_version" not in constraints:
        op.create_unique_constraint(
            "uq_world_bible_page_revision_version",
            "world_bible_page_revisions",
            ["novel_id", "page_id", "version_number"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    constraints = {
        item["name"]
        for item in sa.inspect(bind).get_unique_constraints(
            "world_bible_page_revisions"
        )
    }
    if "uq_world_bible_page_revision_version" in constraints:
        op.drop_constraint(
            "uq_world_bible_page_revision_version",
            "world_bible_page_revisions",
            type_="unique",
        )
    projection_columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("world_bible_page_projections")
    }
    if "source_hash" in projection_columns:
        op.drop_column("world_bible_page_projections", "source_hash")
    if "source_page_version" in projection_columns:
        op.drop_column("world_bible_page_projections", "source_page_version")
    for table_name in (
        "world_bible_synopsis_heads",
        "world_bible_synopsis_revisions",
        "world_bible_page_drafts",
        "world_bible_categories",
    ):
        if table_name in tables:
            op.drop_table(table_name)
