"""Parallel Phase 2a extraction strategy for small samples and bulk fallback."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.entity_extraction.scene_entity_config import (
    phase2_parallel_llm_timeout_seconds,
    phase2_parallel_provider_timeout_seconds,
    phase2_parallel_scene_concurrency,
    phase2_parallel_scene_max_tokens,
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
        include_alias_relations: bool = True,
        existing_checkpoints: dict[str, dict[str, Any]] | None = None,
        existing_alias_relation_checkpoints: dict[str, Any] | None = None,
        visible_until_chapter: int | None = None,
    ) -> dict[str, Any]:
        service = self.service
        configured_concurrency = phase2_parallel_scene_concurrency()
        scene_max_tokens = phase2_parallel_scene_max_tokens()
        provider_timeout_seconds = phase2_parallel_provider_timeout_seconds()
        llm_timeout_seconds = phase2_parallel_llm_timeout_seconds()
        prepared: list[dict[str, Any]] = []
        skipped_checkpoints: list[dict[str, Any]] = []
        rerun_scenes = 0
        for scene_idx, scene in enumerate(scenes):
            previous = (existing_checkpoints or {}).get(service._scene_id(scene))
            previous_status = (previous or {}).get("status")
            previous_retries = int((previous or {}).get("retry_count") or 0)
            if service._has_persistent_scene_id(scene):
                activation_kwargs: dict[str, Any] = {
                    "novel_id": str(nid),
                    "scene_id": service._scene_id(scene),
                }
                if visible_until_chapter is not None:
                    activation_kwargs["visible_until_chapter"] = visible_until_chapter
                activation = await service._prepare_import_context_activation(
                    db,
                    **activation_kwargs,
                )
                source_chapter_index = (
                    activation.chapter_index or service._scene_source_chapter_index(scene)
                )
                chapters_text = activation.current_scene_text
                world_context = activation.world_context_text
                memory_context = activation.neighbor_context_text
                activation_metadata = {
                    "activation_version": activation.activation_version,
                    "sources": activation.sources,
                    "budget_events": activation.budget_events,
                    "warnings": activation.warnings,
                }
            else:
                source_chapter_index = service._scene_source_chapter_index(scene)
                chapters_text = await service._load_scene_chapters(db, scene)
                world_context = existing_context
                memory_context = service._parallel_scene_memory_context(scene, scene_idx)
                activation_metadata = {
                    "activation_version": "legacy-transient-scene",
                    "sources": [],
                    "budget_events": [],
                    "warnings": ["transient_scene_compatibility_adapter"],
                }
            input_fingerprint = service._scene_input_fingerprint(scene, chapters_text)
            fingerprint_matches = bool(
                previous and previous.get("input_fingerprint") == input_fingerprint
            )
            if previous_status in {"done", "skipped"} and fingerprint_matches:
                skipped_checkpoints.append(
                    service._build_scene_checkpoint(
                        scene,
                        status="skipped",
                        workflow_id=workflow_id,
                        scene_provenance_key=service._scene_provenance_key(
                            workflow_id,
                            scene,
                        ),
                        retry_count=previous_retries,
                        created_entity_ids=previous.get("created_entity_ids", []),
                        created_relation_ids=previous.get("created_relation_ids", []),
                        created_delta_ids=previous.get("created_delta_ids", []),
                        input_fingerprint=input_fingerprint,
                    )
                )
                continue
            if (
                previous_status == "quality_failed"
                and previous_retries >= 1
                and fingerprint_matches
            ):
                skipped_checkpoints.append(
                    service._build_scene_checkpoint(
                        scene,
                        status="skipped",
                        workflow_id=workflow_id,
                        scene_provenance_key=service._scene_provenance_key(
                            workflow_id,
                            scene,
                        ),
                        retry_count=previous_retries,
                        error="quality_rerun_exhausted",
                        error_kind="quality_rerun_exhausted",
                        input_fingerprint=input_fingerprint,
                    )
                )
                continue
            if previous_status is not None:
                rerun_scenes += 1
            if not chapters_text:
                prepared.append(
                    {
                        "scene_idx": scene_idx,
                        "scene": scene,
                        "source_chapter_index": source_chapter_index,
                        "chapters_text": "",
                        "memory_context": memory_context,
                        "world_context": world_context,
                        "activation": activation_metadata,
                        "snapshot_id": None,
                        "input_fingerprint": input_fingerprint,
                    }
                )
                continue
            snapshot = await service._create_phase2_snapshot(
                db,
                nid,
                scene,
                source_chapter_index,
                chapters_text,
                world_context,
                memory_context,
                [],
                workflow_id=workflow_id,
                activation=activation_metadata,
            )
            prepared.append(
                {
                    "scene_idx": scene_idx,
                    "scene": scene,
                    "source_chapter_index": source_chapter_index,
                    "chapters_text": chapters_text,
                    "memory_context": memory_context,
                    "world_context": world_context,
                    "activation": activation_metadata,
                    "snapshot_id": snapshot.id,
                    "input_fingerprint": input_fingerprint,
                }
            )

        async def extract_scene(item: dict[str, Any]) -> dict[str, Any]:
            if not item["chapters_text"]:
                return {**item, "extraction": None, "error": None}
            format_diagnostics: list[dict[str, Any]] = []
            try:
                extraction = await asyncio.wait_for(
                    service._call_llm_extraction(
                        item["chapters_text"],
                        item["world_context"],
                        item["memory_context"],
                        max_tokens=scene_max_tokens,
                        client_timeout=provider_timeout_seconds,
                        transport_retries=False,
                        diagnostics=format_diagnostics,
                    ),
                    timeout=llm_timeout_seconds,
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

        extracted: list[dict[str, Any]] = []
        concurrency = configured_concurrency
        throttle_reasons: list[str] = []
        healthy_completions = 0
        for start in range(0, len(prepared), concurrency):
            wave = prepared[start : start + concurrency]
            results = await asyncio.gather(*(extract_scene(item) for item in wave))
            extracted.extend(results)
            transport_failures = sum(1 for item in results if item.get("error"))
            format_failures = sum(1 for item in results if item.get("format_diagnostics"))
            if transport_failures >= 2 or format_failures >= 3:
                next_concurrency = max(1, concurrency // 2)
                if next_concurrency < concurrency:
                    throttle_reasons.append("transport_or_format_failure_window")
                    concurrency = next_concurrency
                healthy_completions = 0
            else:
                healthy_completions += len(results)
                if healthy_completions >= 16 and concurrency < configured_concurrency:
                    concurrency = min(
                        configured_concurrency,
                        concurrency * 2,
                    )
                    healthy_completions = 0

        total_created = 0
        total_relations = 0
        total_deltas = 0
        completed_scenes = 0
        failed_scene_indices: list[int] = []
        unresolved_scene_indices: list[int] = []
        unresolved_scene_ids: list[str] = []
        scene_checkpoints: list[dict[str, Any]] = list(skipped_checkpoints)
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
                    from modules.context.facade import fail_context_snapshot

                    await fail_context_snapshot(
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
                        activation_version=item["activation"]["activation_version"],
                        activation_source_count=len(item["activation"]["sources"]),
                        input_fingerprint=item["input_fingerprint"],
                    )
                )
                if on_scene_progress is not None:
                    await on_scene_progress(scene_idx + 1, len(scenes))
                continue

            if extraction is None:
                missing_current_evidence = not item["chapters_text"]
                if missing_current_evidence:
                    unresolved_scene_indices.append(scene_index)
                    unresolved_scene_ids.append(scene_id)
                scene_checkpoints.append(
                    service._build_scene_checkpoint(
                        scene,
                        status="skipped" if missing_current_evidence else "done",
                        workflow_id=workflow_id,
                        scene_provenance_key=scene_provenance_key,
                        retry_count=0,
                        error=(
                            "current_scene_span_coverage_missing"
                            if missing_current_evidence
                            else None
                        ),
                        error_kind=(
                            "current_scene_span_coverage_missing"
                            if missing_current_evidence
                            else None
                        ),
                        activation_version=item["activation"]["activation_version"],
                        activation_source_count=len(item["activation"]["sources"]),
                        input_fingerprint=item["input_fingerprint"],
                    )
                )
                if not missing_current_evidence:
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
                    source_chapter_index=item["source_chapter_index"],
                    workflow_id=workflow_id,
                    scene_id=scene_id,
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
                    from modules.context.facade import succeed_context_snapshot

                    await succeed_context_snapshot(
                        db,
                        snapshot_id=snapshot_id,
                        result_refs=result_refs,
                    )
            except Exception as exc:
                error_kind = service._error_kind(exc)
                error_message = str(exc)[:300]
                failed_scene_indices.append(scene_index)
                if snapshot_id is not None:
                    from modules.context.facade import fail_context_snapshot

                    await fail_context_snapshot(
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
                        activation_version=item["activation"]["activation_version"],
                        activation_source_count=len(item["activation"]["sources"]),
                        input_fingerprint=item["input_fingerprint"],
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
                    activation_version=item["activation"]["activation_version"],
                    activation_source_count=len(item["activation"]["sources"]),
                    input_fingerprint=item["input_fingerprint"],
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
                or unresolved_scene_indices
                or flush_status["degraded"]
            ),
            "error_kind": error_kind
            or (
                "current_scene_span_coverage_missing"
                if unresolved_scene_indices
                else flush_status["error_kind"]
            ),
            "error_message": error_message
            or (
                "Skipped Scenes without exact or reanchored source spans."
                if unresolved_scene_indices
                else flush_status["error_message"]
            ),
            "failed_scene_indices": failed_scene_indices,
            "failed_scene_ids": [
                service._scene_id(item["scene"])
                for item in extracted
                if item.get("error") is not None
            ],
            "completed_scenes": completed_scenes,
            "skipped_scenes": len(skipped_checkpoints) + len(unresolved_scene_indices),
            "rerun_scenes": rerun_scenes,
            "quality_failed_scene_ids": [],
            "unresolved_scene_indices": unresolved_scene_indices,
            "unresolved_scene_ids": unresolved_scene_ids,
            "stopped_early": False,
            "audit_summary": audit_summary,
            "snapshot_health_summary": snapshot_health_summary,
            "checkpoints": {"phase2": {"scenes": scene_checkpoints}},
            "parallel_llm_fallback": not str(bulk_error_kind or "").startswith(
                "unified_activation:"
            ),
            "bulk_error_kind": bulk_error_kind,
            "activation_version": "import-context-v1",
            "phase2_effective_concurrency": configured_concurrency,
            "phase2_scene_max_tokens": scene_max_tokens,
            "phase2_provider_timeout_seconds": provider_timeout_seconds,
            "phase2_llm_timeout_seconds": llm_timeout_seconds,
            "phase2_throttle_reasons": throttle_reasons,
            "supplemental_llm_created": 0,
            "fallback_created": 0,
            "supplemental_error_kind": None,
            "structured_format_diagnostics": structured_format_diagnostics[:20],
        }
        if include_alias_relations:
            alias_result = await service._run_alias_relation_phase(
                db,
                nid,
                scenes,
                workflow_id=workflow_id,
                existing_checkpoints=existing_alias_relation_checkpoints,
            )
        else:
            alias_result = {"alias_relation_skipped": True}
        return service._merge_alias_relation_result(phase2_result, alias_result)
