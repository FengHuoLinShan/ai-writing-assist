"""add context_snapshots table

Revision ID: 20260628_context_snapshots
Revises: 20260628_context_confirmations
Create Date: 2026-06-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260628_context_snapshots"
down_revision: str | None = "20260628_context_confirmations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "context_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("novel_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("workflow_id", sa.String(length=64), nullable=True),
        sa.Column("phase", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=128), nullable=False),
        sa.Column("scene_id", sa.String(length=64), nullable=True),
        sa.Column("scene_index", sa.Integer(), nullable=True),
        sa.Column("chapter_index", sa.Integer(), nullable=True),
        sa.Column(
            "context_mode",
            sa.String(length=32),
            nullable=False,
            server_default="working",
        ),
        sa.Column(
            "include_pending_objects",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="running",
        ),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("prompt_hash", sa.String(length=64), nullable=False),
        sa.Column("prompt_name", sa.String(length=128), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column(
            "compile_options",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "included_asset_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "excluded_asset_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "context_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "section_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "token_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("rendered_context", sa.Text(), nullable=True),
        sa.Column(
            "result_refs",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("error_kind", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "rendered_context_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
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
        comment="AI 调用上下文快照审计记录",
    )
    op.create_index(
        "ix_context_snapshots_novel_workflow_phase",
        "context_snapshots",
        ["novel_id", "workflow_id", "phase"],
        unique=False,
    )
    op.create_index(
        "ix_context_snapshots_novel_created",
        "context_snapshots",
        ["novel_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_context_snapshots_status",
        "context_snapshots",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_context_snapshots_rendered_expires",
        "context_snapshots",
        ["rendered_context_expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_context_snapshots_rendered_expires",
        table_name="context_snapshots",
    )
    op.drop_index("ix_context_snapshots_status", table_name="context_snapshots")
    op.drop_index("ix_context_snapshots_novel_created", table_name="context_snapshots")
    op.drop_index(
        "ix_context_snapshots_novel_workflow_phase",
        table_name="context_snapshots",
    )
    op.drop_table("context_snapshots")
