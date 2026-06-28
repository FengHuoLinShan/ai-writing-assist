"""add context_confirmations table

Revision ID: 20260628_context_confirmations
Revises: 8bb02b4b94ba
Create Date: 2026-06-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260628_context_confirmations"
down_revision: str | None = "8bb02b4b94ba"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "context_confirmations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column(
            "context_mode",
            sa.String(length=32),
            nullable=False,
            server_default="canonical",
        ),
        sa.Column(
            "include_pending_objects",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "excluded_asset_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "selected_asset_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("user_note", sa.Text(), nullable=True),
        sa.Column(
            "compile_options",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "warnings",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "result_refs",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "result_status",
            sa.String(length=32),
            nullable=False,
            server_default="confirmed",
        ),
        sa.Column(
            "stale_reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "compiled_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("timezone('utc', now())"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('utc', now())"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("timezone('utc', now())"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        comment="AI 参考资料确认记录",
    )
    op.create_index(
        "ix_context_confirmations_action",
        "context_confirmations",
        ["action"],
        unique=False,
    )
    op.create_index(
        "ix_context_confirmations_novel_id",
        "context_confirmations",
        ["novel_id"],
        unique=False,
    )
    op.create_index(
        "ix_context_confirmations_novel_action",
        "context_confirmations",
        ["novel_id", "action"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_context_confirmations_novel_action",
        table_name="context_confirmations",
    )
    op.drop_index(
        "ix_context_confirmations_novel_id",
        table_name="context_confirmations",
    )
    op.drop_index(
        "ix_context_confirmations_action",
        table_name="context_confirmations",
    )
    op.drop_table("context_confirmations")
