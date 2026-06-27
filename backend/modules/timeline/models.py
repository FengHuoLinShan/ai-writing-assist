"""
Timeline ORM 模型

包含：
- TimelineEvent: timeline_events 表 — 正史时间线事件
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, NovelMixin, TimestampMixin, UUIDMixin


class TimelineEvent(Base, UUIDMixin, NovelMixin, TimestampMixin):
    """时间线事件 — 正史事件顺序记录"""

    __tablename__ = "timeline_events"

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="事件标题",
    )
    summary: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="事件摘要",
    )
    order_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True,
        comment="事件顺序索引（绝对值，非章节内顺序）",
    )
    chapter_index: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="所属章节索引",
    )
    event_type: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment=(
            "事件类型（plot / character / world / battle / travel / discovery / "
            "relationship / geo_change / offscreen）"
        ),
    )
    related_character_ids: Mapped[list[Any]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="关联角色 ID 列表",
    )
    related_entity_ids: Mapped[list[Any]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="关联世界对象 ID 列表",
    )
    related_thread_ids: Mapped[list[Any]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="关联剧情线 ID 列表",
    )
    related_location_ids: Mapped[list[Any]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="关联地点 ID 列表",
    )
    geo_effects: Mapped[list[Any]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="地理影响列表（如某地点被毁、道路被阻断）",
    )
    visibility: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="author_only",
        comment="可见性（author_only / author_safe / reader_known / public）",
    )
    known_by_character_ids: Mapped[list[Any]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="已知该事件的角色 ID 列表",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="candidate",
        index=True,
        comment="状态（candidate / canonical / deprecated）",
    )

    def __repr__(self) -> str:
        return (
            f"<TimelineEvent id={self.id} order={self.order_index} title={self.title!r}>"
        )
