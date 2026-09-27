"""Align hand-written migrations with the declared ORM schema.

Revision ID: 20260928_schema_drift_repair
Revises: 20260927_guimi_editorial_merge
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260928_schema_drift_repair"
down_revision = "20260927_guimi_editorial_merge"
branch_labels = None
depends_on = None

_MISSING_INDEXES = {
    "story_character_cards": ("character_id", "novel_id", "scene_id", "status"),
    "story_character_card_revisions": (
        "card_id",
        "character_id",
        "novel_id",
        "scene_id",
        "status",
    ),
    "story_scene_script_files": ("novel_id", "scene_id", "status"),
    "story_scene_script_revisions": ("file_id", "novel_id", "scene_id", "status"),
    "world_library_topics": ("status",),
}
_CREATED_AT_REQUIRED = (
    "memory_scene_checkpoints",
    "memory_scene_snapshots",
    "story_character_card_revisions",
    "story_character_cards",
    "story_scene_script_files",
    "story_scene_script_revisions",
)
# TimestampMixin declares updated_at nullable; these tables were created stricter.
_UPDATED_AT_OPTIONAL = (
    "demo_project_copies",
    "interaction_openings",
    "project_author_tasks",
    "world_validation_review_items",
    "world_validation_runs",
    "writing_comments",
)
# Duplicates uq_story_character_card_novel_character on the same columns.
_REDUNDANT_CARD_INDEX = "ix_story_character_cards_novel_scene_character"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    for table, columns in _MISSING_INDEXES.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column], if_not_exists=True)
    op.drop_index(
        _REDUNDANT_CARD_INDEX, table_name="story_character_cards", if_exists=True
    )

    recents_fks = sa.inspect(bind).get_foreign_keys("world_library_recents")
    if not any(
        fk["constrained_columns"] == ["novel_id"] and fk["referred_table"] == "projects"
        for fk in recents_fks
    ):
        # Rows of permanently deleted projects were never cascaded away.
        op.execute(
            "DELETE FROM world_library_recents AS recent WHERE NOT EXISTS "
            "(SELECT 1 FROM projects WHERE projects.id = recent.novel_id)"
        )
        op.create_foreign_key(
            "world_library_recents_novel_id_fkey",
            "world_library_recents",
            "projects",
            ["novel_id"],
            ["id"],
            ondelete="CASCADE",
        )

    for table in _CREATED_AT_REQUIRED:
        fallback = (
            "COALESCE(updated_at, timezone('utc', now()))"
            if table.startswith("story_")
            else "timezone('utc', now())"
        )
        op.execute(f"UPDATE {table} SET created_at = {fallback} WHERE created_at IS NULL")
        op.alter_column(table, "created_at", nullable=False)
    for table in _UPDATED_AT_OPTIONAL:
        op.alter_column(table, "updated_at", nullable=True)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    # Earlier downgrades drop this index by name; the other repairs restore
    # declared invariants and are intentionally kept.
    op.create_index(
        _REDUNDANT_CARD_INDEX,
        "story_character_cards",
        ["novel_id", "scene_id", "character_id"],
        if_not_exists=True,
    )
