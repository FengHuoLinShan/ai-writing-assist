"""Restrict immutable step cleanup to the owning project's deletion.

Revision ID: 20261016_wp_cascade_guard
Revises: 20261016_wp_cascade
Create Date: 2026-10-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261016_wp_cascade_guard"
down_revision: str | None = "20261016_wp_cascade"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_story_world_progression_step_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE project_deleted boolean;
        BEGIN
            IF TG_OP = 'DELETE' AND pg_trigger_depth() > 1 THEN
                EXECUTE format(
                    'SELECT NOT EXISTS (SELECT 1 FROM %I.projects WHERE id = $1)',
                    TG_TABLE_SCHEMA
                ) INTO project_deleted USING OLD.novel_id;
                IF project_deleted THEN RETURN OLD; END IF;
            END IF;
            RAISE EXCEPTION 'world progression steps are immutable';
        END;
        $$
        """
    )


def downgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_story_world_progression_step_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND pg_trigger_depth() > 1 THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'world progression steps are immutable';
        END;
        $$
        """
    )
