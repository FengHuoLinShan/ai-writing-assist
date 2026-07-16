"""add immutable StoryOutline revisions and per-project heads

Revision ID: 20260716_story_outline
Revises: 20260715_world_bible_v2
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "20260716_story_outline"
down_revision = "20260715_world_bible_v2"
branch_labels = None
depends_on = None


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


def _install_immutability_guard() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
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
        return
    if bind.dialect.name == "sqlite":
        op.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_story_outline_revision_immutable
            BEFORE UPDATE ON story_outline_revisions
            BEGIN
                SELECT RAISE(ABORT, 'story_outline_revisions are immutable');
            END
            """
        )


def upgrade() -> None:
    tables = _tables()
    if "story_outline_revisions" not in tables:
        op.create_table(
            "story_outline_revisions",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "novel_id",
                UUID(as_uuid=True),
                sa.ForeignKey("projects.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("creative_core_json", sa.JSON(), nullable=False),
            sa.Column("outline_markdown", sa.Text(), nullable=False),
            sa.Column("major_storylines_json", sa.JSON(), nullable=False),
            sa.Column("macro_movements_json", sa.JSON(), nullable=False),
            sa.Column("open_decisions_json", sa.JSON(), nullable=False),
            sa.Column("source", sa.String(32), nullable=False),
            sa.Column("provenance_json", sa.JSON(), nullable=False),
            sa.Column(
                "base_revision_id",
                UUID(as_uuid=True),
                nullable=True,
            ),
            sa.Column(
                "restored_from_revision_id",
                UUID(as_uuid=True),
                nullable=True,
            ),
            sa.Column("idempotency_key", sa.String(128), nullable=False),
            sa.Column("request_hash", sa.String(64), nullable=False),
            sa.Column("content_hash", sa.String(64), nullable=False),
            *_timestamps(),
            sa.UniqueConstraint(
                "novel_id",
                "version_number",
                name="uq_story_outline_revision_version",
            ),
            sa.UniqueConstraint(
                "novel_id",
                "idempotency_key",
                name="uq_story_outline_revision_idempotency",
            ),
            sa.UniqueConstraint(
                "id",
                "novel_id",
                name="uq_story_outline_revision_id_novel",
            ),
            sa.ForeignKeyConstraint(
                ["base_revision_id", "novel_id"],
                ["story_outline_revisions.id", "story_outline_revisions.novel_id"],
                name="fk_story_outline_revision_base_novel",
            ),
            sa.ForeignKeyConstraint(
                ["restored_from_revision_id", "novel_id"],
                ["story_outline_revisions.id", "story_outline_revisions.novel_id"],
                name="fk_story_outline_revision_restored_novel",
            ),
        )
        op.create_index(
            "ix_story_outline_revisions_novel_id",
            "story_outline_revisions",
            ["novel_id"],
        )
        op.create_index(
            "ix_story_outline_revisions_novel_version",
            "story_outline_revisions",
            ["novel_id", "version_number"],
        )

    if "story_outline_heads" not in tables:
        op.create_table(
            "story_outline_heads",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "novel_id",
                UUID(as_uuid=True),
                sa.ForeignKey("projects.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "current_revision_id",
                UUID(as_uuid=True),
                nullable=True,
            ),
            *_timestamps(),
            sa.UniqueConstraint(
                "novel_id",
                name="uq_story_outline_head_novel",
            ),
            sa.ForeignKeyConstraint(
                ["current_revision_id", "novel_id"],
                ["story_outline_revisions.id", "story_outline_revisions.novel_id"],
                name="fk_story_outline_head_current_novel",
            ),
        )
        op.create_index(
            "ix_story_outline_heads_novel_id",
            "story_outline_heads",
            ["novel_id"],
        )

    _install_immutability_guard()


def downgrade() -> None:
    tables = _tables()
    bind = op.get_bind()
    if "story_outline_revisions" in tables:
        if bind.dialect.name == "postgresql":
            op.execute(
                "DROP TRIGGER IF EXISTS trg_story_outline_revision_immutable "
                "ON story_outline_revisions"
            )
            op.execute("DROP FUNCTION IF EXISTS reject_story_outline_revision_update()")
        elif bind.dialect.name == "sqlite":
            op.execute("DROP TRIGGER IF EXISTS trg_story_outline_revision_immutable")
    if "story_outline_heads" in tables:
        op.drop_table("story_outline_heads")
    if "story_outline_revisions" in tables:
        op.drop_table("story_outline_revisions")
