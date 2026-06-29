"""add writing scene conflict checks

Revision ID: f20260629
Revises: 20260629_map_dynamic_facts
Create Date: 2026-06-29 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f20260629"
down_revision: str | None = "20260629_map_dynamic_facts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "writing_drafts",
        sa.Column(
            "conflict_check_snapshot_json",
            sa.JSON(),
            nullable=True,
            comment="发布时归档的最近一次冲突检查快照",
        ),
    )
    op.create_table(
        "writing_conflict_checks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "novel_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chapter_index", sa.Integer(), nullable=False),
        sa.Column("scene_id", sa.UUID(), nullable=True),
        sa.Column(
            "draft_id",
            sa.UUID(),
            sa.ForeignKey("writing_drafts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("version_number", sa.Integer(), nullable=True),
        sa.Column("scope", sa.JSON(), nullable=False),
        sa.Column("include_candidates", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.timezone("utc", sa.func.now()),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.timezone("utc", sa.func.now()),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="写作页剧情设定冲突检查记录",
    )
    op.create_index(
        "ix_writing_conflict_checks_novel_id",
        "writing_conflict_checks",
        ["novel_id"],
    )
    op.create_index(
        "ix_writing_conflict_checks_chapter_index",
        "writing_conflict_checks",
        ["chapter_index"],
    )
    op.create_index(
        "ix_writing_conflict_checks_scene_id",
        "writing_conflict_checks",
        ["scene_id"],
    )
    op.create_index(
        "ix_writing_conflict_checks_status",
        "writing_conflict_checks",
        ["status"],
    )
    op.create_index(
        "ix_writing_conflict_checks_scope",
        "writing_conflict_checks",
        ["novel_id", "chapter_index", "scene_id", "created_at"],
    )

    op.create_table(
        "writing_conflict_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "novel_id",
            sa.UUID(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "check_id",
            sa.UUID(),
            sa.ForeignKey("writing_conflict_checks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("source_module", sa.String(32), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=True),
        sa.Column("source_id", sa.String(128), nullable=True),
        sa.Column("evidence_summary", sa.Text(), nullable=False),
        sa.Column("location_json", sa.JSON(), nullable=True),
        sa.Column("is_ai_judgment", sa.Boolean(), nullable=False),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("ai_suggestion", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.timezone("utc", sa.func.now()),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.timezone("utc", sa.func.now()),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="写作页剧情设定冲突检查问题项",
    )
    op.create_index(
        "ix_writing_conflict_items_novel_id",
        "writing_conflict_items",
        ["novel_id"],
    )
    op.create_index(
        "ix_writing_conflict_items_check_id",
        "writing_conflict_items",
        ["check_id"],
    )
    op.create_index(
        "ix_writing_conflict_items_kind",
        "writing_conflict_items",
        ["kind"],
    )
    op.create_index(
        "ix_writing_conflict_items_severity",
        "writing_conflict_items",
        ["severity"],
    )
    op.create_index(
        "ix_writing_conflict_items_status",
        "writing_conflict_items",
        ["status"],
    )
    op.create_index(
        "ix_writing_conflict_items_novel_status",
        "writing_conflict_items",
        ["novel_id", "status"],
    )


def downgrade() -> None:
    op.drop_table("writing_conflict_items", if_exists=True)
    op.drop_table("writing_conflict_checks", if_exists=True)
    op.drop_column("writing_drafts", "conflict_check_snapshot_json")
