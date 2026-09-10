"""Assistant execution and presentation state; domain assets remain external."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, NovelMixin, TimestampMixin, UUIDMixin
from modules.assistant.session_models import AssistantMessage, AssistantSession

__all__ = [
    "AssistantSession",
    "AssistantMessage",
    "AssistantRun",
    "AssistantActionBatch",
    "AssistantNotice",
    "AssistantWatch",
]


class AssistantRun(Base, UUIDMixin, TimestampMixin, NovelMixin):
    __tablename__ = "assistant_runs"
    __table_args__ = (
        UniqueConstraint("novel_id", "id", name="uq_assistant_run_novel"),
        ForeignKeyConstraint(
            ["novel_id", "session_id"],
            ["world_cocreation_sessions.novel_id", "world_cocreation_sessions.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status IN ('pending','running','completed','failed','cancelled',"
            "'waiting_approval','budget_exceeded')",
            name="ck_assistant_run_status",
        ),
        CheckConstraint("mode IN ('author','background')", name="ck_assistant_run_mode"),
        Index(
            "uq_assistant_session_active",
            "session_id",
            unique=True,
            postgresql_where=text(
                "status IN ('pending','running') AND session_id IS NOT NULL"
            ),
            sqlite_where=text(
                "status IN ('pending','running') AND session_id IS NOT NULL"
            ),
        ),
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("async_tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    mode: Mapped[str] = mapped_column(String(16), default="author")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    request_hash: Mapped[str] = mapped_column(String(64))
    request_json: Mapped[dict] = mapped_column(JSON, default=dict)
    budget_json: Mapped[dict] = mapped_column(JSON, default=dict)
    checkpoint_json: Mapped[dict] = mapped_column(JSON, default=dict)
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class AssistantActionBatch(Base, UUIDMixin, TimestampMixin, NovelMixin):
    __tablename__ = "assistant_action_batches"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_assistant_batch_run"),
        ForeignKeyConstraint(
            ["novel_id", "run_id"],
            ["assistant_runs.novel_id", "assistant_runs.id"],
            ondelete="CASCADE",
        ),
    )
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    actions_json: Mapped[list] = mapped_column(JSON, default=list)
    authorization_json: Mapped[dict] = mapped_column(JSON, default=dict)
    results_json: Mapped[list] = mapped_column(JSON, default=list)


class AssistantNotice(Base, UUIDMixin, TimestampMixin, NovelMixin):
    __tablename__ = "assistant_notices"
    __table_args__ = (
        UniqueConstraint(
            "novel_id", "fingerprint", name="uq_assistant_notice_fingerprint"
        ),
        CheckConstraint(
            "status IN ('unread','read','snoozed','dismissed')",
            name="ck_assistant_notice_status",
        ),
    )
    fingerprint: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(20), default="suggestion")
    status: Mapped[str] = mapped_column(String(20), default="unread")
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text)
    sources_json: Mapped[list] = mapped_column(JSON, default=list)
    result_ref_json: Mapped[dict] = mapped_column(JSON, default=dict)
    disposition: Mapped[str | None] = mapped_column(String(32), nullable=True)
    wake_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AssistantWatch(Base, TimestampMixin, NovelMixin):
    __tablename__ = "assistant_watches"
    __table_args__ = (UniqueConstraint("novel_id", name="uq_assistant_watch_novel"),)
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    policy_json: Mapped[dict] = mapped_column(JSON, default=dict)
    dirty_json: Mapped[dict] = mapped_column(JSON, default=dict)
    generation: Mapped[int] = mapped_column(Integer, default=0)
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    active_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    last_checked_json: Mapped[dict] = mapped_column(JSON, default=dict)
