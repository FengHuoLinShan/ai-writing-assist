"""
Context API 路由

提供上下文编译和渲染的 REST API。
API 层不写复杂业务逻辑，仅做参数校验和路由分发。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from core.dependencies import DbSession
from modules.context.facade import compile_structure_context, render_context_markdown
from modules.context.contracts import CONTEXT_BUDGET
from modules.context.schemas import (
    BudgetUsedItem,
    ContextCompileRequest,
    ContextCompileResponse,
    ContextRenderRequest,
    ContextRenderResponse,
)

router = APIRouter(prefix="/api/context", tags=["context"])


@router.post("/compile", response_model=ContextCompileResponse)
async def compile_context(
    db: DbSession,
    request: ContextCompileRequest,
) -> ContextCompileResponse:
    """编译结构化创作上下文

    根据 scope 从各模块按需加载数据，返回结构化的上下文包（内存对象）。
    """
    if request.scope not in ("project", "world", "world_character", "arc", "chapter", "full"):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的 scope: {request.scope}。"
                   f"支持: project / world / world_character / arc / chapter / full",
        )

    bundle = await compile_structure_context(
        db=db,
        novel_id=request.novel_id,
        task=request.task,
        scope=request.scope,
        chapter_index=request.chapter_index,
        arc_id=request.arc_id,
        entity_ids=request.entity_ids,
        character_ids=request.character_ids,
        location_ids=request.location_ids,
        reveal_mode=request.reveal_mode,
    )

    # 统计非空段落
    sections_present = []
    if bundle.project:
        sections_present.append("project")
    if bundle.world_entities:
        sections_present.append("world_entities")
    if bundle.characters:
        sections_present.append("characters")
    if bundle.geo_locations:
        sections_present.append("geo_locations")
    if bundle.memory_records:
        sections_present.append("memory_records")
    if bundle.timeline_events:
        sections_present.append("timeline_events")
    if bundle.plot_threads:
        sections_present.append("plot_threads")
    if bundle.outline_arc:
        sections_present.append("outline_arc")
    if bundle.chapter_card:
        sections_present.append("chapter_card")
    if bundle.rag_chunks:
        sections_present.append("rag_chunks")

    budgets = [
        BudgetUsedItem(
            category=k,
            budget=CONTEXT_BUDGET.get(k, 10),
            used=v,
        )
        for k, v in bundle.budget_used.items()
    ]

    return ContextCompileResponse(
        novel_id=bundle.novel_id,
        task=bundle.task,
        scope=bundle.scope,
        reveal_mode=bundle.reveal_mode,
        budgets=budgets,
        warnings=bundle.warnings,
        section_count=len(sections_present),
        sections_present=sections_present,
    )


@router.post("/render", response_model=ContextRenderResponse)
async def render_context(
    db: DbSession,
    request: ContextRenderRequest,
) -> ContextRenderResponse:
    """编译 + 渲染上下文为 Markdown

    一次调用完成编译和 Markdown 渲染，返回可直接放入 LLM Prompt 的文本。
    """
    if request.scope not in ("project", "world", "world_character", "arc", "chapter", "full"):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的 scope: {request.scope}。"
                   f"支持: project / world / world_character / arc / chapter / full",
        )

    bundle = await compile_structure_context(
        db=db,
        novel_id=request.novel_id,
        task=request.task,
        scope=request.scope,
        chapter_index=request.chapter_index,
        arc_id=request.arc_id,
        entity_ids=request.entity_ids,
        character_ids=request.character_ids,
        location_ids=request.location_ids,
        reveal_mode=request.reveal_mode,
    )

    markdown = render_context_markdown(bundle)

    # 统计
    sections_present = [k for k, v in {
        "project": bundle.project,
        "world_entities": bundle.world_entities,
        "characters": bundle.characters,
        "geo_locations": bundle.geo_locations,
        "memory_records": bundle.memory_records,
        "timeline_events": bundle.timeline_events,
        "plot_threads": bundle.plot_threads,
        "outline_arc": bundle.outline_arc,
        "chapter_card": bundle.chapter_card,
        "rag_chunks": bundle.rag_chunks,
    }.items() if v]

    budgets = [
        BudgetUsedItem(
            category=k,
            budget=CONTEXT_BUDGET.get(k, 10),
            used=v,
        )
        for k, v in bundle.budget_used.items()
    ]

    compile_info = ContextCompileResponse(
        novel_id=bundle.novel_id,
        task=bundle.task,
        scope=bundle.scope,
        reveal_mode=bundle.reveal_mode,
        budgets=budgets,
        warnings=bundle.warnings,
        section_count=len(sections_present),
        sections_present=sections_present,
    )

    return ContextRenderResponse(
        markdown=markdown,
        compile_info=compile_info,
    )
