"""
Memory API 路由

提供世界全景查询、事件时间线、快照管理和全更新接口。
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from core.api_params import NovelIdPath
from core.dependencies import DbSession
from modules.story.continuity.scene_projection import SceneMemoryProjectionService
from modules.story.continuity.schemas import (
    ChapterPanorama,
    EventListResponse,
    MemoryStatusResponse,
    SceneCheckpointEnsureRequest,
    SceneCheckpointRebuildRequest,
    SceneCheckpointRepairRequest,
    SceneCheckpointRepairResponse,
    SceneCheckpointSetResponse,
    SnapshotListResponse,
    SnapshotResponse,
)
from modules.story.continuity.services import MemoryService

router = APIRouter(prefix="/api/novels/{novel_id}/memories", tags=["memory"])
_service = MemoryService()
_scene_service = SceneMemoryProjectionService()


async def _require_active_project(db: DbSession, novel_id: str) -> None:
    from modules.project.facade import require_active_project

    await require_active_project(db, novel_id)


# ============================================================
# 全景
# ============================================================


@router.get("/panorama", response_model=ChapterPanorama)
async def get_panorama(
    db: DbSession,
    novel_id: NovelIdPath,
    chapter_index: int = Query(..., ge=1, description="章节号"),
) -> ChapterPanorama:
    """获取指定章节的世界全景"""
    await _require_active_project(db, novel_id)
    return await _service.get_panorama(db, novel_id, chapter_index)


# ============================================================
# 事件
# ============================================================


@router.get("/events", response_model=EventListResponse)
async def list_events(
    db: DbSession,
    novel_id: NovelIdPath,
    from_chapter: int = Query(default=1, ge=1, description="起始章"),
    to_chapter: int = Query(default=999999, ge=1, description="结束章"),
) -> EventListResponse:
    """查询事件列表"""
    await _require_active_project(db, novel_id)
    return await _service.list_events(db, novel_id, from_chapter, to_chapter)


@router.get("/events/{entity_id}/timeline", response_model=EventListResponse)
async def get_entity_timeline(
    db: DbSession,
    novel_id: NovelIdPath,
    entity_id: str,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
) -> EventListResponse:
    """获取单个实体的变化时间线"""
    await _require_active_project(db, novel_id)
    return await _service.get_entity_timeline(
        db,
        novel_id,
        entity_id,
        skip,
        limit,
    )


# ============================================================
# 快照
# ============================================================


@router.post("/snapshots/capture", response_model=SnapshotResponse, status_code=201)
async def trigger_capture(
    db: DbSession,
    novel_id: NovelIdPath,
    chapter_index: int = Query(..., ge=1, description="章节号"),
) -> SnapshotResponse:
    """手动生成快照"""
    await _require_active_project(db, novel_id)
    return await _service.capture_snapshot(db, novel_id, chapter_index)


@router.get("/snapshots", response_model=SnapshotListResponse)
async def list_snapshots(
    db: DbSession,
    novel_id: NovelIdPath,
) -> SnapshotListResponse:
    """列出所有快照"""
    await _require_active_project(db, novel_id)
    return await _service.list_snapshots(db, novel_id)


# ============================================================
# 全更新
# ============================================================


@router.post("/rebuild")
async def trigger_rebuild(
    db: DbSession,
    novel_id: NovelIdPath,
    from_chapter: int = Query(..., ge=1, description="从哪一章开始重建"),
) -> dict:
    """从前文修正点全量重建后续事件和快照"""
    await _require_active_project(db, novel_id)
    return await _service.full_rebuild(db, novel_id, from_chapter)


# ============================================================
# 状态
# ============================================================


@router.get("/status", response_model=MemoryStatusResponse)
async def get_status(
    db: DbSession,
    novel_id: NovelIdPath,
) -> MemoryStatusResponse:
    """获取 memory 模块当前状态"""
    await _require_active_project(db, novel_id)
    return await _service.get_status(db, novel_id)


@router.get("/scene-checkpoints", response_model=SceneCheckpointSetResponse)
async def get_scene_checkpoints(
    db: DbSession,
    novel_id: NovelIdPath,
    scene_id: str = Query(..., description="Scene ID"),
) -> SceneCheckpointSetResponse:
    """读取已有 Scene 分维度 checkpoint，不在 GET 中隐式写入。"""
    await _require_active_project(db, novel_id)
    return await _scene_service.get_scene(db, novel_id, scene_id)


@router.post("/scene-checkpoints/ensure", response_model=SceneCheckpointSetResponse)
async def ensure_scene_checkpoints(
    db: DbSession,
    novel_id: NovelIdPath,
    request: SceneCheckpointEnsureRequest,
) -> SceneCheckpointSetResponse:
    """确定性生成截至目标 Scene 的全部维度 checkpoint。"""
    await _require_active_project(db, novel_id)
    return await _scene_service.ensure_scene(db, novel_id, request.scene_id)


@router.post("/scene-checkpoints/rebuild")
async def rebuild_scene_checkpoints(
    db: DbSession,
    novel_id: NovelIdPath,
    request: SceneCheckpointRebuildRequest,
) -> dict:
    await _require_active_project(db, novel_id)
    return await _scene_service.rebuild_from_scene(
        db,
        novel_id,
        from_scene_id=request.from_scene_id,
        dimensions=request.dimensions,
    )


@router.post(
    "/scene-checkpoints/repair",
    response_model=SceneCheckpointRepairResponse,
)
async def repair_scene_checkpoint(
    db: DbSession,
    novel_id: NovelIdPath,
    request: SceneCheckpointRepairRequest,
) -> SceneCheckpointRepairResponse:
    """One-action manual repair; protected manual/confirmed rows fail closed."""
    await _require_active_project(db, novel_id)
    return await _scene_service.repair(db, novel_id, request)
