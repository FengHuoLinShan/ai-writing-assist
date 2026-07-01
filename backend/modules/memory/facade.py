"""
Memory Facade — 对外入口

其他模块只能从 facade 导入 memory 功能。
Facade 不写复杂业务逻辑，只做薄层转发。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.memory.contracts import MemoryContinuityEvidenceContract
from modules.memory.services import MemoryService

_memory = MemoryService()


async def get_memory_panorama(
    db: AsyncSession,
    novel_id: str,
    chapter_index: int,
):
    """获取指定章节的世界全景（事件溯源视角）。"""
    return await _memory.get_panorama(db, novel_id, chapter_index)


async def get_continuity_evidence_for_writing(
    db: AsyncSession,
    novel_id: str,
    chapter_index: int,
    *,
    pov_character_id: str | None,
    current_location_id: str | None,
    current_location_name: str | None = None,
) -> MemoryContinuityEvidenceContract | None:
    """Return previous-location evidence for writing continuity checks."""
    return await _memory.get_continuity_evidence_for_writing(
        db,
        novel_id,
        chapter_index,
        pov_character_id=pov_character_id,
        current_location_id=current_location_id,
        current_location_name=current_location_name,
    )


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


async def count_deep_import_delta_logs_by_workflow(
    db: AsyncSession,
    novel_id: str,
    workflow_id: str,
) -> int:
    """Count deep import delta logs for cleanup reporting only."""
    from sqlalchemy import select

    from modules.memory.models import DeltaLog
    from shared.utils import parse_uuid

    nid = parse_uuid(novel_id, "novel_id")
    stmt = select(DeltaLog).where(
        DeltaLog.novel_id == nid,
        DeltaLog.source == "deep_import",
    )
    result = await db.execute(stmt)
    items = result.scalars().all()
    return sum(
        1
        for item in items
        if (item.meta or {}).get("workflow_id") == workflow_id
        and (item.meta or {}).get("auto_ingested") is True
    )
