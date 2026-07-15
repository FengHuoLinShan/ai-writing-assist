"""Context review projection helpers."""

from __future__ import annotations

from modules.context.schemas import (
    ContextCompileRequest,
    ContextRenderRequest,
    ContextSectionItem,
    ContextTierCompileResponse,
)
from modules.context.services.compiled_context import CompiledContext


def build_tier_compile_response(
    request: ContextCompileRequest | ContextRenderRequest,
    ctx: CompiledContext,
) -> ContextTierCompileResponse:
    """Build the stable tiered context review response."""
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
            )
            for section in ctx.sections
        ],
        evicted=ctx.evicted_keys,
        truncated=ctx.truncated_keys,
        budget_events=[event.model_dump() for event in ctx.budget_events],
        warnings=list(ctx.warnings),
        activation_trace=dict(ctx.activation_trace),
    )
