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
    ContextSnapshotContract,
    StructureContextBundle,
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
)
from modules.context.services.compiled_context import CompiledContext
from modules.context.services.confirmed_ai_action import ConfirmedAIActionService
from modules.context.services.hidden_guard import HiddenGuardBuilder, HiddenGuardTerm

_compiler = ContextCompiler()
_confirmation_service = ContextConfirmationService()
_confirmed_ai_action_service = ConfirmedAIActionService(_confirmation_service)
_snapshot_service = ContextSnapshotService()
_hidden_guard_builder = HiddenGuardBuilder()


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
    arc_id: str | None = None,
    entity_ids: list[str] | None = None,
    character_ids: list[str] | None = None,
    location_ids: list[str] | None = None,
    reveal_mode: str = "author_safe",
    enable_geo_filter: bool = False,
    viewpoint_character_id: str | None = None,
    context_mode: str = "canonical",
    include_pending_objects: bool = False,
    excluded_asset_ids: dict[str, list[str]] | None = None,
    user_note: str | None = None,
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
    options = CompileOptions(
        novel_id=novel_id,
        task=task,
        scope=scope,
        chapter_index=chapter_index,
        arc_id=arc_id,
        entity_ids=entity_ids,
        character_ids=character_ids,
        location_ids=location_ids,
        reveal_mode=reveal_mode,
        enable_geo_filter=enable_geo_filter,
        viewpoint_character_id=viewpoint_character_id,
        context_mode=context_mode,
        include_pending_objects=include_pending_objects,
        excluded_asset_ids=excluded_asset_ids or {},
        user_note=user_note,
    )
    return await _compiler.compile(db, options)


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
) -> dict:
    """Preview worldbuilding activation through the world facade."""
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


async def confirm_context(
    db: AsyncSession,
    *,
    novel_id: str,
    action: str,
    task: str,
    scope: str,
    chapter_index: int | None = None,
    scene_id: str | None = None,
    arc_id: str | None = None,
    entity_ids: list[str] | None = None,
    character_ids: list[str] | None = None,
    location_ids: list[str] | None = None,
    reveal_mode: str = "author_safe",
    enable_geo_filter: bool = False,
    viewpoint_character_id: str | None = None,
    budget_tokens: int = 4000,
    context_mode: str = "canonical",
    include_pending_objects: bool = False,
    excluded_asset_ids: dict[str, list[str]] | None = None,
    user_note: str | None = None,
) -> ContextConfirmationContract:
    return await _confirmation_service.confirm_context(
        db,
        novel_id=novel_id,
        action=action,
        task=task,
        scope=scope,
        chapter_index=chapter_index,
        scene_id=scene_id,
        arc_id=arc_id,
        entity_ids=entity_ids,
        character_ids=character_ids,
        location_ids=location_ids,
        reveal_mode=reveal_mode,
        enable_geo_filter=enable_geo_filter,
        viewpoint_character_id=viewpoint_character_id,
        budget_tokens=budget_tokens,
        context_mode=context_mode,
        include_pending_objects=include_pending_objects,
        excluded_asset_ids=excluded_asset_ids,
        user_note=user_note,
    )


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
) -> ContextConfirmationContract:
    return await _confirmation_service.require_fresh_confirmation(
        db,
        novel_id=novel_id,
        action=action,
        confirmation_id=confirmation_id,
    )


async def prepare_confirmed_ai_action(
    db: AsyncSession,
    *,
    novel_id: str,
    action: str,
    confirmation_id: str,
) -> ConfirmedAIActionContext:
    """Return validated, rendered context for an AI action."""
    return await _confirmed_ai_action_service.prepare(
        db,
        novel_id=novel_id,
        action=action,
        confirmation_id=confirmation_id,
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
    confirmation_id: str,
    result_type: str,
    result_id: str,
    status: str = "running",
) -> ContextConfirmationContract:
    return await _confirmation_service.attach_result_ref(
        db,
        confirmation_id=confirmation_id,
        result_type=result_type,
        result_id=result_id,
        status=status,
    )


async def bind_confirmed_action_result(
    db: AsyncSession,
    *,
    confirmation_id: str,
    result_type: str,
    result_id: str,
    status: str = "running",
) -> ContextConfirmationContract:
    """Attach an AI action result reference to a context confirmation."""
    return await _confirmed_ai_action_service.bind_result(
        db,
        confirmation_id=confirmation_id,
        result_type=result_type,
        result_id=result_id,
        status=status,
    )


async def attach_result_refs(
    db: AsyncSession,
    *,
    confirmation_id: str,
    result_refs: list[dict[str, str]],
    status: str = "running",
) -> ContextConfirmationContract:
    return await _confirmation_service.attach_result_refs(
        db,
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
    return await _snapshot_service.create_context_snapshot(
        db,
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
    )


async def mark_context_snapshot_succeeded(
    db: AsyncSession,
    *,
    snapshot_id: str,
    result_refs: list[dict],
) -> ContextSnapshotContract:
    return await _snapshot_service.mark_context_snapshot_succeeded(
        db,
        snapshot_id=snapshot_id,
        result_refs=result_refs,
    )


async def mark_context_snapshot_failed(
    db: AsyncSession,
    *,
    snapshot_id: str,
    error_kind: str,
    error_message: str,
) -> ContextSnapshotContract:
    return await _snapshot_service.mark_context_snapshot_failed(
        db,
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
    dry_run: bool = True,
) -> dict:
    return await _snapshot_service.run_snapshot_maintenance(
        db,
        novel_id=novel_id,
        workflow_id=workflow_id,
        running_timeout_minutes=running_timeout_minutes,
        prune_rendered_context=prune_rendered_context,
        retain_latest_full_context_per_project=retain_latest_full_context_per_project,
        dry_run=dry_run,
    )
