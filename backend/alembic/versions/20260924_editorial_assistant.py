"""Versioned editorial work and author decisions."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260924_editorial_assistant"
down_revision = "20260922_evolution_reading"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "writing_drafts",
        sa.Column("editorial_ready_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "writing_drafts", sa.Column("editorial_ready_hash", sa.String(64), nullable=True)
    )
    op.create_table(
        "assistant_editorial_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "novel_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("async_tasks.id", ondelete="SET NULL"),
        ),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("scope_json", sa.JSON(), nullable=False),
        sa.Column("brief_json", sa.JSON(), nullable=False),
        sa.Column("source_json", sa.JSON(), nullable=False),
        sa.Column("progress_json", sa.JSON(), nullable=False),
        sa.Column("report_json", sa.JSON(), nullable=False),
        sa.Column("llm_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("novel_id", "id"),
        sa.UniqueConstraint("novel_id", "operation_id"),
    )
    op.create_index(
        "ix_assistant_editorial_reviews_novel_id",
        "assistant_editorial_reviews",
        ["novel_id"],
    )
    op.create_index(
        "ix_editorial_reviews_recent",
        "assistant_editorial_reviews",
        ["novel_id", "created_at"],
    )
    op.create_table(
        "assistant_editorial_issues",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "novel_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("review_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column(
            "recheck_task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("async_tasks.id", ondelete="SET NULL"),
        ),
        sa.Column("disposition", sa.String(32), nullable=False),
        sa.Column("finding_json", sa.JSON(), nullable=False),
        sa.Column("history_json", sa.JSON(), nullable=False),
        sa.Column("decision_json", sa.JSON(), nullable=False),
        sa.Column("recheck_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["novel_id", "review_id"],
            ["assistant_editorial_reviews.novel_id", "assistant_editorial_reviews.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("novel_id", "fingerprint"),
    )
    op.create_index(
        "ix_assistant_editorial_issues_novel_id",
        "assistant_editorial_issues",
        ["novel_id"],
    )
    op.create_index(
        "ix_editorial_issues_state",
        "assistant_editorial_issues",
        ["novel_id", "disposition"],
    )


def downgrade():
    op.drop_table("assistant_editorial_issues")
    op.drop_table("assistant_editorial_reviews")
    op.drop_column("writing_drafts", "editorial_ready_hash")
    op.drop_column("writing_drafts", "editorial_ready_at")
