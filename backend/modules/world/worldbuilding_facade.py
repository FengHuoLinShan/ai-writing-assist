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


async def get_world_background(
    db,
    novel_id: str,
    *,
    context_mode: str = "canonical",
    limit: int = 160,
):
    """Return derived world entries for context; never writes canonical state."""
    from modules.world.world_background import WorldBackgroundAggregation

    return await WorldBackgroundAggregation().build(
        db,
        novel_id,
        context_mode=context_mode,
        limit=limit,
    )


async def get_world_bible_synopsis_context(
    db,
    novel_id: str,
    *,
    revision_id: str | None = None,
):
    """Return author-only synopsis data without exposing world ORM models."""
    from modules.world.contracts import WorldBibleSynopsisContextContract
    from modules.world.services.worldbuilding.world_bible_synopsis_service import (
        WorldBibleSynopsisService,
    )

    payload = await WorldBibleSynopsisService().context_payload(
        db,
        novel_id,
        revision_id=revision_id,
    )
    return WorldBibleSynopsisContextContract(novel_id=novel_id, **payload)


async def mark_world_bible_synopsis_stale(db, novel_id: str) -> None:
    """Mark the project synopsis stale after a world-owned source change."""
    from modules.world.services.worldbuilding.world_bible_synopsis_service import (
        WorldBibleSynopsisService,
    )

    await WorldBibleSynopsisService().mark_stale(db, novel_id)


async def get_world_bible_working_pages_context(
    db,
    novel_id: str,
    *,
    draft_ids: list[str],
) -> list[dict]:
    """Return explicitly selected working pages through a stable world seam."""
    from modules.world.services.worldbuilding.world_bible_lifecycle_service import (
        WorldBibleLifecycleService,
    )

    service = WorldBibleLifecycleService()
    items = []
    for draft_id in list(dict.fromkeys(draft_ids))[:20]:
        draft = await service.get_draft(db, novel_id, draft_id)
        items.append(draft.model_dump(mode="json"))
    return items


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
