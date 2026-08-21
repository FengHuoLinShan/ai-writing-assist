from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, HTTPException, Path, Query
from fastapi import status as http_status

from core.api_params import NovelIdQuery
from core.dependencies import DbSession
from infrastructure.llm.redaction import redact_diagnostic
from infrastructure.tasks.facade import (
    enqueue_task_with_optional_operation,
    get_operation_task,
)
from modules.evidence.facade import attach_result_ref, require_fresh_confirmation
from modules.project.facade import (
    build_project_llm_execution_snapshot,
    require_active_project,
)
from modules.story.outline_state.p20_schemas import OutlineLayerGenerateRequest
from modules.story.outline_state.p20_service import P20ConflictError, P20GenerationService
from modules.story.outline_state.scene_workbench import (
    SceneSuggestionConflictError,
    SceneWorkbenchService,
)
from modules.story.outline_state.schemas import (
    ForeshadowingPlanCreate,
    ForeshadowingPlanListResponse,
    ForeshadowingPlanResponse,
    ForeshadowingPlanUpdate,
    OutlineAiTaskRequest,
    OutlineAiTaskResponse,
    OutlineArcCreate,
    OutlineArcListResponse,
    OutlineArcResponse,
    OutlineArcUpdate,
    OutlineStructurePreviewApplyRequest,
    OutlineStructurePreviewApplyResponse,
    PlotThreadCreate,
    PlotThreadListResponse,
    PlotThreadResponse,
    PlotThreadUpdate,
    RevealPlanCreate,
    RevealPlanListResponse,
    RevealPlanResponse,
    RevealPlanUpdate,
    SceneChapterQuickCreate,
    SceneCreate,
    SceneFusionPreviewRequest,
    SceneFusionPreviewResponse,
    SceneFusionPreviewTaskRequest,
    SceneFusionPreviewTaskResponse,
    SceneFusionSaveRequest,
    SceneFusionSaveResponse,
    SceneFusionSuggestionDismissRequest,
    SceneFusionSuggestionDismissResponse,
    SceneFusionSuggestionListResponse,
    SceneImpactPreview,
    SceneListResponse,
    SceneMappingUpdate,
    SceneMergeRequest,
    SceneReorderRequest,
    SceneReorderResponse,
    SceneReplacementApplyRequest,
    SceneReplacementApplyResponse,
    SceneResponse,
    SceneReviewRequest,
    SceneReviewResponse,
    SceneSourceMappingReviewRequest,
    SceneSourceMappingReviewResponse,
    SceneSplitRequest,
    SceneUpdate,
    SceneWorkbenchItem,
    SceneWorkbenchResponse,
    SplitChaptersRequest,
)
from modules.story.outline_state.services import (
    ForeshadowingPlanService,
    OutlineArcService,
    PlotThreadService,
    RevealPlanService,
    SceneService,
)
from modules.story.outline_state.story_outline_schemas import (
    StoryOutlineCurrentResponse,
    StoryOutlineGeneratedPreviewApply,
    StoryOutlineGenerateRequest,
    StoryOutlineRevisionApply,
    StoryOutlineRevisionCreate,
    StoryOutlineRevisionListResponse,
    StoryOutlineRevisionResponse,
)
from modules.story.outline_state.story_outline_service import (
    StoryOutlineConflictError,
    StoryOutlineNotFoundError,
    StoryOutlineService,
)
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

router = APIRouter(prefix="/api/outline", tags=["outline"])
logger = logging.getLogger(__name__)

_thread_service = PlotThreadService()
_arc_service = OutlineArcService()
_scene_service = SceneService()
_scene_workbench_service = SceneWorkbenchService()
_foreshadowing_service = ForeshadowingPlanService()
_reveal_service = RevealPlanService()
_story_outline_service = StoryOutlineService()


def _workbench_error(exc: Exception) -> HTTPException:
    if isinstance(exc, SceneSuggestionConflictError):
        return HTTPException(status_code=409, detail=redact_diagnostic(exc))
    if isinstance(exc, LookupError):
        return HTTPException(
            status_code=404,
            detail=redact_diagnostic(exc) or "Not found",
        )
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=400, detail=redact_diagnostic(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=redact_diagnostic(exc))
    logger.error(
        "outline_scene_workbench_unexpected_error error_type=%s",
        type(exc).__name__,
        exc_info=(
            RuntimeError,
            RuntimeError(redact_diagnostic(exc, limit=300)),
            exc.__traceback__,
        ),
    )
    return HTTPException(
        status_code=500,
        detail="服务器内部错误，请稍后重试。",
    )


def _story_outline_error(exc: Exception) -> HTTPException:
    if isinstance(exc, StoryOutlineConflictError):
        return HTTPException(status_code=409, detail=redact_diagnostic(exc))
    if isinstance(exc, StoryOutlineNotFoundError):
        return HTTPException(status_code=404, detail=redact_diagnostic(exc))
    logger.error(
        "outline_story_outline_unexpected_error error_type=%s",
        type(exc).__name__,
        exc_info=(
            RuntimeError,
            RuntimeError(redact_diagnostic(exc, limit=300)),
            exc.__traceback__,
        ),
    )
    return HTTPException(
        status_code=500,
        detail="服务器内部错误，请稍后重试。",
    )


async def _enqueue_confirmed_outline_task(
    db: DbSession,
    data: OutlineAiTaskRequest,
    *,
    action: str,
    task_type: str,
) -> OutlineAiTaskResponse:
    request_payload = data.model_dump(
        mode="json",
        exclude_none=True,
        exclude={"operation_id"},
    )
    try:
        existing = await get_operation_task(
            db,
            operation_id=str(data.operation_id) if data.operation_id else None,
            task_type=task_type,
            novel_id=data.novel_id,
            request_payload=request_payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=redact_diagnostic(exc)) from exc
    if existing is not None:
        return OutlineAiTaskResponse(
            task_id=existing.task_id,
            status=existing.status,
        )
    try:
        await require_fresh_confirmation(
            db,
            novel_id=data.novel_id,
            action=action,
            confirmation_id=data.context_confirmation_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=redact_diagnostic(exc),
        ) from exc

    meta = dict(request_payload)
    from modules.project.facade import build_project_llm_execution_snapshot

    meta["llm_execution_snapshot"] = await build_project_llm_execution_snapshot(
        db,
        data.novel_id,
    )
    try:
        receipt = await enqueue_task_with_optional_operation(
            db,
            operation_id=str(data.operation_id) if data.operation_id else None,
            task_type=task_type,
            novel_id=data.novel_id,
            request_payload=request_payload,
            meta=meta,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=redact_diagnostic(exc)) from exc
    if not receipt.reused:
        await attach_result_ref(
            db,
            novel_id=data.novel_id,
            confirmation_id=data.context_confirmation_id,
            result_type="task",
            result_id=receipt.task_id,
            status="running",
        )
    await db.flush()
    return OutlineAiTaskResponse(task_id=receipt.task_id, status=receipt.status)


async def _enqueue_outline_layer_task(
    db: DbSession,
    data: OutlineLayerGenerateRequest,
) -> OutlineAiTaskResponse:
    request_payload = data.model_dump(
        exclude_none=True,
        mode="json",
        exclude={"operation_id"},
    )
    try:
        existing = await get_operation_task(
            db,
            operation_id=str(data.operation_id) if data.operation_id else None,
            task_type="outline_generate",
            novel_id=data.novel_id,
            request_payload=request_payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=redact_diagnostic(exc)) from exc
    if existing is not None:
        return OutlineAiTaskResponse(
            task_id=existing.task_id,
            status=existing.status,
        )
    try:
        await require_fresh_confirmation(
            db,
            novel_id=data.novel_id,
            action="outline.generate",
            confirmation_id=data.context_confirmation_id,
        )
        plan = await P20GenerationService().prepare(db, data)
    except (LookupError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail=redact_diagnostic(exc),
        ) from exc

    meta = dict(request_payload)
    meta.update(
        {
            "action": "outline.generate",
            "submission_fingerprint": plan.source_fingerprint,
            "context_provenance": plan.context_provenance,
        }
    )
    from modules.project.facade import build_project_llm_execution_snapshot

    meta["llm_execution_snapshot"] = await build_project_llm_execution_snapshot(
        db,
        data.novel_id,
    )
    try:
        receipt = await enqueue_task_with_optional_operation(
            db,
            operation_id=str(data.operation_id) if data.operation_id else None,
            task_type="outline_generate",
            novel_id=data.novel_id,
            request_payload=request_payload,
            meta=meta,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=redact_diagnostic(exc)) from exc
    if not receipt.reused:
        await attach_result_ref(
            db,
            novel_id=data.novel_id,
            confirmation_id=data.context_confirmation_id,
            result_type="task",
            result_id=receipt.task_id,
            status="running",
        )
    await db.flush()
    return OutlineAiTaskResponse(task_id=receipt.task_id, status=receipt.status)


# ============================================================
# StoryOutline
# ============================================================


@router.get("/story-outline", response_model=StoryOutlineCurrentResponse)
async def api_get_story_outline(
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    await require_active_project(db, novel_id)
    try:
        return await _story_outline_service.get_current(db, novel_id)
    except Exception as exc:
        raise _story_outline_error(exc) from exc


@router.post(
    "/story-outline/revisions",
    response_model=StoryOutlineRevisionResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def api_create_story_outline_revision(
    data: StoryOutlineRevisionCreate,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    await require_active_project(db, novel_id)
    try:
        return await _story_outline_service.create_revision(db, novel_id, data)
    except Exception as exc:
        raise _story_outline_error(exc) from exc


@router.get(
    "/story-outline/revisions",
    response_model=StoryOutlineRevisionListResponse,
)
async def api_list_story_outline_revisions(
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
):
    await require_active_project(db, novel_id)
    try:
        return await _story_outline_service.list_revisions(
            db,
            novel_id,
            skip=skip,
            limit=limit,
        )
    except Exception as exc:
        raise _story_outline_error(exc) from exc


@router.get(
    "/story-outline/revisions/{revision_id}",
    response_model=StoryOutlineRevisionResponse,
)
async def api_get_story_outline_revision(
    revision_id: uuid.UUID,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    await require_active_project(db, novel_id)
    try:
        return await _story_outline_service.get_revision(
            db,
            novel_id,
            revision_id,
        )
    except Exception as exc:
        raise _story_outline_error(exc) from exc


@router.post(
    "/story-outline/revisions/{revision_id}/apply",
    response_model=StoryOutlineRevisionResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def api_apply_story_outline_revision(
    revision_id: uuid.UUID,
    data: StoryOutlineRevisionApply,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    await require_active_project(db, novel_id)
    try:
        return await _story_outline_service.apply_revision(
            db,
            novel_id,
            revision_id,
            data,
        )
    except Exception as exc:
        raise _story_outline_error(exc) from exc


@router.post(
    "/story-outline/generate",
    response_model=OutlineAiTaskResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def api_generate_story_outline(
    data: StoryOutlineGenerateRequest,
    db: DbSession,
) -> OutlineAiTaskResponse:
    """Validate the bounded source set and enqueue a preview-only task."""
    await require_active_project(db, data.novel_id)
    from modules.project.facade import build_project_llm_execution_snapshot
    from modules.story.outline_state.story_outline_generation import (
        STORY_OUTLINE_GENERATE_ACTION,
        StoryOutlineGenerationService,
    )

    request_payload = data.model_dump(
        mode="json",
        exclude_none=True,
        exclude={"operation_id"},
    )
    try:
        existing = await get_operation_task(
            db,
            operation_id=str(data.operation_id) if data.operation_id else None,
            task_type="story_outline_generate",
            novel_id=data.novel_id,
            request_payload=request_payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=redact_diagnostic(exc)) from exc
    if existing is not None:
        return OutlineAiTaskResponse(
            task_id=existing.task_id,
            status=existing.status,
        )
    try:
        submission_plan = await StoryOutlineGenerationService().prepare(db, data)
    except Exception as exc:
        if isinstance(exc, ValueError):
            raise HTTPException(
                status_code=400,
                detail=redact_diagnostic(exc),
            ) from exc
        raise _story_outline_error(exc) from exc
    meta = dict(request_payload)
    meta.update(
        {
            "action": STORY_OUTLINE_GENERATE_ACTION,
            "submission_context_hash": submission_plan.source_fingerprint,
            "llm_execution_snapshot": await build_project_llm_execution_snapshot(
                db,
                data.novel_id,
            ),
        }
    )
    try:
        receipt = await enqueue_task_with_optional_operation(
            db,
            operation_id=str(data.operation_id) if data.operation_id else None,
            task_type="story_outline_generate",
            novel_id=data.novel_id,
            request_payload=request_payload,
            meta=meta,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=redact_diagnostic(exc)) from exc
    await db.flush()
    return OutlineAiTaskResponse(task_id=receipt.task_id, status=receipt.status)


@router.post(
    "/story-outline/generate/apply",
    response_model=StoryOutlineRevisionResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def api_apply_generated_story_outline(
    data: StoryOutlineGeneratedPreviewApply,
    db: DbSession,
) -> StoryOutlineRevisionResponse:
    """Adopt an edited AI preview with server-validated task provenance."""
    await require_active_project(db, data.novel_id)
    try:
        return await _story_outline_service.apply_generated_preview(db, data)
    except Exception as exc:
        if isinstance(exc, ValueError):
            raise HTTPException(
                status_code=400,
                detail=redact_diagnostic(exc),
            ) from exc
        raise _story_outline_error(exc) from exc


# ============================================================
# PlotThreads
# ============================================================


@router.post(
    "/threads",
    response_model=PlotThreadResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def api_create_thread(
    data: PlotThreadCreate,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    await require_active_project(db, novel_id)
    return await _thread_service.create(db, novel_id, data)


@router.get("/threads", response_model=PlotThreadListResponse)
async def api_list_threads(
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
    status: str | None = Query(None, description="状态过滤"),
    source: str | None = Query(None, description="来源过滤"),
    workflow_id: str | None = Query(None, description="深度导入 workflow ID"),
    needs_review: bool | None = Query(None, description="是否需要复核"),
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
):
    await require_active_project(db, novel_id)
    return await _thread_service.list_with_response(
        db,
        novel_id,
        skip=skip,
        limit=limit,
        status=status,
        source=source,
        workflow_id=workflow_id,
        needs_review=needs_review,
    )


@router.get("/threads/{thread_id}", response_model=PlotThreadResponse)
async def api_get_thread(
    thread_id: str,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    await require_active_project(db, novel_id)
    return await _thread_service.get(db, thread_id, novel_id=novel_id)


@router.patch("/threads/{thread_id}", response_model=PlotThreadResponse)
async def api_update_thread(
    thread_id: str,
    data: PlotThreadUpdate,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    await require_active_project(db, novel_id)
    return await _thread_service.update(db, thread_id, data, novel_id=novel_id)


@router.delete("/threads/{thread_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def api_delete_thread(
    thread_id: str,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    await require_active_project(db, novel_id)
    await _thread_service.delete(db, thread_id, novel_id=novel_id)


# ============================================================
# OutlineArcs
# ============================================================


@router.post(
    "/arcs", response_model=OutlineArcResponse, status_code=http_status.HTTP_201_CREATED
)
async def api_create_arc(
    data: OutlineArcCreate,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    await require_active_project(db, novel_id)
    return await _arc_service.create(db, novel_id, data)


@router.get("/arcs", response_model=OutlineArcListResponse)
async def api_list_arcs(
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
    status: str | None = Query(None, description="状态过滤"),
    source: str | None = Query(None, description="来源过滤"),
    workflow_id: str | None = Query(None, description="深度导入 workflow ID"),
    needs_review: bool | None = Query(None, description="是否需要复核"),
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
):
    await require_active_project(db, novel_id)
    return await _arc_service.list_with_response(
        db,
        novel_id,
        skip=skip,
        limit=limit,
        status=status,
        source=source,
        workflow_id=workflow_id,
        needs_review=needs_review,
    )


@router.get("/arcs/{arc_id}", response_model=OutlineArcResponse)
async def api_get_arc(
    arc_id: str,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    await require_active_project(db, novel_id)
    return await _arc_service.get(db, arc_id, novel_id=novel_id)


@router.patch("/arcs/{arc_id}", response_model=OutlineArcResponse)
async def api_update_arc(
    arc_id: str,
    data: OutlineArcUpdate,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    await require_active_project(db, novel_id)
    return await _arc_service.update(db, arc_id, data, novel_id=novel_id)


@router.delete("/arcs/{arc_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def api_delete_arc(
    arc_id: str,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    await require_active_project(db, novel_id)
    await _arc_service.delete(db, arc_id, novel_id=novel_id)


# ============================================================
# Scenes
# ============================================================


@router.get("/scene-workbench", response_model=SceneWorkbenchResponse)
async def api_get_scene_workbench(
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
    selected_scene_id: str | None = Query(None, description="当前选中的 Scene ID"),
    status: str | None = Query(None, description="Scene 状态过滤"),
    source: str | None = Query(None, description="Scene 来源过滤"),
    workflow_id: str | None = Query(None, description="深度导入 workflow ID"),
    needs_review: bool | None = Query(None, description="是否需要复核"),
    boundary_status: str | None = Query(None, description="边界状态过滤"),
    phase: str | None = Query(None, description="深度导入阶段过滤"),
    phase1a_fallback: bool | None = Query(None, description="是否 Phase 1a fallback"),
    health: str | None = Query(None, description="Scene 健康筛选"),
    q: str | None = Query(None, description="Scene 文本搜索"),
    chapter_from: int | None = Query(None, ge=1, description="起始章节筛选"),
    chapter_to: int | None = Query(None, ge=1, description="结束章节筛选"),
    confidence_band: str | None = Query(None, description="置信度分档"),
    view_mode: str = Query("normal", pattern="^(normal|hot)$"),
    segment: str | None = Query(
        None,
        pattern="^(current|upcoming|past|unassigned)$",
    ),
    anchor: str | None = Query(None, pattern="^latest$"),
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
):
    await require_active_project(db, novel_id)
    try:
        return await _scene_workbench_service.get_workbench(
            db,
            novel_id,
            selected_scene_id=selected_scene_id,
            status=status,
            source=source,
            workflow_id=workflow_id,
            needs_review=needs_review,
            boundary_status=boundary_status,
            phase=phase,
            phase1a_fallback=phase1a_fallback,
            health=health,
            q=q,
            chapter_from=chapter_from,
            chapter_to=chapter_to,
            confidence_band=confidence_band,
            view_mode=view_mode,
            segment=segment,
            anchor=anchor,
            skip=skip,
            limit=limit,
        )
    except Exception as exc:
        raise _workbench_error(exc) from exc


@router.post(
    "/scene-workbench/review",
    response_model=SceneReviewResponse,
)
async def api_review_scene_workbench_items(
    data: SceneReviewRequest,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    await require_active_project(db, novel_id)
    try:
        return await _scene_workbench_service.review_scenes(db, novel_id, data)
    except Exception as exc:
        raise _workbench_error(exc) from exc


@router.post(
    "/scene-workbench/source-mapping/review",
    response_model=SceneSourceMappingReviewResponse,
)
async def api_review_scene_source_mappings(
    data: SceneSourceMappingReviewRequest,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    await require_active_project(db, novel_id)
    try:
        return await _scene_workbench_service.review_source_mappings(
            db,
            novel_id,
            data,
        )
    except Exception as exc:
        raise _workbench_error(exc) from exc


@router.patch(
    "/scene-workbench/scenes/{scene_id}/mapping",
    response_model=SceneResponse,
)
async def api_update_scene_workbench_mapping(
    scene_id: str,
    data: SceneMappingUpdate,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    await require_active_project(db, novel_id)
    try:
        return await _scene_workbench_service.update_mapping(
            db,
            novel_id,
            scene_id,
            data,
        )
    except Exception as exc:
        raise _workbench_error(exc) from exc


@router.post(
    "/scene-workbench/chapters/{chapter_index}/scenes/{scene_id}",
    response_model=SceneResponse,
)
async def api_link_scene_to_chapter(
    scene_id: str,
    db: DbSession,
    chapter_index: int = Path(..., ge=1, description="章节索引"),
    *,
    novel_id: NovelIdQuery,
):
    await require_active_project(db, novel_id)
    try:
        return await _scene_workbench_service.link_scene_to_chapter(
            db,
            novel_id,
            chapter_index,
            scene_id,
        )
    except Exception as exc:
        raise _workbench_error(exc) from exc


@router.post(
    "/scene-workbench/chapters/{chapter_index}/scenes",
    response_model=SceneResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def api_create_scene_for_chapter(
    data: SceneChapterQuickCreate,
    db: DbSession,
    chapter_index: int = Path(..., ge=1, description="章节索引"),
    *,
    novel_id: NovelIdQuery,
):
    await require_active_project(db, novel_id)
    try:
        return await _scene_workbench_service.create_scene_for_chapter(
            db,
            novel_id,
            chapter_index,
            data,
        )
    except Exception as exc:
        raise _workbench_error(exc) from exc


@router.post(
    "/scene-workbench/merge/preview",
    response_model=SceneImpactPreview,
)
async def api_preview_scene_merge(
    data: SceneMergeRequest,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    await require_active_project(db, novel_id)
    try:
        return await _scene_workbench_service.preview_merge(db, novel_id, data)
    except Exception as exc:
        raise _workbench_error(exc) from exc


@router.post("/scene-workbench/merge", response_model=SceneWorkbenchItem)
async def api_merge_scene(
    data: SceneMergeRequest,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    await require_active_project(db, novel_id)
    try:
        return await _scene_workbench_service.merge(db, novel_id, data)
    except Exception as exc:
        raise _workbench_error(exc) from exc


@router.post(
    "/scene-workbench/split/preview",
    response_model=SceneImpactPreview,
)
async def api_preview_scene_split(
    data: SceneSplitRequest,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    await require_active_project(db, novel_id)
    try:
        return await _scene_workbench_service.preview_split(db, novel_id, data)
    except Exception as exc:
        raise _workbench_error(exc) from exc


@router.post("/scene-workbench/split", response_model=SceneWorkbenchItem)
async def api_split_scene(
    data: SceneSplitRequest,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    await require_active_project(db, novel_id)
    try:
        return await _scene_workbench_service.split(db, novel_id, data)
    except Exception as exc:
        raise _workbench_error(exc) from exc


@router.post(
    "/scene-workbench/fusion/preview",
    response_model=SceneFusionPreviewResponse,
    deprecated=True,
)
async def api_preview_scene_fusion(
    data: SceneFusionPreviewRequest,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    await require_active_project(db, novel_id)
    try:
        return await _scene_workbench_service.preview_llm_fusion(db, novel_id, data)
    except Exception as exc:
        raise _workbench_error(exc) from exc


@router.post(
    "/scene-workbench/fusion/preview-task",
    response_model=SceneFusionPreviewTaskResponse,
    status_code=202,
)
async def api_preview_scene_fusion_task(
    data: SceneFusionPreviewTaskRequest,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
) -> SceneFusionPreviewTaskResponse:
    await require_active_project(db, novel_id)
    payload = data.model_dump(mode="json", exclude={"operation_id"})
    try:
        existing = await get_operation_task(
            db,
            operation_id=str(data.operation_id),
            task_type="scene_fusion_preview",
            novel_id=novel_id,
            request_payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if existing is not None:
        return SceneFusionPreviewTaskResponse(
            task_id=existing.task_id,
            status=existing.status,
        )
    snapshot = await build_project_llm_execution_snapshot(db, novel_id)
    try:
        receipt = await enqueue_task_with_optional_operation(
            db,
            operation_id=str(data.operation_id),
            task_type="scene_fusion_preview",
            novel_id=novel_id,
            request_payload=payload,
            meta={**payload, "novel_id": novel_id, "llm_execution_snapshot": snapshot},
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.flush()
    return SceneFusionPreviewTaskResponse(
        task_id=receipt.task_id,
        status=receipt.status,
    )


@router.post(
    "/scene-workbench/fusion/save",
    response_model=SceneFusionSaveResponse,
)
async def api_save_scene_fusion(
    data: SceneFusionSaveRequest,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    await require_active_project(db, novel_id)
    try:
        return await _scene_workbench_service.save_llm_fusion(db, novel_id, data)
    except Exception as exc:
        raise _workbench_error(exc) from exc


@router.get(
    "/scene-workbench/fusion-suggestions",
    response_model=SceneFusionSuggestionListResponse,
)
async def api_list_fusion_suggestions(
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
):
    await require_active_project(db, novel_id)
    try:
        return await _scene_workbench_service.list_fusion_suggestions(
            db,
            novel_id,
            skip=skip,
            limit=limit,
        )
    except Exception as exc:
        raise _workbench_error(exc) from exc


@router.post(
    "/scene-workbench/fusion-suggestions/dismiss",
    response_model=SceneFusionSuggestionDismissResponse,
)
async def api_dismiss_fusion_suggestions(
    data: SceneFusionSuggestionDismissRequest,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    await require_active_project(db, novel_id)
    try:
        return await _scene_workbench_service.dismiss_fusion_suggestions(
            db,
            novel_id,
            data,
        )
    except Exception as exc:
        raise _workbench_error(exc) from exc


@router.post(
    "/scene-workbench/replacement-suggestions/apply",
    response_model=SceneReplacementApplyResponse,
)
async def api_apply_replacement_suggestion(
    data: SceneReplacementApplyRequest,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    await require_active_project(db, novel_id)
    try:
        return await _scene_workbench_service.apply_replacement_suggestion(
            db,
            novel_id,
            data,
        )
    except SceneSuggestionConflictError as exc:
        if exc.persist_stale:
            await db.commit()
        raise _workbench_error(exc) from exc
    except Exception as exc:
        raise _workbench_error(exc) from exc


@router.post(
    "/scenes", response_model=SceneResponse, status_code=http_status.HTTP_201_CREATED
)
async def api_create_scene(
    data: SceneCreate,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    await require_active_project(db, novel_id)
    return await _scene_workbench_service.create_scene(db, novel_id, data)


@router.get("/scenes", response_model=SceneListResponse)
async def api_list_scenes(
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
):
    await require_active_project(db, novel_id)
    return await _scene_service.list_with_response(db, novel_id, skip=skip, limit=limit)


@router.get("/scenes/ordered", response_model=list[SceneResponse])
async def api_list_scenes_ordered(
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    await require_active_project(db, novel_id)
    contracts = await _scene_service.get_ordered(db, novel_id)
    return [SceneResponse.model_validate(c.__dict__) for c in contracts]


@router.get("/scenes/by-chapter", response_model=list[SceneResponse])
async def api_list_scenes_by_chapter(
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
    chapter_index: int = Query(..., ge=1, description="章节索引"),
):
    await require_active_project(db, novel_id)
    contracts = await _scene_service.get_by_chapter(db, novel_id, chapter_index)
    return [SceneResponse.model_validate(c.__dict__) for c in contracts]


@router.get("/scenes/{scene_id}", response_model=SceneResponse)
async def api_get_scene(
    scene_id: str,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    await require_active_project(db, novel_id)
    return await _scene_service.get(db, scene_id, novel_id=novel_id)


@router.patch("/scenes/{scene_id}", response_model=SceneResponse)
async def api_update_scene(
    scene_id: str,
    data: SceneUpdate,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    await require_active_project(db, novel_id)
    return await _scene_workbench_service.update_scene(db, novel_id, scene_id, data)


@router.delete("/scenes/{scene_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def api_delete_scene(
    scene_id: str,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    await require_active_project(db, novel_id)
    await _scene_workbench_service.delete_scene(db, novel_id, scene_id)


@router.post("/scenes/reorder", response_model=SceneReorderResponse)
async def api_reorder_scenes(
    data: SceneReorderRequest,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    """批量重排 Scene 顺序，按 scene_ids 列表顺序从 0 重新编号"""
    await require_active_project(db, novel_id)
    return await _scene_workbench_service.reorder_scenes(db, novel_id, data.scene_ids)


@router.post("/scenes/split", response_model=list[SceneResponse])
async def api_split_chapters(
    data: SplitChaptersRequest,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    """断章：从 chapter_index 开始将章节从当前 Scene 移到目标 Scene"""
    await require_active_project(db, novel_id)
    return await _scene_workbench_service.split_chapters_from_api(
        db,
        novel_id,
        data.chapter_index,
        data.target_scene_id,
    )


# ============================================================
# AI Generation
# ============================================================


@router.post(
    "/analyze",
    response_model=OutlineAiTaskResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def api_analyze_outline(
    data: OutlineAiTaskRequest,
    db: DbSession,
) -> OutlineAiTaskResponse:
    await require_active_project(db, data.novel_id)
    return await _enqueue_confirmed_outline_task(
        db,
        data,
        action="outline.analyze",
        task_type="outline_analyze",
    )


@router.post(
    "/generate",
    response_model=OutlineAiTaskResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def api_generate_plot_structure(
    db: DbSession,
    data: OutlineLayerGenerateRequest,
) -> OutlineAiTaskResponse:
    await require_active_project(db, data.novel_id)
    return await _enqueue_outline_layer_task(db, data)


@router.post(
    "/generate/apply",
    response_model=OutlineStructurePreviewApplyResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def api_apply_structure_preview(
    data: OutlineStructurePreviewApplyRequest,
    db: DbSession,
) -> OutlineStructurePreviewApplyResponse:
    await require_active_project(db, data.novel_id)
    from modules.story.outline_state.ai_workflow_service import OutlineAIWorkflowService

    try:
        result = await OutlineAIWorkflowService().apply_structure_preview(
            db,
            novel_id=data.novel_id,
            confirmation_id=data.context_confirmation_id,
            source_task_id=data.source_task_id,
            draft_structure=data.draft_structure,
            confirmed=data.confirmed,
        )
    except P20ConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail=redact_diagnostic(exc),
        ) from exc
    except (PermissionError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail=redact_diagnostic(exc),
        ) from exc
    return OutlineStructurePreviewApplyResponse.model_validate(result)


# ============================================================
# Foreshadowing Plans
# ============================================================


@router.post(
    "/foreshadowing",
    response_model=ForeshadowingPlanResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def api_create_foreshadowing(
    data: ForeshadowingPlanCreate,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    await require_active_project(db, novel_id)
    return await _foreshadowing_service.create(db, novel_id, data)


@router.get("/foreshadowing", response_model=ForeshadowingPlanListResponse)
async def api_list_foreshadowing(
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
    status: str | None = Query(None, description="状态过滤"),
    source: str | None = Query(None, description="来源过滤"),
    workflow_id: str | None = Query(None, description="深度导入 workflow ID"),
    needs_review: bool | None = Query(None, description="是否需要复核"),
    related_thread_id: str | None = Query(None, description="关联剧情线 ID"),
    unassigned: bool | None = Query(None, description="是否未归入有效剧情线"),
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
):
    await require_active_project(db, novel_id)
    return await _foreshadowing_service.list_with_response(
        db,
        novel_id,
        skip=skip,
        limit=limit,
        status=status,
        source=source,
        workflow_id=workflow_id,
        needs_review=needs_review,
        related_thread_id=related_thread_id,
        unassigned=unassigned,
    )


@router.get("/foreshadowing/{plan_id}", response_model=ForeshadowingPlanResponse)
async def api_get_foreshadowing(
    plan_id: str,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    await require_active_project(db, novel_id)
    return await _foreshadowing_service.get_foreshadowing_plan(db, plan_id, novel_id)


@router.patch("/foreshadowing/{plan_id}", response_model=ForeshadowingPlanResponse)
async def api_update_foreshadowing(
    plan_id: str,
    data: ForeshadowingPlanUpdate,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    await require_active_project(db, novel_id)
    return await _foreshadowing_service.update(db, plan_id, data, novel_id=novel_id)


@router.delete(
    "/foreshadowing/{plan_id}",
    status_code=http_status.HTTP_204_NO_CONTENT,
)
async def api_delete_foreshadowing(
    plan_id: str,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    await require_active_project(db, novel_id)
    await _foreshadowing_service.delete(db, plan_id, novel_id=novel_id)


# ============================================================
# Reveal Plans
# ============================================================


@router.post(
    "/reveals",
    response_model=RevealPlanResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def api_create_reveal(
    data: RevealPlanCreate,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    await require_active_project(db, novel_id)
    return await _reveal_service.create(db, novel_id, data)


@router.get("/reveals", response_model=RevealPlanListResponse)
async def api_list_reveals(
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
    status: str | None = Query(None, description="状态过滤"),
    source: str | None = Query(None, description="来源过滤"),
    workflow_id: str | None = Query(None, description="深度导入 workflow ID"),
    needs_review: bool | None = Query(None, description="是否需要复核"),
    related_thread_id: str | None = Query(None, description="关联剧情线 ID"),
    unassigned: bool | None = Query(None, description="是否未归入有效剧情线"),
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
):
    await require_active_project(db, novel_id)
    return await _reveal_service.list_with_response(
        db,
        novel_id,
        skip=skip,
        limit=limit,
        status=status,
        source=source,
        workflow_id=workflow_id,
        needs_review=needs_review,
        related_thread_id=related_thread_id,
        unassigned=unassigned,
    )


@router.get("/reveals/{plan_id}", response_model=RevealPlanResponse)
async def api_get_reveal(
    plan_id: str,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    await require_active_project(db, novel_id)
    return await _reveal_service.get_reveal_plan(db, plan_id, novel_id)


@router.patch("/reveals/{plan_id}", response_model=RevealPlanResponse)
async def api_update_reveal(
    plan_id: str,
    data: RevealPlanUpdate,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    await require_active_project(db, novel_id)
    return await _reveal_service.update(db, plan_id, data, novel_id=novel_id)


@router.delete(
    "/reveals/{plan_id}",
    status_code=http_status.HTTP_204_NO_CONTENT,
)
async def api_delete_reveal(
    plan_id: str,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    await require_active_project(db, novel_id)
    await _reveal_service.delete(db, plan_id, novel_id=novel_id)
