"""
Project 数据模型
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, String, text
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
