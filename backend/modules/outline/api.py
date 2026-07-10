from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi import status as http_status

from core.api_params import NovelIdQuery
from core.dependencies import DbSession
from infrastructure.tasks.enqueuer import enqueue_task
from modules.context.facade import attach_result_ref, require_fresh_confirmation
from modules.outline.scene_workbench import SceneWorkbenchService
from modules.outline.schemas import (
    CrossChapterSceneDetectRequest,
    CrossChapterSceneDetectResponse,
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
    OutlineScenePreviewApplyRequest,
    OutlineScenePreviewApplyResponse,
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
    SceneCreate,
    SceneFusionPreviewRequest,
    SceneFusionPreviewResponse,
    SceneFusionSaveRequest,
    SceneFusionSaveResponse,
    SceneImpactPreview,
    SceneListResponse,
    SceneMappingUpdate,
    SceneMergeRequest,
    SceneReorderRequest,
    SceneReorderResponse,
    SceneResponse,
    SceneSplitRequest,
    SceneUpdate,
    SceneWorkbenchItem,
    SceneWorkbenchResponse,
    SplitChaptersRequest,
)
from modules.outline.services import (
    ForeshadowingPlanService,
    OutlineArcService,
    PlotThreadService,
    RevealPlanService,
    SceneService,
)
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

router = APIRouter(prefix="/api/outline", tags=["outline"])

_thread_service = PlotThreadService()
_arc_service = OutlineArcService()
_scene_service = SceneService()
_scene_workbench_service = SceneWorkbenchService()
_foreshadowing_service = ForeshadowingPlanService()
_reveal_service = RevealPlanService()


def _workbench_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc) or "Not found")
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


async def _enqueue_confirmed_outline_task(
    db: DbSession,
    data: OutlineAiTaskRequest,
    *,
    action: str,
    task_type: str,
) -> OutlineAiTaskResponse:
    try:
        await require_fresh_confirmation(
            db,
            novel_id=data.novel_id,
            action=action,
            confirmation_id=data.context_confirmation_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    meta = data.model_dump(exclude_none=True)
    task_id = enqueue_task(db, task_type, meta=meta)
    await attach_result_ref(
        db,
        confirmation_id=data.context_confirmation_id,
        result_type="task",
        result_id=task_id,
        status="running",
    )
    await db.flush()
    return OutlineAiTaskResponse(task_id=task_id)


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
    return await _thread_service.get(db, thread_id, novel_id=novel_id)


@router.patch("/threads/{thread_id}", response_model=PlotThreadResponse)
async def api_update_thread(
    thread_id: str,
    data: PlotThreadUpdate,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    return await _thread_service.update(db, thread_id, data, novel_id=novel_id)


@router.delete("/threads/{thread_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def api_delete_thread(
    thread_id: str,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
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
    return await _arc_service.get(db, arc_id, novel_id=novel_id)


@router.patch("/arcs/{arc_id}", response_model=OutlineArcResponse)
async def api_update_arc(
    arc_id: str,
    data: OutlineArcUpdate,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    return await _arc_service.update(db, arc_id, data, novel_id=novel_id)


@router.delete("/arcs/{arc_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def api_delete_arc(
    arc_id: str,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
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
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
):
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
            skip=skip,
            limit=limit,
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
    "/scene-workbench/merge/preview",
    response_model=SceneImpactPreview,
)
async def api_preview_scene_merge(
    data: SceneMergeRequest,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
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
    try:
        return await _scene_workbench_service.split(db, novel_id, data)
    except Exception as exc:
        raise _workbench_error(exc) from exc


@router.post(
    "/scene-workbench/fusion/preview",
    response_model=SceneFusionPreviewResponse,
)
async def api_preview_scene_fusion(
    data: SceneFusionPreviewRequest,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    try:
        return await _scene_workbench_service.preview_llm_fusion(db, novel_id, data)
    except Exception as exc:
        raise _workbench_error(exc) from exc


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
    try:
        return await _scene_workbench_service.save_llm_fusion(db, novel_id, data)
    except Exception as exc:
        raise _workbench_error(exc) from exc


@router.post(
    "/scene-workbench/cross-chapter/detect",
    response_model=CrossChapterSceneDetectResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def api_detect_cross_chapter_scenes(
    data: CrossChapterSceneDetectRequest,
    db: DbSession,
):
    task_id = enqueue_task(
        db,
        "scene_cross_chapter_detection",
        meta=data.model_dump(exclude_none=True),
    )
    await db.flush()
    return CrossChapterSceneDetectResponse(task_id=task_id)


@router.post(
    "/scenes", response_model=SceneResponse, status_code=http_status.HTTP_201_CREATED
)
async def api_create_scene(
    data: SceneCreate,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    return await _scene_workbench_service.create_scene(db, novel_id, data)


@router.get("/scenes", response_model=SceneListResponse)
async def api_list_scenes(
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
):
    return await _scene_service.list_with_response(db, novel_id, skip=skip, limit=limit)


@router.get("/scenes/ordered", response_model=list[SceneResponse])
async def api_list_scenes_ordered(
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    contracts = await _scene_service.get_ordered(db, novel_id)
    return [SceneResponse.model_validate(c.__dict__) for c in contracts]


@router.get("/scenes/by-chapter", response_model=list[SceneResponse])
async def api_list_scenes_by_chapter(
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
    chapter_index: int = Query(..., ge=1, description="章节索引"),
):
    contracts = await _scene_service.get_by_chapter(db, novel_id, chapter_index)
    return [SceneResponse.model_validate(c.__dict__) for c in contracts]


@router.get("/scenes/{scene_id}", response_model=SceneResponse)
async def api_get_scene(
    scene_id: str,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    return await _scene_service.get(db, scene_id, novel_id=novel_id)


@router.patch("/scenes/{scene_id}", response_model=SceneResponse)
async def api_update_scene(
    scene_id: str,
    data: SceneUpdate,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    return await _scene_workbench_service.update_scene(db, novel_id, scene_id, data)


@router.delete("/scenes/{scene_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def api_delete_scene(
    scene_id: str,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    await _scene_workbench_service.delete_scene(db, novel_id, scene_id)


@router.post("/scenes/reorder", response_model=SceneReorderResponse)
async def api_reorder_scenes(
    data: SceneReorderRequest,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    """批量重排 Scene 顺序，按 scene_ids 列表顺序从 0 重新编号"""
    return await _scene_workbench_service.reorder_scenes(db, novel_id, data.scene_ids)


@router.post("/scenes/split", response_model=list[SceneResponse])
async def api_split_chapters(
    data: SplitChaptersRequest,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    """断章：从 chapter_index 开始将章节从当前 Scene 移到目标 Scene"""
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
    data: OutlineAiTaskRequest,
) -> OutlineAiTaskResponse:
    return await _enqueue_confirmed_outline_task(
        db,
        data,
        action="outline.generate",
        task_type="outline_generate",
    )


@router.post(
    "/generate/apply",
    response_model=OutlineStructurePreviewApplyResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def api_apply_structure_preview(
    data: OutlineStructurePreviewApplyRequest,
    db: DbSession,
) -> OutlineStructurePreviewApplyResponse:
    from modules.outline.ai_workflow_service import OutlineAIWorkflowService

    try:
        result = await OutlineAIWorkflowService().apply_structure_preview(
            db,
            novel_id=data.novel_id,
            confirmation_id=data.context_confirmation_id,
            source_task_id=data.source_task_id,
            draft_structure=data.draft_structure,
            confirmed=data.confirmed,
        )
    except (PermissionError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return OutlineStructurePreviewApplyResponse.model_validate(result)


@router.post(
    "/chapter-scenes/extract",
    response_model=OutlineAiTaskResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def api_extract_chapter_scenes(
    data: OutlineAiTaskRequest,
    db: DbSession,
) -> OutlineAiTaskResponse:
    return await _enqueue_confirmed_outline_task(
        db,
        data,
        action="outline.chapter_scenes.extract",
        task_type="outline_chapter_scenes_extract",
    )


@router.post(
    "/chapter-scenes/apply",
    response_model=OutlineScenePreviewApplyResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def api_apply_chapter_scene_preview(
    data: OutlineScenePreviewApplyRequest,
    db: DbSession,
) -> OutlineScenePreviewApplyResponse:
    from modules.outline.ai_workflow_service import OutlineAIWorkflowService

    try:
        result = await OutlineAIWorkflowService().apply_chapter_scene_preview(
            db,
            novel_id=data.novel_id,
            confirmation_id=data.context_confirmation_id,
            source_task_id=data.source_task_id,
            draft_scenes=data.draft_scenes,
            confirmed=data.confirmed,
        )
    except (PermissionError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return OutlineScenePreviewApplyResponse.model_validate(result)


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
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
):
    return await _foreshadowing_service.list_with_response(
        db,
        novel_id,
        skip=skip,
        limit=limit,
        status=status,
        source=source,
        workflow_id=workflow_id,
        needs_review=needs_review,
    )


@router.get("/foreshadowing/{plan_id}", response_model=ForeshadowingPlanResponse)
async def api_get_foreshadowing(
    plan_id: str,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    return await _foreshadowing_service.get_foreshadowing_plan(db, plan_id, novel_id)


@router.patch("/foreshadowing/{plan_id}", response_model=ForeshadowingPlanResponse)
async def api_update_foreshadowing(
    plan_id: str,
    data: ForeshadowingPlanUpdate,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
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
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
):
    return await _reveal_service.list_with_response(
        db,
        novel_id,
        skip=skip,
        limit=limit,
        status=status,
        source=source,
        workflow_id=workflow_id,
        needs_review=needs_review,
    )


@router.get("/reveals/{plan_id}", response_model=RevealPlanResponse)
async def api_get_reveal(
    plan_id: str,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
    return await _reveal_service.get_reveal_plan(db, plan_id, novel_id)


@router.patch("/reveals/{plan_id}", response_model=RevealPlanResponse)
async def api_update_reveal(
    plan_id: str,
    data: RevealPlanUpdate,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
):
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
    await _reveal_service.delete(db, plan_id, novel_id=novel_id)
