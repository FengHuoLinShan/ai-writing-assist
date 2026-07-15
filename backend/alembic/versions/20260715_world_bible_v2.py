"""add World Bible sections, page templates, and activation profiles

Revision ID: 20260715_world_bible_v2
Revises: 20260714_map_dynamic_timeline
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "20260715_world_bible_v2"
down_revision = "20260714_map_dynamic_timeline"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table_name)}


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


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


def _add_workspace_columns(tables: set[str]) -> None:
    page_columns = _columns("world_bible_pages")
    if "sections_json" not in page_columns:
        op.add_column(
            "world_bible_pages",
            sa.Column(
                "sections_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            ),
        )

    draft_columns = _columns("world_bible_page_drafts")
    if "sections_json" not in draft_columns:
        op.add_column(
            "world_bible_page_drafts",
            sa.Column(
                "sections_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            ),
        )
    if "template_key" not in draft_columns:
        op.add_column(
            "world_bible_page_drafts",
            sa.Column("template_key", sa.String(128), nullable=True),
        )
    if "template_version" not in draft_columns:
        op.add_column(
            "world_bible_page_drafts",
            sa.Column(
                "template_version",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
        )

    category_columns = _columns("world_bible_categories")
    if "default_template_key" not in category_columns:
        op.add_column(
            "world_bible_categories",
            sa.Column("default_template_key", sa.String(128), nullable=True),
        )


def _create_page_template_tables(tables: set[str]) -> None:
    if "world_bible_page_templates" not in tables:
        op.create_table(
            "world_bible_page_templates",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "novel_id",
                UUID(as_uuid=True),
                sa.ForeignKey("projects.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("template_key", sa.String(128), nullable=False),
            sa.Column("name", sa.String(80), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("category_key_hint", sa.String(64), nullable=True),
            sa.Column("sections_schema_json", sa.JSON(), nullable=False),
            sa.Column("default_sections_json", sa.JSON(), nullable=False),
            sa.Column("validation_rules_json", sa.JSON(), nullable=False),
            sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("created_by", sa.String(64), nullable=True),
            sa.Column("updated_by", sa.String(64), nullable=True),
            *_timestamps(),
            sa.UniqueConstraint(
                "novel_id",
                "template_key",
                name="uq_world_bible_page_template_key",
            ),
        )
        op.create_index(
            "ix_world_bible_page_templates_novel_id",
            "world_bible_page_templates",
            ["novel_id"],
        )
        op.create_index(
            "ix_world_bible_page_templates_status",
            "world_bible_page_templates",
            ["status"],
        )

    if "world_bible_page_template_revisions" not in tables:
        op.create_table(
            "world_bible_page_template_revisions",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "novel_id",
                UUID(as_uuid=True),
                sa.ForeignKey("projects.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "template_id",
                UUID(as_uuid=True),
                sa.ForeignKey("world_bible_page_templates.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column("snapshot_json", sa.JSON(), nullable=False),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.Column("revision_reason", sa.String(64), nullable=False),
            sa.Column("created_by", sa.String(64), nullable=True),
            *_timestamps(),
            sa.UniqueConstraint(
                "template_id",
                "version_number",
                name="uq_world_bible_page_template_revision",
            ),
        )
        op.create_index(
            "ix_world_bible_page_template_revisions_novel_id",
            "world_bible_page_template_revisions",
            ["novel_id"],
        )
        op.create_index(
            "ix_world_bible_page_template_revisions_template_id",
            "world_bible_page_template_revisions",
            ["template_id"],
        )


def _create_activation_profile_tables(tables: set[str]) -> None:
    if "context_activation_profiles" not in tables:
        op.create_table(
            "context_activation_profiles",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "novel_id",
                UUID(as_uuid=True),
                sa.ForeignKey("projects.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("profile_key", sa.String(128), nullable=False),
            sa.Column("name", sa.String(80), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("applicable_actions_json", sa.JSON(), nullable=False),
            sa.Column("rules_json", sa.JSON(), nullable=False),
            sa.Column("budget_hints_json", sa.JSON(), nullable=False),
            sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("created_by", sa.String(64), nullable=True),
            sa.Column("updated_by", sa.String(64), nullable=True),
            *_timestamps(),
            sa.UniqueConstraint(
                "novel_id",
                "profile_key",
                name="uq_context_activation_profile_key",
            ),
        )
        op.create_index(
            "ix_context_activation_profiles_novel_id",
            "context_activation_profiles",
            ["novel_id"],
        )
        op.create_index(
            "ix_context_activation_profiles_novel_status",
            "context_activation_profiles",
            ["novel_id", "status"],
        )

    if "context_activation_profile_revisions" not in tables:
        op.create_table(
            "context_activation_profile_revisions",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "novel_id",
                UUID(as_uuid=True),
                sa.ForeignKey("projects.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "profile_id",
                UUID(as_uuid=True),
                sa.ForeignKey("context_activation_profiles.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column("snapshot_json", sa.JSON(), nullable=False),
            sa.Column("rule_hash", sa.String(64), nullable=False),
            sa.Column("revision_reason", sa.String(64), nullable=False),
            sa.Column("created_by", sa.String(64), nullable=True),
            *_timestamps(),
            sa.UniqueConstraint(
                "profile_id",
                "version_number",
                name="uq_context_activation_profile_revision",
            ),
        )
        op.create_index(
            "ix_context_activation_profile_revisions_novel_id",
            "context_activation_profile_revisions",
            ["novel_id"],
        )
        op.create_index(
            "ix_context_activation_profile_revisions_profile_id",
            "context_activation_profile_revisions",
            ["profile_id"],
        )


def upgrade() -> None:
    tables = _tables()
    _add_workspace_columns(tables)
    _create_page_template_tables(tables)
    _create_activation_profile_tables(tables)


def downgrade() -> None:
    tables = _tables()
    for table_name in (
        "context_activation_profile_revisions",
        "context_activation_profiles",
        "world_bible_page_template_revisions",
        "world_bible_page_templates",
    ):
        if table_name in tables:
            op.drop_table(table_name)
    if "world_bible_categories" in tables:
        columns = _columns("world_bible_categories")
        if "default_template_key" in columns:
            op.drop_column("world_bible_categories", "default_template_key")
    if "world_bible_page_drafts" in tables:
        columns = _columns("world_bible_page_drafts")
        for column_name in ("template_version", "template_key", "sections_json"):
            if column_name in columns:
                op.drop_column("world_bible_page_drafts", column_name)
    if "world_bible_pages" in tables and "sections_json" in _columns(
        "world_bible_pages"
    ):
        op.drop_column("world_bible_pages", "sections_json")
