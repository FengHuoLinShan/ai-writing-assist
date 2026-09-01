"""Context review projection helpers."""

from __future__ import annotations

from modules.evidence.compilation.schemas import (
    ContextCompileRequest,
    ContextRenderRequest,
    ContextSectionItem,
    ContextTierCompileResponse,
)
from modules.evidence.compilation.services.compiled_context import (
    CompiledContext,
    compiled_context_fingerprint,
)

_ASSET_KEYS = {
    "world_entity": "world_entities",
    "entity": "world_entities",
    "core_entity": "world_entities",
    "character": "characters",
    "scene": "scenes",
    "outline_scene": "scenes",
    "outline_arc": "outline_arcs",
    "plot_thread": "plot_threads",
    "foreshadowing_plan": "foreshadowing_plans",
    "reveal_plan": "reveal_plans",
    "writing_draft": "writing_drafts",
}


def selected_asset_ids_from_compiled(
    ctx: CompiledContext,
    *,
    novel_id: str,
) -> dict[str, list[str]]:
    selected: dict[str, list[str]] = {"project": [str(novel_id)]}
    for section in ctx.sections:
        sources = [item.source for item in section.items if item.source]
        if not sources:
            sources = list(section.sources)
        for source in sources:
            asset_type = _ASSET_KEYS.get(
                str(source.get("type") or ""),
                str(source.get("type") or ""),
            )
            asset_id = str(source.get("id") or "").strip()
            if asset_type and asset_id and asset_type not in {"task", "compiler"}:
                selected.setdefault(asset_type, []).append(asset_id)
    selected["context_sections"] = [section.key for section in ctx.sections]
    return {key: list(dict.fromkeys(values)) for key, values in selected.items()}


def selection_state_from_compiled(ctx: CompiledContext, options) -> dict:
    counts = {
        "required": 0,
        "automatic": 0,
        "author_pinned": 0,
        "excluded": len(ctx.excluded_items),
        "omitted": len(ctx.omitted_items),
    }
    for section in ctx.sections:
        for item in section.items:
            counts[item.selection_state] = counts.get(item.selection_state, 0) + 1
    effective_range = dict(ctx.selection_trace.get("effective_range") or {})
    if not effective_range:
        effective_range = {
            "chapter_from": getattr(options, "chapter_index", None),
            "chapter_to": getattr(options, "visible_until_chapter", None),
            "scene_id": getattr(options, "scene_id", None),
        }
    return {
        "status": "blocked" if ctx.blockers else "ready",
        "counts": counts,
        "effective_range": effective_range,
        "excluded_items": [item.model_dump(mode="json") for item in ctx.excluded_items],
        "omitted_items": [item.model_dump(mode="json") for item in ctx.omitted_items],
    }


def context_review_metadata(ctx: CompiledContext, options) -> dict:
    return {
        "context_fingerprint": compiled_context_fingerprint(ctx),
        "selected_asset_ids": selected_asset_ids_from_compiled(
            ctx,
            novel_id=str(getattr(options, "novel_id")),
        ),
        "selection_state": selection_state_from_compiled(ctx, options),
        "blockers": list(ctx.blockers),
    }


def build_tier_compile_response(
    request: ContextCompileRequest | ContextRenderRequest,
    ctx: CompiledContext,
) -> ContextTierCompileResponse:
    """Build the stable tiered context review response."""
    metadata = context_review_metadata(ctx, request)
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
                key=section.key,
                tier=int(section.tier),
                content=section.content,
                token_count=section.token_count,
                truncated=section.key in ctx.truncated_keys,
                title=section.title,
                preview=section.preview or section.content[:160],
                status=section.status,
                activation_reason=section.activation_reason,
                sources=section.sources,
                can_exclude=section.can_exclude and int(section.tier) != 0,
                excluded=section.excluded,
                truncated_reason=section.truncated_reason,
                retrieval_metadata=section.retrieval_metadata,
                items=[item.model_dump(mode="json") for item in section.items],
            )
            for section in ctx.sections
        ],
        evicted=ctx.evicted_keys,
        truncated=ctx.truncated_keys,
        budget_events=[event.model_dump() for event in ctx.budget_events],
        warnings=list(ctx.warnings),
        activation_trace=dict(ctx.activation_trace),
        **metadata,
    )
