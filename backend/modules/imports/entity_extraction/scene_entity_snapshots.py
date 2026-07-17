"""Context snapshot helpers for Phase 2 scene entity extraction."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.context_snapshot_helpers import build_phase2_snapshot_payload


def _phase2_profile_summary() -> dict[str, Any]:
    """Resolve the same secret-free profile used by active Phase 2 adapters."""
    from infrastructure.llm.profiles import resolve_llm_profile
    from modules.imports.entity_extraction.scene_entity_config import (
        current_phase2_project_settings,
        current_phase2_request_model,
    )

    summary = resolve_llm_profile(current_phase2_project_settings()).sanitized_summary()
    request_model = current_phase2_request_model() or str(summary.get("model") or "")
    summary["profile_model"] = summary.get("model")
    summary["request_model"] = request_model
    summary["model"] = request_model
    return summary


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
    activation: dict[str, Any] | None = None,
):
    from modules.context.contracts import ContextSnapshotRequest
    from modules.context.facade import open_context_snapshot
    from modules.imports.entity_extraction.scene_entity_config import (
        phase2_parallel_scene_max_tokens,
    )

    profile_summary = _phase2_profile_summary()
    max_tokens = phase2_parallel_scene_max_tokens()
    temperature = 0.3
    payload = build_phase2_snapshot_payload(
        scene=scene,
        source_chapter_index=source_chapter_index,
        existing_context=existing_context,
        memory_context=memory_context,
        chapters_text=chapters_text,
        accumulated_memory=accumulated_memory,
        model=str(profile_summary["model"]),
        max_tokens=max_tokens,
        temperature=temperature,
        activation=activation,
        profile_summary=profile_summary,
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
            model=str(profile_summary["model"]),
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
    phase_snapshots = [item for item in snapshots if item.phase == "entity_extraction"]
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
            "succeeded": sum(1 for item in phase_snapshots if item.status == "succeeded"),
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
    context_bundle: dict[str, Any] | None = None,
):
    from core.errors import ValidationError
    from modules.context.contracts import ContextSnapshotRequest
    from modules.context.facade import get_import_scene_source_refs, open_context_snapshot
    from modules.imports.entity_extraction.scene_entity_config import (
        PHASE2B_PROMPT_CONTRACT_VERSION,
    )
    from modules.imports.entity_extraction.scene_entity_phase2b_context import (
        prompt_context_bundle,
        render_phase2b_user_payload,
    )

    profile_summary = _phase2_profile_summary()
    prompt_bundle = prompt_context_bundle(context_bundle or {})
    if context_bundle is not None:
        rendered_context = render_phase2b_user_payload(
            context_bundle,
            chapters_text,
        )
    else:
        rendered_context = (
            f"{entity_index}\n\n{service._scene_context_header(scene)}"
            f"\n\n{chapters_text}"
        )
    source_refs: list[dict] = []
    source_warning = None
    if context_bundle is not None:
        source_refs = list(context_bundle.get("_current_scene_sources") or [])
        if not source_refs:
            raise ValueError("Phase 2b snapshot source refs are missing")
    else:
        try:
            source_refs = await get_import_scene_source_refs(
                db,
                novel_id=str(nid),
                scene_id=service._scene_id(scene),
                content_mode="working",
            )
        except (ValidationError, ValueError) as exc:
            source_warning = str(exc)
    included_sources = list((context_bundle or {}).get("_included_sources") or [])
    omitted_sources = list((context_bundle or {}).get("_omitted_sources") or [])
    included_asset_ids: dict[str, list[str]] | list = (
        _snapshot_asset_ids(included_sources) if context_bundle is not None else []
    )
    excluded_asset_ids: dict[str, list[str]] | None = (
        _snapshot_asset_ids(omitted_sources) if context_bundle is not None else None
    )
    section_metadata = [
        {"name": "entity_index", "chars": len(entity_index)},
        {
            "name": "scene_text",
            "chars": len(chapters_text),
            "source_refs": source_refs,
            "source_warning": source_warning,
        },
    ]
    if context_bundle is not None:
        section_metadata.append(
            {
                "name": "phase2b_context",
                "chars": len(rendered_context) - len(chapters_text),
                "prompt_contract_version": PHASE2B_PROMPT_CONTRACT_VERSION,
                "activation_context_fingerprint": context_bundle.get(
                    "_activation_context_fingerprint"
                ),
                "included_sources": included_sources,
                "omitted_sources": omitted_sources,
            }
        )
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
            model=str(profile_summary["model"]),
            compile_options={
                "source": "deep_import_phase2b_alias_relation",
                "content_mode": "working",
                "llm_runtime": profile_summary,
                "prompt_contract_version": PHASE2B_PROMPT_CONTRACT_VERSION,
                "context_fingerprint": (context_bundle or {}).get(
                    "context_fingerprint"
                ),
            },
            included_asset_ids=included_asset_ids,
            excluded_asset_ids=excluded_asset_ids,
            context_summary={
                "scene_index": scene.get("scene_index"),
                "entity_index_chars": len(entity_index),
                "text_chars": len(chapters_text),
                "source_ref_count": len(source_refs),
                "identity_candidate_count": len(
                    prompt_bundle.get("identity_candidates") or []
                ),
                "relation_candidate_count": len(
                    prompt_bundle.get("relation_candidates") or []
                ),
                "context_fingerprint": (context_bundle or {}).get(
                    "context_fingerprint"
                ),
            },
            section_metadata=section_metadata,
            token_metadata={"estimated_chars": len(rendered_context)},
            rendered_context=rendered_context,
            retain_rendered_context=context_bundle is not None,
        ),
    )


def _snapshot_asset_ids(sources: list[dict[str, Any]]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for source in sources:
        if not isinstance(source, dict) or not source.get("id"):
            continue
        source_type = str(source.get("type") or "unknown")
        grouped.setdefault(source_type, []).append(str(source["id"]))
    return {
        key: sorted(dict.fromkeys(values))
        for key, values in sorted(grouped.items())
    }
