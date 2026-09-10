"""Assistant execution state; existing discussion rows retain their IDs and tables.

Revision ID: 20260911_assistant_runtime
Revises: 20260910_world_review_phase4
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "20260911_assistant_runtime"
down_revision = "20260910_world_review_phase4"
branch_labels = None
depends_on = None


def _base():
    return [
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "novel_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")
        ),
    ]


def _json(name, default="{}"):
    return sa.Column(name, sa.JSON(), nullable=False, server_default=default)


def upgrade():
    op.add_column("interaction_generation_attempts", _json("agent_checkpoint_json"))
    op.create_table(
        "assistant_runs",
        *_base(),
        sa.Column(
            "owner_id", UUID(as_uuid=True), sa.ForeignKey("accounts.id"), nullable=False
        ),
        sa.Column("session_id", UUID(as_uuid=True)),
        sa.Column(
            "task_id",
            UUID(as_uuid=True),
            sa.ForeignKey("async_tasks.id", ondelete="SET NULL"),
        ),
        sa.Column("mode", sa.String(16), nullable=False, server_default="author"),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("request_hash", sa.String(64), nullable=False),
        *[
            _json(name)
            for name in ("request_json", "budget_json", "checkpoint_json", "result_json")
        ],
        sa.Column("error", sa.Text()),
        sa.UniqueConstraint("novel_id", "id", name="uq_assistant_run_novel"),
        sa.ForeignKeyConstraint(
            ["novel_id", "session_id"],
            ["world_cocreation_sessions.novel_id", "world_cocreation_sessions.id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "status IN ('pending','running','completed','failed','cancelled',"
            "'waiting_approval','budget_exceeded')",
            name="ck_assistant_run_status",
        ),
        sa.CheckConstraint(
            "mode IN ('author','background')", name="ck_assistant_run_mode"
        ),
    )
    op.create_index(
        "uq_assistant_session_active",
        "assistant_runs",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('pending','running') AND session_id IS NOT NULL"
        ),
    )
    op.create_table(
        "assistant_action_batches",
        *_base(),
        sa.Column("run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        _json("actions_json", "[]"),
        _json("authorization_json"),
        _json("results_json", "[]"),
        sa.UniqueConstraint("run_id", name="uq_assistant_batch_run"),
        sa.ForeignKeyConstraint(
            ["novel_id", "run_id"],
            ["assistant_runs.novel_id", "assistant_runs.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_table(
        "assistant_notices",
        *_base(),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False, server_default="suggestion"),
        sa.Column("status", sa.String(20), nullable=False, server_default="unread"),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        _json("sources_json", "[]"),
        _json("result_ref_json"),
        sa.Column("disposition", sa.String(32)),
        sa.Column("wake_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "novel_id", "fingerprint", name="uq_assistant_notice_fingerprint"
        ),
        sa.CheckConstraint(
            "status IN ('unread','read','snoozed','dismissed')",
            name="ck_assistant_notice_status",
        ),
    )
    op.create_table(
        "assistant_watches",
        *_base(),
        _json("policy_json"),
        _json("dirty_json"),
        _json("last_checked_json"),
        sa.Column("generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("active_run_id", UUID(as_uuid=True)),
        sa.UniqueConstraint("novel_id", name="uq_assistant_watch_novel"),
    )
    for table in (
        "assistant_runs",
        "assistant_action_batches",
        "assistant_notices",
        "assistant_watches",
    ):
        op.create_index(f"ix_{table}_novel_id", table, ["novel_id"])
    op.create_index("ix_assistant_watches_due_at", "assistant_watches", ["due_at"])


def downgrade():
    op.drop_column("interaction_generation_attempts", "agent_checkpoint_json")
    for table in (
        "assistant_watches",
        "assistant_notices",
        "assistant_action_batches",
        "assistant_runs",
    ):
        op.drop_table(table)
