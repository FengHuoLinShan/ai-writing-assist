"""人物知识、知识标签排除与实体批次路由。"""

from __future__ import annotations

from fastapi import HTTPException, Query

from core.dependencies import DbSession
from modules.project.facade import require_active_project
from modules.world.api._shared import (
    ActiveNovelIdQuery,
    _context_service,
    _knowledge_service,
    _knowledge_tag_service,
    router,
)
from modules.world.schemas import (
    CharacterKnowledgeCreate,
    CharacterKnowledgeListResponse,
    CharacterKnowledgeResponse,
    CharacterKnowledgeUpdate,
    KnowledgeTagExclusionRequest,
    KnowledgeTagExclusionResponse,
)
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


@router.post(
    "/characters/{character_id}/knowledge-tags/{tag_id}/exclude",
    response_model=KnowledgeTagExclusionResponse,
)
async def exclude_character_knowledge_tag(
    db: DbSession,
    character_id: str,
    tag_id: str,
    data: KnowledgeTagExclusionRequest,
) -> KnowledgeTagExclusionResponse:
    await require_active_project(db, data.novel_id)
    return await _knowledge_tag_service.create_exclusion(
        db,
        data.novel_id,
        character_id,
        tag_id,
        reason=data.reason,
    )


@router.delete(
    "/characters/{character_id}/knowledge-tags/{tag_id}/exclude",
    response_model=KnowledgeTagExclusionResponse,
)
async def delete_character_knowledge_tag_exclusion(
    db: DbSession,
    character_id: str,
    tag_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> KnowledgeTagExclusionResponse:
    return await _knowledge_tag_service.delete_exclusion(
        db,
        novel_id,
        character_id,
        tag_id,
    )


@router.post("/characters/{character_id}/knowledge-tags/{tag_id}/lock")
async def lock_character_knowledge_tag(
    db: DbSession,
    character_id: str,
    tag_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> dict:
    return await _knowledge_tag_service.lock_tag(db, novel_id, character_id, tag_id)


@router.get(
    "/characters/{character_id}/knowledge",
    response_model=CharacterKnowledgeListResponse,
)
async def list_knowledge(
    db: DbSession,
    character_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> CharacterKnowledgeListResponse:
    return await _knowledge_service.list(
        db,
        novel_id,
        character_id,
        skip=skip,
        limit=limit,
    )


@router.post(
    "/characters/{character_id}/knowledge",
    response_model=CharacterKnowledgeResponse,
    status_code=201,
)
async def create_knowledge(
    db: DbSession,
    character_id: str,
    data: CharacterKnowledgeCreate,
    *,
    novel_id: ActiveNovelIdQuery,
) -> CharacterKnowledgeResponse:
    if data.character_id != character_id:
        raise HTTPException(
            status_code=400,
            detail="character_id in path and body must match",
        )
    return await _knowledge_service.create(db, novel_id, data)


@router.put(
    "/knowledge/{knowledge_id}",
    response_model=CharacterKnowledgeResponse,
)
async def update_knowledge(
    db: DbSession,
    knowledge_id: str,
    data: CharacterKnowledgeUpdate,
    *,
    novel_id: ActiveNovelIdQuery,
) -> CharacterKnowledgeResponse:
    return await _knowledge_service.update(
        db,
        knowledge_id,
        data,
        novel_id=novel_id,
    )


@router.delete("/knowledge/{knowledge_id}", status_code=204)
async def delete_knowledge(
    db: DbSession,
    knowledge_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> None:
    await _knowledge_service.delete(
        db,
        knowledge_id,
        novel_id=novel_id,
    )


@router.get("/entity-batches")
async def list_entity_batches(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    limit: int = Query(default=10, ge=1, le=50, description="最多返回的批次数量"),
) -> list[dict]:
    """获取自动入库实体的批次分组列表

    每次 LLM 抽取生成一个 batch_id，同一批次的实体归为一组。
    按入库时间倒序排列。
    """
    return await _context_service.list_entity_batches(
        db,
        novel_id,
        limit=limit,
    )
