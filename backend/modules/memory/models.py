"""
Memory ORM 模型

- MemoryEvent: 每章的变化事件（真相源）
- MemorySnapshot: 每 10 章物化节点（查询加速）
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base


class MemoryEvent(Base):
    """记忆变化事件 — 每章写入时记录，重放可得任意章的世界全景"""

    __tablename__ = "memory_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    novel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chapter_index: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="所属章节",
    )
    sequence: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="章内事件顺序",
    )
    event_type: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True, comment="事件类型",
    )
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True, comment="影响的实体 ID",
    )
    entity_type: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="实体类型",
    )
    snapshot_before: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, comment="变化前状态",
    )
    snapshot_after: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, comment="变化后状态",
    )
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ai_extraction", comment="来源",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return (
            f"<MemoryEvent ch={self.chapter_index} seq={self.sequence} "
            f"type={self.event_type!r}>"
        )


class MemorySnapshot(Base):
    """记忆阶段性快照 — 每 10 章物化，加速全景查询"""

    __tablename__ = "memory_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    novel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chapter_index: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="快照对应章节",
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="current", comment="current | stale",
    )
    full_state: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, comment="完整世界状态",
    )
    events_until: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="覆盖到第几个事件序号",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return (
            f"<MemorySnapshot ch={self.chapter_index} "
            f"status={self.status!r}>"
        )
