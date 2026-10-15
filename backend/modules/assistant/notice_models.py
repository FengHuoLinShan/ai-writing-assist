"""Assistant-owned presentation state for sources without domain dispositions."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, NovelMixin, TimestampMixin, UUIDMixin


class AssistantNoticeDisposition(Base, UUIDMixin, TimestampMixin, NovelMixin):
    __tablename__ = "assistant_notice_dispositions"
    __table_args__ = (
        UniqueConstraint(
            "novel_id",
            "source_id",
            "notice_key",
            "basis_fingerprint",
            name="uq_assistant_notice_disposition_basis",
        ),
        CheckConstraint(
            "status IN ('read','snoozed','ignored')",
            name="ck_assistant_notice_disposition_status",
        ),
        CheckConstraint(
            "row_version >= 1", name="ck_assistant_notice_disposition_version"
        ),
        Index(
            "ix_assistant_notice_dispositions_novel_status",
            "novel_id",
            "status",
            "wake_at",
        ),
        {"comment": "统一提醒展示处置，按来源依据指纹隔离"},
    )

    source_id: Mapped[str] = mapped_column(String(80), nullable=False)
    notice_key: Mapped[str] = mapped_column(String(200), nullable=False)
    basis_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    wake_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    row_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )


class AssistantNoticeCategoryMute(Base, UUIDMixin, TimestampMixin, NovelMixin):
    __tablename__ = "assistant_notice_category_mutes"
    __table_args__ = (
        UniqueConstraint(
            "novel_id",
            "source_id",
            "category",
            name="uq_assistant_notice_category_mute",
        ),
        CheckConstraint(
            "row_version >= 1", name="ck_assistant_notice_category_mute_version"
        ),
        Index(
            "ix_assistant_notice_category_mutes_novel_muted",
            "novel_id",
            "is_muted",
        ),
        {"comment": "作者按来源和类别设置的统一提醒静默状态"},
    )

    source_id: Mapped[str] = mapped_column(String(80), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    is_muted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    row_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
