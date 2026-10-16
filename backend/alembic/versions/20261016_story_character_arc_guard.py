"""Allow immutable arc history cleanup only after its real Project is deleted.

Revision ID: 20261016_story_arc_guard
Revises: 20261016_story_character_arc_plan
Create Date: 2026-10-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261016_story_arc_guard"
down_revision: str | None = "20261016_story_character_arc_plan"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_story_character_arc_plan_revision_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE project_deleted boolean;
        BEGIN
            IF TG_OP = 'DELETE' AND pg_trigger_depth() > 1 THEN
                -- Qualify the real table's schema: a TEMP projects table or
                -- search_path change cannot impersonate Project deletion.
                EXECUTE format(
                    'SELECT NOT EXISTS (SELECT 1 FROM %I.projects WHERE id = $1)',
                    TG_TABLE_SCHEMA
                ) INTO project_deleted USING OLD.novel_id;
                IF project_deleted THEN RETURN OLD; END IF;
            END IF;
            RAISE EXCEPTION 'Story character arc plan revisions are immutable';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_story_character_arc_plan_head_delete()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE project_deleted boolean;
        BEGIN
            IF pg_trigger_depth() > 1 THEN
                EXECUTE format(
                    'SELECT NOT EXISTS (SELECT 1 FROM %I.projects WHERE id = $1)',
                    TG_TABLE_SCHEMA
                ) INTO project_deleted USING OLD.novel_id;
                IF project_deleted THEN RETURN OLD; END IF;
            END IF;
            RAISE EXCEPTION 'Story character arc plan heads are soft-deleted';
        END;
        $$
        """
    )


def downgrade() -> None:
    # Restore the preceding revision's behavior exactly. A downgrade of the
    # guard is unsafe for retained history and should not be used in service.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_story_character_arc_plan_revision_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
        IF TG_OP = 'DELETE' AND pg_trigger_depth() > 1 THEN RETURN OLD; END IF;
        RAISE EXCEPTION 'Story character arc plan revisions are immutable';
        END $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_story_character_arc_plan_head_delete()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
        IF pg_trigger_depth() > 1 THEN RETURN OLD; END IF;
        RAISE EXCEPTION 'Story character arc plan heads are soft-deleted';
        END $$
        """
    )
