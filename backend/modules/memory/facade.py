"""
Memory Facade — 对外入口

其他模块只能从 facade 导入 memory 功能。
Facade 不写复杂业务逻辑，只做薄层转发。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.memory.contracts import (
    MemoryContinuityEvidenceContract,
    MemoryDeltaEventIngest,
    MemoryDeltaIngestResult,
)
from modules.memory.scene_projection import SceneMemoryProjectionService
from modules.memory.services import MemoryService

_memory = MemoryService()
_scene_memory = SceneMemoryProjectionService()


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
    return await _memory.create_delta_log(db, novel_id, **kwargs)


async def ingest_delta_events(
    db: AsyncSession,
    novel_id: str,
    events: list[MemoryDeltaEventIngest],
    *,
    result_refs: list[dict[str, str]] | None = None,
) -> MemoryDeltaIngestResult:
    """Ingest typed delta events into DeltaLog rows."""
    return await _memory.ingest_delta_events(
        db,
        novel_id,
        events,
        result_refs=result_refs,
    )


async def replace_scene_memory_events(
    db: AsyncSession,
    novel_id: str,
    *,
    scene_id: str,
    scene_index: int,
    chapter_index: int,
    events: list[dict[str, Any]],
):
    """Replace one Scene event stream, including an explicitly empty rerun."""
    return await _memory.record_scene_events(
        db,
        novel_id,
        scene_id=scene_id,
        scene_index=scene_index,
        chapter_index=chapter_index,
        events=events,
    )


async def count_deep_import_delta_logs_by_workflow(
    db: AsyncSession,
    novel_id: str,
    workflow_id: str,
) -> int:
    """Count deep import delta logs for cleanup reporting only."""
    return await _memory.count_deep_import_delta_logs_by_workflow(
        db,
        novel_id,
        workflow_id,
    )


async def ensure_scene_checkpoints(
    db: AsyncSession,
    novel_id: str,
    scene_id: str,
):
    """Build every Scene checkpoint through the requested Scene."""
    return await _scene_memory.ensure_scene(db, novel_id, scene_id)


async def get_scene_checkpoints(
    db: AsyncSession,
    novel_id: str,
    scene_id: str,
):
    return await _scene_memory.get_scene(db, novel_id, scene_id)


async def rollback_deep_import_delta_logs_by_workflow(
    db: AsyncSession,
    novel_id: str,
    workflow_id: str,
) -> int:
    """Soft-rollback workflow-owned import delta logs while retaining provenance."""
    return await _memory.rollback_deep_import_delta_logs_by_workflow(
        db,
        novel_id,
        workflow_id,
    )
