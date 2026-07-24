"""
异步任务队列数据库模型

使用 PostgreSQL 表 + FOR UPDATE SKIP LOCKED 实现轻量任务队列。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, TimestampMixin, UUIDMixin


class AsyncTask(Base, UUIDMixin, TimestampMixin):
    """异步任务记录

    使用 FOR UPDATE SKIP LOCKED 实现并发安全的任务消费。
    """

    __tablename__ = "async_tasks"
    __table_args__ = (
        Index(
            "uq_async_tasks_coalescing_pending",
            "coalescing_key",
            unique=True,
            postgresql_where=text(
                "coalescing_key IS NOT NULL AND status = 'pending'"
            ),
            sqlite_where=text("coalescing_key IS NOT NULL AND status = 'pending'"),
        ),
        Index(
            "uq_async_tasks_coalescing_running",
            "coalescing_key",
            unique=True,
            postgresql_where=text(
                "coalescing_key IS NOT NULL AND status = 'running'"
            ),
            sqlite_where=text("coalescing_key IS NOT NULL AND status = 'running'"),
        ),
        Index(
            "ix_async_tasks_coalescing_created",
            "coalescing_key",
            "created_at",
        ),
    )

    task_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="任务类型标识，如 embedding_build, rag_reindex 等",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        index=True,
        comment="任务状态：pending / running / done / failed / cancelled",
    )
    progress: Mapped[float | None] = mapped_column(
        Float,
        default=0.0,
        comment="任务进度 0.0 ~ 1.0",
    )
    meta: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        default=dict,
        comment="任务元数据（入参、配置等）",
    )
    result: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        default=dict,
        comment="任务执行结果",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        default=None,
        comment="错误信息（任务失败时）",
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
        comment="任务开始执行时间",
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
        comment="任务完成（或失败）时间",
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
        comment="上次心跳时间",
    )
    attempt: Mapped[int] = mapped_column(
        default=0,
        nullable=False,
        comment="已领取次数；首次 claim 后为 1",
    )
    max_attempts: Mapped[int] = mapped_column(
        default=1,
        nullable=False,
        comment="冻结的最大领取次数",
    )
    recovery_policy: Mapped[str] = mapped_column(
        String(32),
        default="restart_origin",
        nullable=False,
        comment="auto_requeue/manual_resume/restart_origin/never_retry",
    )
    lease_id: Mapped[str | None] = mapped_column(
        String(36),
        default=None,
        nullable=True,
        index=True,
        comment="当前 worker lease；pending/terminal 为空",
    )
    stale_detected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
        nullable=True,
    )
    transition_reason: Mapped[str | None] = mapped_column(
        String(64),
        default=None,
        nullable=True,
    )
    coalescing_key: Mapped[str | None] = mapped_column(
        String(64),
        default=None,
        nullable=True,
        comment="内部 keyed-coalescing identity 的 SHA-256；不得进入公开响应或日志",
    )

    def __repr__(self) -> str:
        return f"<AsyncTask id={self.id} type={self.task_type} status={self.status}>"

    def mark_running(self, *, lease_id: str | None = None) -> None:
        """标记任务为运行中"""
        now = datetime.now(UTC)
        self.status = "running"
        self.started_at = now
        self.heartbeat_at = now
        self.attempt = int(self.attempt or 0) + 1
        self.lease_id = lease_id or str(uuid.uuid4())
        self.finished_at = None
        self.transition_reason = None
        self.error_message = None

    def mark_done(self, result_data: dict[str, Any] | None = None) -> None:
        """标记任务为已完成"""
        self.status = "done"
        self.finished_at = datetime.now(UTC)
        self.progress = 1.0
        self.lease_id = None
        if result_data:
            self.result = result_data

    def mark_failed(self, error: str) -> None:
        """标记任务为失败"""
        self.status = "failed"
        self.finished_at = datetime.now(UTC)
        self.error_message = error
        self.lease_id = None

    def mark_cancelled(self) -> None:
        """标记任务为已取消"""
        self.status = "cancelled"
        self.finished_at = datetime.now(UTC)
        self.lease_id = None

    def update_heartbeat(self) -> None:
        """更新心跳时间"""
        self.heartbeat_at = datetime.now(UTC)

    def update_progress(self, progress: float) -> None:
        """更新进度并刷新心跳"""
        self.progress = progress
        self.heartbeat_at = datetime.now(UTC)
