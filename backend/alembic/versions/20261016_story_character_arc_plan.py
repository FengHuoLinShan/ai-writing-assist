"""Add Story-owned author-confirmed director-only character arc plans.

Revision ID: 20261016_story_character_arc_plan
Revises: 20261016_wp_read_count
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261016_story_character_arc_plan"
down_revision: str | None = "20261016_wp_read_count"
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
        "story_character_arc_plan_heads",
        *_identity_columns(),
        sa.Column("character_id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("current_revision_id", sa.UUID(), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.UUID(), nullable=True),
        sa.CheckConstraint(
            "version_number >= 0",
            name="ck_story_character_arc_plan_head_version",
        ),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "novel_id", "character_id", name="uq_story_character_arc_plan_character"
        ),
        sa.UniqueConstraint(
            "novel_id", "id", name="uq_story_character_arc_plan_head_novel"
        ),
    )
    op.create_index(
        "ix_story_character_arc_plan_heads_novel_id",
        "story_character_arc_plan_heads",
        ["novel_id"],
    )
    op.create_index(
        "ix_story_character_arc_plan_heads_character_id",
        "story_character_arc_plan_heads",
        ["character_id"],
    )
    op.create_index(
        "ix_story_character_arc_plan_heads_owner_id",
        "story_character_arc_plan_heads",
        ["owner_id"],
    )
    op.create_index(
        "ix_story_character_arc_plan_novel_character",
        "story_character_arc_plan_heads",
        ["novel_id", "character_id"],
    )

    op.create_table(
        "story_character_arc_plan_revisions",
        *_identity_columns(),
        sa.Column("head_id", sa.UUID(), nullable=False),
        sa.Column("character_id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("plan_text", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("audience", sa.String(length=32), nullable=False),
        sa.Column("operation_id", sa.UUID(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("base_revision_id", sa.UUID(), nullable=True),
        sa.Column("restored_from_revision_id", sa.UUID(), nullable=True),
        sa.CheckConstraint(
            "version_number >= 1", name="ck_story_arc_plan_revision_version"
        ),
        sa.CheckConstraint(
            "source IN ('author_confirmed', 'author_restore', "
            "'author_archive', 'author_unarchive')",
            name="ck_story_character_arc_plan_revision_source",
        ),
        sa.CheckConstraint(
            "audience = 'director_only'",
            name="ck_story_character_arc_plan_director_only",
        ),
        sa.CheckConstraint(
            "length(request_hash) = 64 AND length(content_hash) = 64",
            name="ck_story_character_arc_plan_hashes",
        ),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["novel_id", "head_id"],
            [
                "story_character_arc_plan_heads.novel_id",
                "story_character_arc_plan_heads.id",
            ],
            ondelete="CASCADE",
            name="fk_story_character_arc_plan_revision_head",
        ),
        sa.ForeignKeyConstraint(
            ["novel_id", "base_revision_id"],
            [
                "story_character_arc_plan_revisions.novel_id",
                "story_character_arc_plan_revisions.id",
            ],
            name="fk_story_character_arc_plan_revision_base",
        ),
        sa.ForeignKeyConstraint(
            ["novel_id", "restored_from_revision_id"],
            [
                "story_character_arc_plan_revisions.novel_id",
                "story_character_arc_plan_revisions.id",
            ],
            name="fk_story_character_arc_plan_revision_restored_from",
        ),
        sa.UniqueConstraint(
            "novel_id",
            "head_id",
            "version_number",
            name="uq_story_character_arc_plan_revision_version",
        ),
        sa.UniqueConstraint(
            "novel_id",
            "character_id",
            "operation_id",
            name="uq_story_character_arc_plan_operation",
        ),
        sa.UniqueConstraint(
            "novel_id", "id", name="uq_story_character_arc_plan_revision_novel"
        ),
    )
    op.create_index(
        "ix_story_character_arc_plan_revisions_novel_id",
        "story_character_arc_plan_revisions",
        ["novel_id"],
    )
    op.create_index(
        "ix_story_character_arc_plan_revisions_head_id",
        "story_character_arc_plan_revisions",
        ["head_id"],
    )
    op.create_index(
        "ix_story_character_arc_plan_revisions_character_id",
        "story_character_arc_plan_revisions",
        ["character_id"],
    )
    op.create_index(
        "ix_story_character_arc_plan_revisions_owner_id",
        "story_character_arc_plan_revisions",
        ["owner_id"],
    )
    op.create_index(
        "ix_story_character_arc_plan_revision_history",
        "story_character_arc_plan_revisions",
        ["novel_id", "character_id", "version_number"],
    )
    op.create_foreign_key(
        "fk_story_character_arc_plan_head_current_revision",
        "story_character_arc_plan_heads",
        "story_character_arc_plan_revisions",
        ["novel_id", "current_revision_id"],
        ["novel_id", "id"],
    )

    op.execute(
        """CREATE FUNCTION reject_story_character_arc_plan_revision_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
        IF TG_OP = 'DELETE' AND pg_trigger_depth() > 1 THEN
            RETURN OLD;
        END IF;
        RAISE EXCEPTION 'Story character arc plan revisions are immutable';
        END $$"""
    )
    op.execute(
        """CREATE TRIGGER story_character_arc_plan_revisions_immutable
        BEFORE UPDATE OR DELETE ON story_character_arc_plan_revisions
        FOR EACH ROW
        EXECUTE FUNCTION reject_story_character_arc_plan_revision_mutation()
        """
    )
    op.execute(
        """CREATE FUNCTION reject_story_character_arc_plan_head_delete()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
        IF pg_trigger_depth() > 1 THEN
            RETURN OLD;
        END IF;
        RAISE EXCEPTION 'Story character arc plan heads are soft-deleted';
        END $$"""
    )
    op.execute(
        """CREATE TRIGGER story_character_arc_plan_heads_soft_delete
        BEFORE DELETE ON story_character_arc_plan_heads
        FOR EACH ROW EXECUTE FUNCTION reject_story_character_arc_plan_head_delete()"""
    )


def downgrade() -> None:
    connection = op.get_bind()
    count = connection.execute(
        sa.text("SELECT COUNT(*) FROM story_character_arc_plan_revisions")
    ).scalar_one()
    if count:
        raise RuntimeError(
            "Character arc plan revisions are author history; "
            "export and remove them before downgrade"
        )
    op.execute(
        "DROP TRIGGER story_character_arc_plan_heads_soft_delete "
        "ON story_character_arc_plan_heads"
    )
    op.execute("DROP FUNCTION reject_story_character_arc_plan_head_delete()")
    op.execute(
        "DROP TRIGGER story_character_arc_plan_revisions_immutable "
        "ON story_character_arc_plan_revisions"
    )
    op.execute("DROP FUNCTION reject_story_character_arc_plan_revision_mutation()")
    op.drop_constraint(
        "fk_story_character_arc_plan_head_current_revision",
        "story_character_arc_plan_heads",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_story_character_arc_plan_revision_history",
        table_name="story_character_arc_plan_revisions",
    )
    for name in (
        "ix_story_character_arc_plan_revisions_owner_id",
        "ix_story_character_arc_plan_revisions_character_id",
        "ix_story_character_arc_plan_revisions_head_id",
        "ix_story_character_arc_plan_revisions_novel_id",
    ):
        op.drop_index(name, table_name="story_character_arc_plan_revisions")
    op.drop_table("story_character_arc_plan_revisions")
    for name in (
        "ix_story_character_arc_plan_novel_character",
        "ix_story_character_arc_plan_heads_owner_id",
        "ix_story_character_arc_plan_heads_character_id",
        "ix_story_character_arc_plan_heads_novel_id",
    ):
        op.drop_index(name, table_name="story_character_arc_plan_heads")
    op.drop_table("story_character_arc_plan_heads")
