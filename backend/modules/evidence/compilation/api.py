"""
Context API 路由

提供上下文编译和渲染的 REST API。
API 层不写复杂业务逻辑，仅做参数校验和路由分发。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi import status as http_status

from core.api_params import NovelIdQuery
from core.dependencies import DbSession
from modules.evidence.compilation.contracts import VisibilityContextContract
from modules.evidence.compilation.facade import compile_with_tiers
from modules.evidence.compilation.facade import confirm_context as _confirm_context
from modules.evidence.compilation.facade import (
    create_activation_profile as _create_activation_profile,
)
from modules.evidence.compilation.facade import (
    get_context_snapshot as _get_context_snapshot,
)
from modules.evidence.compilation.facade import (
    get_evidence_health as _get_evidence_health,
)
from modules.evidence.compilation.facade import (
    grep_novel_evidence as _grep_novel_evidence,
)
from modules.evidence.compilation.facade import (
    inspect_novel_target as _inspect_novel_target,
)
from modules.evidence.compilation.facade import (
    list_activation_profile_revisions as _list_activation_profile_revisions,
)
from modules.evidence.compilation.facade import (
    list_activation_profiles as _list_activation_profiles,
)
from modules.evidence.compilation.facade import (
    list_context_snapshots as _list_context_snapshots,
)
from modules.evidence.compilation.facade import (
    list_retrieval_traces as _list_retrieval_traces,
)
from modules.evidence.compilation.facade import load_scene_lens as _load_scene_lens
from modules.evidence.compilation.facade import preview_activation as _preview_activation
from modules.evidence.compilation.facade import (
    publish_activation_profile as _publish_activation_profile,
)
from modules.evidence.compilation.facade import (
    read_novel_evidence as _read_novel_evidence,
)
from modules.evidence.compilation.facade import (
    restore_activation_profile_revision as _restore_activation_profile_revision,
)
from modules.evidence.compilation.facade import (
    run_snapshot_maintenance as _run_snapshot_maintenance,
)
from modules.evidence.compilation.facade import (
    search_novel_evidence as _search_novel_evidence,
)
from modules.evidence.compilation.facade import (
    trace_novel_evidence as _trace_novel_evidence,
)
from modules.evidence.compilation.facade import (
    update_activation_profile as _update_activation_profile,
)
from modules.evidence.compilation.markdown_renderer import render_compiled_context
from modules.evidence.compilation.schemas import (
    ContextActivationPreviewRequest,
    ContextActivationPreviewResponse,
    ContextActivationProfileCreate,
    ContextActivationProfileListResponse,
    ContextActivationProfilePublishRequest,
    ContextActivationProfileResponse,
    ContextActivationProfileRestoreRequest,
    ContextActivationProfileRevisionResponse,
    ContextActivationProfileUpdate,
    ContextCompileRequest,
    ContextConfirmationResponse,
    ContextConfirmRequest,
    ContextRenderRequest,
    ContextRenderResponse,
    ContextRetrievalTraceListResponse,
    ContextRetrievalTraceResponse,
    ContextSnapshotListItemResponse,
    ContextSnapshotListResponse,
    ContextSnapshotMaintenanceRequest,
    ContextSnapshotMaintenanceResponse,
    ContextSnapshotResponse,
    ContextTierCompileResponse,
    EvidenceGrepRequest,
    EvidenceHealthResponse,
    EvidenceInspectRequest,
    EvidenceInspectResponse,
    EvidenceReadRequest,
    EvidenceReadResponse,
    EvidenceSearchRequest,
    EvidenceSearchResponse,
    EvidenceTraceRequest,
    EvidenceTraceResponse,
    SceneLensRequest,
    SceneLensResponse,
)
from modules.evidence.compilation.services.review_projection import (
    build_tier_compile_response,
)
from modules.project.facade import require_active_project
from modules.writing.contracts import SourceRangeRefContract

_VALID_SCOPES: frozenset[str] = frozenset(
    {"project", "world", "world_character", "arc", "chapter", "full"}
)

handler_router = APIRouter(tags=["context"])
router = handler_router


@router.post("/scene-lens", response_model=SceneLensResponse)
async def scene_lens(
    db: DbSession,
    request: SceneLensRequest,
) -> SceneLensResponse:
    """Load one Scene's safe POV knowledge and existing world-state checkpoints."""
    await require_active_project(db, request.novel_id)
    result = await _load_scene_lens(
        db,
        novel_id=request.novel_id,
        scene_id=request.scene_id,
        chapter_index=request.chapter_index,
    )
    return SceneLensResponse(**result)


def _build_tier_compile_response(
    request: ContextCompileRequest | ContextRenderRequest,
    ctx,
) -> ContextTierCompileResponse:
    """从 CompiledContext IR 构建 ContextTierCompileResponse。"""
    return build_tier_compile_response(request, ctx)


def _validate_scope(
    request: ContextCompileRequest | ContextRenderRequest | ContextConfirmRequest,
) -> None:
    """scope 必须是受支持的取值之一。"""
    if request.scope not in _VALID_SCOPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"无效的 scope: {request.scope}，"
                f"必须是 {', '.join(sorted(_VALID_SCOPES))} 之一"
            ),
        )


def _validate_character_reveal_mode(
    request: ContextCompileRequest | ContextRenderRequest | ContextConfirmRequest,
) -> None:
    """character 揭示模式必须提供 viewpoint_character_id。"""
    if request.reveal_mode == "character" and not request.viewpoint_character_id:
        raise HTTPException(
            status_code=400,
            detail="character 揭示模式必须提供 viewpoint_character_id",
        )
    if (
        request.reveal_mode in {"reader", "character"}
        and request.visible_until_chapter is None
        and request.chapter_index is None
    ):
        raise HTTPException(
            status_code=400,
            detail="reader/character 揭示模式必须提供可见截止章",
        )


@router.post("/compile", response_model=ContextTierCompileResponse)
async def compile_context(
    db: DbSession,
    request: ContextCompileRequest,
) -> ContextTierCompileResponse:
    """编译结构化创作上下文

    根据 scope 从各模块按需加载数据，返回 Tier 化的编译 IR。
    """
    await require_active_project(db, request.novel_id)
    _validate_scope(request)
    _validate_character_reveal_mode(request)

    ctx = await compile_with_tiers(
        db=db,
        novel_id=request.novel_id,
        task=request.task,
        scope=request.scope,
        budget_tokens=request.budget_tokens,
        scene_id=request.scene_id,
        retrieval_purpose=request.retrieval_purpose,
        chapter_index=request.chapter_index,
        visible_until_chapter=request.visible_until_chapter,
        visible_until_scene_id=request.visible_until_scene_id,
        visible_until_offset=request.visible_until_offset,
        arc_id=request.arc_id,
        entity_ids=request.entity_ids,
        character_ids=request.character_ids,
        thread_ids=request.thread_ids,
        location_ids=request.location_ids,
        reveal_mode=request.reveal_mode,
        enable_geo_filter=request.enable_geo_filter,
        viewpoint_character_id=request.viewpoint_character_id,
        context_mode=request.context_mode,
        content_mode=request.content_mode,
        include_pending_objects=request.include_pending_objects,
        excluded_asset_ids=request.excluded_asset_ids,
        user_note=request.user_note,
        include_world_synopsis=request.include_world_synopsis,
        selected_world_bible_draft_ids=request.selected_world_bible_draft_ids,
        activation_profile_id=request.activation_profile_id,
        activation_profile_version=request.activation_profile_version,
    )

    return _build_tier_compile_response(request, ctx)


@router.post("/render", response_model=ContextRenderResponse)
async def render_context(
    db: DbSession,
    request: ContextRenderRequest,
) -> ContextRenderResponse:
    """编译 + 渲染上下文为 Markdown

    一次调用完成 Tier IR 编译和 Markdown 渲染，返回可直接放入 LLM Prompt 的文本
    以及编译元信息。
    """
    await require_active_project(db, request.novel_id)
    _validate_scope(request)
    _validate_character_reveal_mode(request)

    ctx = await compile_with_tiers(
        db=db,
        novel_id=request.novel_id,
        task=request.task,
        scope=request.scope,
        budget_tokens=request.budget_tokens,
        scene_id=request.scene_id,
        retrieval_purpose=request.retrieval_purpose,
        chapter_index=request.chapter_index,
        visible_until_chapter=request.visible_until_chapter,
        visible_until_scene_id=request.visible_until_scene_id,
        visible_until_offset=request.visible_until_offset,
        arc_id=request.arc_id,
        entity_ids=request.entity_ids,
        character_ids=request.character_ids,
        thread_ids=request.thread_ids,
        location_ids=request.location_ids,
        reveal_mode=request.reveal_mode,
        enable_geo_filter=request.enable_geo_filter,
        viewpoint_character_id=request.viewpoint_character_id,
        context_mode=request.context_mode,
        content_mode=request.content_mode,
        include_pending_objects=request.include_pending_objects,
        excluded_asset_ids=request.excluded_asset_ids,
        user_note=request.user_note,
        include_world_synopsis=request.include_world_synopsis,
        selected_world_bible_draft_ids=request.selected_world_bible_draft_ids,
        activation_profile_id=request.activation_profile_id,
        activation_profile_version=request.activation_profile_version,
    )

    markdown = render_compiled_context(ctx)
    compile_info = _build_tier_compile_response(request, ctx)

    return ContextRenderResponse(
        markdown=markdown,
        compile_info=compile_info,
    )


@router.post(
    "/confirm",
    response_model=ContextConfirmationResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def confirm_context(
    db: DbSession,
    request: ContextConfirmRequest,
) -> ContextConfirmationResponse:
    """确认一次手动 AI 操作使用的参考资料摘要。"""
    await require_active_project(db, request.novel_id)
    _validate_scope(request)
    _validate_character_reveal_mode(request)

    confirmation = await _confirm_context(
        db,
        novel_id=request.novel_id,
        action=request.action,
        task=request.task,
        scope=request.scope,
        retrieval_purpose=request.retrieval_purpose,
        chapter_index=request.chapter_index,
        visible_until_chapter=request.visible_until_chapter,
        visible_until_scene_id=request.visible_until_scene_id,
        visible_until_offset=request.visible_until_offset,
        scene_id=request.scene_id,
        arc_id=request.arc_id,
        entity_ids=request.entity_ids,
        character_ids=request.character_ids,
        thread_ids=request.thread_ids,
        location_ids=request.location_ids,
        reveal_mode=request.reveal_mode,
        enable_geo_filter=request.enable_geo_filter,
        viewpoint_character_id=request.viewpoint_character_id,
        budget_tokens=request.budget_tokens,
        context_mode=request.context_mode,
        content_mode=request.content_mode,
        include_pending_objects=request.include_pending_objects,
        excluded_asset_ids=request.excluded_asset_ids,
        user_note=request.user_note,
        include_world_synopsis=request.include_world_synopsis,
        selected_world_bible_draft_ids=request.selected_world_bible_draft_ids,
        activation_profile_id=request.activation_profile_id,
        activation_profile_version=request.activation_profile_version,
    )
    return ContextConfirmationResponse(**confirmation.__dict__)


@router.get("/evidence-health", response_model=EvidenceHealthResponse)
async def get_evidence_health(
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
    content_mode: str = Query("canonical", pattern="^(canonical|working)$"),
    window_hours: int = Query(24, ge=1, le=24 * 30),
) -> EvidenceHealthResponse:
    await require_active_project(db, novel_id)
    result = await _get_evidence_health(
        db,
        novel_id=str(novel_id),
        content_mode=content_mode,
        window_hours=window_hours,
    )
    return EvidenceHealthResponse(**result.__dict__)


@router.get(
    "/retrieval-traces",
    response_model=ContextRetrievalTraceListResponse,
)
async def list_retrieval_traces(
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
    content_mode: str | None = Query(None, pattern="^(canonical|working)$"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> ContextRetrievalTraceListResponse:
    await require_active_project(db, novel_id)
    records = await _list_retrieval_traces(
        db,
        novel_id=str(novel_id),
        content_mode=content_mode,
        limit=limit,
        offset=offset,
    )
    items = [ContextRetrievalTraceResponse(**record.__dict__) for record in records]
    return ContextRetrievalTraceListResponse(items=items, total=len(items))


def _visibility(request) -> VisibilityContextContract:
    return VisibilityContextContract(**request.model_dump())


@router.post("/evidence/grep", response_model=EvidenceSearchResponse)
async def grep_evidence(
    db: DbSession,
    request: EvidenceGrepRequest,
) -> EvidenceSearchResponse:
    await require_active_project(db, request.novel_id)
    result = await _grep_novel_evidence(
        db,
        novel_id=request.novel_id,
        pattern=request.pattern,
        content_mode=request.content_mode,
        visibility=_visibility(request.visibility),
        chapter_from=request.chapter_from,
        chapter_to=request.chapter_to,
        case_sensitive=request.case_sensitive,
        skip=request.skip,
        limit=request.limit,
        group_by_chapter=request.group_by_chapter,
        context_scene_id=request.context_scene_id,
    )
    return EvidenceSearchResponse(**result)


@router.post("/evidence/search", response_model=EvidenceSearchResponse)
async def search_evidence(
    db: DbSession,
    request: EvidenceSearchRequest,
) -> EvidenceSearchResponse:
    await require_active_project(db, request.novel_id)
    result = await _search_novel_evidence(
        db,
        novel_id=request.novel_id,
        query=request.query,
        content_mode=request.content_mode,
        visibility=_visibility(request.visibility),
        scopes=list(request.scopes),
        include_pending_objects=request.include_pending_objects,
        chapter_from=request.chapter_from,
        chapter_to=request.chapter_to,
        top_k=request.top_k,
        context_scene_id=request.context_scene_id,
    )
    return EvidenceSearchResponse(**result)


@router.post("/evidence/read", response_model=EvidenceReadResponse)
async def read_evidence(
    db: DbSession,
    request: EvidenceReadRequest,
) -> EvidenceReadResponse:
    await require_active_project(db, request.novel_id)
    if request.source_ref.content_mode != request.content_mode:
        raise HTTPException(status_code=400, detail="source_ref content_mode mismatch")
    try:
        result = await _read_novel_evidence(
            db,
            novel_id=request.novel_id,
            source_ref=SourceRangeRefContract(**request.source_ref.model_dump()),
            visibility=_visibility(request.visibility),
            before=request.before,
            after=request.after,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return EvidenceReadResponse(**result)


@router.post("/evidence/inspect", response_model=EvidenceInspectResponse)
async def inspect_evidence(
    db: DbSession,
    request: EvidenceInspectRequest,
) -> EvidenceInspectResponse:
    await require_active_project(db, request.novel_id)
    try:
        result = await _inspect_novel_target(
            db,
            novel_id=request.novel_id,
            target_ref=request.target_ref,
            content_mode=request.content_mode,
            visibility=_visibility(request.visibility),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return EvidenceInspectResponse(**result)


@router.post("/evidence/trace", response_model=EvidenceTraceResponse)
async def trace_evidence(
    db: DbSession,
    request: EvidenceTraceRequest,
) -> EvidenceTraceResponse:
    await require_active_project(db, request.novel_id)
    try:
        result = await _trace_novel_evidence(
            db,
            novel_id=request.novel_id,
            target_ref=request.target_ref,
            claim_path=request.claim_path,
            content_mode=request.content_mode,
            visibility=_visibility(request.visibility),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return EvidenceTraceResponse(**result)


@router.get(
    "/activation-profiles",
    response_model=ContextActivationProfileListResponse,
)
async def list_activation_profiles(
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
    include_archived: bool = False,
) -> ContextActivationProfileListResponse:
    await require_active_project(db, novel_id)
    items = await _list_activation_profiles(
        db,
        str(novel_id),
        include_archived=include_archived,
    )
    return ContextActivationProfileListResponse(items=items, total=len(items))


@router.post(
    "/activation-profiles",
    response_model=ContextActivationProfileResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def create_activation_profile(
    db: DbSession,
    request: ContextActivationProfileCreate,
) -> ContextActivationProfileResponse:
    await require_active_project(db, request.novel_id)
    return await _create_activation_profile(db, request)


@router.patch(
    "/activation-profiles/{profile_id}",
    response_model=ContextActivationProfileResponse,
)
async def update_activation_profile(
    db: DbSession,
    profile_id: str,
    request: ContextActivationProfileUpdate,
    *,
    novel_id: NovelIdQuery,
) -> ContextActivationProfileResponse:
    await require_active_project(db, novel_id)
    return await _update_activation_profile(
        db,
        str(novel_id),
        profile_id,
        request,
    )


@router.post(
    "/activation-profiles/{profile_id}/publish",
    response_model=ContextActivationProfileResponse,
)
async def publish_activation_profile(
    db: DbSession,
    profile_id: str,
    request: ContextActivationProfilePublishRequest,
    *,
    novel_id: NovelIdQuery,
) -> ContextActivationProfileResponse:
    await require_active_project(db, novel_id)
    return await _publish_activation_profile(
        db,
        str(novel_id),
        profile_id,
        request,
    )


@router.get(
    "/activation-profiles/{profile_id}/revisions",
    response_model=list[ContextActivationProfileRevisionResponse],
)
async def list_activation_profile_revisions(
    db: DbSession,
    profile_id: str,
    *,
    novel_id: NovelIdQuery,
) -> list[ContextActivationProfileRevisionResponse]:
    await require_active_project(db, novel_id)
    return await _list_activation_profile_revisions(
        db,
        str(novel_id),
        profile_id,
    )


@router.post(
    "/activation-profiles/{profile_id}/revisions/{version_number}/restore-draft",
    response_model=ContextActivationProfileResponse,
)
async def restore_activation_profile_revision(
    db: DbSession,
    profile_id: str,
    version_number: int,
    request: ContextActivationProfileRestoreRequest,
    *,
    novel_id: NovelIdQuery,
) -> ContextActivationProfileResponse:
    await require_active_project(db, novel_id)
    return await _restore_activation_profile_revision(
        db,
        str(novel_id),
        profile_id,
        version_number,
        restored_by=request.restored_by,
    )


@router.get("/activation-preview", response_model=ContextActivationPreviewResponse)
async def activation_preview(
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
    entity_ids: list[str] | None = Query(None),
    map_id: str | None = None,
    scene_id: str | None = None,
    focus_entity_id: str | None = None,
    top_k: int = Query(64, ge=1, le=256),
    depth: int = Query(2, ge=0, le=2),
) -> ContextActivationPreviewResponse:
    await require_active_project(db, novel_id)
    request = ContextActivationPreviewRequest(
        novel_id=novel_id,
        entity_ids=entity_ids or [],
        map_id=map_id,
        scene_id=scene_id,
        focus_entity_id=focus_entity_id,
        top_k=top_k,
        depth=depth,
    )
    result = await _preview_activation(db, **request.model_dump())
    return ContextActivationPreviewResponse(**result)


@router.post("/activation-preview", response_model=ContextActivationPreviewResponse)
async def structured_activation_preview(
    db: DbSession,
    request: ContextActivationPreviewRequest,
) -> ContextActivationPreviewResponse:
    """Return the additive typed trace while preserving the legacy GET route."""
    await require_active_project(db, request.novel_id)
    result = await _preview_activation(db, **request.model_dump())
    return ContextActivationPreviewResponse(**result)


@router.get("/snapshots", response_model=ContextSnapshotListResponse)
async def list_context_snapshots(
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
    workflow_id: str | None = None,
    task_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> ContextSnapshotListResponse:
    """按项目和任务/工作流查询自动上下文快照。"""
    await require_active_project(db, novel_id)
    snapshots = await _list_context_snapshots(
        db,
        novel_id=novel_id,
        workflow_id=workflow_id,
        task_id=task_id,
        limit=limit,
        offset=offset,
    )
    items = [
        ContextSnapshotListItemResponse(
            **{
                **snapshot.__dict__,
                "has_rendered_context": snapshot.rendered_context is not None,
            }
        )
        for snapshot in snapshots
    ]
    return ContextSnapshotListResponse(items=items, total=len(items))


@router.post(
    "/snapshots/maintenance",
    response_model=ContextSnapshotMaintenanceResponse,
)
async def maintain_context_snapshots(
    db: DbSession,
    request: ContextSnapshotMaintenanceRequest,
) -> ContextSnapshotMaintenanceResponse:
    """显式运行上下文快照生命周期维护；默认 dry-run。"""
    await require_active_project(db, request.novel_id)
    result = await _run_snapshot_maintenance(
        db,
        novel_id=request.novel_id,
        workflow_id=request.workflow_id,
        running_timeout_minutes=request.running_timeout_minutes,
        prune_rendered_context=request.prune_rendered_context,
        retain_latest_full_context_per_project=(
            request.retain_latest_full_context_per_project
        ),
        prune_retrieval_traces=request.prune_retrieval_traces,
        retrieval_trace_retention_days=request.retrieval_trace_retention_days,
        retain_latest_retrieval_traces=request.retain_latest_retrieval_traces,
        dry_run=request.dry_run,
    )
    return ContextSnapshotMaintenanceResponse(**result)


@router.get("/snapshots/{snapshot_id}", response_model=ContextSnapshotResponse)
async def get_context_snapshot(
    db: DbSession,
    snapshot_id: str,
    *,
    novel_id: NovelIdQuery,
) -> ContextSnapshotResponse:
    """读取单条上下文快照；必须匹配 novel_id。"""
    await require_active_project(db, novel_id)
    try:
        snapshot = await _get_context_snapshot(
            db,
            novel_id=novel_id,
            snapshot_id=snapshot_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ContextSnapshotResponse(**snapshot.__dict__)
