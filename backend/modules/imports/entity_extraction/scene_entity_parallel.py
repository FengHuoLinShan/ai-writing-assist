"""Parallel Phase 2a extraction strategy for small samples and bulk fallback."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.entity_extraction.scene_entity_config import (
    PHASE2_PARALLEL_LLM_TIMEOUT_SECONDS,
    PHASE2_PARALLEL_PROVIDER_TIMEOUT_SECONDS,
    PHASE2_PARALLEL_SCENE_CONCURRENCY,
)
from modules.imports.entity_extraction.scene_entity_runtime import (
    SceneEntityExtractionRuntime,
)

logger = logging.getLogger(__name__)


class ParallelSceneEntityExtractor:
    """Runs LLM extraction concurrently, then persists results serially."""

    def __init__(self, service: SceneEntityExtractionRuntime) -> None:
        self.service = service

    async def run(
        self,
        db: AsyncSession,
        nid,
        scenes: list[dict[str, Any]],
        existing_context: str,
        *,
        workflow_id: str | None,
        on_scene_progress: Callable[[int, int], Awaitable[None]] | None,
        bulk_error_kind: str | None,
    ) -> dict[str, Any]:
        service = self.service
        prepared: list[dict[str, Any]] = []
        for scene_idx, scene in enumerate(scenes):
            source_chapter_index = service._scene_source_chapter_index(scene)
            chapters_text = await service._load_scene_chapters(db, scene)
            if not chapters_text:
                prepared.append(
                    {
                        "scene_idx": scene_idx,
                        "scene": scene,
                        "source_chapter_index": source_chapter_index,
                        "chapters_text": "",
                        "memory_context": "无前序 Scene 上下文",
                        "snapshot_id": None,
                    }
                )
                continue
            memory_context = service._parallel_scene_memory_context(scene, scene_idx)
            snapshot = await service._create_phase2_snapshot(
                db,
                nid,
                scene,
                source_chapter_index,
                chapters_text,
                existing_context,
                memory_context,
                [],
                workflow_id=workflow_id,
            )
            prepared.append(
                {
                    "scene_idx": scene_idx,
                    "scene": scene,
                    "source_chapter_index": source_chapter_index,
                    "chapters_text": chapters_text,
                    "memory_context": memory_context,
                    "snapshot_id": snapshot.id,
                }
            )

        semaphore = asyncio.Semaphore(PHASE2_PARALLEL_SCENE_CONCURRENCY)

        async def extract_scene(item: dict[str, Any]) -> dict[str, Any]:
            if not item["chapters_text"]:
                return {**item, "extraction": None, "error": None}
            format_diagnostics: list[dict[str, Any]] = []
            try:
                async with semaphore:
                    extraction = await asyncio.wait_for(
                        service._call_llm_extraction(
                            item["chapters_text"],
                            existing_context,
                            item["memory_context"],
                            client_timeout=PHASE2_PARALLEL_PROVIDER_TIMEOUT_SECONDS,
                            transport_retries=False,
                            diagnostics=format_diagnostics,
                        ),
                        timeout=PHASE2_PARALLEL_LLM_TIMEOUT_SECONDS,
                    )
            except Exception as exc:
                return {
                    **item,
                    "extraction": None,
                    "error": exc,
                    "format_diagnostics": format_diagnostics,
                }
            return {
                **item,
                "extraction": extraction,
                "error": None,
                "format_diagnostics": format_diagnostics,
            }

        extracted = await asyncio.gather(
            *(extract_scene(item) for item in prepared),
        )

        total_created = 0
        total_relations = 0
        total_deltas = 0
        completed_scenes = 0
        failed_scene_indices: list[int] = []
        scene_checkpoints: list[dict[str, Any]] = []
        seen_entity_keys: set[tuple[str, str]] = set()
        accumulated_memory: list[dict] = []
        updated_context = existing_context
        error_kind: str | None = None
        error_message: str | None = None
        structured_format_diagnostics: list[dict[str, Any]] = []

        for item in sorted(extracted, key=lambda entry: entry["scene_idx"]):
            structured_format_diagnostics.extend(item.get("format_diagnostics") or [])
            scene = item["scene"]
            scene_idx = int(item["scene_idx"])
            scene_index = int(scene.get("scene_index") or scene_idx)
            scene_id = service._scene_id(scene)
            scene_provenance_key = service._scene_provenance_key(workflow_id, scene)
            snapshot_id = item["snapshot_id"]
            extraction = item["extraction"]
            error = item["error"]

            if error is not None:
                error_kind = service._error_kind(error)
                error_message = str(error)[:300]
                failed_scene_indices.append(scene_index)
                if snapshot_id is not None:
                    from modules.context.facade import mark_context_snapshot_failed

                    await mark_context_snapshot_failed(
                        db,
                        snapshot_id=snapshot_id,
                        error_kind=error_kind,
                        error_message=error_message,
                    )
                scene_checkpoints.append(
                    service._build_scene_checkpoint(
                        scene,
                        status="failed",
                        workflow_id=workflow_id,
                        scene_provenance_key=scene_provenance_key,
                        retry_count=1,
                        error=error_message,
                        error_kind=error_kind,
                    )
                )
                if on_scene_progress is not None:
                    await on_scene_progress(scene_idx + 1, len(scenes))
                continue

            if extraction is None:
                scene_checkpoints.append(
                    service._build_scene_checkpoint(
                        scene,
                        status="done",
                        workflow_id=workflow_id,
                        scene_provenance_key=scene_provenance_key,
                        retry_count=0,
                    )
                )
                completed_scenes += 1
                if on_scene_progress is not None:
                    await on_scene_progress(scene_idx + 1, len(scenes))
                continue

            result_refs: list[dict[str, str]] = []
            try:
                created_count = await service._persist_entities(
                    db,
                    nid,
                    extraction.entities,
                    scene_index=scene_index,
                    source_chapter_index=item["source_chapter_index"],
                    seen_entity_keys=seen_entity_keys,
                    workflow_id=workflow_id,
                    scene_id=scene_id,
                    scene_provenance_key=scene_provenance_key,
                    context_snapshot_id=snapshot_id,
                    result_refs=result_refs,
                )
                relation_count = await service._persist_relations(
                    db,
                    nid,
                    extraction.relations,
                    scene_index=scene_index,
                    workflow_id=workflow_id,
                    context_snapshot_id=snapshot_id,
                    result_refs=result_refs,
                )
                delta_count = await service._record_deltas(
                    db,
                    nid,
                    extraction.delta_events,
                    scene_index=scene_index,
                    workflow_id=workflow_id,
                    scene_id=scene_id,
                    scene_provenance_key=scene_provenance_key,
                    context_snapshot_id=snapshot_id,
                    result_refs=result_refs,
                )
                if snapshot_id is not None:
                    from modules.context.facade import mark_context_snapshot_succeeded

                    await mark_context_snapshot_succeeded(
                        db,
                        snapshot_id=snapshot_id,
                        result_refs=result_refs,
                    )
            except Exception as exc:
                error_kind = service._error_kind(exc)
                error_message = str(exc)[:300]
                failed_scene_indices.append(scene_index)
                if snapshot_id is not None:
                    from modules.context.facade import mark_context_snapshot_failed

                    await mark_context_snapshot_failed(
                        db,
                        snapshot_id=snapshot_id,
                        error_kind=error_kind,
                        error_message=error_message,
                    )
                scene_checkpoints.append(
                    service._build_scene_checkpoint(
                        scene,
                        status="failed",
                        workflow_id=workflow_id,
                        scene_provenance_key=scene_provenance_key,
                        retry_count=1,
                        error=error_message,
                        error_kind=error_kind,
                    )
                )
                if on_scene_progress is not None:
                    await on_scene_progress(scene_idx + 1, len(scenes))
                continue

            total_created += created_count
            total_relations += relation_count
            total_deltas += delta_count
            completed_scenes += 1
            updated_context = service._append_extracted_entities_to_context(
                updated_context,
                extraction,
            )
            accumulated_memory.append(
                {"scene_index": scene_index, "entities": len(extraction.entities)}
            )
            scene_checkpoints.append(
                service._build_scene_checkpoint(
                    scene,
                    status="done",
                    workflow_id=workflow_id,
                    scene_provenance_key=scene_provenance_key,
                    retry_count=0,
                    created_entity_ids=service._result_ref_ids(
                        result_refs,
                        "core_entity",
                    ),
                    created_relation_ids=service._result_ref_ids(
                        result_refs,
                        "entity_relation",
                    ),
                    created_delta_ids=service._result_ref_ids(result_refs, "delta_log"),
                )
            )
            try:
                from modules.memory.facade import capture_snapshot

                await capture_snapshot(
                    db,
                    str(nid),
                    chapter_index=item["source_chapter_index"],
                )
            except Exception as exc:
                logger.warning(
                    "Memory snapshot after scene %d failed: %s",
                    scene_index,
                    exc,
                )
            if on_scene_progress is not None:
                await on_scene_progress(scene_idx + 1, len(scenes))

        supplement_result = await service._supplement_small_sample_entities(
            db,
            nid,
            scenes,
            current_count=total_created,
            workflow_id=workflow_id,
        )
        if supplement_result["created"]:
            total_created += supplement_result["created"]

        flush_status = await service._phase2_flush_with_timeout(db)
        audit_summary = await service._phase2_audit_summary(
            db,
            str(nid),
            workflow_id=workflow_id,
        )
        snapshot_health_summary = await service._phase2_snapshot_health_summary(
            db,
            str(nid),
            workflow_id=workflow_id,
        )
        phase2_result = {
            "total_created": total_created,
            "total_relations": total_relations,
            "total_aliases": 0,
            "total_deltas": total_deltas,
            "total_scenes": len(scenes),
            "degraded": bool(
                failed_scene_indices
                or supplement_result["created"]
                or flush_status["degraded"]
            ),
            "error_kind": error_kind or flush_status["error_kind"],
            "error_message": error_message or flush_status["error_message"],
            "failed_scene_indices": failed_scene_indices,
            "completed_scenes": completed_scenes,
            "skipped_scenes": 0,
            "rerun_scenes": 0,
            "stopped_early": False,
            "audit_summary": audit_summary,
            "snapshot_health_summary": snapshot_health_summary,
            "checkpoints": {"phase2": {"scenes": scene_checkpoints}},
            "parallel_llm_fallback": True,
            "bulk_error_kind": bulk_error_kind,
            "supplemental_llm_created": supplement_result["supplemental_llm_created"],
            "fallback_created": supplement_result["fallback_created"],
            "supplemental_error_kind": supplement_result["supplemental_error_kind"],
            "structured_format_diagnostics": structured_format_diagnostics[:20],
        }
        alias_result = await service._run_alias_relation_phase(
            db,
            nid,
            scenes,
            workflow_id=workflow_id,
        )
        return service._merge_alias_relation_result(phase2_result, alias_result)
