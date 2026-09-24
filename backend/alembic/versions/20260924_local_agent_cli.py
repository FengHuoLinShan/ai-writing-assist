"""Add owner-bound local CLI devices and invocation receipts."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260924_local_agent_cli"
down_revision = "20260921_evolution_single_writer"
branch_labels = None
depends_on = None


def upgrade():
    uuid = postgresql.UUID(as_uuid=True)
    op.create_table(
        "local_agent_devices",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "novel_id",
            uuid,
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "owner_id",
            uuid,
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("token_digest", sa.String(64)),
        sa.Column("pair_digest", sa.String(64)),
        sa.Column("pair_expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("novel_id", "id", name="uq_local_agent_device_novel"),
    )
    op.create_index(
        "ix_local_agent_device_pair_digest",
        "local_agent_devices",
        ["pair_digest"],
        unique=True,
    )
    op.create_table(
        "local_agent_invocations",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "novel_id",
            uuid,
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "owner_id",
            uuid,
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "device_id",
            uuid,
            sa.ForeignKey("local_agent_devices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "task_id",
            uuid,
            sa.ForeignKey("async_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("cli", sa.String(16), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("lease_id", sa.String(36)),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.UniqueConstraint(
            "task_id", "ordinal", name="uq_local_agent_invocation_task_step"
        ),
    )
    op.create_index(
        "ix_local_agent_invocation_device_status",
        "local_agent_invocations",
        ["device_id", "status"],
    )
    op.create_table(
        "local_agent_tool_calls",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "invocation_id",
            uuid,
            sa.ForeignKey("local_agent_invocations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("call_id", sa.String(80), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("arguments_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("result_json", sa.JSON()),
        sa.Column("error", sa.Text()),
        sa.UniqueConstraint(
            "invocation_id", "call_id", name="uq_local_agent_tool_call_identity"
        ),
    )


def downgrade():
    op.drop_table("local_agent_tool_calls")
    op.drop_index(
        "ix_local_agent_invocation_device_status", table_name="local_agent_invocations"
    )
    op.drop_table("local_agent_invocations")
    op.drop_index("ix_local_agent_device_pair_digest", table_name="local_agent_devices")
    op.drop_table("local_agent_devices")
