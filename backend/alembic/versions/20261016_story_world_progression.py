"""Persist Story world-progression roots, branches, immutable steps, and consent.

Revision ID: 20261016_story_world_progression
Revises: 20261016_story_director_candidate_transfer
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261016_story_world_progression"
down_revision: str | None = "20261016_story_director_candidate_transfer"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _identity_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column("novel_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.timezone("utc", sa.func.now()),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.timezone("utc", sa.func.now()),
            nullable=True,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "story_world_progression_roots",
        *_identity_columns(),
        sa.Column("scene_id", sa.UUID(), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("source_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("llm_execution_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("run_envelope_json", sa.JSON(), nullable=False),
        sa.Column("context_confirmation_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("current_task_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "novel_id", "id", name="uq_story_world_progression_root_novel"
        ),
    )
    op.create_index(
        "ix_story_world_progression_root_scene",
        "story_world_progression_roots",
        ["novel_id", "scene_id", "created_at"],
    )

    op.create_table(
        "story_world_progression_branches",
        *_identity_columns(),
        sa.Column("root_id", sa.UUID(), nullable=False),
        sa.Column("parent_step_id", sa.UUID(), nullable=True),
        sa.Column("branch_kind", sa.String(length=24), nullable=False),
        sa.Column("basis_choice", sa.String(length=16), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("source_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("pending_step_json", sa.JSON(), nullable=False),
        sa.Column("stop_reason", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=180), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("starred", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("restore_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_task_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["novel_id", "root_id"],
            [
                "story_world_progression_roots.novel_id",
                "story_world_progression_roots.id",
            ],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "novel_id", "id", name="uq_story_world_progression_branch_novel"
        ),
    )
    op.create_index(
        "ix_story_world_progression_branch_root",
        "story_world_progression_branches",
        ["novel_id", "root_id", "created_at"],
    )

    op.create_table(
        "story_world_progression_steps",
        *_identity_columns(),
        sa.Column("root_id", sa.UUID(), nullable=False),
        sa.Column("branch_id", sa.UUID(), nullable=False),
        sa.Column("parent_step_id", sa.UUID(), nullable=True),
        sa.Column("step_number", sa.Integer(), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("output_hash", sa.String(length=64), nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("state_json", sa.JSON(), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        sa.Column("basis_changed", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["novel_id", "root_id"],
            [
                "story_world_progression_roots.novel_id",
                "story_world_progression_roots.id",
            ],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["novel_id", "branch_id"],
            [
                "story_world_progression_branches.novel_id",
                "story_world_progression_branches.id",
            ],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["novel_id", "parent_step_id"],
            [
                "story_world_progression_steps.novel_id",
                "story_world_progression_steps.id",
            ],
        ),
        sa.UniqueConstraint(
            "novel_id", "id", name="uq_story_world_progression_step_novel"
        ),
        sa.UniqueConstraint(
            "novel_id",
            "branch_id",
            "step_number",
            name="uq_story_world_progression_step_number",
        ),
    )
    op.create_index(
        "ix_story_world_progression_step_branch",
        "story_world_progression_steps",
        ["novel_id", "branch_id", "step_number"],
    )
    op.create_foreign_key(
        "fk_story_world_progression_branch_parent_step",
        "story_world_progression_branches",
        "story_world_progression_steps",
        ["novel_id", "parent_step_id"],
        ["novel_id", "id"],
    )

    op.create_table(
        "story_world_progression_authorizations",
        *_identity_columns(),
        sa.Column("root_id", sa.UUID(), nullable=True),
        sa.Column("branch_id", sa.UUID(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("participant_ids_json", sa.JSON(), nullable=False),
        sa.Column("every_new_chapters", sa.Integer(), nullable=False),
        sa.Column("last_seen_chapter", sa.Integer(), nullable=False),
        sa.Column("context_confirmation_id", sa.String(length=128), nullable=True),
        sa.Column("trigger_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["novel_id", "root_id"],
            [
                "story_world_progression_roots.novel_id",
                "story_world_progression_roots.id",
            ],
        ),
        sa.ForeignKeyConstraint(
            ["novel_id", "branch_id"],
            [
                "story_world_progression_branches.novel_id",
                "story_world_progression_branches.id",
            ],
        ),
        sa.UniqueConstraint(
            "novel_id", name="uq_story_world_progression_authorization_novel"
        ),
    )

    for table in (
        "story_world_progression_roots",
        "story_world_progression_branches",
        "story_world_progression_steps",
        "story_world_progression_authorizations",
    ):
        op.create_index(f"ix_{table}_novel_id", table, ["novel_id"])

    op.execute(
        """
        CREATE FUNCTION reject_story_world_progression_step_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'world progression steps are immutable';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER story_world_progression_steps_immutable
        BEFORE UPDATE OR DELETE ON story_world_progression_steps
        FOR EACH ROW EXECUTE FUNCTION reject_story_world_progression_step_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER story_world_progression_steps_immutable "
        "ON story_world_progression_steps"
    )
    op.drop_index(
        "ix_story_world_progression_authorizations_novel_id",
        table_name="story_world_progression_authorizations",
    )
    op.drop_table("story_world_progression_authorizations")
    op.drop_constraint(
        "fk_story_world_progression_branch_parent_step",
        "story_world_progression_branches",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_story_world_progression_steps_novel_id",
        table_name="story_world_progression_steps",
    )
    op.drop_index(
        "ix_story_world_progression_step_branch",
        table_name="story_world_progression_steps",
    )
    op.drop_table("story_world_progression_steps")
    op.execute("DROP FUNCTION reject_story_world_progression_step_mutation()")
    op.drop_index(
        "ix_story_world_progression_branches_novel_id",
        table_name="story_world_progression_branches",
    )
    op.drop_index(
        "ix_story_world_progression_branch_root",
        table_name="story_world_progression_branches",
    )
    op.drop_table("story_world_progression_branches")
    op.drop_index(
        "ix_story_world_progression_roots_novel_id",
        table_name="story_world_progression_roots",
    )
    op.drop_index(
        "ix_story_world_progression_root_scene",
        table_name="story_world_progression_roots",
    )
    op.drop_table("story_world_progression_roots")
