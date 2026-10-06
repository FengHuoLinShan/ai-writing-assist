"""实体修订与回滚路由。"""

from __future__ import annotations

from fastapi import HTTPException, Query

from core.config import get_settings
from core.dependencies import DbSession
from modules.project.facade import require_active_project
from modules.world.api._shared import (
    ActiveNovelIdQuery,
    _entity_service,
    _revision_service,
    router,
)
from modules.world.revision_history_schemas import (
    EntityRevisionListResponse,
    EntityRevisionRollbackRequest,
)
from modules.world.schemas import (
    CoreEntityResponse,
    EntityRollbackRequest,
    EntityRollbackResponse,
    TextArchiveSeedRequest,
    TextArchiveSeedResponse,
)


@router.get(
    "/entities/{entity_id}/revisions",
    response_model=EntityRevisionListResponse,
)
async def list_revisions(
    db: DbSession,
    entity_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(default=20, ge=1, le=100, description="每页条数"),
) -> EntityRevisionListResponse:
    return await _revision_service.get_revisions(
        db,
        entity_id,
        novel_id,
        skip=skip,
        limit=limit,
    )


@router.post("/entities/{entity_id}/rollback", response_model=EntityRollbackResponse)
async def rollback_entity(
    db: DbSession,
    entity_id: str,
    data: EntityRollbackRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> EntityRollbackResponse:
    result = await _revision_service.rollback_to_scene_index(
        db,
        entity_id,
        data.target_scene_index,
        novel_id,
    )
    return EntityRollbackResponse(
        entity_id=result["entity_id"],
        target_scene_index=result["target_scene_index"],
        restored_fields=result["restored_fields"],
        warnings=result["warnings"],
    )


@router.post(
    "/entities/{entity_id}/rollback-by-revision",
    response_model=CoreEntityResponse,
)
async def rollback_entity_by_revision(
    db: DbSession,
    entity_id: str,
    data: EntityRevisionRollbackRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> CoreEntityResponse:
    """把实体恢复到指定修订（那次改动之前）的状态；基线过期返回 409。"""
    return await _entity_service.rollback_to_revision(
        db,
        entity_id,
        data.revision_id,
        novel_id=novel_id,
        expected_updated_at=data.expected_updated_at,
    )


@router.post(
    "/_test/entities/{entity_id}/text-archive",
    response_model=TextArchiveSeedResponse,
    status_code=201,
    summary="E2E 测试专用：为实体写入 TextArchive 归档",
)
async def seed_entity_text_archive(
    db: DbSession,
    entity_id: str,
    data: TextArchiveSeedRequest,
) -> TextArchiveSeedResponse:
    settings = get_settings()
    if settings.app_env != "test":
        raise HTTPException(status_code=404, detail="Not found")

    await require_active_project(db, data.novel_id)

    archive = await _revision_service.seed_text_archive(
        db,
        entity_id=entity_id,
        novel_id=data.novel_id,
        field_name=data.field_name,
        text_content=data.text_content,
        scene_index=data.scene_index,
    )
    return TextArchiveSeedResponse(
        status="ok",
        entity_id=entity_id,
        field_name=data.field_name,
        archive_id=str(archive.id),
    )
