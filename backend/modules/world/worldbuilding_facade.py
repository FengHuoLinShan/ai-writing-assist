"""Worldbuilding Facade — 世界书 / 上下文激活子域的对外入口。"""

from __future__ import annotations


async def inspect_world_draft(db, novel_id: str, draft_id: str) -> dict:
    """Read an author work draft through the world's stable boundary."""
    from modules.world.services.worldbuilding.world_bible_lifecycle_service import (
        WorldBibleLifecycleService,
    )

    row = await WorldBibleLifecycleService().get_draft(db, novel_id, draft_id)
    return row.model_dump(mode="json")


async def inspect_world_page_history(
    db, novel_id: str, page_id: str, version_number: int | None = None
) -> dict:
    from modules.world.assistant_page_tools import inspect_page_history

    return await inspect_page_history(db, novel_id, page_id, version_number)


async def inspect_world_checkpoint(db, novel_id: str, checkpoint_id: str) -> dict | None:
    from modules.world.services.worldbuilding.suggestion_queue_service import (
        SuggestionQueueService,
    )

    row = await SuggestionQueueService()._get_suggestion(db, novel_id, checkpoint_id)
    if (
        row.target_type not in {"world_design_checkpoint", "world_core_checkpoint"}
        or row.status == "rejected"
    ):
        return None
    return {
        "id": str(row.id),
        "checkpoint_type": row.target_type,
        "status": row.status,
        "payload": row.payload_json,
        "authority": "作者阶段成果；不是正式世界事实或角色知识",
    }


async def authorize_focused_world_completion(db, **kwargs):
    from modules.world.services.worldbuilding.focused_adoption import authorize

    return await authorize(db, **kwargs)


async def submit_focused_world_package(db, request):
    from modules.world.services.worldbuilding.adoption_package_service import (
        WorldAdoptionPackageService,
    )
    from modules.world.services.worldbuilding.focused_adoption import submit

    return await submit(WorldAdoptionPackageService(), db, request)


async def apply_focused_world_package(db, request):
    from modules.world.services.worldbuilding.adoption_package_service import (
        WorldAdoptionPackageService,
    )
    from modules.world.services.worldbuilding.focused_adoption import apply

    return await apply(WorldAdoptionPackageService(), db, request)


async def rollback_focused_world_package(db, *, novel_id, suggestion_id):
    from modules.world.services.worldbuilding.adoption_package_service import (
        WorldAdoptionPackageService,
    )
    from modules.world.services.worldbuilding.focused_adoption import rollback

    return await rollback(
        WorldAdoptionPackageService(), db, novel_id=novel_id, suggestion_id=suggestion_id
    )


async def initialize_world_canon(db, novel_id: str) -> None:
    """Create the idempotent empty canon root for one author project."""
    from modules.world.services.worldbuilding.world_authority_service import (
        WorldAuthorityService,
    )

    await WorldAuthorityService().initialize_empty_canon(db, novel_id)


async def assemble_post_import_adoption_package(db, request):
    """Create or return the one pending package for a completed deep import."""
    from modules.world.services.worldbuilding.adoption_package_service import (
        WorldAdoptionPackageService,
    )

    return await WorldAdoptionPackageService().assemble_post_import(db, request)


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
    reveal_mode: str = "author_safe",
    limit: int = 160,
):
    """Return derived world entries for one status view and author reveal mode."""
    from modules.world.world_background import WorldBackgroundAggregation

    return await WorldBackgroundAggregation().build(
        db,
        novel_id,
        context_mode=context_mode,
        reveal_mode=reveal_mode,
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


async def list_world_bible_working_page_ids(db, novel_id: str) -> list[str]:
    """List current working-page IDs for one explicit author opt-in."""
    from modules.world.services.worldbuilding.world_bible_lifecycle_service import (
        WorldBibleLifecycleService,
    )

    items, _total = await WorldBibleLifecycleService().list_drafts(db, novel_id)
    return [item.id for item in items[:20]]


async def get_world_bible_projection_candidates(
    db,
    novel_id: str,
    target_refs: list[dict],
    *,
    projection_type: str = "context_brief",
    expand_page_links: bool = False,
    relation_types: list[str] | None = None,
    max_depth: int = 0,
    reveal_mode: str = "author_safe",
):
    """Resolve fixed activation targets without exposing world persistence."""
    from modules.world.services.worldbuilding.activation_target_service import (
        WorldBibleActivationTargetService,
    )

    return await WorldBibleActivationTargetService().resolve(
        db,
        novel_id,
        target_refs,
        projection_type=projection_type,
        expand_page_links=expand_page_links,
        relation_types=relation_types,
        max_depth=max_depth,
        reveal_mode=reveal_mode,
    )


async def get_world_bible_page_source_manifest(
    db,
    novel_id: str,
    page_ids: list[str],
) -> list[dict]:
    """Return stable page source hashes for activation snapshot auditing."""
    from modules.world.services.worldbuilding.activation_target_service import (
        WorldBibleActivationTargetService,
    )

    return await WorldBibleActivationTargetService().page_source_manifest(
        db,
        novel_id,
        page_ids,
    )


async def mark_worldbuilding_context_stale(
    db,
    novel_id: str,
    *,
    reason: str,
    asset_id: str = "worldbuilding",
) -> int:
    """Compatibility hook for context invalidation after worldbuilding changes."""
    from modules.evidence import facade as context_facade

    return await context_facade.mark_asset_context_changed(
        db,
        novel_id=novel_id,
        asset_type="worldbuilding",
        asset_id=asset_id,
        reason=reason,
    )
