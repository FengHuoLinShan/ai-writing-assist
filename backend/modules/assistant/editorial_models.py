"""Saved editorial observations; never writing adoption receipts."""

import uuid

from sqlalchemy import (
    JSON,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, NovelMixin, TimestampMixin, UUIDMixin, UUIDType


class EditorialReview(Base, UUIDMixin, TimestampMixin, NovelMixin):
    __tablename__ = "assistant_editorial_reviews"
    __table_args__ = (
        UniqueConstraint("novel_id", "id"),
        UniqueConstraint("novel_id", "operation_id"),
        Index("ix_editorial_reviews_recent", "novel_id", "created_at"),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("accounts.id"))
    operation_id: Mapped[uuid.UUID] = mapped_column(UUIDType)
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("async_tasks.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(24), default="queued")
    scope_json: Mapped[dict] = mapped_column(JSON, default=dict)
    brief_json: Mapped[dict] = mapped_column(JSON, default=dict)
    source_json: Mapped[list] = mapped_column(JSON, default=list)
    progress_json: Mapped[dict] = mapped_column(JSON, default=dict)
    report_json: Mapped[dict] = mapped_column(JSON, default=dict)
    llm_snapshot_json: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class EditorialIssue(Base, UUIDMixin, TimestampMixin, NovelMixin):
    __tablename__ = "assistant_editorial_issues"
    __table_args__ = (
        UniqueConstraint("novel_id", "fingerprint"),
        ForeignKeyConstraint(
            ["novel_id", "review_id"],
            ["assistant_editorial_reviews.novel_id", "assistant_editorial_reviews.id"],
            ondelete="CASCADE",
        ),
        Index("ix_editorial_issues_state", "novel_id", "disposition"),
    )

    review_id: Mapped[uuid.UUID] = mapped_column(UUIDType)
    fingerprint: Mapped[str] = mapped_column(String(64))
    row_version: Mapped[int] = mapped_column(Integer, default=0)
    recheck_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("async_tasks.id", ondelete="SET NULL"), nullable=True
    )
    disposition: Mapped[str] = mapped_column(String(32), default="open")
    finding_json: Mapped[dict] = mapped_column(JSON, default=dict)
    history_json: Mapped[list] = mapped_column(JSON, default=list)
    decision_json: Mapped[list] = mapped_column(JSON, default=list)
    recheck_json: Mapped[list] = mapped_column(JSON, default=list)
