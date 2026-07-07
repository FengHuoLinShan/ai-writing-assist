"""Settings module ORM models."""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, TimestampMixin, UUIDMixin


class GlobalLLMDefaults(Base, UUIDMixin, TimestampMixin):
    """全局 LLM 默认（owner 隔离，不含 API Key）。

    所有非 PK 字段允许 NULL，NULL = 继承系统内置默认（D2）。
    deep_import 列保留但本期永不写入（D9）。
    """

    __tablename__ = "global_llm_defaults"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        nullable=False,
        unique=True,
        index=True,
        comment="owner 占位；demo=LOCAL_OWNER_ID nil UUID",
    )
    provider_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    model: Mapped[str | None] = mapped_column(String(256), nullable=True)
    timeout: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    top_p: Mapped[float | None] = mapped_column(Float, nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    creative_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    deep_import: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class GlobalAuthorPreferences(Base, UUIDMixin, TimestampMixin):
    """全局作者偏好默认（owner 隔离）。"""

    __tablename__ = "global_author_preferences"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        nullable=False,
        unique=True,
        index=True,
    )
    daily_goal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    editor_font: Mapped[str | None] = mapped_column(String(32), nullable=True)
    default_focus_mode: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )


class ProjectAuthorPreferences(Base, UUIDMixin, TimestampMixin):
    """项目级作者偏好覆盖。

    所有字段允许 NULL：NULL = 继承全局（D2）。
    UNIQUE(project_id) 保证每个项目最多一行。
    """

    __tablename__ = "project_author_preferences"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    daily_goal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    editor_font: Mapped[str | None] = mapped_column(String(32), nullable=True)
    default_focus_mode: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )
