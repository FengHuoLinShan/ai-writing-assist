"""
Context Facade — 对外入口

其他模块只能从 facade 导入。
Facade 不写复杂业务逻辑，只做稳定的对外代理。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import (
    CompileOptions,
    ConfirmedAIActionContext,
    ContextConfirmationContract,
    ContextRetrievalTraceContract,
    ContextSnapshotContract,
    ContextSnapshotRequest,
    EvidenceHealthContract,
    ImportContextActivationContract,
    StructureContextBundle,
    VisibilityContextContract,
)
from modules.context.markdown_renderer import (
    render_compiled_context as _render_compiled_context,
)
from modules.context.markdown_renderer import (
    render_context_markdown as _render_markdown,
)
from modules.context.services import (
    ContextCompiler,
    ContextConfirmationService,
    ContextSnapshotService,
    DurableContextSnapshotService,
)
from modules.context.services.compiled_context import CompiledContext
from modules.context.services.confirmed_ai_action import ConfirmedAIActionService
from modules.context.services.generation_background import (
    GenerationBackgroundRequest,
    GenerationBackgroundService,
)
from modules.context.services.hidden_guard import HiddenGuardBuilder, HiddenGuardTerm

_compiler = ContextCompiler()
_confirmation_service = ContextConfirmationService()
_confirmed_ai_action_service = ConfirmedAIActionService(_confirmation_service)
_snapshot_service = ContextSnapshotService()
_durable_snapshot_service = DurableContextSnapshotService(_snapshot_service)
_generation_background_service = GenerationBackgroundService(
    compiler=_compiler,
    renderer=_render_compiled_context,
    snapshot_writer=_durable_snapshot_service,
)
_hidden_guard_builder = HiddenGuardBuilder()


def _retrieval_trace_service():
    from modules.context.services.retrieval_trace_service import RetrievalTraceService

    return RetrievalTraceService()


def _evidence_health_service():
    from modules.context.services.evidence_health_service import EvidenceHealthService

    return EvidenceHealthService()


def _evidence_service():
    from modules.context.novel_evidence import NovelEvidenceService

    return NovelEvidenceService()


def render_context_markdown(context: StructureContextBundle) -> str:
    """将结构化上下文渲染为 Markdown

    同步函数，将 StructureContextBundle 渲染为分层 Markdown，
    适合直接放入 LLM Prompt。

    Args:
        context: Context Compiler 输出的结构化上下文包

    Returns:
        str: 渲染后的 Markdown 文本
    """
    return _render_markdown(context)


def render_compiled_context(context: CompiledContext) -> str:
    """将已编译的上下文 IR 渲染为 Markdown。"""
    return _render_compiled_context(context)


async def compile_structure_context(
    db: AsyncSession,
    novel_id: str,
    task: str,
    scope: str,
    chapter_index: int | None = None,
    visible_until_chapter: int | None = None,
    visible_until_scene_id: str | None = None,
    visible_until_offset: int | None = None,
    arc_id: str | None = None,
    map_id: str | None = None,
    focus_entity_id: str | None = None,
    entity_ids: list[str] | None = None,
    character_ids: list[str] | None = None,
    location_ids: list[str] | None = None,
    reveal_mode: str = "author_safe",
    enable_geo_filter: bool = False,
    viewpoint_character_id: str | None = None,
    context_mode: str = "canonical",
    content_mode: str = "canonical",
    include_pending_objects: bool = False,
    excluded_asset_ids: dict[str, list[str]] | None = None,
    user_note: str | None = None,
    retrieval_purpose: str = "generic_context",
    consumer_action: str | None = None,
    thread_ids: list[str] | None = None,
    include_world_synopsis: bool = False,
    selected_world_bible_draft_ids: list[str] | None = None,
    world_synopsis_revision_id: str | None = None,
) -> StructureContextBundle:
    """编译结构化创作上下文

    Context Compiler 的核心入口。
    根据 scope 从各模块按需加载数据，组装为结构化的上下文包。

    Args:
        db: 数据库 session
        novel_id: 项目 ID (UUID hex string)
        task: 创作任务描述，如「生成章节卡」、「生成剧情线」
        scope: 编译范围
            - project: 只加载项目信息
            - world: 项目 + 世界对象 + 关系
            - world_character: 项目 + 世界对象 + 人物 + 人物知识
            - arc: 加载篇章所有相关上下文
            - chapter: 加载单章所有相关上下文
            - full: 加载所有上下文（有限预算）
        chapter_index: 当前章节索引（scope=chapter 时推荐提供）
        visible_until_chapter: RAG 读者进度上界；默认由 loader 使用当前章
        arc_id: 当前篇章 ID（scope=arc 时推荐提供）
        entity_ids: 指定关注的世界对象 ID 列表
        character_ids: 指定关注的人物 ID 列表
        location_ids: 指定关注的地点 ID 列表
        reveal_mode: 揭示模式
            - author_safe: 隐藏 hidden_truth（默认）
            - author_full: 显示所有信息，标注作者视角
            - reader: 只显示读者已知信息
            - character: 按指定角色的知识边界过滤
        enable_geo_filter: 是否启用地缘可达性过滤（默认关闭）
        viewpoint_character_id: 视角人物 ID（reveal_mode="character" 时必填）

    Returns:
        StructureContextBundle — 结构化创作上下文包
    """
    if retrieval_purpose == "generic_context":
        if reveal_mode == "character":
            retrieval_purpose = "character_context"
        elif reveal_mode == "reader":
            retrieval_purpose = "reader_context"
    options = CompileOptions(
        novel_id=novel_id,
        task=task,
        scope=scope,
        consumer_action=consumer_action,
        retrieval_purpose=retrieval_purpose,
        chapter_index=chapter_index,
        visible_until_chapter=visible_until_chapter,
        visible_until_scene_id=visible_until_scene_id,
        visible_until_offset=visible_until_offset,
        arc_id=arc_id,
        map_id=map_id,
        focus_entity_id=focus_entity_id,
        entity_ids=entity_ids,
        character_ids=character_ids,
        thread_ids=thread_ids,
        location_ids=location_ids,
        reveal_mode=reveal_mode,
        enable_geo_filter=enable_geo_filter,
        viewpoint_character_id=viewpoint_character_id,
        context_mode=context_mode,
        content_mode=content_mode,
        include_pending_objects=include_pending_objects,
        excluded_asset_ids=excluded_asset_ids or {},
        user_note=user_note,
        include_world_synopsis=include_world_synopsis,
        selected_world_bible_draft_ids=selected_world_bible_draft_ids or [],
        world_synopsis_revision_id=world_synopsis_revision_id,
    )
    return await _compiler.compile(db, options)


async def retrieve_planned_context_evidence(
    db: AsyncSession,
    *,
    novel_id: str,
    task: str,
    retrieval_purpose: str,
    consumer_action: str,
    content_mode: str = "canonical",
    chapter_index: int | None = None,
    scene_id: str | None = None,
    entity_ids: list[str] | None = None,
    character_ids: list[str] | None = None,
    thread_ids: list[str] | None = None,
    top_k: int = 5,
) -> StructureContextBundle:
    """Run only the context-owned planner/RAG/rehydrate path for a consumer."""
    from modules.context.services.planned_retrieval_service import (
        PlannedContextRetrievalService,
    )

    options = CompileOptions(
        novel_id=novel_id,
        task=task,
        scope="full",
        consumer_action=consumer_action,
        retrieval_purpose=retrieval_purpose,
        chapter_index=chapter_index,
        scene_id=scene_id,
        entity_ids=entity_ids,
        character_ids=character_ids,
        thread_ids=thread_ids,
        content_mode=content_mode,
        top_k=max(1, min(top_k, 50)),
    )
    return await PlannedContextRetrievalService().retrieve(db, options)


async def prepare_import_context_activation(
    db: AsyncSession,
    *,
    novel_id: str,
    scene_id: str,
    context_mode: str = "working",
    budget_tokens: int = 4000,
    prior_neighbor_limit: int = 2,
    visible_until_chapter: int | None = None,
    visible_until_offset: int | None = None,
) -> ImportContextActivationContract:
    """Build the only cross-module context input consumed by Phase 2a."""
    from modules.context.services.import_activation import ImportContextActivationService

    return await ImportContextActivationService().prepare(
        db,
        novel_id=novel_id,
        scene_id=scene_id,
        context_mode=context_mode,
        budget_tokens=budget_tokens,
        prior_neighbor_limit=prior_neighbor_limit,
        visible_until_chapter=visible_until_chapter,
        visible_until_offset=visible_until_offset,
    )


async def get_import_scene_source_refs(
    db: AsyncSession,
    *,
    novel_id: str,
    scene_id: str,
    content_mode: str = "working",
    visible_until_chapter: int | None = None,
    visible_until_offset: int | None = None,
) -> list[dict]:
    """Return validated source refs for deep-import snapshot provenance."""
    from modules.context.services.import_activation import ImportContextActivationService

    return await ImportContextActivationService().source_refs(
        db,
        novel_id=novel_id,
        scene_id=scene_id,
        content_mode=content_mode,
        visible_until_chapter=visible_until_chapter,
        visible_until_offset=visible_until_offset,
    )


async def compile_with_tiers(
    db: AsyncSession,
    novel_id: str,
    task: str,
    scope: str,
    budget_tokens: int = 4000,
    scene_id: str | None = None,
    **kwargs,
) -> CompiledContext:
    options = CompileOptions(
        novel_id=novel_id,
        task=task,
        scope=scope,
        scene_id=scene_id,
        budget_tokens=budget_tokens,
        **kwargs,
    )
    return await _compiler.compile_with_tiers(db, options, budget_tokens=budget_tokens)


async def render_compiled_context_markdown(
    db: AsyncSession,
    novel_id: str,
    task: str,
    scope: str,
    budget_tokens: int = 4000,
    scene_id: str | None = None,
    **kwargs,
) -> str:
    ctx = await compile_with_tiers(
        db,
        novel_id,
        task,
        scope,
        budget_tokens=budget_tokens,
        scene_id=scene_id,
        **kwargs,
    )
    return _render_compiled_context(ctx)


async def compile_generation_background(
    db: AsyncSession,
    *,
    novel_id: str,
    task: str,
    include_world_synopsis: bool = False,
    selected_world_bible_draft_ids: list[str] | None = None,
    activation_profile_id: str | None = None,
    activation_profile_version: int | None = None,
    operation: str = "world.generation.core_entity",
    prompt_name: str = "world.generation.core_entity.structured",
    model: str = "project-default",
    focus_text: str = "",
    reference_chapter_index: int | None = None,
    scene_id: str | None = None,
    thread_ids: list[str] | None = None,
    character_ids: list[str] | None = None,
    entity_ids: list[str] | None = None,
    source_snapshot: dict | None = None,
) -> dict:
    """Compile the actual author-only background consumed by generation center."""
    return await _generation_background_service.compile(
        db,
        GenerationBackgroundRequest(
            novel_id=novel_id,
            task=task,
            include_world_synopsis=include_world_synopsis,
            selected_world_bible_draft_ids=tuple(selected_world_bible_draft_ids or ()),
            activation_profile_id=activation_profile_id,
            activation_profile_version=activation_profile_version,
            operation=operation,
            prompt_name=prompt_name,
            model=model,
            focus_text=focus_text,
            reference_chapter_index=reference_chapter_index,
            scene_id=scene_id,
            thread_ids=tuple(thread_ids) if thread_ids is not None else None,
            character_ids=(
                tuple(character_ids) if character_ids is not None else None
            ),
            entity_ids=tuple(entity_ids) if entity_ids is not None else None,
            source_snapshot=dict(source_snapshot or {}),
        ),
    )


async def preview_activation(
    db: AsyncSession,
    *,
    novel_id: str,
    entity_ids: list[str] | None = None,
    map_id: str | None = None,
    scene_id: str | None = None,
    focus_entity_id: str | None = None,
    top_k: int = 64,
    depth: int = 2,
    action: str | None = None,
    profile_id: str | None = None,
    profile_version: int | None = None,
    reveal_mode: str = "author_safe",
    task_text: str = "",
    current_scene_text: str = "",
    previous_scene_briefs: list[str] | None = None,
    explicit_focus: str = "",
) -> dict:
    """Preview worldbuilding activation through the world facade."""
    if profile_id or action:
        from modules.context.schemas import ContextActivationPreviewRequest
        from modules.context.services.activation_profile_service import (
            ActivationProfileService,
        )

        request = ContextActivationPreviewRequest(
            novel_id=novel_id,
            action=action,
            profile_id=profile_id,
            profile_version=profile_version,
            reveal_mode=reveal_mode,
            task_text=task_text,
            current_scene_text=current_scene_text,
            previous_scene_briefs=previous_scene_briefs or [],
            explicit_focus=explicit_focus,
            entity_ids=entity_ids or [],
            map_id=map_id,
            scene_id=scene_id,
            focus_entity_id=focus_entity_id,
            top_k=top_k,
            depth=depth,
        )
        return await ActivationProfileService().preview(db, request)
    from modules.world import facade as world_facade

    return await world_facade.preview_worldbuilding_activation(
        db,
        novel_id,
        entity_ids=entity_ids,
        map_id=map_id,
        scene_id=scene_id,
        focus_entity_id=focus_entity_id,
        top_k=top_k,
        depth=depth,
    )


async def list_activation_profiles(
    db: AsyncSession,
    novel_id: str,
    *,
    include_archived: bool = False,
):
    from modules.context.services.activation_profile_service import (
        ActivationProfileService,
    )

    return await ActivationProfileService().list_profiles(
        db,
        novel_id,
        include_archived=include_archived,
    )


async def create_activation_profile(db: AsyncSession, data):
    from modules.context.services.activation_profile_service import (
        ActivationProfileService,
    )

    return await ActivationProfileService().create_profile(db, data)


async def update_activation_profile(
    db: AsyncSession,
    novel_id: str,
    profile_id: str,
    data,
):
    from modules.context.services.activation_profile_service import (
        ActivationProfileService,
    )

    return await ActivationProfileService().update_profile(
        db,
        novel_id,
        profile_id,
        data,
    )


async def publish_activation_profile(
    db: AsyncSession,
    novel_id: str,
    profile_id: str,
    data,
):
    from modules.context.services.activation_profile_service import (
        ActivationProfileService,
    )

    return await ActivationProfileService().publish_profile(
        db,
        novel_id,
        profile_id,
        data,
    )


async def list_activation_profile_revisions(
    db: AsyncSession,
    novel_id: str,
    profile_id: str,
):
    from modules.context.services.activation_profile_service import (
        ActivationProfileService,
    )

    return await ActivationProfileService().list_revisions(
        db,
        novel_id,
        profile_id,
    )


async def restore_activation_profile_revision(
    db: AsyncSession,
    novel_id: str,
    profile_id: str,
    version_number: int,
    *,
    restored_by: str | None = None,
):
    from modules.context.services.activation_profile_service import (
        ActivationProfileService,
    )

    return await ActivationProfileService().restore_revision(
        db,
        novel_id,
        profile_id,
        version_number,
        restored_by=restored_by,
    )


async def resolve_activation_profile(
    db: AsyncSession,
    novel_id: str,
    action: str,
    *,
    profile_id: str | None = None,
    version_number: int | None = None,
) -> dict | None:
    """Resolve one immutable published revision for a runtime action."""
    from modules.context.services.activation_profile_service import (
        ActivationProfileService,
    )

    return await ActivationProfileService().resolve_published(
        db,
        novel_id,
        action,
        profile_id=profile_id,
        version_number=version_number,
    )


async def preview_activation_profile(
    db: AsyncSession,
    request,
    *,
    published_only: bool = False,
) -> dict:
    """Evaluate a draft for dry-run or a published revision for runtime."""
    from modules.context.services.activation_profile_service import (
        ActivationProfileService,
    )

    service = ActivationProfileService()
    if published_only:
        return await service.preview_published(db, request)
    return await service.preview(db, request)


async def confirm_context(
    db: AsyncSession,
    *,
    novel_id: str,
    action: str,
    task: str,
    scope: str,
    chapter_index: int | None = None,
    visible_until_chapter: int | None = None,
    visible_until_scene_id: str | None = None,
    visible_until_offset: int | None = None,
    scene_id: str | None = None,
    arc_id: str | None = None,
    entity_ids: list[str] | None = None,
    character_ids: list[str] | None = None,
    thread_ids: list[str] | None = None,
    location_ids: list[str] | None = None,
    reveal_mode: str = "author_safe",
    enable_geo_filter: bool = False,
    viewpoint_character_id: str | None = None,
    budget_tokens: int = 4000,
    context_mode: str = "canonical",
    content_mode: str = "canonical",
    include_pending_objects: bool = False,
    excluded_asset_ids: dict[str, list[str]] | None = None,
    user_note: str | None = None,
    retrieval_purpose: str = "generic_context",
    include_world_synopsis: bool = False,
    selected_world_bible_draft_ids: list[str] | None = None,
    activation_profile_id: str | None = None,
    activation_profile_version: int | None = None,
) -> ContextConfirmationContract:
    return await _confirmation_service.confirm_context(
        db,
        novel_id=novel_id,
        action=action,
        task=task,
        scope=scope,
        retrieval_purpose=retrieval_purpose,
        chapter_index=chapter_index,
        visible_until_chapter=visible_until_chapter,
        visible_until_scene_id=visible_until_scene_id,
        visible_until_offset=visible_until_offset,
        scene_id=scene_id,
        arc_id=arc_id,
        entity_ids=entity_ids,
        character_ids=character_ids,
        thread_ids=thread_ids,
        location_ids=location_ids,
        reveal_mode=reveal_mode,
        enable_geo_filter=enable_geo_filter,
        viewpoint_character_id=viewpoint_character_id,
        budget_tokens=budget_tokens,
        context_mode=context_mode,
        content_mode=content_mode,
        include_pending_objects=include_pending_objects,
        excluded_asset_ids=excluded_asset_ids,
        user_note=user_note,
        include_world_synopsis=include_world_synopsis,
        selected_world_bible_draft_ids=selected_world_bible_draft_ids,
        activation_profile_id=activation_profile_id,
        activation_profile_version=activation_profile_version,
    )


async def grep_novel_evidence(
    db: AsyncSession,
    *,
    novel_id: str,
    pattern: str,
    content_mode: str,
    visibility: VisibilityContextContract,
    chapter_from: int | None = None,
    chapter_to: int | None = None,
    case_sensitive: bool = False,
    skip: int = 0,
    limit: int = 20,
    group_by_chapter: bool = False,
    context_scene_id: str | None = None,
) -> dict:
    return await _evidence_service().grep(
        db,
        novel_id=novel_id,
        pattern=pattern,
        content_mode=content_mode,
        visibility=visibility,
        chapter_from=chapter_from,
        chapter_to=chapter_to,
        case_sensitive=case_sensitive,
        skip=skip,
        limit=limit,
        group_by_chapter=group_by_chapter,
        context_scene_id=context_scene_id,
    )


async def search_novel_evidence(
    db: AsyncSession,
    *,
    novel_id: str,
    query: str,
    content_mode: str,
    visibility: VisibilityContextContract,
    scopes: list[str],
    include_pending_objects: bool = False,
    chapter_from: int | None = None,
    chapter_to: int | None = None,
    top_k: int = 100,
    context_scene_id: str | None = None,
) -> dict:
    return await _evidence_service().search(
        db,
        novel_id=novel_id,
        query=query,
        content_mode=content_mode,
        visibility=visibility,
        scopes=scopes,
        include_pending_objects=include_pending_objects,
        chapter_from=chapter_from,
        chapter_to=chapter_to,
        top_k=top_k,
        context_scene_id=context_scene_id,
    )


async def read_novel_evidence(
    db: AsyncSession,
    *,
    novel_id: str,
    source_ref,
    visibility: VisibilityContextContract,
    before: int = 3,
    after: int = 3,
) -> dict:
    return await _evidence_service().read(
        db,
        novel_id=novel_id,
        source_ref=source_ref,
        visibility=visibility,
        before=before,
        after=after,
    )


async def inspect_novel_target(
    db: AsyncSession,
    *,
    novel_id: str,
    target_ref: dict,
    content_mode: str,
    visibility: VisibilityContextContract,
) -> dict:
    return await _evidence_service().inspect(
        db,
        novel_id=novel_id,
        target_ref=target_ref,
        content_mode=content_mode,
        visibility=visibility,
    )


async def trace_novel_evidence(
    db: AsyncSession,
    *,
    novel_id: str,
    target_ref: dict,
    claim_path: str,
    visibility: VisibilityContextContract,
    content_mode: str = "canonical",
) -> dict:
    return await _evidence_service().trace(
        db,
        novel_id=novel_id,
        target_ref=target_ref,
        claim_path=claim_path,
        content_mode=content_mode,
        visibility=visibility,
    )


async def record_evidence_link(
    db: AsyncSession,
    **kwargs,
) -> dict:
    """Validate the original-text reference before persisting provenance."""
    return await _evidence_service().record_link(db, **kwargs)


async def record_unresolved_evidence_link(
    db: AsyncSession,
    **kwargs,
) -> dict:
    return await _evidence_service().record_unresolved_link(db, **kwargs)


async def locate_scene_quote(
    db: AsyncSession,
    **kwargs,
):
    return await _evidence_service().locate_scene_quote(db, **kwargs)


async def require_confirmation(
    db: AsyncSession,
    *,
    novel_id: str,
    action: str,
    confirmation_id: str,
) -> ContextConfirmationContract:
    return await _confirmation_service.require_confirmation(
        db,
        novel_id=novel_id,
        action=action,
        confirmation_id=confirmation_id,
    )


async def require_fresh_confirmation(
    db: AsyncSession,
    *,
    novel_id: str,
    action: str,
    confirmation_id: str,
    for_update: bool = False,
) -> ContextConfirmationContract:
    """Require a usable confirmation, optionally locking it for finalization."""
    return await _confirmation_service.require_fresh_confirmation(
        db,
        novel_id=novel_id,
        action=action,
        confirmation_id=confirmation_id,
        for_update=for_update,
    )


async def prepare_confirmed_ai_action(
    db: AsyncSession,
    *,
    novel_id: str,
    action: str,
    confirmation_id: str,
    for_update: bool = False,
) -> ConfirmedAIActionContext:
    """Return validated context, optionally locking its confirmation row."""
    return await _confirmed_ai_action_service.prepare(
        db,
        novel_id=novel_id,
        action=action,
        confirmation_id=confirmation_id,
        for_update=for_update,
    )


async def build_hidden_guard_context(
    db: AsyncSession,
    *,
    confirmed_context: ConfirmedAIActionContext,
) -> list[HiddenGuardTerm]:
    """Build deterministic hidden guard terms for post-generation validation."""
    return await _hidden_guard_builder.build(db, confirmed_context)


async def compile_from_confirmation(
    db: AsyncSession,
    *,
    novel_id: str,
    action: str,
    confirmation_id: str,
) -> CompiledContext:
    return await _confirmation_service.compile_from_confirmation(
        db,
        novel_id=novel_id,
        action=action,
        confirmation_id=confirmation_id,
    )


async def attach_result_ref(
    db: AsyncSession,
    *,
    novel_id: str,
    confirmation_id: str,
    result_type: str,
    result_id: str,
    status: str = "running",
) -> ContextConfirmationContract:
    return await _confirmation_service.attach_result_ref(
        db,
        novel_id=novel_id,
        confirmation_id=confirmation_id,
        result_type=result_type,
        result_id=result_id,
        status=status,
    )


async def bind_confirmed_action_result(
    db: AsyncSession,
    *,
    novel_id: str,
    confirmation_id: str,
    result_type: str,
    result_id: str,
    status: str = "running",
) -> ContextConfirmationContract:
    """Attach an AI action result reference to a context confirmation."""
    return await _confirmed_ai_action_service.bind_result(
        db,
        novel_id=novel_id,
        confirmation_id=confirmation_id,
        result_type=result_type,
        result_id=result_id,
        status=status,
    )


async def attach_result_refs(
    db: AsyncSession,
    *,
    novel_id: str,
    confirmation_id: str,
    result_refs: list[dict[str, str]],
    status: str = "running",
) -> ContextConfirmationContract:
    return await _confirmation_service.attach_result_refs(
        db,
        novel_id=novel_id,
        confirmation_id=confirmation_id,
        result_refs=result_refs,
        status=status,
    )


async def mark_asset_context_changed(
    db: AsyncSession,
    *,
    novel_id: str,
    asset_type: str,
    asset_id: str,
    reason: str,
) -> int:
    return await _confirmation_service.mark_asset_context_changed(
        db,
        novel_id=novel_id,
        asset_type=asset_type,
        asset_id=asset_id,
        reason=reason,
    )


async def create_context_snapshot(
    db: AsyncSession,
    *,
    novel_id: str,
    task_id: str | None = None,
    workflow_id: str | None = None,
    phase: str,
    operation: str,
    scene_id: str | None = None,
    scene_index: int | None = None,
    chapter_index: int | None = None,
    context_mode: str = "working",
    include_pending_objects: bool = True,
    attempt: int = 1,
    prompt_name: str,
    model: str,
    compile_options: dict,
    included_asset_ids: dict,
    excluded_asset_ids: dict | None = None,
    context_summary: dict,
    section_metadata: dict,
    token_metadata: dict,
    rendered_context: str | None = None,
    retain_rendered_context: bool = False,
) -> ContextSnapshotContract:
    return await open_context_snapshot(
        db,
        ContextSnapshotRequest(
            novel_id=novel_id,
            task_id=task_id,
            workflow_id=workflow_id,
            phase=phase,
            operation=operation,
            scene_id=scene_id,
            scene_index=scene_index,
            chapter_index=chapter_index,
            context_mode=context_mode,
            include_pending_objects=include_pending_objects,
            attempt=attempt,
            prompt_name=prompt_name,
            model=model,
            compile_options=compile_options,
            included_asset_ids=included_asset_ids,
            excluded_asset_ids=excluded_asset_ids,
            context_summary=context_summary,
            section_metadata=section_metadata,
            token_metadata=token_metadata,
            rendered_context=rendered_context,
            retain_rendered_context=retain_rendered_context,
        ),
    )


async def open_context_snapshot(
    db: AsyncSession,
    request: ContextSnapshotRequest,
) -> ContextSnapshotContract:
    return await _snapshot_service.open_context_snapshot(
        db,
        request,
    )


async def open_generation_context_snapshot(
    db: AsyncSession,
    request: ContextSnapshotRequest,
) -> ContextSnapshotContract:
    """Durably open a generation snapshot outside the caller transaction."""
    return await _durable_snapshot_service.open_context_snapshot(
        db,
        request,
    )


async def mark_context_snapshot_succeeded(
    db: AsyncSession,
    *,
    novel_id: str,
    snapshot_id: str,
    result_refs: list[dict],
) -> ContextSnapshotContract:
    return await succeed_context_snapshot(
        db,
        novel_id=novel_id,
        snapshot_id=snapshot_id,
        result_refs=result_refs,
    )


async def succeed_context_snapshot(
    db: AsyncSession,
    *,
    novel_id: str,
    snapshot_id: str,
    result_refs: list[dict],
) -> ContextSnapshotContract:
    return await _snapshot_service.succeed_context_snapshot(
        db,
        novel_id=novel_id,
        snapshot_id=snapshot_id,
        result_refs=result_refs,
    )


async def succeed_generation_context_snapshot(
    db: AsyncSession,
    *,
    novel_id: str,
    snapshot_id: str,
    result_refs: list[dict],
) -> ContextSnapshotContract:
    """Durably close a generation snapshot as succeeded."""
    return await _durable_snapshot_service.succeed_context_snapshot(
        db,
        novel_id=novel_id,
        snapshot_id=snapshot_id,
        result_refs=result_refs,
    )


async def mark_context_snapshot_failed(
    db: AsyncSession,
    *,
    novel_id: str,
    snapshot_id: str,
    error_kind: str,
    error_message: str,
) -> ContextSnapshotContract:
    return await fail_context_snapshot(
        db,
        novel_id=novel_id,
        snapshot_id=snapshot_id,
        error_kind=error_kind,
        error_message=error_message,
    )


async def fail_context_snapshot(
    db: AsyncSession,
    *,
    novel_id: str,
    snapshot_id: str,
    error_kind: str,
    error_message: str,
) -> ContextSnapshotContract:
    return await _snapshot_service.fail_context_snapshot(
        db,
        novel_id=novel_id,
        snapshot_id=snapshot_id,
        error_kind=error_kind,
        error_message=error_message,
    )


async def fail_generation_context_snapshot(
    db: AsyncSession,
    *,
    novel_id: str,
    snapshot_id: str,
    error_kind: str,
    error_message: str,
) -> ContextSnapshotContract:
    """Durably close a generation snapshot as failed."""
    return await _durable_snapshot_service.fail_context_snapshot(
        db,
        novel_id=novel_id,
        snapshot_id=snapshot_id,
        error_kind=error_kind,
        error_message=error_message,
    )


async def get_context_snapshot(
    db: AsyncSession,
    *,
    novel_id: str,
    snapshot_id: str,
) -> ContextSnapshotContract:
    return await _snapshot_service.get_context_snapshot(
        db,
        novel_id=novel_id,
        snapshot_id=snapshot_id,
    )


async def list_context_snapshots(
    db: AsyncSession,
    *,
    novel_id: str,
    workflow_id: str | None = None,
    task_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[ContextSnapshotContract]:
    return await _snapshot_service.list_context_snapshots(
        db,
        novel_id=novel_id,
        workflow_id=workflow_id,
        task_id=task_id,
        limit=limit,
        offset=offset,
    )


async def build_snapshot_health_summary(
    db: AsyncSession,
    *,
    novel_id: str,
    workflow_id: str | None = None,
    running_timeout_minutes: int = 120,
) -> dict:
    return await _snapshot_service.build_snapshot_health_summary(
        db,
        novel_id=novel_id,
        workflow_id=workflow_id,
        running_timeout_minutes=running_timeout_minutes,
    )


async def list_retrieval_traces(
    db: AsyncSession,
    *,
    novel_id: str,
    content_mode: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[ContextRetrievalTraceContract]:
    return await _retrieval_trace_service().list(
        db,
        novel_id=novel_id,
        content_mode=content_mode,
        limit=limit,
        offset=offset,
    )


async def get_evidence_health(
    db: AsyncSession,
    *,
    novel_id: str,
    content_mode: str = "canonical",
    window_hours: int = 24,
) -> EvidenceHealthContract:
    return await _evidence_health_service().get_health(
        db,
        novel_id=novel_id,
        content_mode=content_mode,
        window_hours=max(1, min(window_hours, 24 * 30)),
    )


async def mark_stale_running_snapshots(
    db: AsyncSession,
    *,
    novel_id: str,
    workflow_id: str | None = None,
    running_timeout_minutes: int = 120,
    dry_run: bool = True,
) -> int:
    return await _snapshot_service.mark_stale_running_snapshots(
        db,
        novel_id=novel_id,
        workflow_id=workflow_id,
        running_timeout_minutes=running_timeout_minutes,
        dry_run=dry_run,
    )


async def prune_rendered_context(
    db: AsyncSession,
    *,
    novel_id: str | None = None,
    workflow_id: str | None = None,
    retain_latest_full_context_per_project: int | None = None,
    dry_run: bool = False,
    older_than_days: int | None = None,
    keep_latest_per_project: int | None = None,
) -> int:
    return await _snapshot_service.prune_rendered_context(
        db,
        novel_id=novel_id,
        workflow_id=workflow_id,
        retain_latest_full_context_per_project=retain_latest_full_context_per_project,
        dry_run=dry_run,
        older_than_days=older_than_days,
        keep_latest_per_project=keep_latest_per_project,
    )


async def run_snapshot_maintenance(
    db: AsyncSession,
    *,
    novel_id: str,
    workflow_id: str | None = None,
    running_timeout_minutes: int = 120,
    prune_rendered_context: bool = True,
    retain_latest_full_context_per_project: int = 200,
    prune_retrieval_traces: bool = True,
    retrieval_trace_retention_days: int = 30,
    retain_latest_retrieval_traces: int = 10_000,
    dry_run: bool = True,
) -> dict:
    return await _snapshot_service.run_snapshot_maintenance(
        db,
        novel_id=novel_id,
        workflow_id=workflow_id,
        running_timeout_minutes=running_timeout_minutes,
        prune_rendered_context=prune_rendered_context,
        retain_latest_full_context_per_project=retain_latest_full_context_per_project,
        prune_retrieval_traces=prune_retrieval_traces,
        retrieval_trace_retention_days=retrieval_trace_retention_days,
        retain_latest_retrieval_traces=retain_latest_retrieval_traces,
        dry_run=dry_run,
    )
