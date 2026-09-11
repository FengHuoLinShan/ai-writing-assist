"""Repair schema invariants skipped by older live-metadata baselines.

Revision ID: 20260913_schema_parity_repair
Revises: 20260912_web_search_consent
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260913_schema_parity_repair"
down_revision = "20260912_web_search_consent"
branch_labels = None
depends_on = None


def _names(items: list[dict[str, object]]) -> set[str]:
    return {str(item["name"]) for item in items if item.get("name")}


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    inspector = sa.inspect(bind)
    task_checks = _names(inspector.get_check_constraints("project_author_tasks"))
    if "ck_project_author_tasks_title_not_blank" not in task_checks:
        op.create_check_constraint(
            "ck_project_author_tasks_title_not_blank",
            "project_author_tasks",
            "length(trim(title)) > 0",
        )
    if "ck_project_author_tasks_note_length" not in task_checks:
        op.create_check_constraint(
            "ck_project_author_tasks_note_length",
            "project_author_tasks",
            "note IS NULL OR length(note) <= 4000",
        )

    revision_uniques = _names(
        inspector.get_unique_constraints("story_outline_revisions")
    )
    if "uq_story_outline_revision_id_novel" not in revision_uniques:
        op.create_unique_constraint(
            "uq_story_outline_revision_id_novel",
            "story_outline_revisions",
            ["id", "novel_id"],
        )

    foreign_keys = {
        "story_outline_revisions": (
            (
                "base_revision_id",
                "fk_story_outline_revision_base_novel",
            ),
            (
                "restored_from_revision_id",
                "fk_story_outline_revision_restored_novel",
            ),
        ),
        "story_outline_heads": (
            (
                "current_revision_id",
                "fk_story_outline_head_current_novel",
            ),
        ),
    }
    for table, repairs in foreign_keys.items():
        existing = inspector.get_foreign_keys(table)
        existing_names = _names(existing)
        for column, canonical_name in repairs:
            for foreign_key in existing:
                if foreign_key.get("constrained_columns") == [column]:
                    op.drop_constraint(
                        str(foreign_key["name"]),
                        table,
                        type_="foreignkey",
                    )
            if canonical_name not in existing_names:
                op.create_foreign_key(
                    canonical_name,
                    table,
                    "story_outline_revisions",
                    [column, "novel_id"],
                    ["id", "novel_id"],
                )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_story_outline_revision_update()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'story_outline_revisions are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_story_outline_revision_immutable "
        "ON story_outline_revisions"
    )
    op.execute(
        """
        CREATE TRIGGER trg_story_outline_revision_immutable
        BEFORE UPDATE ON story_outline_revisions
        FOR EACH ROW EXECUTE FUNCTION reject_story_outline_revision_update()
        """
    )


def downgrade() -> None:
    # This migration restores constraints that predate it. Removing them on
    # downgrade would recreate the drift it repairs.
    pass
