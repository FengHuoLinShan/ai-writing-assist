"""
Memory ORM 模型

- MemoryEvent: 每章的变化事件（真相源）
- MemorySnapshot: 每 10 章物化节点（查询加速）
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, NovelMixin, UUIDMixin, UUIDType


class MemoryEvent(Base):
    """记忆变化事件 — 每章写入时记录，重放可得任意章的世界全景"""

    __tablename__ = "memory_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    novel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chapter_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="所属章节",
    )
    sequence: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="章内事件顺序",
    )
    event_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="事件类型",
    )
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
        comment="影响的实体 ID",
    )
    entity_type: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        comment="实体类型",
    )
    snapshot_before: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        comment="变化前状态",
    )
    snapshot_after: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        comment="变化后状态",
    )
    source: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="ai_extraction",
        comment="来源",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(UTC),
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
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    novel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chapter_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="快照对应章节",
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="current",
        comment="current | stale",
    )
    full_state: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        comment="完整世界状态",
    )
    events_until: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="覆盖到第几个事件序号",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(UTC),
    )

    def __repr__(self) -> str:
        return f"<MemorySnapshot ch={self.chapter_index} status={self.status!r}>"


class DeltaLog(Base, UUIDMixin, NovelMixin):
    """实体变更日志 — 记录每次结构化字段的 before/after"""

    __tablename__ = "delta_log"
    __table_args__ = {"comment": "实体变更日志"}

    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        nullable=True,
        index=True,
        comment="关联实体 ID",
    )
    character_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        nullable=True,
        comment="关联网格人物 ID",
    )
    scene_index: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="变更发生的 Scene",
    )
    category: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="变更类别",
    )
    field_path: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="变更字段路径",
    )
    old_value: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="变更前的值",
    )
    new_value: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="变更后的值",
    )
    source: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="ai_extraction",
        comment="来源: ai_extraction / manual_edit / manual_rollback",
    )
    meta: Mapped[dict] = mapped_column(
        JSON,
        nullable=True,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"<DeltaLog id={self.id} entity={self.entity_id} "
            f"category={self.category} field={self.field_path}>"
        )
