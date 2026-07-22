"""
Memory ORM 模型

- MemoryEvent: 每章的变化事件（真相源）
- MemorySnapshot: 每 10 章物化节点（查询加速）
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, NovelMixin, UUIDMixin, UUIDType


class MemoryEvent(Base):
    """记忆变化事件 — 每章写入时记录，重放可得任意章的世界全景"""

    __tablename__ = "memory_events"
    __table_args__ = (
        UniqueConstraint(
            "novel_id",
            "chapter_index",
            "sequence",
            name="uq_memory_events_novel_chapter_sequence",
        ),
        UniqueConstraint(
            "novel_id",
            "scene_id",
            "scene_sequence",
            name="uq_memory_events_novel_scene_sequence",
        ),
    )

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
    scene_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
        comment="Scene 时间锚点；新事件必须提供",
    )
    scene_index: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        index=True,
        comment="Scene 逻辑顺序冗余，用于确定性重放",
    )
    scene_sequence: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Scene 内事件顺序",
    )
    dimension: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        index=True,
        comment="entities / relations / locations / knowledge",
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


class MemorySceneCheckpoint(Base, UUIDMixin):
    """Scene 结束后的单维度轻量状态；历史版本只软 supersede。"""

    __tablename__ = "memory_scene_checkpoints"
    __table_args__ = (
        Index(
            "uq_memory_scene_checkpoint_current",
            "novel_id",
            "scene_id",
            "dimension",
            unique=True,
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current = 1"),
        ),
        Index(
            "ix_memory_scene_checkpoint_order",
            "novel_id",
            "scene_index",
            "dimension",
        ),
        {"comment": "Scene 分维度轻量状态与覆盖缺口"},
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scene_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    scene_index: Mapped[int] = mapped_column(Integer, nullable=False)
    stage_index: Mapped[int] = mapped_column(Integer, nullable=False)
    dimension: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ready")
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="system_generated"
    )
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    state_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    display_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    gap_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    decision_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(UTC),
    )


class MemorySceneSnapshot(Base, UUIDMixin):
    """stage0、周期、章末和 latest 的稀疏全量 Scene 快照。"""

    __tablename__ = "memory_scene_snapshots"
    __table_args__ = (
        Index(
            "uq_memory_scene_snapshot_current_stage",
            "novel_id",
            "stage_index",
            unique=True,
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current = 1"),
        ),
        Index("ix_memory_scene_snapshot_latest", "novel_id", "is_latest"),
        {"comment": "Scene 时间轴稀疏全量快照"},
    )

    novel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scene_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    scene_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stage_index: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_reasons: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    full_state: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_latest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(UTC),
    )
