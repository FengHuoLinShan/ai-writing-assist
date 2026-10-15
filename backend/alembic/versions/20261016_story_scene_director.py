"""Persist isolated Scene Director roots, branches, immutable rounds and references.

Revision ID: 20261016_story_scene_director
Revises: 20261015_operation_trace_v2
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261016_story_scene_director"
down_revision: str | None = "20261015_operation_trace_v2"
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
        "story_scene_director_roots",
        *_identity_columns(),
        sa.Column("scene_id", sa.UUID(), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("llm_execution_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("run_envelope_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("current_task_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("novel_id", "id", name="uq_story_scene_director_root_novel"),
    )
    op.create_index(
        "ix_story_scene_director_root_scene",
        "story_scene_director_roots",
        ["novel_id", "scene_id", "created_at"],
    )

    op.create_table(
        "story_scene_director_branches",
        *_identity_columns(),
        sa.Column("root_id", sa.UUID(), nullable=False),
        sa.Column("parent_round_id", sa.UUID(), nullable=True),
        sa.Column("branch_kind", sa.String(length=24), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("pending_round_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=180), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("starred", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("restore_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_task_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["novel_id", "root_id"],
            ["story_scene_director_roots.novel_id", "story_scene_director_roots.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("novel_id", "id", name="uq_story_scene_director_branch_novel"),
    )
    op.create_index(
        "ix_story_scene_director_branch_root",
        "story_scene_director_branches",
        ["novel_id", "root_id", "created_at"],
    )

    op.create_table(
        "story_scene_director_rounds",
        *_identity_columns(),
        sa.Column("root_id", sa.UUID(), nullable=False),
        sa.Column("branch_id", sa.UUID(), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("parent_round_id", sa.UUID(), nullable=True),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("output_hash", sa.String(length=64), nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("output_json", sa.JSON(), nullable=False),
        sa.Column("state_json", sa.JSON(), nullable=False),
        sa.Column("run_envelope_json", sa.JSON(), nullable=False),
        sa.Column("name", sa.String(length=180), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("starred", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["novel_id", "branch_id"],
            ["story_scene_director_branches.novel_id", "story_scene_director_branches.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("novel_id", "id", name="uq_story_scene_director_round_novel"),
        sa.UniqueConstraint(
            "novel_id",
            "branch_id",
            "round_number",
            name="uq_story_scene_director_round_number",
        ),
    )
    op.create_index(
        "ix_story_scene_director_round_root",
        "story_scene_director_rounds",
        ["novel_id", "root_id", "created_at"],
    )
    op.execute(
        """CREATE FUNCTION reject_story_scene_director_round_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
        IF TG_OP = 'DELETE' AND pg_trigger_depth() > 1 THEN
            RETURN OLD;
        END IF;
        IF TG_OP = 'UPDATE' AND
           (to_jsonb(NEW) - ARRAY['name', 'note', 'starred', 'updated_at']) =
           (to_jsonb(OLD) - ARRAY['name', 'note', 'starred', 'updated_at']) THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'completed Scene Director rounds are immutable'; END $$"""
    )
    op.execute(
        """CREATE TRIGGER story_scene_director_rounds_immutable
        BEFORE UPDATE OR DELETE ON story_scene_director_rounds
        FOR EACH ROW EXECUTE FUNCTION reject_story_scene_director_round_mutation()"""
    )

    op.create_table(
        "story_scene_director_references",
        *_identity_columns(),
        # Root and source round identities are weak references: the copied
        # reference must survive independent deletion/purge of its source tree.
        sa.Column("root_id", sa.UUID(), nullable=False),
        sa.Column("scene_id", sa.UUID(), nullable=False),
        sa.Column("source_round_id", sa.UUID(), nullable=True),
        sa.Column("source_basis_hash", sa.String(length=64), nullable=False),
        sa.Column("source_deleted", sa.Boolean(), nullable=False),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("content_copy_json", sa.JSON(), nullable=False),
        sa.Column("material_ids_json", sa.JSON(), nullable=False),
        sa.Column("angle_json", sa.JSON(), nullable=False),
        sa.Column("annotation", sa.Text(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("restore_until", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "novel_id", "id", name="uq_story_scene_director_reference_novel"
        ),
    )
    op.create_index(
        "ix_story_scene_director_reference_scene",
        "story_scene_director_references",
        ["novel_id", "scene_id", "created_at"],
    )

    op.create_table(
        "story_scene_director_preferences",
        *_identity_columns(),
        sa.Column("cliche_phrases_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("novel_id", name="uq_story_scene_director_preference_novel"),
    )


def downgrade() -> None:
    op.drop_table("story_scene_director_preferences")
    op.drop_index(
        "ix_story_scene_director_reference_scene",
        table_name="story_scene_director_references",
    )
    op.drop_table("story_scene_director_references")
    op.execute("DROP TRIGGER story_scene_director_rounds_immutable ON story_scene_director_rounds")
    op.drop_index(
        "ix_story_scene_director_round_root",
        table_name="story_scene_director_rounds",
    )
    op.drop_table("story_scene_director_rounds")
    op.execute("DROP FUNCTION reject_story_scene_director_round_mutation()")
    op.drop_index(
        "ix_story_scene_director_branch_root",
        table_name="story_scene_director_branches",
    )
    op.drop_table("story_scene_director_branches")
    op.drop_index(
        "ix_story_scene_director_root_scene",
        table_name="story_scene_director_roots",
    )
    op.drop_table("story_scene_director_roots")
