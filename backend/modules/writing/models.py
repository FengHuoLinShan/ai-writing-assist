"""
Writing ORM 模型

对应数据库 writing_drafts 表。
存储人工正文草稿，支持版本管理。
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, NovelMixin, TimestampMixin, UUIDMixin


class WritingDraft(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """正文草稿 — 手工写作的正文承载"""

    __tablename__ = "writing_drafts"
    __table_args__ = (
        UniqueConstraint(
            "novel_id",
            "chapter_index",
            "version_number",
            name="uq_writing_draft_version",
        ),
        {"comment": "正文草稿"},
    )

    chapter_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True,
        comment="章节索引",
    )
    title: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="草稿标题",
    )
    content: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="草稿正文",
    )
    conflict_check_snapshot_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        comment="发布时归档的最近一次冲突检查快照",
    )
    version_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="版本号（从 1 递增）",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="draft",
        comment="状态：draft / candidate / canonical / deprecated",
    )

    def __repr__(self) -> str:
        return (
            f"<WritingDraft id={self.id} novel={self.novel_id} "
            f"ch={self.chapter_index} v{self.version_number}>"
        )


class WritingConflictCheck(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """Scene 写作冲突检查记录。"""

    __tablename__ = "writing_conflict_checks"
    __table_args__ = (
        Index(
            "ix_writing_conflict_checks_scope",
            "novel_id",
            "chapter_index",
            "scene_id",
            "created_at",
        ),
        {"comment": "写作页剧情设定冲突检查记录"},
    )

    chapter_index: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    scene_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
        index=True,
        comment="关联 Scene ID（不建 FK，跨模块弱绑定）",
    )
    draft_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("writing_drafts.id", ondelete="SET NULL"),
        nullable=True,
    )
    version_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scope: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    include_candidates: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="completed",
        index=True,
        comment="completed / degraded",
    )
    summary_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    ai_review_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    ai_review_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="not_requested",
        comment="not_requested / running / done / failed / partial",
    )
    ai_review_confirmation_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
    )
    ai_review_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ai_review_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class WritingConflictItem(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """单条冲突检查问题。"""

    __tablename__ = "writing_conflict_items"
    __table_args__ = (
        Index("ix_writing_conflict_items_novel_status", "novel_id", "status"),
        {"comment": "写作页剧情设定冲突检查问题项"},
    )

    check_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("writing_conflict_checks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    source_module: Mapped[str] = mapped_column(String(32), nullable=False)
    source_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    evidence_summary: Mapped[str] = mapped_column(Text, nullable=False)
    location_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_ai_judgment: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    needs_review: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="open",
        index=True,
        comment="open / resolved / ignored / later",
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_confirmation_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
    )
    llm_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggestion_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="not_requested",
        comment="not_requested / running / done / failed",
    )
    suggestion_confirmation_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=True,
    )
    ai_suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggestion_error: Mapped[str | None] = mapped_column(Text, nullable=True)
