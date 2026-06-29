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
    if not pov_character_id or not current_location_id or chapter_index <= 1:
        return None
    previous_chapter = chapter_index - 1
    panorama = await get_memory_panorama(db, novel_id, previous_chapter)
    character_locations = getattr(panorama, "character_locations", None) or {}
    if not isinstance(character_locations, dict):
        return None
    previous_location = character_locations.get(pov_character_id)
    if previous_location is None:
        return None
    previous_location_id = getattr(previous_location, "location_id", None)
    if previous_location_id is None and isinstance(previous_location, dict):
        previous_location_id = previous_location.get("location_id")
    if not previous_location_id or previous_location_id == current_location_id:
        return None
    previous_text = getattr(previous_location, "text_state", None)
    if previous_text is None and isinstance(previous_location, dict):
        previous_text = previous_location.get("text_state")
    previous_text = previous_text or str(previous_location_id)
    current_text = current_location_name or current_location_id
    return MemoryContinuityEvidenceContract(
        source_module="memory",
        source_type="memory.character_location",
        source_id=pov_character_id,
        source_label=f"章节记忆：第 {previous_chapter} 章",
        source_field="角色位置",
        source_excerpt=f"上一章 {previous_text}，当前 {current_text}",
        open_target={
            "kind": "memory_chapter",
            "chapter_index": previous_chapter,
            "character_id": pov_character_id,
        },
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
