"""
Project 数据模型
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, TimestampMixin, UUIDMixin, UUIDType
from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID


class Project(Base, UUIDMixin, TimestampMixin):
    """小说项目 — 系统的根聚合"""

    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint(
            "project_kind IN ('author', 'interaction')",
            name="ck_projects_project_kind",
        ),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        default=lambda: BOOTSTRAP_ACCOUNT_ID,
        index=True,
        comment="项目唯一所有者；不通过业务响应暴露",
    )
    project_kind: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="author",
        index=True,
        comment="内部项目类型：author / interaction；不接受公共 API 写入",
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="项目标题",
    )
    genre: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="题材（如：玄幻、科幻、悬疑）",
    )
    tone: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="风格基调（如：严肃、轻松、黑暗）",
    )
    language: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="zh",
        comment="创作语言",
    )
    target_length: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        comment="目标规模（short/medium/novel/epic）",
    )
    current_stage: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        comment="当前创作阶段（world_building/outlining/writing/revising）",
    )
    default_reveal_policy: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="author_safe",
        comment="默认揭示策略",
    )
    settings: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="小说配置（JSON，如 temporary_entity_expiry_chapters）",
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="软删除时间，NULL 表示未删除",
    )

    def __repr__(self) -> str:
        return f"<Project id={self.id} title={self.title!r}>"


class SmartDedupWorkbenchDecision(Base, UUIDMixin, TimestampMixin):
    """Project-workbench disposition for one fingerprinted asset pair."""

    __tablename__ = "smart_dedup_workbench_decisions"
    __table_args__ = (
        CheckConstraint(
            "left_asset_id < right_asset_id",
            name="ck_smart_dedup_decision_sorted_pair",
        ),
        CheckConstraint(
            "decision = 'keep_separate'",
            name="ck_smart_dedup_decision_value",
        ),
        Index(
            "ix_smart_dedup_decision_lookup",
            "novel_id",
            "asset_type",
            "left_asset_id",
            "right_asset_id",
            "superseded_at",
        ),
        Index(
            "uq_smart_dedup_active_disposition",
            "novel_id",
            "asset_type",
            "left_asset_id",
            "right_asset_id",
            "left_semantic_fingerprint",
            "right_semantic_fingerprint",
            unique=True,
            postgresql_where=text("superseded_at IS NULL"),
            sqlite_where=text("superseded_at IS NULL"),
        ),
        {"comment": ("项目级智能去重工作台裁决；不替代 world/outline 领域判断")},
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    asset_type: Mapped[str] = mapped_column(String(64), nullable=False)
    left_asset_id: Mapped[str] = mapped_column(String(36), nullable=False)
    right_asset_id: Mapped[str] = mapped_column(String(36), nullable=False)
    left_semantic_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    right_semantic_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(
        String(32), nullable=False, default="keep_separate"
    )
    source_scan_task_id: Mapped[str] = mapped_column(String(36), nullable=False)
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ProjectAuthorTask(Base, UUIDMixin, TimestampMixin):
    """Author-owned lightweight task, distinct from async worker tasks."""

    __tablename__ = "project_author_tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'completed', 'archived')",
            name="ck_project_author_tasks_status",
        ),
        CheckConstraint(
            "length(trim(title)) > 0",
            name="ck_project_author_tasks_title_not_blank",
        ),
        CheckConstraint(
            "note IS NULL OR length(note) <= 4000",
            name="ck_project_author_tasks_note_length",
        ),
        CheckConstraint(
            "(source_kind IS NULL) = (source_id IS NULL)",
            name="ck_project_author_tasks_source_pair",
        ),
        CheckConstraint(
            "source_kind IS NULL OR source_kind IN "
            "('world_page', 'world_entity', 'writing_chapter', 'outline_scene')",
            name="ck_project_author_tasks_source_kind",
        ),
        CheckConstraint(
            "(status = 'completed' AND completed_at IS NOT NULL) OR "
            "(status <> 'completed' AND completed_at IS NULL)",
            name="ck_project_author_tasks_completed_at",
        ),
        Index(
            "ix_project_author_tasks_scope",
            "novel_id",
            "status",
            "due_date",
            "updated_at",
        ),
        {"comment": "作者个人轻量待办；不承载领域决定或后台任务"},
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="open", index=True
    )
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    source_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
