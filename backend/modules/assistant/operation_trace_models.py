"""Append-only, content-minimizing operation lifecycle records."""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, UUIDType


class AssistantOperationTrace(Base):
    __tablename__ = "assistant_operation_traces"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('proposed','previewed','confirmed','declined','edited',"
            "'executed','failed','restored','undone','outcome_unknown')",
            name="ck_assistant_operation_trace_event_type",
        ),
        CheckConstraint(
            "actor_type IN ('assistant','guided_flow','goal','ui','background','system')",
            name="ck_assistant_operation_trace_actor_type",
        ),
        Index(
            "ix_assistant_operation_trace_project_time",
            "novel_id",
            "occurred_at",
        ),
        Index("ix_assistant_operation_trace_time", "occurred_at"),
        Index(
            "ix_assistant_operation_trace_session_sequence",
            "session_id",
            "id",
        ),
        Index(
            "ix_assistant_operation_trace_operation_time",
            "op_id",
            "occurred_at",
        ),
        Index("ix_assistant_operation_trace_call_sequence", "call_id", "id"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    call_id: Mapped[object | None] = mapped_column(UUIDType, nullable=True)
    parent_call_id: Mapped[object | None] = mapped_column(UUIDType, nullable=True)
    novel_id: Mapped[object] = mapped_column(
        UUIDType,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_id: Mapped[object] = mapped_column(UUIDType, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)
    entrypoint: Mapped[str] = mapped_column(String(80), nullable=False)
    run_id: Mapped[object | None] = mapped_column(UUIDType, nullable=True)
    session_id: Mapped[object | None] = mapped_column(UUIDType, nullable=True)
    op_id: Mapped[str] = mapped_column(String(160), nullable=False)
    op_version: Mapped[str] = mapped_column(String(32), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(2), nullable=False)
    fee_category: Mapped[str] = mapped_column(String(32), nullable=False)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_refs: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    parameter_summary: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    result_refs: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    usage: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    event_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class AssistantOperationTracePreference(Base):
    """Account-level opt-in; NULL follows the local/public default."""

    __tablename__ = "assistant_operation_trace_preferences"

    owner_id: Mapped[object] = mapped_column(
        UUIDType,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    enabled: Mapped[bool | None] = mapped_column(nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AssistantOperationTraceProjectSalt(Base):
    """Random, private salt makes string hashes unlinkable across works."""

    __tablename__ = "assistant_operation_trace_project_salts"

    novel_id: Mapped[object] = mapped_column(
        UUIDType,
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    owner_id: Mapped[object] = mapped_column(UUIDType, nullable=False)
    salt: Mapped[str] = mapped_column(String(64), nullable=False)


class AssistantOperationTraceAggregate(Base):
    """Retained counts only; intentionally has no event, target, or run IDs."""

    __tablename__ = "assistant_operation_trace_aggregates"
    __table_args__ = (
        CheckConstraint("event_count > 0", name="ck_operation_trace_aggregate_count"),
    )

    novel_id: Mapped[object] = mapped_column(
        UUIDType,
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    occurred_on: Mapped[date] = mapped_column(Date, primary_key=True)
    op_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(24), primary_key=True)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False)


class AssistantOperationSequenceAggregate(Base):
    """Operation-ID sequences only; no request or asset identifiers."""

    __tablename__ = "assistant_operation_sequence_aggregates"

    novel_id: Mapped[object] = mapped_column(
        UUIDType,
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    occurred_on: Mapped[date] = mapped_column(Date, primary_key=True)
    sequence_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    operation_sequence: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    sequence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sequence_complete: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )


class AssistantOperationTraceMetricAggregate(Base):
    """Forward-only duration and usage coverage without event or request IDs."""

    __tablename__ = "assistant_operation_trace_metric_aggregates"
    __table_args__ = (
        CheckConstraint(
            "observed_event_count > 0",
            name="ck_operation_trace_metric_observed_count",
        ),
    )

    novel_id: Mapped[object] = mapped_column(
        UUIDType,
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    occurred_on: Mapped[date] = mapped_column(Date, primary_key=True)
    op_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(24), primary_key=True)
    observed_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_count: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms_total: Mapped[int] = mapped_column(BigInteger, nullable=False)
    usage_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    usage_complete_count: Mapped[int] = mapped_column(Integer, nullable=False)
    usage_unknown_count: Mapped[int] = mapped_column(Integer, nullable=False)
    usage_pending_count: Mapped[int] = mapped_column(Integer, nullable=False)
    usage_totals: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    usage_field_counts: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class AssistantOperationTraceLifecycleAggregate(Base):
    """ID-free daily lifecycle counts; correlation IDs are discarded at archive."""

    __tablename__ = "assistant_operation_trace_lifecycle_aggregates"

    novel_id: Mapped[object] = mapped_column(
        UUIDType,
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    occurred_on: Mapped[date] = mapped_column(Date, primary_key=True)
    op_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    proposed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted_count: Mapped[int] = mapped_column(Integer, nullable=False)
    declined_count: Mapped[int] = mapped_column(Integer, nullable=False)
    edited_accepted_count: Mapped[int] = mapped_column(Integer, nullable=False)
    unresolved_count: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome_unknown_count: Mapped[int] = mapped_column(Integer, nullable=False)
    unmatched_decision_count: Mapped[int] = mapped_column(Integer, nullable=False)
    ambiguous_count: Mapped[int] = mapped_column(Integer, nullable=False)
    proposal_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    confirmed_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    declined_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    edited_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome_unknown_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    failed_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    failed_execution_count: Mapped[int] = mapped_column(Integer, nullable=False)
    unknown_execution_count: Mapped[int] = mapped_column(Integer, nullable=False)
    restored_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    undone_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    unlinked_proposal_events: Mapped[int] = mapped_column(Integer, nullable=False)
    unlinked_decision_events: Mapped[int] = mapped_column(Integer, nullable=False)
    unlinked_execution_events: Mapped[int] = mapped_column(Integer, nullable=False)
    unlinked_reversal_events: Mapped[int] = mapped_column(Integer, nullable=False)
    executed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    executed_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    reversal_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    matched_reversal_count: Mapped[int] = mapped_column(Integer, nullable=False)
    unmatched_reversal_count: Mapped[int] = mapped_column(Integer, nullable=False)


class AssistantOperationTraceParameterAggregate(Base):
    """Daily counts for coarse, non-content parameter shapes."""

    __tablename__ = "assistant_operation_trace_parameter_aggregates"

    novel_id: Mapped[object] = mapped_column(
        UUIDType,
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    occurred_on: Mapped[date] = mapped_column(Date, primary_key=True)
    op_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(24), primary_key=True)
    profile_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    parameter_profile: Mapped[dict] = mapped_column(JSON, nullable=False)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False)
