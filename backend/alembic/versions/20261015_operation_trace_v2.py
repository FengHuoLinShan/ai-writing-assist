"""add append-only assistant operation lifecycle traces

Revision ID: 20261015_operation_trace_v2
Revises: 20261015_map_node_merge
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261015_operation_trace_v2"
down_revision: str | None = "20261015_object_dossier_v2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    primary_key_type = sa.Integer() if bind.dialect.name == "sqlite" else sa.BigInteger()
    op.create_table(
        "assistant_operation_traces",
        sa.Column("id", primary_key_type, autoincrement=True, nullable=False),
        sa.Column("call_id", sa.UUID(), nullable=True),
        sa.Column("parent_call_id", sa.UUID(), nullable=True),
        sa.Column("novel_id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("actor_type", sa.String(length=20), nullable=False),
        sa.Column("entrypoint", sa.String(length=80), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=True),
        sa.Column("session_id", sa.UUID(), nullable=True),
        sa.Column("op_id", sa.String(length=160), nullable=False),
        sa.Column("op_version", sa.String(length=32), nullable=False),
        sa.Column("risk_level", sa.String(length=2), nullable=False),
        sa.Column("fee_category", sa.String(length=32), nullable=False),
        sa.Column("event_type", sa.String(length=16), nullable=False),
        sa.Column("target_type", sa.String(length=80), nullable=False),
        sa.Column("target_refs", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("parameter_summary", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("result_refs", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("usage", sa.JSON(), nullable=True),
        sa.CheckConstraint(
            "event_type IN ('proposed','previewed','confirmed','declined','edited',"
            "'executed','failed','restored','undone','outcome_unknown')",
            name="ck_assistant_operation_trace_event_type",
        ),
        sa.CheckConstraint(
            "actor_type IN ('assistant','guided_flow','goal','ui','background','system')",
            name="ck_assistant_operation_trace_actor_type",
        ),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_assistant_operation_trace_project_time",
        "assistant_operation_traces",
        ["novel_id", "occurred_at"],
    )
    op.create_index(
        "ix_assistant_operation_trace_time",
        "assistant_operation_traces",
        ["occurred_at"],
    )
    op.create_index(
        "ix_assistant_operation_trace_session_sequence",
        "assistant_operation_traces",
        ["session_id", "id"],
    )
    op.create_index(
        "ix_assistant_operation_trace_operation_time",
        "assistant_operation_traces",
        ["op_id", "occurred_at"],
    )
    op.create_index(
        "ix_assistant_operation_trace_call_sequence",
        "assistant_operation_traces",
        ["call_id", "id"],
    )
    op.create_table(
        "assistant_operation_trace_preferences",
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("owner_id"),
    )
    op.create_table(
        "assistant_operation_trace_project_salts",
        sa.Column("novel_id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("salt", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("novel_id"),
    )
    op.create_table(
        "assistant_operation_trace_aggregates",
        sa.Column("novel_id", sa.UUID(), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("op_id", sa.String(length=160), nullable=False),
        sa.Column("event_type", sa.String(length=24), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.CheckConstraint("event_count > 0", name="ck_operation_trace_aggregate_count"),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("novel_id", "occurred_on", "op_id", "event_type"),
    )
    op.create_table(
        "assistant_operation_sequence_aggregates",
        sa.Column("novel_id", sa.UUID(), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("sequence_hash", sa.String(length=64), nullable=False),
        sa.Column("operation_sequence", sa.JSON(), nullable=False),
        sa.Column("sequence_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("novel_id", "occurred_on", "sequence_hash"),
    )
    if bind.dialect.name == "postgresql":
        op.execute(
            """CREATE FUNCTION reject_assistant_operation_trace_mutation()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    IF pg_trigger_depth() > 1 OR OLD.occurred_at <= now() -
                       interval '180 days' THEN
                        RETURN OLD;
                    END IF;
                END IF;
                RAISE EXCEPTION 'assistant operation traces are append-only'
                    USING ERRCODE = '55000';
            END $$"""
        )
        op.execute(
            """CREATE TRIGGER trg_assistant_operation_trace_append_only
            BEFORE UPDATE OR DELETE ON assistant_operation_traces
            FOR EACH ROW EXECUTE FUNCTION reject_assistant_operation_trace_mutation()"""
        )
    elif bind.dialect.name == "sqlite":
        op.execute(
            """CREATE TRIGGER trg_assistant_operation_trace_no_update
            BEFORE UPDATE ON assistant_operation_traces
            BEGIN
                SELECT RAISE(ABORT, 'assistant operation traces are append-only');
            END"""
        )
        op.execute(
            """CREATE TRIGGER trg_assistant_operation_trace_no_delete
            BEFORE DELETE ON assistant_operation_traces
            WHEN julianday(OLD.occurred_at) >= julianday('now', '-180 days')
            BEGIN
                SELECT RAISE(ABORT, 'assistant operation traces are append-only');
            END"""
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_assistant_operation_trace_append_only "
            "ON assistant_operation_traces"
        )
        op.execute("DROP FUNCTION IF EXISTS reject_assistant_operation_trace_mutation()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_assistant_operation_trace_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_assistant_operation_trace_no_delete")
    op.drop_index(
        "ix_assistant_operation_trace_operation_time",
        table_name="assistant_operation_traces",
    )
    op.drop_index(
        "ix_assistant_operation_trace_call_sequence",
        table_name="assistant_operation_traces",
    )
    op.drop_index(
        "ix_assistant_operation_trace_session_sequence",
        table_name="assistant_operation_traces",
    )
    op.drop_index(
        "ix_assistant_operation_trace_project_time",
        table_name="assistant_operation_traces",
    )
    op.drop_index(
        "ix_assistant_operation_trace_time",
        table_name="assistant_operation_traces",
    )
    op.drop_table("assistant_operation_sequence_aggregates")
    op.drop_table("assistant_operation_trace_aggregates")
    op.drop_table("assistant_operation_trace_project_salts")
    op.drop_table("assistant_operation_trace_preferences")
    op.drop_table("assistant_operation_traces")
