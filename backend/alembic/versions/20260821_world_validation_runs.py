"""Add durable World Bible validation runs.

Revision ID: 20260821_world_validation_runs
Revises: 20260821_world_bible_draft_meta
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260821_world_validation_runs"
down_revision = "20260821_world_bible_draft_meta"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=True)
    json_type = postgresql.JSONB
    op.create_table(
        "world_validation_runs",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("novel_id", uuid_type, nullable=False),
        sa.Column("task_id", uuid_type, nullable=True, unique=True),
        sa.Column("trigger", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("scope_json", json_type, nullable=False, server_default="{}"),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("verdict", sa.String(32), nullable=True),
        sa.Column("gate", sa.String(16), nullable=True),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("policy_hash", sa.String(64), nullable=False),
        sa.Column("manifest_json", json_type, nullable=False, server_default="{}"),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.Column("dependency_hash", sa.String(64), nullable=False),
        sa.Column("packet_hashes_json", json_type, nullable=False, server_default="[]"),
        sa.Column("findings_json", json_type, nullable=False, server_default="[]"),
        sa.Column("omissions_json", json_type, nullable=False, server_default="[]"),
        sa.Column("coverage_ledger_json", json_type, nullable=False, server_default="[]"),
        sa.Column("budget_ledger_json", json_type, nullable=False, server_default="{}"),
        sa.Column("model_snapshot_json", json_type, nullable=False, server_default="{}"),
        sa.Column("warning_receipt_json", json_type, nullable=False, server_default="{}"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_summary", sa.String(500), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "scope IN ('targeted', 'full')", name="ck_world_validation_runs_scope"
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'stale')",
            name="ck_world_validation_runs_status",
        ),
        sa.CheckConstraint(
            "verdict IS NULL OR verdict IN "
            "('pass', 'mixed', 'fail', 'author-required', "
            "'insufficient-evidence')",
            name="ck_world_validation_runs_verdict",
        ),
        sa.CheckConstraint(
            "gate IS NULL OR gate IN ('pass', 'warn', 'block')",
            name="ck_world_validation_runs_gate",
        ),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["async_tasks.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_world_validation_runs_novel_id", "world_validation_runs", ["novel_id"]
    )
    op.create_index(
        "ix_world_validation_runs_novel_created",
        "world_validation_runs",
        ["novel_id", "created_at"],
    )
    op.create_index(
        "ix_world_validation_runs_novel_status",
        "world_validation_runs",
        ["novel_id", "status"],
    )
    op.create_index(
        "uq_world_validation_runs_active_full",
        "world_validation_runs",
        ["novel_id"],
        unique=True,
        postgresql_where=sa.text("scope = 'full' AND status IN ('queued', 'running')"),
        sqlite_where=sa.text("scope = 'full' AND status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_table("world_validation_runs")
