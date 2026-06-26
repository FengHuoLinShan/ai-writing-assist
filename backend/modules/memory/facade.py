"""
Memory Facade — 对外入口

其他模块只能从 facade 导入 memory 功能。
Facade 不写复杂业务逻辑，只做薄层转发。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.memory.services import MemoryService

_memory = MemoryService()


async def get_memory_panorama(
    db: AsyncSession,
    novel_id: str,
    chapter_index: int,
):
    """获取指定章节的世界全景（事件溯源视角）。"""
    return await _memory.get_panorama(db, novel_id, chapter_index)


async def capture_snapshot(
    db: AsyncSession,
    novel_id: str,
    chapter_index: int,
):
    """捕获指定章节的记忆快照。"""
    return await _memory.capture_snapshot(db, novel_id, chapter_index)


async def create_delta_log(
    db: AsyncSession,
    novel_id: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """创建 Delta Log 记录，返回 dict。"""
    from modules.memory.models import DeltaLog
    from shared.utils import parse_uuid

    nid = parse_uuid(novel_id, "novel_id")
    delta = DeltaLog(
        novel_id=nid,
        **kwargs,
    )
    db.add(delta)
    await db.flush()
    return {
        "id": str(delta.id),
        "novel_id": str(delta.novel_id),
        "entity_id": str(delta.entity_id) if delta.entity_id else None,
        "category": delta.category,
        "source": delta.source,
        "scene_index": delta.scene_index,
        "field_path": delta.field_path,
    }
