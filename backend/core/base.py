"""
SQLAlchemy Base ORM 模型与公共 Mixin

提供：
- Base: declarative_base() 基类
- UUIDMixin: UUID 主键
- TimestampMixin: created_at / updated_at 时间戳
- StatusMixin: status 状态字段
- NovelMixin: novel_id 外键
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """SQLAlchemy 声明式基类"""

    pass


class UUIDMixin:
    """UUID 主键 Mixin"""

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )


class TimestampMixin:
    """创建/更新时间戳 Mixin

    修复：统一使用 UTC 时区，添加 server_onupdate
    （Bug H1: server_default 与 default 时区不一致 → 统一 UTC）
    （Bug H2: 缺 server_onupdate → 添加）
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.timezone("utc", func.now()),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        server_default=func.timezone("utc", func.now()),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        server_onupdate=func.timezone("utc", func.now()),
    )


class StatusMixin:
    """状态字段 Mixin — 使用 String 列以支持灵活状态枚举"""

    status: Mapped[str] = mapped_column(
        String(32),
        default="draft",
        index=True,
    )


class NovelMixin:
    """小说项目外键 Mixin"""

    novel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
