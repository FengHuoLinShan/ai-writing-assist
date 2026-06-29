"""conflict check ai phase2

Revision ID: f20260629b
Revises: f20260629
Create Date: 2026-06-29 15:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "f20260629b"
down_revision = "f20260629"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "writing_conflict_checks",
        sa.Column(
            "ai_review_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "writing_conflict_checks",
        sa.Column(
            "ai_review_status",
            sa.String(32),
            nullable=False,
            server_default="not_requested",
        ),
    )
    op.add_column(
        "writing_conflict_checks",
        sa.Column("ai_review_confirmation_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "writing_conflict_checks",
        sa.Column("ai_review_model", sa.String(128), nullable=True),
    )
    op.add_column(
        "writing_conflict_checks",
        sa.Column("ai_review_error", sa.Text(), nullable=True),
    )

    op.add_column(
        "writing_conflict_items",
        sa.Column("confidence", sa.Float(), nullable=True),
    )
    op.add_column(
        "writing_conflict_items",
        sa.Column("source_confirmation_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "writing_conflict_items",
        sa.Column("llm_rationale", sa.Text(), nullable=True),
    )
    op.add_column(
        "writing_conflict_items",
        sa.Column(
            "suggestion_status",
            sa.String(32),
            nullable=False,
            server_default="not_requested",
        ),
    )
    op.add_column(
        "writing_conflict_items",
        sa.Column("suggestion_confirmation_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "writing_conflict_items",
        sa.Column("suggestion_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("writing_conflict_items", "suggestion_error")
    op.drop_column("writing_conflict_items", "suggestion_confirmation_id")
    op.drop_column("writing_conflict_items", "suggestion_status")
    op.drop_column("writing_conflict_items", "llm_rationale")
    op.drop_column("writing_conflict_items", "source_confirmation_id")
    op.drop_column("writing_conflict_items", "confidence")

    op.drop_column("writing_conflict_checks", "ai_review_error")
    op.drop_column("writing_conflict_checks", "ai_review_model")
    op.drop_column("writing_conflict_checks", "ai_review_confirmation_id")
    op.drop_column("writing_conflict_checks", "ai_review_status")
    op.drop_column("writing_conflict_checks", "ai_review_enabled")
