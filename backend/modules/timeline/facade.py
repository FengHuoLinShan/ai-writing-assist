"""
Timeline Facade — 对外入口

其他模块只能从 facade 导入。
Facade 不写复杂业务逻辑，只做稳定的对外代理。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.timeline.schemas import (
    TimelineConflictWarning,
    TimelineEventContext,
)
from modules.timeline.services import TimelineService

_service = TimelineService()


async def get_relevant_timeline_context(
    db: AsyncSession,
    novel_id: str,
    chapter_index: int | None = None,
    related_entity_ids: list[str] | None = None,
    character_id: str | None = None,
    limit: int = 12,
    reveal_mode: str = "author_safe",
) -> list[TimelineEventContext]:
    """获取相关时间线上下文

    用于 Context Compiler 组装创作上下文。
    只返回 status='canonical' 的事件，按顺序排列。
    在 author_safe 模式下过滤 author_only 可见性的事件。

    Args:
        db: 数据库 session
        novel_id: 项目 ID
        chapter_index: 只返回该章节之前的事件
        related_entity_ids: 按关联实体过滤
        character_id: 按关联角色过滤
        limit: 最大返回条数（默认 12）
        reveal_mode: author_only / author_safe（默认 author_safe）

    Returns:
        list[TimelineEventContext]: 时间线事件上下文列表
    """
    events = await _service.get_relevant_timeline_context(
        db,
        novel_id,
        chapter_index=chapter_index,
        related_entity_ids=related_entity_ids,
        character_id=character_id,
        limit=limit,
    )
    # author_safe 模式下过滤 visibility 为 author_only 的事件
    if reveal_mode == "author_safe":
        events = [
            e for e in events
            if getattr(e, "visibility", "reader_known") != "author_only"
        ]
    return events


async def get_geo_effects_up_to_chapter(
    db: AsyncSession,
    novel_id: str,
    chapter_index: int,
) -> list[dict[str, Any]]:
    """获取截止某章节的所有地理影响数据

    供 Geo 模块调用，获取时间线事件中的 geo_effects 数据。
    只返回 status='canonical' 且 chapter_index <= X（含 chapter_index 为 NULL 的全局事件）的事件的 geo_effects，
    按事件 order_index 顺序合并。

    Args:
        db: 数据库 session
        novel_id: 项目 ID
        chapter_index: 截止章节索引

    Returns:
        list[dict]: 合并后的 geo_effects 列表
    """
    return await _service.get_geo_effects_up_to_chapter(
        db, novel_id, chapter_index,
    )


async def check_timeline_conflicts(
    db: AsyncSession,
    novel_id: str,
    structure_candidate: dict[str, Any],
) -> list[TimelineConflictWarning]:
    """检查候选结构事件是否与已有 timeline 冲突

    检查维度：
    - 顺序矛盾
    - 事件重复
    - 角色位置冲突

    Args:
        db: 数据库 session
        novel_id: 项目 ID
        structure_candidate: 候选结构（含 events 列表）

    Returns:
        list[TimelineConflictWarning]: 冲突警告列表
    """
    return await _service.check_timeline_conflicts(
        db, novel_id, structure_candidate
    )
