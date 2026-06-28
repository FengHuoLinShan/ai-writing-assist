"""
Context API 路由

提供上下文编译和渲染的 REST API。
API 层不写复杂业务逻辑，仅做参数校验和路由分发。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi import status as http_status

from core.dependencies import DbSession
from modules.context.facade import compile_with_tiers
from modules.context.facade import confirm_context as _confirm_context
from modules.context.markdown_renderer import render_compiled_context
from modules.context.schemas import (
    ContextCompileRequest,
    ContextConfirmationResponse,
    ContextConfirmRequest,
    ContextRenderRequest,
    ContextRenderResponse,
    ContextSectionItem,
    ContextTierCompileResponse,
)
from modules.context.services.compiled_context import CompiledContext

_VALID_SCOPES: frozenset[str] = frozenset(
    {"project", "world", "world_character", "arc", "chapter", "full"}
)

router = APIRouter(prefix="/api/context", tags=["context"])


def _build_tier_compile_response(
    request: ContextCompileRequest | ContextRenderRequest,
    ctx: CompiledContext,
) -> ContextTierCompileResponse:
    """从 CompiledContext IR 构建 ContextTierCompileResponse。"""
    warnings: list[str] = []
    for s in ctx.sections:
        if s.key == "compiler_warnings":
            warnings.append(s.content)

    return ContextTierCompileResponse(
        novel_id=request.novel_id,
        task=request.task,
        scope=request.scope,
        reveal_mode=request.reveal_mode,
        scene_id=request.scene_id,
        viewpoint_character_id=request.viewpoint_character_id,
        total_tokens=ctx.total_tokens,
        budget_tokens=ctx.budget_tokens,
        sections=[
            ContextSectionItem(
                key=s.key,
                tier=int(s.tier),
                content=s.content,
                token_count=s.token_count,
                truncated=s.key in ctx.truncated_keys,
            )
            for s in ctx.sections
        ],
        evicted=ctx.evicted_keys,
        truncated=ctx.truncated_keys,
        warnings=warnings,
    )


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


@router.post("/compile", response_model=ContextTierCompileResponse)
async def compile_context(
    db: DbSession,
    request: ContextCompileRequest,
) -> ContextTierCompileResponse:
    """编译结构化创作上下文

    根据 scope 从各模块按需加载数据，返回 Tier 化的编译 IR。
    """
    _validate_scope(request)
    _validate_character_reveal_mode(request)

    ctx = await compile_with_tiers(
        db=db,
        novel_id=request.novel_id,
        task=request.task,
        scope=request.scope,
        budget_tokens=request.budget_tokens,
        scene_id=request.scene_id,
        chapter_index=request.chapter_index,
        arc_id=request.arc_id,
        entity_ids=request.entity_ids,
        character_ids=request.character_ids,
        location_ids=request.location_ids,
        reveal_mode=request.reveal_mode,
        enable_geo_filter=request.enable_geo_filter,
        viewpoint_character_id=request.viewpoint_character_id,
        context_mode=request.context_mode,
        include_pending_objects=request.include_pending_objects,
        excluded_asset_ids=request.excluded_asset_ids,
        user_note=request.user_note,
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
    _validate_scope(request)
    _validate_character_reveal_mode(request)

    ctx = await compile_with_tiers(
        db=db,
        novel_id=request.novel_id,
        task=request.task,
        scope=request.scope,
        budget_tokens=request.budget_tokens,
        scene_id=request.scene_id,
        chapter_index=request.chapter_index,
        arc_id=request.arc_id,
        entity_ids=request.entity_ids,
        character_ids=request.character_ids,
        location_ids=request.location_ids,
        reveal_mode=request.reveal_mode,
        enable_geo_filter=request.enable_geo_filter,
        viewpoint_character_id=request.viewpoint_character_id,
        context_mode=request.context_mode,
        include_pending_objects=request.include_pending_objects,
        excluded_asset_ids=request.excluded_asset_ids,
        user_note=request.user_note,
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
    _validate_scope(request)
    _validate_character_reveal_mode(request)

    confirmation = await _confirm_context(
        db,
        novel_id=request.novel_id,
        action=request.action,
        task=request.task,
        scope=request.scope,
        chapter_index=request.chapter_index,
        scene_id=request.scene_id,
        arc_id=request.arc_id,
        entity_ids=request.entity_ids,
        character_ids=request.character_ids,
        location_ids=request.location_ids,
        reveal_mode=request.reveal_mode,
        enable_geo_filter=request.enable_geo_filter,
        viewpoint_character_id=request.viewpoint_character_id,
        budget_tokens=request.budget_tokens,
        context_mode=request.context_mode,
        include_pending_objects=request.include_pending_objects,
        excluded_asset_ids=request.excluded_asset_ids,
        user_note=request.user_note,
    )
    return ContextConfirmationResponse(**confirmation.__dict__)
