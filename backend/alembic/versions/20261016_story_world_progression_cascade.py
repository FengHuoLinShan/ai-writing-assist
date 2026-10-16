"""Allow project deletion to cascade through immutable progression history.

Revision ID: 20261016_wp_cascade
Revises: 20261016_story_world_progression
Create Date: 2026-10-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261016_wp_cascade"
down_revision: str | None = "20261016_story_world_progression"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_story_world_progression_step_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            -- Parent-project deletion is the one allowed physical cleanup path.
            IF TG_OP = 'DELETE' AND pg_trigger_depth() > 1 THEN
                RETURN OLD;
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
            RAISE EXCEPTION 'world progression steps are immutable';
        END;
        $$
        """
    )
