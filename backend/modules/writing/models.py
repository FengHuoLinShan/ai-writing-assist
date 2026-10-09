"""
Writing ORM 模型

对应数据库 writing_drafts 表。
存储人工正文草稿，支持版本管理。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
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
    content_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="",
        index=True,
        comment="正文 SHA-256，用于稳定来源引用和索引新鲜度校验",
    )
    editorial_ready_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    editorial_ready_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    conflict_check_snapshot_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        comment="发布时归档的最近一次冲突检查快照",
    )
    provenance_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        comment="草稿来源追踪信息",
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
        comment="状态：draft / published / candidate / canonical / deprecated",
    )

    def __repr__(self) -> str:
        return (
            f"<WritingDraft id={self.id} novel={self.novel_id} "
            f"ch={self.chapter_index} v{self.version_number}>"
        )


class WritingComment(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """A comment anchored to one saved manuscript revision."""

    __tablename__ = "writing_comments"
    __table_args__ = (
        Index("ix_writing_comments_scope", "novel_id", "draft_id", "created_at"),
        UniqueConstraint(
            "review_task_id", "finding_id", name="uq_writing_comment_finding"
        ),
        CheckConstraint(
            "(start_offset IS NULL AND end_offset IS NULL) OR "
            "(start_offset >= 0 AND end_offset > start_offset)",
            name="ck_writing_comment_range",
        ),
        CheckConstraint(
            "status IN ('open', 'resolved')", name="ck_writing_comment_status"
        ),
    )

    draft_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("writing_drafts.id", ondelete="CASCADE"),
        nullable=False,
    )
    chapter_index: Mapped[int] = mapped_column(Integer, nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    range_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    start_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[str] = mapped_column(String(16), nullable=False)
    severity: Mapped[str | None] = mapped_column(String(16), nullable=True)
    review_task_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    finding_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_run_task_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")


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


class WritingRecomputeOperation(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """已执行的失效重算操作回执（跨会话可查、同编号可回放）。

    P2-C：``operation_id`` + 请求内容指纹构成双幂等键——同编号异摘要的请求
    必须被拒绝（否则一次预览的结果会被另一种重算顶替），已完成的操作在来源
    变化后仍要能回放出原回执（作者离开再回来也要查得到，而不是再改一次正文
    才能找回入口）。追加式：一行即一次已完成的操作，不更新不删除。
    """

    __tablename__ = "writing_recompute_operations"
    __table_args__ = (
        UniqueConstraint(
            "novel_id",
            "operation_id",
            name="uq_writing_recompute_operation_id",
        ),
        Index(
            "ix_writing_recompute_operations_novel_created",
            "novel_id",
            "created_at",
        ),
        {"comment": "失效重算操作回执（跨会话重查与幂等回放）"},
    )

    operation_id: Mapped[str] = mapped_column(String(120), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    expected_source_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    results_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.timezone("utc", func.now()),
        default=lambda: datetime.now(UTC),
    )


class WritingInvalidationNotice(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """保存触发的失效提示（待重算状态），跨会话可回读。

    P2-C：失效范围此前只挂在草稿行的瞬态属性上，作者「暂不重算」并离开后
    原影响列表与重算入口就消失。本表在保存时把作者语言公共视图落库，编辑
    器加载时回读（重算成功覆盖该章后消解），人工稿件始终保留。
    """

    __tablename__ = "writing_invalidation_notices"
    __table_args__ = (
        UniqueConstraint(
            "novel_id",
            "receipt_id",
            name="uq_writing_invalidation_notice_receipt",
        ),
        Index(
            "ix_writing_invalidation_notices_novel_open",
            "novel_id",
            "status",
            "chapter_index",
        ),
        {"comment": "改稿失效提示（待重算状态，跨会话可回读）"},
    )

    receipt_id: Mapped[str] = mapped_column(String(120), nullable=False)
    chapter_index: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    notice_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="open",
        comment="open / resolved",
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
