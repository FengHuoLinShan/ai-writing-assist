"""
World API 路由 — v3 因果时空网

提供核心实体、事件、关系、版本、人物的 RESTful API。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from core.config import get_settings
from core.dependencies import DbSession
from infrastructure.tasks.enqueuer import enqueue_task
from modules.context.facade import attach_result_ref, require_fresh_confirmation
from modules.world.entity_fusion import WorldEntityFusionService
from modules.world.schemas import (
    CharacterCreate,
    CharacterKnowledgeCreate,
    CharacterKnowledgeListResponse,
    CharacterKnowledgeResponse,
    CharacterKnowledgeUpdate,
    CharacterListResponse,
    CharacterResponse,
    CharacterUpdate,
    ConflictQueueListResponse,
    ConflictResolveRequest,
    CoreEntityCreate,
    CoreEntityListResponse,
    CoreEntityResponse,
    CoreEntityUpdate,
    CreationSuggestionListResponse,
    EntityAliasCreate,
    EntityAliasUpdate,
    EntityFusionApplyRequest,
    EntityFusionApplyResponse,
    EntityFusionSuggestionRequest,
    EntityFusionSuggestionResponse,
    EntityMergeRequest,
    EntityMergeResponse,
    EntityPromoteRequest,
    EntityPromoteResponse,
    EntityRelationCreate,
    EntityRelationListResponse,
    EntityRelationResponse,
    EntityRelationUpdate,
    EntityRevisionListResponse,
    EntityRollbackRequest,
    EntityRollbackResponse,
    EventCreate,
    EventListResponse,
    EventResponse,
    EventUpdate,
    KnowledgeTagExclusionRequest,
    KnowledgeTagExclusionResponse,
    ProjectionRefreshResponse,
    SuggestionDecisionResponse,
    TextArchiveSeedRequest,
    TextArchiveSeedResponse,
    WorldAliasRelationExtractRequest,
    WorldAliasRelationExtractResponse,
    WorldBiblePageCreate,
    WorldBiblePageListResponse,
    WorldBiblePageResponse,
    WorldBiblePageUpdate,
    WorldEntityExtractRequest,
    WorldEntityExtractResponse,
    WorldProfileListResponse,
    WorldProfileMigrateResponse,
    WorldProfileResponse,
    WorldProfileUpsertRequest,
)
from modules.world.services import (
    CharacterKnowledgeService,
    CharacterService,
    EntityAliasService,
    EntityContextService,
    EntityRelationService,
    EntityRevisionService,
    EventService,
    WorldEntityService,
)
from modules.world.services.dedup_service import EntityDedupService
from modules.world.services.worldbuilding_service import (
    ConflictQueueService,
    KnowledgeTagService,
    ProjectionRefreshConflictError,
    SuggestionAlreadyProcessedError,
    SuggestionQueueService,
    WorldBibleService,
    WorldProfileService,
)
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

router = APIRouter(prefix="/api/world", tags=["world"])

_entity_service = WorldEntityService()
_alias_service = EntityAliasService()
_context_service = EntityContextService()
_relation_service = EntityRelationService()
_dedup_service = EntityDedupService()
_fusion_service = WorldEntityFusionService()
_revision_service = EntityRevisionService()
_event_service = EventService()
_character_service = CharacterService()
_knowledge_service = CharacterKnowledgeService()
_profile_service = WorldProfileService()
_bible_service = WorldBibleService()
_suggestion_service = SuggestionQueueService()
_conflict_queue_service = ConflictQueueService()
_knowledge_tag_service = KnowledgeTagService()


# ============================================================
# Worldbuilding Workspace 路由
# ============================================================


@router.get("/profiles", response_model=WorldProfileListResponse)
async def list_world_profiles(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    entity_type: str | None = Query(None, description="实体类型"),
    status: str | None = Query(None, description="实体状态"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> WorldProfileListResponse:
    items, total = await _profile_service.list_profiles(
        db,
        novel_id,
        entity_type=entity_type,
        status=status,
        skip=skip,
        limit=limit,
    )
    return WorldProfileListResponse(items=items, total=total)


@router.get("/profiles/{entity_id}", response_model=WorldProfileResponse)
async def get_world_profile(
    db: DbSession,
    entity_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> WorldProfileResponse:
    return await _profile_service.get_profile(db, novel_id, entity_id)


@router.put("/profiles/{entity_id}", response_model=WorldProfileResponse)
async def upsert_world_profile(
    db: DbSession,
    entity_id: str,
    data: WorldProfileUpsertRequest,
    novel_id: str = Query(..., description="项目 ID"),
) -> WorldProfileResponse:
    return await _profile_service.upsert_profile(db, novel_id, entity_id, data)


@router.post(
    "/profiles/{entity_id}/migrate-generic",
    response_model=WorldProfileMigrateResponse,
)
async def migrate_generic_profile(
    db: DbSession,
    entity_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> WorldProfileMigrateResponse:
    profile = await _profile_service.migrate_generic_to_strong(db, novel_id, entity_id)
    return WorldProfileMigrateResponse(
        entity_id=entity_id,
        migrated=True,
        profile=profile,
    )


@router.get("/bible/pages", response_model=WorldBiblePageListResponse)
async def list_bible_pages(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    page_type: str | None = Query(None, description="页面类型"),
) -> WorldBiblePageListResponse:
    items, total = await _bible_service.list_pages(db, novel_id, page_type=page_type)
    return WorldBiblePageListResponse(items=items, total=total)


@router.post("/bible/pages", response_model=WorldBiblePageResponse, status_code=201)
async def create_bible_page(
    db: DbSession,
    data: WorldBiblePageCreate,
) -> WorldBiblePageResponse:
    return await _bible_service.create_page(db, data)


@router.get("/bible/pages/{page_id}", response_model=WorldBiblePageResponse)
async def get_bible_page(
    db: DbSession,
    page_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> WorldBiblePageResponse:
    return await _bible_service.get_page(db, novel_id, page_id)


@router.patch("/bible/pages/{page_id}", response_model=WorldBiblePageResponse)
async def update_bible_page(
    db: DbSession,
    page_id: str,
    data: WorldBiblePageUpdate,
    novel_id: str = Query(..., description="项目 ID"),
) -> WorldBiblePageResponse:
    return await _bible_service.update_page(db, novel_id, page_id, data)


@router.get("/bible/templates")
async def list_bible_templates() -> list[dict]:
    return await _bible_service.list_templates()


@router.post(
    "/bible/pages/{page_id}/refresh-projection",
    response_model=ProjectionRefreshResponse,
)
async def refresh_bible_projection(
    db: DbSession,
    page_id: str,
    novel_id: str = Query(..., description="项目 ID"),
    projection_type: str = Query(default="context_brief"),
    force: bool = Query(default=False),
) -> ProjectionRefreshResponse:
    try:
        task_id, status, existing = await _bible_service.refresh_projection_task(
            db,
            novel_id,
            page_id,
            projection_type=projection_type,
            force=force,
        )
    except ProjectionRefreshConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "status": "projection_task_finished",
                "task_id": exc.task_id,
                "task_status": exc.status,
                "hint": "retry with force=true",
            },
        ) from exc
    return ProjectionRefreshResponse(
        task_id=task_id,
        status=status,
        existing=existing,
        projection_type=projection_type,
    )


@router.post("/bible/pages/{page_id}/organize")
async def organize_bible_page(
    page_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> dict:
    return {
        "page_id": page_id,
        "novel_id": novel_id,
        "status": "preview_only",
        "suggestions": [],
        "conflicts": [],
    }


@router.get("/suggestions", response_model=CreationSuggestionListResponse)
async def list_world_suggestions(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    source_module: str | None = Query(None),
    review_group: str | None = Query(None),
    risk_level: str | None = Query(None),
    status: str | None = Query(None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> CreationSuggestionListResponse:
    items, total = await _suggestion_service.list(
        db,
        novel_id,
        source_module=source_module,
        review_group=review_group,
        risk_level=risk_level,
        status=status,
        skip=skip,
        limit=limit,
    )
    return CreationSuggestionListResponse(items=items, total=total)


@router.post(
    "/suggestions/{suggestion_id}/confirm",
    response_model=SuggestionDecisionResponse,
)
async def confirm_world_suggestion(
    db: DbSession,
    suggestion_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> SuggestionDecisionResponse:
    try:
        suggestion = await _suggestion_service.confirm(db, novel_id, suggestion_id)
    except SuggestionAlreadyProcessedError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "status": "already_processed",
                "suggestion_status": exc.status,
            },
        ) from exc
    return SuggestionDecisionResponse(
        status="accepted",
        suggestion_status=suggestion.status,
        result_ref_json=suggestion.result_ref_json,
    )


@router.post(
    "/suggestions/{suggestion_id}/reject",
    response_model=SuggestionDecisionResponse,
)
async def reject_world_suggestion(
    db: DbSession,
    suggestion_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> SuggestionDecisionResponse:
    try:
        suggestion = await _suggestion_service.reject(db, novel_id, suggestion_id)
    except SuggestionAlreadyProcessedError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "status": "already_processed",
                "suggestion_status": exc.status,
            },
        ) from exc
    return SuggestionDecisionResponse(
        status="rejected",
        suggestion_status=suggestion.status,
        result_ref_json=suggestion.result_ref_json,
    )


@router.get("/conflicts", response_model=ConflictQueueListResponse)
async def list_world_conflicts(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    status: str | None = Query(None),
    conflict_type: str | None = Query(None),
) -> ConflictQueueListResponse:
    items, total = await _conflict_queue_service.list(
        db,
        novel_id,
        status=status,
        conflict_type=conflict_type,
    )
    return ConflictQueueListResponse(items=items, total=total)


@router.post("/conflicts/{conflict_id}/resolve")
async def resolve_world_conflict(
    db: DbSession,
    conflict_id: str,
    data: ConflictResolveRequest,
    novel_id: str = Query(..., description="项目 ID"),
) -> dict:
    item = await _conflict_queue_service.resolve(
        db,
        novel_id,
        conflict_id,
        status=data.status,
        resolution_json=data.resolution_json,
    )
    return {"status": item.status, "id": item.id}


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
    novel_id: str = Query(..., description="项目 ID"),
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
    novel_id: str = Query(..., description="项目 ID"),
) -> dict:
    return await _knowledge_tag_service.lock_tag(db, novel_id, character_id, tag_id)


# ============================================================
# CoreEntity 路由
# ============================================================


@router.get("/entities", response_model=CoreEntityListResponse)
async def list_entities(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    entity_type: str | None = Query(None, description="实体类型过滤"),
    status: str | None = Query(None, description="状态过滤"),
    q: str | None = Query(None, description="名称/别名搜索"),
    source: str | None = Query(None, description="来源过滤"),
    workflow_id: str | None = Query(None, description="深度导入 workflow ID"),
    needs_review: bool | None = Query(None, description="是否需要复核"),
    auto_ingested: bool | None = Query(None, description="是否自动导入"),
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> CoreEntityListResponse:
    return await _entity_service.list(
        db,
        novel_id,
        entity_type=entity_type,
        status=status,
        q=q,
        source=source,
        workflow_id=workflow_id,
        needs_review=needs_review,
        auto_ingested=auto_ingested,
        skip=skip,
        limit=limit,
    )


@router.post("/entities", response_model=CoreEntityResponse, status_code=201)
async def create_entity(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    data: CoreEntityCreate = ...,
) -> CoreEntityResponse:
    return await _entity_service.create(db, novel_id, data)


@router.post(
    "/entities/extract",
    response_model=WorldEntityExtractResponse,
    status_code=201,
)
async def extract_entities(
    db: DbSession,
    data: WorldEntityExtractRequest,
) -> WorldEntityExtractResponse:
    """提交确认后的手动世界对象补抽任务。"""
    try:
        await require_fresh_confirmation(
            db,
            novel_id=data.novel_id,
            action="world.entities.extract",
            confirmation_id=data.context_confirmation_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    task_id = enqueue_task(
        db,
        "world_entity_extraction",
        meta=data.model_dump(exclude_none=True),
    )
    await attach_result_ref(
        db,
        confirmation_id=data.context_confirmation_id,
        result_type="task",
        result_id=task_id,
        status="running",
    )
    await db.flush()
    return WorldEntityExtractResponse(task_id=task_id)


@router.post(
    "/alias-relations/extract",
    response_model=WorldAliasRelationExtractResponse,
    status_code=201,
)
async def extract_alias_relations(
    db: DbSession,
    data: WorldAliasRelationExtractRequest,
) -> WorldAliasRelationExtractResponse:
    """提交手动别名/关系补抽任务。"""
    if not data.context_confirmation_id:
        raise HTTPException(
            status_code=400,
            detail="context_confirmation_id is required",
        )
    try:
        await require_fresh_confirmation(
            db,
            novel_id=data.novel_id,
            action="world.alias_relations.extract",
            confirmation_id=data.context_confirmation_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    task_id = enqueue_task(
        db,
        "world_alias_relation_extraction",
        meta=data.model_dump(exclude_none=True),
    )
    await attach_result_ref(
        db,
        confirmation_id=data.context_confirmation_id,
        result_type="task",
        result_id=task_id,
        status="running",
    )
    await db.flush()
    return WorldAliasRelationExtractResponse(task_id=task_id)


@router.get("/entities/{entity_id}", response_model=CoreEntityResponse)
async def get_entity(
    db: DbSession,
    entity_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> CoreEntityResponse:
    return await _entity_service.get(db, entity_id, novel_id=novel_id)


@router.put("/entities/{entity_id}", response_model=CoreEntityResponse)
async def update_entity(
    db: DbSession,
    entity_id: str,
    data: CoreEntityUpdate,
    novel_id: str = Query(..., description="项目 ID"),
) -> CoreEntityResponse:
    return await _entity_service.update(db, entity_id, data, novel_id=novel_id)


@router.delete("/entities/{entity_id}", status_code=204)
async def delete_entity(
    db: DbSession,
    entity_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> None:
    await _entity_service.delete(db, entity_id, novel_id=novel_id)


@router.post("/entities/{candidate_id}/merge", response_model=EntityMergeResponse)
async def merge_entity(
    db: DbSession,
    candidate_id: str,
    data: EntityMergeRequest,
    novel_id: str = Query(..., description="项目 ID"),
) -> EntityMergeResponse:
    result = await _dedup_service.merge_candidate_into_entity(
        db,
        novel_id,
        candidate_id,
        data.target_entity_id,
    )
    return EntityMergeResponse(target_entity_id=result.target_entity_id)


@router.post(
    "/entities/fusion-suggestions",
    response_model=EntityFusionSuggestionResponse,
    status_code=201,
)
async def create_entity_fusion_suggestions(
    db: DbSession,
    data: EntityFusionSuggestionRequest,
) -> EntityFusionSuggestionResponse:
    task_id = enqueue_task(
        db,
        "world_entity_fusion_suggestions",
        meta=data.model_dump(exclude_none=True),
    )
    await db.flush()
    return EntityFusionSuggestionResponse(task_id=task_id)


@router.post(
    "/entities/fusion-suggestions/apply",
    response_model=EntityFusionApplyResponse,
)
async def apply_entity_fusion_suggestions(
    db: DbSession,
    data: EntityFusionApplyRequest,
) -> EntityFusionApplyResponse:
    result = await _fusion_service.apply(
        db,
        novel_id=data.novel_id,
        confirmed=data.confirmed,
        suggestions=data.suggestions,
    )
    return EntityFusionApplyResponse(**result)


@router.post(
    "/entities/{entity_id}/promote",
    response_model=EntityPromoteResponse,
)
async def promote_entity(
    db: DbSession,
    entity_id: str,
    data: EntityPromoteRequest = EntityPromoteRequest(),
    novel_id: str = Query(..., description="项目 ID"),
) -> EntityPromoteResponse:
    """将草稿/候选实体手动提升为正史。"""
    return await _entity_service.promote(
        db,
        entity_id,
        data,
        novel_id=novel_id,
    )


@router.get("/entities/{entity_id}/relations", response_model=EntityRelationListResponse)
async def get_entity_relations(
    db: DbSession,
    entity_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> EntityRelationListResponse:
    """获取实体的关联关系"""
    return await _relation_service.get_by_entity(db, novel_id, entity_id)


# ============================================================
# Event 路由
# ============================================================


@router.get("/events", response_model=EventListResponse)
async def list_events(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> EventListResponse:
    items, total = await _event_service.list(db, novel_id, skip=skip, limit=limit)
    return EventListResponse(items=items, total=total)


@router.post("/events", response_model=EventResponse, status_code=201)
async def create_event(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    data: EventCreate = ...,
) -> EventResponse:
    return await _event_service.create(db, novel_id, data)


@router.get("/events/{entity_id}", response_model=EventResponse)
async def get_event(
    db: DbSession,
    entity_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> EventResponse:
    return await _event_service.get(db, entity_id, novel_id=novel_id)


@router.put("/events/{entity_id}", response_model=EventResponse)
async def update_event(
    db: DbSession,
    entity_id: str,
    data: EventUpdate,
    novel_id: str = Query(..., description="项目 ID"),
) -> EventResponse:
    return await _event_service.update(db, entity_id, data, novel_id=novel_id)


@router.delete("/events/{entity_id}", status_code=204)
async def delete_event(
    db: DbSession,
    entity_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> None:
    await _event_service.delete(db, entity_id, novel_id=novel_id)


# ============================================================
# EntityRelation 路由
# ============================================================


@router.get("/relations", response_model=EntityRelationListResponse)
async def list_relations(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> EntityRelationListResponse:
    return await _relation_service.list(db, novel_id, skip=skip, limit=limit)


@router.post("/relations", response_model=EntityRelationResponse, status_code=201)
async def create_relation(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    data: EntityRelationCreate = ...,
) -> EntityRelationResponse:
    return await _relation_service.create(db, novel_id, data)


@router.put("/relations/{rel_id}", response_model=EntityRelationResponse)
async def update_relation(
    db: DbSession,
    rel_id: str,
    data: EntityRelationUpdate,
    novel_id: str = Query(..., description="项目 ID"),
) -> EntityRelationResponse:
    return await _relation_service.update(db, rel_id, data, novel_id=novel_id)


@router.delete("/relations/{rel_id}", status_code=204)
async def delete_relation(
    db: DbSession,
    rel_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> None:
    await _relation_service.delete(db, rel_id, novel_id=novel_id)


# ============================================================
# EntityRevision 路由
# ============================================================


@router.get(
    "/entities/{entity_id}/revisions",
    response_model=EntityRevisionListResponse,
)
async def list_revisions(
    db: DbSession,
    entity_id: str,
    novel_id: str = Query(..., description="项目 ID"),
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(default=20, ge=1, le=100, description="每页条数"),
) -> EntityRevisionListResponse:
    result = await _revision_service.get_revisions(
        db,
        entity_id,
        novel_id,
        skip=skip,
        limit=limit,
    )
    return EntityRevisionListResponse(items=result["items"], total=result["total"])


@router.post("/entities/{entity_id}/rollback", response_model=EntityRollbackResponse)
async def rollback_entity(
    db: DbSession,
    entity_id: str,
    data: EntityRollbackRequest,
    novel_id: str = Query(..., description="项目 ID"),
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
    revision_id: str = Query(..., description="目标版本 ID"),
    novel_id: str = Query(..., description="项目 ID"),
) -> CoreEntityResponse:
    return await _revision_service.rollback_to_revision(
        db,
        entity_id,
        revision_id,
        novel_id,
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


# ============================================================
# Character 路由
# ============================================================


@router.get("/characters", response_model=CharacterListResponse)
async def list_characters(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> CharacterListResponse:
    items, total = await _character_service.list(
        db,
        novel_id,
        skip=skip,
        limit=limit,
    )
    return CharacterListResponse(items=items, total=total)


@router.post("/characters", response_model=CharacterResponse, status_code=201)
async def create_character(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    data: CharacterCreate = ...,
) -> CharacterResponse:
    return await _character_service.create(db, novel_id, data)


@router.get("/characters/{character_id}", response_model=CharacterResponse)
async def get_character(
    db: DbSession,
    character_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> CharacterResponse:
    return await _character_service.get(
        db,
        character_id,
        novel_id=novel_id,
    )


@router.put("/characters/{character_id}", response_model=CharacterResponse)
async def update_character(
    db: DbSession,
    character_id: str,
    data: CharacterUpdate,
    novel_id: str = Query(..., description="项目 ID"),
) -> CharacterResponse:
    return await _character_service.update(
        db,
        character_id,
        data,
        novel_id=novel_id,
    )


@router.delete("/characters/{character_id}", status_code=204)
async def delete_character(
    db: DbSession,
    character_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> None:
    await _character_service.delete(db, character_id, novel_id=novel_id)


# ============================================================
# CharacterKnowledge 路由 (独立 CharacterKnowledgeService)
# ============================================================


@router.get(
    "/characters/{character_id}/knowledge",
    response_model=CharacterKnowledgeListResponse,
)
async def list_knowledge(
    db: DbSession,
    character_id: str,
    novel_id: str = Query(..., description="项目 ID"),
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
    novel_id: str = Query(..., description="项目 ID"),
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
    novel_id: str = Query(..., description="项目 ID"),
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
    novel_id: str = Query(..., description="项目 ID"),
) -> None:
    await _knowledge_service.delete(
        db,
        knowledge_id,
        novel_id=novel_id,
    )


@router.get("/entity-batches")
async def list_entity_batches(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
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


# ============================================================
# Entity Alias 路由（操作 core_entities.content_json.aliases）
# ============================================================


@router.get("/aliases")
async def list_aliases(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    """列出项目下所有实体的别名"""
    return await _alias_service.list_aliases_page(
        db,
        novel_id,
        skip=skip,
        limit=limit,
    )


@router.post("/aliases", status_code=201)
async def create_alias(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    data: EntityAliasCreate = ...,
) -> dict:
    """为实体添加别名"""
    return await _alias_service.create_alias(
        db,
        novel_id,
        data.entity_id,
        data.alias,
        data.alias_type,
    )


@router.patch("/entities/{entity_id}/aliases")
async def update_alias(
    db: DbSession,
    entity_id: str,
    data: EntityAliasUpdate,
    novel_id: str = Query(..., description="项目 ID"),
    alias: str = Query(..., description="要更新的别名文本"),
) -> dict:
    """更新实体的指定别名元数据。"""
    return await _alias_service.update_alias(
        db,
        novel_id,
        entity_id,
        alias,
        data.model_dump(exclude_unset=True),
    )


@router.delete("/entities/{entity_id}/aliases")
async def delete_alias(
    db: DbSession,
    entity_id: str,
    novel_id: str = Query(..., description="项目 ID"),
    alias: str = Query(..., description="要删除的别名文本"),
) -> dict:
    """删除实体的指定别名"""
    return await _alias_service.delete_alias(
        db,
        novel_id,
        entity_id,
        alias,
    )
