"""Context snapshot helpers for Phase 2 scene entity extraction."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.context_snapshot_helpers import build_phase2_snapshot_payload


async def create_phase2_snapshot(
    service,
    db: AsyncSession,
    nid,
    scene: dict[str, Any],
    source_chapter_index: int,
    chapters_text: str,
    existing_context: str,
    memory_context: str,
    accumulated_memory: list[dict],
    workflow_id: str | None = None,
):
    from core.config import get_settings
    from modules.context.contracts import ContextSnapshotRequest
    from modules.context.facade import open_context_snapshot

    settings = get_settings()
    max_tokens = 16384
    temperature = 0.3
    payload = build_phase2_snapshot_payload(
        scene=scene,
        source_chapter_index=source_chapter_index,
        existing_context=existing_context,
        memory_context=memory_context,
        chapters_text=chapters_text,
        accumulated_memory=accumulated_memory,
        model=settings.llm_model,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return await open_context_snapshot(
        db,
        ContextSnapshotRequest(
            novel_id=str(nid),
            task_id=workflow_id,
            workflow_id=workflow_id,
            phase="entity_extraction",
            operation="scene_entity_extraction",
            scene_id=payload["scene_id"],
            scene_index=payload["scene_index"],
            chapter_index=payload["chapter_index"],
            prompt_name="scene_entity_extraction",
            model=settings.llm_model,
            compile_options=payload["compile_options"],
            included_asset_ids=payload["included_asset_ids"],
            context_summary=payload["context_summary"],
            section_metadata=payload["section_metadata"],
            token_metadata=payload["token_metadata"],
            rendered_context=payload["rendered_context"],
        ),
    )

async def phase2_audit_summary(
    service,
    db: AsyncSession,
    novel_id: str,
    *,
    workflow_id: str | None,
) -> dict[str, Any]:
    if not workflow_id:
        return {}
    from modules.context.facade import list_context_snapshots

    snapshots = await list_context_snapshots(
        db,
        novel_id=novel_id,
        workflow_id=workflow_id,
        limit=200,
    )
    phase_snapshots = [
        item for item in snapshots if item.phase == "entity_extraction"
    ]
    failed_scenes = [
        item.scene_index
        for item in phase_snapshots
        if item.status == "failed" and item.scene_index is not None
    ]
    retained_expirations = [
        item.rendered_context_expires_at
        for item in phase_snapshots
        if item.rendered_context is not None
    ]
    return {
        "entity_extraction": {
            "snapshot_count": len(phase_snapshots),
            "succeeded": sum(
                1 for item in phase_snapshots if item.status == "succeeded"
            ),
            "failed": sum(1 for item in phase_snapshots if item.status == "failed"),
            "failed_scenes": failed_scenes,
            "retained_rendered_context_count": len(retained_expirations),
            "rendered_context_expires_at": retained_expirations,
        }
    }

async def phase2_snapshot_health_summary(
    service,
    db: AsyncSession,
    novel_id: str,
    *,
    workflow_id: str | None,
) -> dict[str, Any]:
    if not workflow_id:
        return {}
    from modules.context.facade import build_snapshot_health_summary

    return await build_snapshot_health_summary(
        db,
        novel_id=novel_id,
        workflow_id=workflow_id,
    )

async def create_phase2b_snapshot(
    service,
    db: AsyncSession,
    nid,
    scene: dict[str, Any],
    chapters_text: str,
    entity_index: str,
    *,
    workflow_id: str | None = None,
):
    from core.config import get_settings
    from modules.context.contracts import ContextSnapshotRequest
    from modules.context.facade import open_context_snapshot

    settings = get_settings()
    rendered_context = f"{entity_index}\n\n{service._scene_context_header(scene)}"
    return await open_context_snapshot(
        db,
        ContextSnapshotRequest(
            novel_id=str(nid),
            task_id=workflow_id,
            workflow_id=workflow_id,
            phase="entity_extraction",
            operation="alias_relation_extraction",
            scene_id=service._scene_id(scene),
            scene_index=scene.get("scene_index"),
            chapter_index=service._scene_source_chapter_index(scene),
            prompt_name="alias_relation_extraction",
            model=settings.llm_model,
            compile_options={"source": "deep_import_phase2b_alias_relation"},
            included_asset_ids=[],
            context_summary={
                "scene_index": scene.get("scene_index"),
                "entity_index_chars": len(entity_index),
                "text_chars": len(chapters_text),
            },
            section_metadata=[
                {"name": "entity_index", "chars": len(entity_index)},
                {"name": "scene_text", "chars": len(chapters_text)},
            ],
            token_metadata={"estimated_chars": len(rendered_context)},
            rendered_context=rendered_context,
        ),
    )
