"""Append-only, content-minimizing operation lifecycle records."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
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
            "'executed','failed','restored','undone')",
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
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
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
