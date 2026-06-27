"""
Timeline 对外契约

定义其他模块可以安全依赖的时间线接口和数据类。
其他模块只能导入 contracts.py 和 facade.py。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from modules.timeline.schemas import (  # noqa: F401
    TimelineConflictWarning,
    TimelineEventContext,
)


@dataclass(frozen=True)
class TimelineEventContract:
    """时间线事件契约 — 其他模块通过此契约读取事件信息"""

    id: str
    """事件 ID"""
    title: str
    """事件标题"""
    summary: str
    """事件摘要"""
    order_index: int
    """事件顺序索引"""
    chapter_index: int | None = None
    """所属章节索引"""
    event_type: str | None = None
    """事件类型"""
    related_character_ids: list[str] = field(default_factory=list)
    """关联角色 ID 列表"""
    related_entity_ids: list[str] = field(default_factory=list)
    """关联世界对象 ID 列表"""
    related_thread_ids: list[str] = field(default_factory=list)
    """关联剧情线 ID 列表"""
    related_location_ids: list[str] = field(default_factory=list)
    """关联地点 ID 列表"""
    geo_effects: list[dict[str, Any]] = field(default_factory=list)
    """地理影响"""
    visibility: str = "author_only"
    """可见性"""
    known_by_character_ids: list[str] = field(default_factory=list)
    """已知该事件的角色 ID 列表"""


@dataclass(frozen=True)
class TimelineConflictWarningContract:
    """时间线冲突警告契约"""

    type: str = "order_conflict"
    """冲突类型"""
    description: str = ""
    """冲突描述"""
    severity: str = "warning"
    """严重程度"""
    source_event_ids: list[str] = field(default_factory=list)
    """相关事件 ID"""
    suggestion: str | None = None
    """修改建议"""
