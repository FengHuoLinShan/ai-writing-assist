"""
Project 数据模型
"""

from __future__ import annotations

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, TimestampMixin, UUIDMixin


class Project(Base, UUIDMixin, TimestampMixin):
    """小说项目 — 系统的根聚合"""

    __tablename__ = "projects"

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

    def __repr__(self) -> str:
        return f"<Project id={self.id} title={self.title!r}>"
