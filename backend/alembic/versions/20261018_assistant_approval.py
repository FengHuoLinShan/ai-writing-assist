"""Persist task-scoped grants and explicit model calibration receipts.

Revision ID: 20261018_assistant_approval
Revises: 20261017_wp_scope_stop
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261018_assistant_approval"
down_revision = "20261017_wp_scope_stop"
branch_labels = None
depends_on = None


def _shared_columns():
    return [
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
            nullable=True,
            server_default=sa.text("timezone('utc', now())"),
        ),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
    ]


def upgrade():
    op.create_table(
        "assistant_approval_grants",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("policy_json", sa.JSON(), nullable=False),
        sa.Column("model_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("attempts_json", sa.JSON(), nullable=False),
        *_shared_columns(),
        sa.ForeignKeyConstraint(
            ["novel_id", "run_id"],
            ["assistant_runs.novel_id", "assistant_runs.id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "status IN ('active','revoked')", name="ck_approval_grant_status"
        ),
    )
    op.create_index(
        "ix_assistant_approval_grants_novel_id", "assistant_approval_grants", ["novel_id"]
    )
    op.create_table(
        "assistant_approval_calibrations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id"),
            nullable=False,
        ),
        sa.Column("model_fingerprint", sa.String(64), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("suite_hash", sa.String(64), nullable=False),
        sa.Column("receipt_json", sa.JSON(), nullable=False),
        *_shared_columns(),
        sa.UniqueConstraint(
            "novel_id",
            "owner_id",
            "model_fingerprint",
            "policy_version",
            name="uq_approval_calibration",
        ),
    )
    op.create_index(
        "ix_assistant_approval_calibrations_novel_id",
        "assistant_approval_calibrations",
        ["novel_id"],
    )


def downgrade():
    op.drop_table("assistant_approval_grants")
    op.drop_table("assistant_approval_calibrations")
