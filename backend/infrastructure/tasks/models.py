"""
异步任务队列数据库模型

使用 PostgreSQL 表 + FOR UPDATE SKIP LOCKED 实现轻量任务队列。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, TimestampMixin, UUIDMixin


class AsyncTask(Base, UUIDMixin, TimestampMixin):
    """异步任务记录

    使用 FOR UPDATE SKIP LOCKED 实现并发安全的任务消费。
    """

    __tablename__ = "async_tasks"

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

    def __repr__(self) -> str:
        return f"<AsyncTask id={self.id} type={self.task_type} status={self.status}>"

    def mark_running(self) -> None:
        """标记任务为运行中"""
        now = datetime.now(UTC)
        self.status = "running"
        self.started_at = now
        self.heartbeat_at = now

    def mark_done(self, result_data: dict[str, Any] | None = None) -> None:
        """标记任务为已完成"""
        self.status = "done"
        self.finished_at = datetime.now(UTC)
        self.progress = 1.0
        if result_data:
            self.result = result_data

    def mark_failed(self, error: str) -> None:
        """标记任务为失败"""
        self.status = "failed"
        self.finished_at = datetime.now(UTC)
        self.error_message = error

    def mark_cancelled(self) -> None:
        """标记任务为已取消"""
        self.status = "cancelled"
        self.finished_at = datetime.now(UTC)

    def update_heartbeat(self) -> None:
        """更新心跳时间"""
        self.heartbeat_at = datetime.now(UTC)

    def update_progress(self, progress: float) -> None:
        """更新进度并刷新心跳"""
        self.progress = progress
        self.heartbeat_at = datetime.now(UTC)
