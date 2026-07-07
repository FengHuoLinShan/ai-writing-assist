"""Worldbuilding Facade — 世界书 / 上下文激活子域的对外入口。"""

from __future__ import annotations


async def preview_worldbuilding_activation(
    db,
    novel_id: str,
    *,
    entity_ids: list[str] | None = None,
    map_id: str | None = None,
    scene_id: str | None = None,
    focus_entity_id: str | None = None,
    top_k: int = 64,
    depth: int = 2,
) -> dict:
    """Return deterministic worldbuilding activation candidates."""
    from modules.world.services.worldbuilding.worldbuilding_service import (
        ActivationPreviewService,
    )

    return await ActivationPreviewService().preview(
        db,
        novel_id,
        entity_ids=entity_ids,
        map_id=map_id,
        scene_id=scene_id,
        focus_entity_id=focus_entity_id,
        top_k=top_k,
        depth=depth,
    )


async def mark_worldbuilding_context_stale(
    db,
    novel_id: str,
    *,
    reason: str,
    asset_id: str = "worldbuilding",
) -> int:
    """Compatibility hook for context invalidation after worldbuilding changes."""
    from modules.context import facade as context_facade

    return await context_facade.mark_asset_context_changed(
        db,
        novel_id=novel_id,
        asset_type="worldbuilding",
        asset_id=asset_id,
        reason=reason,
    )
