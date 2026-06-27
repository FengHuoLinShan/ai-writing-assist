"""
Context API 路由

提供上下文编译和渲染的 REST API。
API 层不写复杂业务逻辑，仅做参数校验和路由分发。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from core.dependencies import DbSession
from modules.context.facade import compile_with_tiers
from modules.context.markdown_renderer import render_compiled_context
from modules.context.schemas import (
    ContextCompileRequest,
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
    request: ContextCompileRequest | ContextRenderRequest,
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
    request: ContextCompileRequest | ContextRenderRequest,
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
    )

    markdown = render_compiled_context(ctx)
    compile_info = _build_tier_compile_response(request, ctx)

    return ContextRenderResponse(
        markdown=markdown,
        compile_info=compile_info,
    )
