"""Saved manuscript comments anchored to exact ranges.

Revision ID: 20260924_writing_comments
Revises: 20260922_evolution_reading
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260924_writing_comments"
down_revision = "20260922_evolution_reading"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "writing_comments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("timezone('utc', now())"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("timezone('utc', now())"),
        ),
        sa.Column(
            "draft_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("writing_drafts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chapter_index", sa.Integer(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("range_hash", sa.String(64), nullable=True),
        sa.Column("start_offset", sa.Integer(), nullable=True),
        sa.Column("end_offset", sa.Integer(), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("origin", sa.String(16), nullable=False),
        sa.Column("severity", sa.String(16), nullable=True),
        sa.Column("review_task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("finding_id", sa.String(80), nullable=True),
        sa.Column("last_run_task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.UniqueConstraint(
            "review_task_id", "finding_id", name="uq_writing_comment_finding"
        ),
        sa.CheckConstraint(
            "(start_offset IS NULL AND end_offset IS NULL) OR "
            "(start_offset >= 0 AND end_offset > start_offset)",
            name="ck_writing_comment_range",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'resolved')", name="ck_writing_comment_status"
        ),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_writing_comments_novel_id", "writing_comments", ["novel_id"])
    op.create_index(
        "ix_writing_comments_scope",
        "writing_comments",
        ["novel_id", "draft_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_writing_comments_scope", table_name="writing_comments")
    op.drop_index("ix_writing_comments_novel_id", table_name="writing_comments")
    op.drop_table("writing_comments")
