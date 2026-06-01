"""
Memory Facade — 对外入口

其他模块只能从 facade 导入。
Facade 不写复杂业务逻辑，只做稳定的对外代理。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.memory.schemas import (
    ChapterPanorama,
    MemoryEventResponse,
    MemoryStatusResponse,
    SnapshotResponse,
)
from modules.memory.services import MemoryService

_service = MemoryService()


async def record_events(
    db: AsyncSession,
    novel_id: str,
    chapter_index: int,
    events: list[dict[str, Any]],
) -> list[MemoryEventResponse]:
    """记录一章的变化事件"""
    return await _service.record_events(db, novel_id, chapter_index, events)


async def get_chapter_panorama(
    db: AsyncSession,
    novel_id: str,
    chapter_index: int,
) -> ChapterPanorama:
    """获取指定章节的世界全景"""
    return await _service.get_panorama(db, novel_id, chapter_index)


async def capture_snapshot(
    db: AsyncSession,
    novel_id: str,
    chapter_index: int,
) -> SnapshotResponse:
    """在指定章节生成快照"""
    return await _service.capture_snapshot(db, novel_id, chapter_index)


async def mark_stale(
    db: AsyncSession,
    novel_id: str,
    from_chapter: int,
) -> dict[str, Any]:
    """标记从指定章节开始的所有快照为过时"""
    return await _service.mark_stale(db, novel_id, from_chapter)


async def full_rebuild(
    db: AsyncSession,
    novel_id: str,
    from_chapter: int,
) -> dict[str, Any]:
    """从前文修正点全量重建后续事件和快照"""
    return await _service.full_rebuild(db, novel_id, from_chapter)


async def get_status(
    db: AsyncSession,
    novel_id: str,
) -> MemoryStatusResponse:
    """获取 memory 模块当前状态"""
    return await _service.get_status(db, novel_id)
