"""add reproducible, ID-free operation trace report aggregates

Revision ID: 20261016_operation_trace_reports
Revises: 20261016_dossier_story_field_key
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261016_operation_trace_reports"
down_revision: str | None = "20261016_dossier_story_field_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _project_key() -> list[sa.Column]:
    return [
        sa.Column("novel_id", sa.UUID(), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("op_id", sa.String(length=160), nullable=False),
        sa.ForeignKeyConstraint(["novel_id"], ["projects.id"], ondelete="CASCADE"),
    ]


def upgrade() -> None:
    op.add_column(
        "assistant_operation_traces",
        sa.Column(
            "event_metadata",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )
    op.add_column(
        "assistant_operation_sequence_aggregates",
        sa.Column(
            "sequence_complete",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )

    op.create_table(
        "assistant_operation_trace_metric_aggregates",
        *_project_key(),
        sa.Column("event_type", sa.String(length=24), nullable=False),
        sa.Column("observed_event_count", sa.Integer(), nullable=False),
        sa.Column("duration_count", sa.Integer(), nullable=False),
        sa.Column("duration_ms_total", sa.BigInteger(), nullable=False),
        sa.Column("usage_event_count", sa.Integer(), nullable=False),
        sa.Column("usage_complete_count", sa.Integer(), nullable=False),
        sa.Column("usage_unknown_count", sa.Integer(), nullable=False),
        sa.Column("usage_pending_count", sa.Integer(), nullable=False),
        sa.Column("usage_totals", sa.JSON(), nullable=False),
        sa.Column("usage_field_counts", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "observed_event_count > 0",
            name="ck_operation_trace_metric_observed_count",
        ),
        sa.PrimaryKeyConstraint(
            "novel_id",
            "occurred_on",
            "op_id",
            "event_type",
            name="pk_assistant_operation_trace_metric_aggregates",
        ),
    )
    op.create_table(
        "assistant_operation_trace_lifecycle_aggregates",
        *_project_key(),
        sa.Column("proposed_count", sa.Integer(), nullable=False),
        sa.Column("accepted_count", sa.Integer(), nullable=False),
        sa.Column("declined_count", sa.Integer(), nullable=False),
        sa.Column("edited_accepted_count", sa.Integer(), nullable=False),
        sa.Column("unresolved_count", sa.Integer(), nullable=False),
        sa.Column("outcome_unknown_count", sa.Integer(), nullable=False),
        sa.Column("unmatched_decision_count", sa.Integer(), nullable=False),
        sa.Column("ambiguous_count", sa.Integer(), nullable=False),
        sa.Column("proposal_event_count", sa.Integer(), nullable=False),
        sa.Column("confirmed_event_count", sa.Integer(), nullable=False),
        sa.Column("declined_event_count", sa.Integer(), nullable=False),
        sa.Column("edited_event_count", sa.Integer(), nullable=False),
        sa.Column("outcome_unknown_event_count", sa.Integer(), nullable=False),
        sa.Column("failed_event_count", sa.Integer(), nullable=False),
        sa.Column("failed_execution_count", sa.Integer(), nullable=False),
        sa.Column("unknown_execution_count", sa.Integer(), nullable=False),
        sa.Column("restored_event_count", sa.Integer(), nullable=False),
        sa.Column("undone_event_count", sa.Integer(), nullable=False),
        sa.Column("unlinked_proposal_events", sa.Integer(), nullable=False),
        sa.Column("unlinked_decision_events", sa.Integer(), nullable=False),
        sa.Column("unlinked_reversal_events", sa.Integer(), nullable=False),
        sa.Column("executed_count", sa.Integer(), nullable=False),
        sa.Column("executed_event_count", sa.Integer(), nullable=False),
        sa.Column("reversal_event_count", sa.Integer(), nullable=False),
        sa.Column("matched_reversal_count", sa.Integer(), nullable=False),
        sa.Column("unmatched_reversal_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint(
            "novel_id",
            "occurred_on",
            "op_id",
            name="pk_assistant_operation_trace_lifecycle_aggregates",
        ),
    )
    op.create_table(
        "assistant_operation_trace_parameter_aggregates",
        *_project_key(),
        sa.Column("event_type", sa.String(length=24), nullable=False),
        sa.Column("profile_hash", sa.String(length=64), nullable=False),
        sa.Column("parameter_profile", sa.JSON(), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.CheckConstraint("event_count > 0", name="ck_operation_trace_parameter_count"),
        sa.PrimaryKeyConstraint(
            "novel_id",
            "occurred_on",
            "op_id",
            "event_type",
            "profile_hash",
            name="pk_assistant_operation_trace_parameter_aggregates",
        ),
    )


def downgrade() -> None:
    op.drop_table("assistant_operation_trace_parameter_aggregates")
    op.drop_table("assistant_operation_trace_lifecycle_aggregates")
    op.drop_table("assistant_operation_trace_metric_aggregates")
    op.drop_column("assistant_operation_sequence_aggregates", "sequence_complete")
    op.drop_column("assistant_operation_traces", "event_metadata")
