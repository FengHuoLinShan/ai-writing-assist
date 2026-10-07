"""Worldbuilding Workspace 路由：画像、世界书页面与分类。"""

from __future__ import annotations

from fastapi import Query

from core.dependencies import DbSession
from core.errors import ConflictError
from modules.account.facade import current_account_id
from modules.project.facade import require_active_project
from modules.project.facade import (
    require_active_project_exclusive as _require_active_project_exclusive,
)
from modules.world.api._shared import (
    ActiveNovelIdQuery,
    _bible_lifecycle_service,
    _bible_service,
    _profile_service,
    _world_authority_service,
    router,
)
from modules.world.schemas import (
    WorldBibleCategoryCreate,
    WorldBibleCategoryListResponse,
    WorldBibleCategoryResponse,
    WorldBibleCategoryUpdate,
    WorldBiblePageCreate,
    WorldBiblePageDraftCreate,
    WorldBiblePageDraftUpdate,
    WorldBiblePageListResponse,
    WorldBiblePageResponse,
    WorldBiblePageUpdate,
    WorldProfileListResponse,
    WorldProfileMigrateResponse,
    WorldProfileResponse,
    WorldProfileUpsertRequest,
)


@router.get("/profiles", response_model=WorldProfileListResponse)
async def list_world_profiles(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
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
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldProfileResponse:
    return await _profile_service.get_profile(db, novel_id, entity_id)


@router.put("/profiles/{entity_id}", response_model=WorldProfileResponse)
async def upsert_world_profile(
    db: DbSession,
    entity_id: str,
    data: WorldProfileUpsertRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldProfileResponse:
    return await _profile_service.upsert_profile(db, novel_id, entity_id, data)


@router.post(
    "/profiles/{entity_id}/migrate-generic",
    response_model=WorldProfileMigrateResponse,
)
async def migrate_generic_profile(
    db: DbSession,
    entity_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
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
    *,
    novel_id: ActiveNovelIdQuery,
    page_type: str | None = Query(None, description="页面类型"),
) -> WorldBiblePageListResponse:
    items, total = await _bible_service.list_pages(db, novel_id, page_type=page_type)
    return WorldBiblePageListResponse(items=items, total=total)


@router.post("/bible/pages", response_model=WorldBiblePageResponse, status_code=201)
async def create_bible_page(
    db: DbSession,
    data: WorldBiblePageCreate,
) -> WorldBiblePageResponse:
    if data.status not in {"canonical", "confirmed"}:
        await require_active_project(db, data.novel_id)
        return await _bible_service.create_page(db, data)
    await _require_active_project_exclusive(db, data.novel_id)
    expected_canon_head = await _world_authority_service.lock_head_for_admission(
        db, data.novel_id
    )
    async with db.begin_nested():
        staged = await _bible_service.create_page(
            db,
            data.model_copy(update={"status": "draft"}),
        )
        draft = await _bible_lifecycle_service.create_draft(
            db,
            WorldBiblePageDraftCreate(
                novel_id=data.novel_id,
                page_id=staged.id,
                created_by=data.created_by,
            ),
        )
        return await _bible_lifecycle_service.admit_draft(
            db,
            data.novel_id,
            draft.id,
            authorizer_id=current_account_id(),
            expected_canon_head=expected_canon_head,
        )


@router.get("/bible/pages/{page_id}", response_model=WorldBiblePageResponse)
async def get_bible_page(
    db: DbSession,
    page_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldBiblePageResponse:
    return await _bible_service.get_page(db, novel_id, page_id)


@router.patch("/bible/pages/{page_id}", response_model=WorldBiblePageResponse)
async def update_bible_page(
    db: DbSession,
    page_id: str,
    data: WorldBiblePageUpdate,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldBiblePageResponse:
    current = await _bible_service.get_page(db, novel_id, page_id)
    payload = data.model_dump(mode="json", exclude_unset=True)
    if set(payload) <= {"updated_by"}:
        return await _bible_service.update_page(db, novel_id, page_id, data)
    if (
        current.status in {"canonical", "confirmed"}
        and payload.get("status") == "archived"
        and set(payload) <= {"status", "updated_by"}
    ):
        return await _bible_service.update_page(db, novel_id, page_id, data)
    needs_admission = current.status in {
        "canonical",
        "confirmed",
        "archived",
    } or payload.get("status") in {"canonical", "confirmed"}
    if not needs_admission:
        return await _bible_service.update_page(db, novel_id, page_id, data)
    if payload.get("status") not in {None, "canonical", "confirmed"}:
        raise ConflictError(
            "This World Bible status change is not supported by Canon admission",
            code="canon_admission_required",
            context={"next_action": "create_and_publish_world_bible_draft"},
        )
    if "activation_defaults_json" in payload:
        raise ConflictError(
            "Activation defaults cannot be changed through the legacy page adapter",
            code="canon_admission_required",
            context={"next_action": "create_and_publish_world_bible_draft"},
        )
    await _require_active_project_exclusive(db, novel_id)
    expected_canon_head = await _world_authority_service.lock_head_for_admission(
        db, novel_id
    )
    async with db.begin_nested():
        draft = await _bible_lifecycle_service.create_draft(
            db,
            WorldBiblePageDraftCreate(
                novel_id=novel_id,
                page_id=page_id,
                created_by=payload.get("updated_by"),
            ),
        )
        draft_payload = {
            key: value
            for key, value in payload.items()
            if key not in {"status", "activation_defaults_json", "updated_by"}
        }
        if draft_payload:
            draft = await _bible_lifecycle_service.update_draft(
                db,
                novel_id,
                draft.id,
                WorldBiblePageDraftUpdate(
                    **draft_payload,
                    updated_by=payload.get("updated_by"),
                ),
            )
        return await _bible_lifecycle_service.admit_draft(
            db,
            novel_id,
            draft.id,
            authorizer_id=current_account_id(),
            expected_canon_head=expected_canon_head,
        )


@router.get("/bible/categories", response_model=WorldBibleCategoryListResponse)
async def list_bible_categories(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    include_archived: bool = Query(default=False),
) -> WorldBibleCategoryListResponse:
    items = await _bible_lifecycle_service.list_categories(
        db,
        novel_id,
        include_archived=include_archived,
    )
    return WorldBibleCategoryListResponse(items=items)


@router.post(
    "/bible/categories",
    response_model=WorldBibleCategoryResponse,
    status_code=201,
)
async def create_bible_category(
    db: DbSession,
    data: WorldBibleCategoryCreate,
) -> WorldBibleCategoryResponse:
    await require_active_project(db, data.novel_id)
    return await _bible_lifecycle_service.create_category(db, data)


@router.patch(
    "/bible/categories/{category_id}",
    response_model=WorldBibleCategoryResponse,
)
async def update_bible_category(
    db: DbSession,
    category_id: str,
    data: WorldBibleCategoryUpdate,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldBibleCategoryResponse:
    return await _bible_lifecycle_service.update_category(
        db,
        novel_id,
        category_id,
        data,
    )
