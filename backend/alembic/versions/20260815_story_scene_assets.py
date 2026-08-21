"""Persist Story character cards and multi-file Scene script revisions.

Revision ID: 20260815_story_scene_assets
Revises: 20260814_world_object_images
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260815_story_scene_assets"
down_revision = "20260814_world_object_images"
branch_labels = None
depends_on = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=True)
    json_type = postgresql.JSONB

    op.create_table(
        "story_character_cards",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("novel_id", uuid_type, nullable=False),
        sa.Column("scene_id", uuid_type, nullable=False),
        sa.Column("character_id", uuid_type, nullable=False),
        sa.Column("current_revision_id", uuid_type, nullable=True),
        sa.Column(
            "current_version_number", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("stale", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("stale_reason", sa.String(255), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "novel_id",
            "scene_id",
            "character_id",
            name="uq_story_character_card_novel_character",
        ),
        sa.UniqueConstraint("id", "novel_id", name="uq_story_character_card_id_novel"),
    )
    op.create_index(
        "ix_story_character_cards_novel_status",
        "story_character_cards",
        ["novel_id", "status"],
    )
    op.create_index(
        "ix_story_character_cards_novel_scene_character",
        "story_character_cards",
        ["novel_id", "scene_id", "character_id"],
        unique=False,
    )

    op.create_table(
        "story_character_card_revisions",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("novel_id", uuid_type, nullable=False),
        sa.Column("card_id", uuid_type, nullable=False),
        sa.Column("scene_id", uuid_type, nullable=False),
        sa.Column("character_id", uuid_type, nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("payload_json", json_type, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(32), nullable=False, server_default="accepted"),
        sa.Column("authorization_ref", sa.String(255), nullable=True),
        sa.Column("source_manifest_json", json_type, nullable=False),
        sa.Column("source_task_id", uuid_type, nullable=True),
        sa.Column("context_snapshot_id", uuid_type, nullable=True),
        sa.Column("base_revision_id", uuid_type, nullable=True),
        sa.Column("restored_from_revision_id", uuid_type, nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "novel_id",
            "card_id",
            "version_number",
            name="uq_story_character_card_revision_version",
        ),
        sa.UniqueConstraint(
            "id", "novel_id", name="uq_story_character_card_revision_id_novel"
        ),
    )
    op.create_index(
        "ix_story_character_card_revisions_novel_card",
        "story_character_card_revisions",
        ["novel_id", "card_id", "version_number"],
    )
    op.create_foreign_key(
        "fk_story_character_card_revision_card_novel",
        "story_character_card_revisions",
        "story_character_cards",
        ["card_id", "novel_id"],
        ["id", "novel_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_story_character_card_current_novel",
        "story_character_cards",
        "story_character_card_revisions",
        ["current_revision_id", "novel_id"],
        ["id", "novel_id"],
    )

    op.create_table(
        "story_scene_script_files",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("novel_id", uuid_type, nullable=False),
        sa.Column("scene_id", uuid_type, nullable=False),
        sa.Column("file_key", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("current_revision_id", uuid_type, nullable=True),
        sa.Column(
            "current_version_number", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("adopted_revision_id", uuid_type, nullable=True),
        sa.Column(
            "adopted_version_number", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "novel_id",
            "scene_id",
            "file_key",
            name="uq_story_scene_script_file_novel_scene_key",
        ),
        sa.UniqueConstraint("id", "novel_id", name="uq_story_scene_script_file_id_novel"),
    )
    op.create_index(
        "ix_story_scene_script_file_novel_scene",
        "story_scene_script_files",
        ["novel_id", "scene_id"],
    )

    op.create_table(
        "story_scene_script_revisions",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("novel_id", uuid_type, nullable=False),
        sa.Column("file_id", uuid_type, nullable=False),
        sa.Column("scene_id", uuid_type, nullable=False),
        sa.Column("file_key", sa.String(64), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_json", json_type, nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(32), nullable=False, server_default="candidate"),
        sa.Column("authorization_ref", sa.String(255), nullable=True),
        sa.Column("provenance_json", json_type, nullable=False),
        sa.Column("source_task_id", uuid_type, nullable=True),
        sa.Column("context_snapshot_id", uuid_type, nullable=True),
        sa.Column("base_revision_id", uuid_type, nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "novel_id",
            "file_id",
            "version_number",
            name="uq_story_scene_script_revision_version",
        ),
        sa.UniqueConstraint(
            "id", "novel_id", name="uq_story_scene_script_revision_id_novel"
        ),
    )
    op.create_index(
        "ix_story_scene_script_revision_novel_file",
        "story_scene_script_revisions",
        ["novel_id", "file_id", "version_number"],
    )
    op.create_foreign_key(
        "fk_story_scene_script_revision_file_novel",
        "story_scene_script_revisions",
        "story_scene_script_files",
        ["file_id", "novel_id"],
        ["id", "novel_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_story_scene_script_file_current_novel",
        "story_scene_script_files",
        "story_scene_script_revisions",
        ["current_revision_id", "novel_id"],
        ["id", "novel_id"],
    )
    op.create_foreign_key(
        "fk_story_scene_script_file_adopted_novel",
        "story_scene_script_files",
        "story_scene_script_revisions",
        ["adopted_revision_id", "novel_id"],
        ["id", "novel_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_story_scene_script_file_adopted_novel",
        "story_scene_script_files",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_story_scene_script_file_current_novel",
        "story_scene_script_files",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_story_scene_script_revision_file_novel",
        "story_scene_script_revisions",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_story_scene_script_revision_novel_file",
        table_name="story_scene_script_revisions",
    )
    op.drop_table("story_scene_script_revisions")
    op.drop_index(
        "ix_story_scene_script_file_novel_scene", table_name="story_scene_script_files"
    )
    op.drop_table("story_scene_script_files")
    op.drop_constraint(
        "fk_story_character_card_current_novel",
        "story_character_cards",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_story_character_card_revision_card_novel",
        "story_character_card_revisions",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_story_character_card_revisions_novel_card",
        table_name="story_character_card_revisions",
    )
    op.drop_table("story_character_card_revisions")
    op.drop_index(
        "ix_story_character_cards_novel_scene_character",
        table_name="story_character_cards",
    )
    op.drop_index(
        "ix_story_character_cards_novel_status", table_name="story_character_cards"
    )
    op.drop_table("story_character_cards")
