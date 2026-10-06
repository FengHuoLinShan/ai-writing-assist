"""World Bible 路由：工作稿、导入、修订、梗概、模板与投影。"""

from __future__ import annotations

import json
import uuid

from fastapi import HTTPException, Query, Request
from pydantic import ValidationError as PydanticValidationError

from core.api_params import NovelIdQuery
from core.dependencies import DbSession
from modules.account.facade import current_account_id
from modules.evidence.facade import attach_result_ref, require_fresh_confirmation
from modules.project.facade import require_active_project
from modules.project.facade import (
    require_active_project_exclusive as _require_active_project_exclusive,
)
from modules.world.api._shared import (
    ActiveNovelIdQuery,
    _bible_lifecycle_service,
    _bible_page_template_service,
    _bible_service,
    _bible_synopsis_service,
    _world_authority_service,
    _worldbook_import_service,
    router,
)
from modules.world.schemas import (
    ProjectionRefreshResponse,
    WorldBibleApplyTemplateRequest,
    WorldBibleDraftPublicationResponse,
    WorldBiblePageDraftCreate,
    WorldBiblePageDraftListResponse,
    WorldBiblePageDraftResponse,
    WorldBiblePageDraftUpdate,
    WorldBiblePageResponse,
    WorldBiblePageRevisionResponse,
    WorldBiblePageTemplateCreate,
    WorldBiblePageTemplateListResponse,
    WorldBiblePageTemplateResponse,
    WorldBiblePageTemplateRevisionResponse,
    WorldBiblePageTemplateUpdate,
    WorldBiblePublishImpactResponse,
    WorldBibleSynopsisAutoRefreshRequest,
    WorldBibleSynopsisRefreshResponse,
    WorldBibleSynopsisResponse,
    WorldBibleSynopsisRevisionListResponse,
)
from modules.world.services.worldbuilding.worldbuilding_service import (
    ProjectionRefreshConflictError,
)
from modules.world.worldbook_import_schemas import (
    WorldbookImportApplyRequest,
    WorldbookImportApplyResponse,
    WorldbookImportManifest,
    WorldbookImportPreviewResponse,
)


async def _read_worldbook_import_manifest(request: Request) -> WorldbookImportManifest:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 64 * 1024 * 1024:
            raise HTTPException(
                status_code=413, detail="Worldbook import body is too large"
            )
    try:
        value = json.loads(body.decode("utf-8"))
        return WorldbookImportManifest.model_validate(value)
    except (UnicodeDecodeError, json.JSONDecodeError, PydanticValidationError) as exc:
        raise HTTPException(
            status_code=422,
            detail="Worldbook import manifest is invalid",
        ) from exc


@router.get("/bible/drafts", response_model=WorldBiblePageDraftListResponse)
async def list_bible_drafts(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    page_id: uuid.UUID | None = Query(None),
) -> WorldBiblePageDraftListResponse:
    items, total = await _bible_lifecycle_service.list_drafts(
        db, novel_id, page_id=str(page_id) if page_id else None
    )
    return WorldBiblePageDraftListResponse(items=items, total=total)


@router.post(
    "/bible/imports/preview",
    response_model=WorldbookImportPreviewResponse,
    status_code=201,
)
async def preview_worldbook_import(
    db: DbSession,
    request: Request,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldbookImportPreviewResponse:
    manifest = await _read_worldbook_import_manifest(request)
    return await _worldbook_import_service.preview(db, novel_id, manifest)


@router.get(
    "/bible/imports/{suggestion_id}",
    response_model=WorldbookImportPreviewResponse,
)
async def get_worldbook_import_preview(
    db: DbSession,
    suggestion_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldbookImportPreviewResponse:
    return await _worldbook_import_service.get_preview(db, novel_id, suggestion_id)


@router.post(
    "/bible/imports/{suggestion_id}/apply",
    response_model=WorldbookImportApplyResponse,
)
async def apply_worldbook_import(
    db: DbSession,
    suggestion_id: str,
    data: WorldbookImportApplyRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldbookImportApplyResponse:
    return await _worldbook_import_service.apply(
        db,
        novel_id,
        suggestion_id,
        data,
    )


@router.post(
    "/bible/drafts",
    response_model=WorldBiblePageDraftResponse,
    status_code=201,
)
async def create_bible_draft(
    db: DbSession,
    data: WorldBiblePageDraftCreate,
) -> WorldBiblePageDraftResponse:
    await require_active_project(db, data.novel_id)
    # 工作稿允许携带 `local:{dataset_key}:{rel_path}` 资料集待发布引用
    # （m1-contract 第 4 条，导入物化与采用包先例同型）；发布链负责物化。
    return await _bible_lifecycle_service.create_draft(db, data, allow_local_refs=True)


@router.get("/bible/drafts/{draft_id}", response_model=WorldBiblePageDraftResponse)
async def get_bible_draft(
    db: DbSession,
    draft_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldBiblePageDraftResponse:
    return await _bible_lifecycle_service.get_draft(db, novel_id, draft_id)


@router.get(
    "/bible/drafts/{draft_id}/publication",
    response_model=WorldBibleDraftPublicationResponse,
)
async def get_bible_draft_publication(
    db: DbSession, draft_id: str, *, novel_id: ActiveNovelIdQuery
):
    return await _world_authority_service.find_page_publication(db, novel_id, draft_id)


@router.patch("/bible/drafts/{draft_id}", response_model=WorldBiblePageDraftResponse)
async def update_bible_draft(
    db: DbSession,
    draft_id: str,
    data: WorldBiblePageDraftUpdate,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldBiblePageDraftResponse:
    return await _bible_lifecycle_service.update_draft(
        db,
        novel_id,
        draft_id,
        data,
        expected_updated_at=data.expected_updated_at,
        require_edit_baseline=True,
        # 编辑器每次保存整份回传 refs；导入草稿携带的资料集待发布引用须放行。
        allow_local_refs=True,
    )


@router.delete("/bible/drafts/{draft_id}")
async def discard_bible_draft(
    db: DbSession,
    draft_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
    confirmed: bool = Query(default=False),
) -> dict:
    if not confirmed:
        raise HTTPException(status_code=400, detail="confirmed=true is required")
    await _bible_lifecycle_service.discard_draft(db, novel_id, draft_id)
    return {"draft_id": draft_id, "discarded": True}


@router.post(
    "/bible/drafts/{draft_id}/publish",
    response_model=WorldBiblePageResponse,
)
async def publish_bible_draft(
    db: DbSession,
    draft_id: str,
    *,
    novel_id: NovelIdQuery,
    expected_canon_head: uuid.UUID | None = Query(default=None),
    canon_decision_id: uuid.UUID | None = Query(default=None),
    expected_impact_scope_hash: str | None = Query(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    ),
    validation_run_id: uuid.UUID | None = Query(default=None),
) -> WorldBiblePageResponse:
    if (expected_canon_head is None) != (canon_decision_id is None):
        raise HTTPException(
            status_code=422,
            detail="expected_canon_head and canon_decision_id must be provided together",
        )
    await _require_active_project_exclusive(db, novel_id)
    return await _bible_lifecycle_service.admit_draft(
        db,
        novel_id,
        draft_id,
        authorizer_id=current_account_id(),
        expected_canon_head=expected_canon_head,
        canon_decision_id=canon_decision_id,
        expected_impact_scope_hash=expected_impact_scope_hash,
        validation_run_id=validation_run_id,
    )


@router.get(
    "/bible/drafts/{draft_id}/publish-impact",
    response_model=WorldBiblePublishImpactResponse,
)
async def preview_bible_draft_publish_impact(
    db: DbSession,
    draft_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldBiblePublishImpactResponse:
    return await _bible_lifecycle_service.preview_publish_impact(
        db,
        novel_id,
        draft_id,
    )


@router.get(
    "/bible/pages/{page_id}/revisions",
    response_model=list[WorldBiblePageRevisionResponse],
)
async def list_bible_page_revisions(
    db: DbSession,
    page_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> list[WorldBiblePageRevisionResponse]:
    return await _bible_lifecycle_service.list_revisions(db, novel_id, page_id)


@router.post(
    "/bible/pages/{page_id}/revisions/{version_number}/restore-draft",
    response_model=WorldBiblePageDraftResponse,
)
async def restore_bible_revision_to_draft(
    db: DbSession,
    page_id: str,
    version_number: int,
    *,
    novel_id: ActiveNovelIdQuery,
    restored_by: str | None = Query(default=None, max_length=64),
) -> WorldBiblePageDraftResponse:
    return await _bible_lifecycle_service.restore_revision_to_draft(
        db,
        novel_id,
        page_id,
        version_number,
        restored_by=restored_by,
    )


@router.get("/bible/synopsis", response_model=WorldBibleSynopsisResponse)
async def get_bible_synopsis(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldBibleSynopsisResponse:
    return await _bible_synopsis_service.get(db, novel_id)


@router.post(
    "/bible/synopsis/refresh",
    response_model=WorldBibleSynopsisRefreshResponse,
)
async def refresh_bible_synopsis(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    context_confirmation_id: str | None = Query(default=None, max_length=128),
) -> WorldBibleSynopsisRefreshResponse:
    if not context_confirmation_id:
        raise HTTPException(status_code=400, detail="context_confirmation_id is required")
    try:
        await require_fresh_confirmation(
            db,
            novel_id=novel_id,
            action="world.world_bible.synopsis.refresh",
            confirmation_id=context_confirmation_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    (
        task_id,
        status,
        existing,
        source_hash,
    ) = await _bible_synopsis_service.request_refresh(
        db,
        novel_id,
        context_confirmation_id=context_confirmation_id,
    )
    await attach_result_ref(
        db,
        novel_id=novel_id,
        confirmation_id=context_confirmation_id,
        result_type="task",
        result_id=task_id,
        status="running",
    )
    return WorldBibleSynopsisRefreshResponse(
        task_id=task_id,
        status=status,
        existing=existing,
        source_hash=source_hash,
    )


@router.patch(
    "/bible/synopsis/auto-refresh",
    response_model=WorldBibleSynopsisResponse,
)
async def set_bible_synopsis_auto_refresh(
    db: DbSession,
    data: WorldBibleSynopsisAutoRefreshRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldBibleSynopsisResponse:
    return await _bible_synopsis_service.set_auto_refresh(
        db,
        novel_id,
        enabled=data.enabled,
        changed_by=data.changed_by,
    )


@router.get(
    "/bible/synopsis/revisions",
    response_model=WorldBibleSynopsisRevisionListResponse,
)
async def list_bible_synopsis_revisions(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldBibleSynopsisRevisionListResponse:
    items, total = await _bible_synopsis_service.list_revisions(db, novel_id)
    return WorldBibleSynopsisRevisionListResponse(items=items, total=total)


@router.post(
    "/bible/synopsis/revisions/{revision_id}/restore",
    response_model=WorldBibleSynopsisResponse,
)
async def restore_bible_synopsis_revision(
    db: DbSession,
    revision_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldBibleSynopsisResponse:
    return await _bible_synopsis_service.restore_revision(
        db,
        novel_id,
        revision_id,
    )


@router.post("/bible/synopsis/unpin", response_model=WorldBibleSynopsisResponse)
async def unpin_bible_synopsis(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldBibleSynopsisResponse:
    return await _bible_synopsis_service.unpin(db, novel_id)


@router.get("/bible/templates")
async def list_bible_templates() -> list[dict]:
    return await _bible_service.list_templates()


@router.get(
    "/bible/page-templates",
    response_model=WorldBiblePageTemplateListResponse,
)
async def list_bible_page_templates(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    include_archived: bool = Query(default=False),
) -> WorldBiblePageTemplateListResponse:
    items = await _bible_page_template_service.list_templates(
        db,
        novel_id,
        include_archived=include_archived,
    )
    return WorldBiblePageTemplateListResponse(items=items, total=len(items))


@router.post(
    "/bible/page-templates",
    response_model=WorldBiblePageTemplateResponse,
    status_code=201,
)
async def create_bible_page_template(
    db: DbSession,
    data: WorldBiblePageTemplateCreate,
) -> WorldBiblePageTemplateResponse:
    await require_active_project(db, data.novel_id)
    return await _bible_page_template_service.create_template(db, data)


@router.patch(
    "/bible/page-templates/{template_id}",
    response_model=WorldBiblePageTemplateResponse,
)
async def update_bible_page_template(
    db: DbSession,
    template_id: str,
    data: WorldBiblePageTemplateUpdate,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldBiblePageTemplateResponse:
    return await _bible_page_template_service.update_template(
        db,
        novel_id,
        template_id,
        data,
    )


@router.get(
    "/bible/page-templates/{template_id}/revisions",
    response_model=list[WorldBiblePageTemplateRevisionResponse],
)
async def list_bible_page_template_revisions(
    db: DbSession,
    template_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> list[WorldBiblePageTemplateRevisionResponse]:
    return await _bible_page_template_service.list_revisions(
        db,
        novel_id,
        template_id,
    )


@router.post(
    "/bible/page-templates/{template_id}/revisions/{version_number}/restore-draft",
    response_model=WorldBiblePageTemplateResponse,
)
async def restore_bible_page_template_revision(
    db: DbSession,
    template_id: str,
    version_number: int,
    *,
    novel_id: ActiveNovelIdQuery,
    restored_by: str | None = Query(default=None, max_length=64),
) -> WorldBiblePageTemplateResponse:
    return await _bible_page_template_service.restore_revision(
        db,
        novel_id,
        template_id,
        version_number,
        restored_by=restored_by,
    )


@router.post(
    "/bible/drafts/{draft_id}/apply-template",
    response_model=WorldBiblePageDraftResponse,
)
async def apply_bible_page_template(
    db: DbSession,
    draft_id: str,
    data: WorldBibleApplyTemplateRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldBiblePageDraftResponse:
    return await _bible_page_template_service.apply_to_draft(
        db,
        novel_id,
        draft_id,
        data,
    )


@router.post(
    "/bible/pages/{page_id}/refresh-projection",
    response_model=ProjectionRefreshResponse,
)
async def refresh_bible_projection(
    db: DbSession,
    page_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
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
    *,
    novel_id: ActiveNovelIdQuery,
) -> dict:
    return {
        "page_id": page_id,
        "novel_id": novel_id,
        "status": "preview_only",
        "suggestions": [],
        "conflicts": [],
    }
