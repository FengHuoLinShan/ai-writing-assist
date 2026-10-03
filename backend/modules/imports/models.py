"""
Import ORM 模型

对应 import_records 和 imported_chapters 表。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    and_,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, NovelMixin, TimestampMixin, UUIDMixin


class ImportRecord(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """导入记录 — 记录每次文件导入的结果"""

    __tablename__ = "import_records"

    file_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="原始文件名",
    )
    file_type: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        comment="文件类型：txt/epub/html/mobi",
    )
    file_size: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="文件大小（字节）",
    )
    total_chapters: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="解析出的章节总数",
    )
    imported_chapters: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="成功导入的章节数",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        comment="状态：pending/processing/done/failed",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="错误信息（status=failed 时填充）",
    )
    import_kind: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="manuscript",
        comment="manuscript / source_revision",
    )

    __table_args__ = (
        Index(
            "uq_import_records_done_file_name",
            "novel_id",
            "file_name",
            unique=True,
            postgresql_where=and_(status == "done", import_kind == "manuscript"),
            sqlite_where=and_(status == "done", import_kind == "manuscript"),
        ),
        CheckConstraint(
            "import_kind IN ('manuscript', 'source_revision')",
            name="ck_import_records_import_kind",
        ),
        {"comment": "小说文件导入记录"},
    )

    def __repr__(self) -> str:
        return (
            f"<ImportRecord id={self.id} file={self.file_name!r} "
            f"type={self.file_type} status={self.status}>"
        )


class ImportedChapter(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """已导入的章节正文内容"""

    __tablename__ = "imported_chapters"
    __table_args__ = {"comment": "已导入的章节内容"}

    import_record_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("import_records.id", ondelete="CASCADE"),
        nullable=False,
    )
    chapter_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="章节序号",
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="章节标题",
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="章节正文",
    )
    is_analyzed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="是否已分析（实体/关系提取）",
    )

    def __repr__(self) -> str:
        return (
            f"<ImportedChapter id={self.id} index={self.chapter_index} "
            f"title={self.title!r}>"
        )


class ImportWorkflowRun(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """Imports-owned durable workflow state and attempt ownership.

    ``async_tasks`` remains the queue/lease projection.  This row owns the
    recoverable domain checkpoint and fences every write-capable workflow
    attempt with ``task_id + generation + owner_attempt + owner_lease_id``.
    """

    __tablename__ = "import_workflow_runs"
    __table_args__ = (
        Index(
            "uq_import_workflow_runs_active_novel",
            "novel_id",
            unique=True,
            postgresql_where=text(
                "status IN ('pending', 'running') OR recovery_required = true"
            ),
            sqlite_where=text(
                "status IN ('pending', 'running') OR recovery_required = 1"
            ),
        ),
        Index(
            "ix_import_workflow_runs_task_generation",
            "task_id",
            "generation",
        ),
        {"comment": "imports-owned deep-import/map enrichment workflow state"},
    )

    task_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("async_tasks.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    workflow_type: Mapped[str] = mapped_column(String(64), nullable=False)
    stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    start_chapter: Mapped[int] = mapped_column(Integer, nullable=False)
    end_chapter: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        index=True,
    )
    generation: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )
    owner_task_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("async_tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    owner_attempt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    owner_lease_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    recovery_required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    authorization_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    llm_execution_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    prepare_checkpoint: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    checkpoints: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    progress: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    def __repr__(self) -> str:
        return (
            f"<ImportWorkflowRun id={self.id} task={self.task_id} "
            f"type={self.workflow_type} status={self.status} "
            f"generation={self.generation}>"
        )


class ImportMigrationSession(Base, UUIDMixin, TimestampMixin, NovelMixin):
    """表格迁移会话（ADR-0030）— 草稿期暂存有界单元格，采用或删除后清空 rows。

    回执只存 id、hash 和被改字段的原值，不存正文。
    """

    __tablename__ = "import_migration_sessions"
    __table_args__ = (
        Index("ix_import_migration_sessions_novel_created", "novel_id", "created_at"),
        CheckConstraint(
            "status IN ('draft', 'applied', 'rolled_back', 'partially_rolled_back')",
            name="ck_import_migration_sessions_status",
        ),
        {"comment": "表格迁移（xlsx/csv）作者会话"},
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="创建会话的账户",
    )
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default="draft",
        comment="draft / applied / rolled_back / partially_rolled_back",
    )
    revision: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        comment="mapping/decisions/AI 结果写入时 +1，作 CAS 用",
    )
    file_manifest: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="文件与表的清单（不含单元格）",
    )
    rows_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="{sheet_key: rows}；采用或删除后置空",
    )
    mapping_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="表类型、表头行与列映射",
    )
    decisions_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="作者逐项决策与关系种类分组",
    )
    plan_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="最近一次 world/story 计划及其 fingerprint",
    )
    preview_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="最近一次预览的稳定 hash",
    )
    ai_task_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("async_tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    ai_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="idle",
        comment="idle / queued / running / done / failed",
    )
    ai_scope_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="AI 任务绑定的 scope 指纹",
    )
    ai_authorization: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="AI 运行授权快照",
    )
    ai_result_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="AI 整理结果（仅预览用）",
    )
    receipt_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="{world, story, counts}；不含正文",
    )
    error_code: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="失败时的机器码（不含正文）",
    )
    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    rolled_back_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"<ImportMigrationSession id={self.id} status={self.status} "
            f"revision={self.revision}>"
        )
