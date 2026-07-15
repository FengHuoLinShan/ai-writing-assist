"""Context ORM models."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    CHAR,
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from core.base import Base, TimestampMixin


class GUID(TypeDecorator):
    """Platform-independent UUID type for SQLite tests and PostgreSQL runtime."""

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect: Dialect):
        if value is None:
            return None
        if not isinstance(value, uuid.UUID):
            value = uuid.UUID(str(value))
        if dialect.name == "postgresql":
            return value
        return str(value)

    def process_result_value(self, value, dialect: Dialect):
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))


class ContextConfirmation(Base, TimestampMixin):
    """User-approved AI reference material summary."""

    __tablename__ = "context_confirmations"
    __table_args__ = (
        Index("ix_context_confirmations_novel_action", "novel_id", "action"),
        {"comment": "AI 参考资料确认记录"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        primary_key=True,
        default=uuid.uuid4,
    )
    novel_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        index=True,
        comment="手动 AI 操作标识，如 writing.generate",
    )
    task: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="本次上下文编译任务描述",
    )
    scope: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="上下文 scope",
    )
    context_mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="canonical",
        comment="上下文模式：canonical / working",
    )
    include_pending_objects: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="是否包含待确认对象",
    )
    excluded_asset_ids: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="本次排除的资产 ID",
    )
    selected_asset_ids: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="编译时纳入摘要的资产 ID",
    )
    user_note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="用户本次 AI 操作的额外注意事项",
    )
    compile_options: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="可重新编译上下文的选择参数",
    )
    warnings: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="编译告警摘要",
    )
    result_refs: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="由本确认记录触发的任务或产物引用",
    )
    result_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="confirmed",
        comment="结果追踪状态",
    )
    stale_reasons: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="上下文失效或需复核原因",
    )
    compiled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        comment="确认时重新编译完成时间",
    )


class ContextSnapshot(Base, TimestampMixin):
    """Automated AI-call context audit snapshot."""

    __tablename__ = "context_snapshots"
    __table_args__ = (
        Index(
            "ix_context_snapshots_novel_workflow_phase",
            "novel_id",
            "workflow_id",
            "phase",
        ),
        Index("ix_context_snapshots_novel_created", "novel_id", "created_at"),
        Index("ix_context_snapshots_status", "status"),
        Index(
            "ix_context_snapshots_rendered_expires",
            "rendered_context_expires_at",
        ),
        {"comment": "AI 调用上下文快照审计记录"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        primary_key=True,
        default=uuid.uuid4,
    )
    novel_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    workflow_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    phase: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(128), nullable=False)
    scene_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scene_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chapter_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    context_mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="working",
    )
    include_pending_objects: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="running",
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_name: Mapped[str] = mapped_column(String(128), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    compile_options: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    included_asset_ids: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    excluded_asset_ids: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    context_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    section_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    token_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    rendered_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    error_kind: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    rendered_context_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class EvidenceLink(Base, TimestampMixin):
    """Provenance link from a domain target/field to original manuscript text."""

    __tablename__ = "evidence_links"
    __table_args__ = (
        Index("ix_evidence_links_novel_target", "novel_id", "target_hash"),
        Index("ix_evidence_links_novel_status", "novel_id", "status"),
        {"comment": "业务资产字段到原始正文的来源链接"},
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    novel_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_ref: Mapped[dict] = mapped_column(JSON, nullable=False)
    target_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    claim_path: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    evidence_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_ref: Mapped[dict] = mapped_column(JSON, nullable=False)
    precision: Mapped[str] = mapped_column(String(32), nullable=False, default="range")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    provenance: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class ContextRetrievalTrace(Base, TimestampMixin):
    """Privacy-safe diagnostics for a context RAG retrieval execution."""

    __tablename__ = "context_retrieval_traces"
    __table_args__ = (
        Index(
            "ix_context_retrieval_traces_novel_mode_created",
            "novel_id",
            "content_mode",
            "created_at",
        ),
        {"comment": "上下文检索运行诊断，不保存正文或原始 query"},
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    novel_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    content_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    consumer_action: Mapped[str] = mapped_column(
        String(128), nullable=False, default="generic"
    )
    retrieval_purpose: Mapped[str] = mapped_column(
        String(64), nullable=False, default="generic_context"
    )
    reveal_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    scene_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    chapter_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    plan_version: Mapped[str] = mapped_column(String(32), nullable=False)
    plan_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    clause_summaries: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unique_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hydrated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    drop_counts: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    safe_empty_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    degraded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    warning_codes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    latency_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class ContextActivationProfile(Base, TimestampMixin):
    """Versioned deterministic activation policy aggregate."""

    __tablename__ = "context_activation_profiles"
    __table_args__ = (
        UniqueConstraint(
            "novel_id",
            "profile_key",
            name="uq_context_activation_profile_key",
        ),
        Index(
            "ix_context_activation_profiles_novel_status",
            "novel_id",
            "status",
        ),
        {"comment": "上下文激活规则当前版本"},
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    novel_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    profile_key: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    applicable_actions_json: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    rules_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    budget_hints_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ContextActivationProfileRevision(Base, TimestampMixin):
    """Immutable snapshot of one published activation policy version."""

    __tablename__ = "context_activation_profile_revisions"
    __table_args__ = (
        UniqueConstraint(
            "profile_id",
            "version_number",
            name="uq_context_activation_profile_revision",
        ),
        {"comment": "上下文激活规则不可变版本"},
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    novel_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("context_activation_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    rule_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    revision_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
