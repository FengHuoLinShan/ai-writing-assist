"""Parallel Phase 2a extraction strategy for small samples and bulk fallback."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.entity_extraction.scene_entity_checkpoint import (
    phase2a_input_fingerprint,
)
from modules.imports.entity_extraction.scene_entity_config import (
    PHASE2A_PROMPT_CONTRACT_VERSION,
    phase2_parallel_llm_timeout_seconds,
    phase2_parallel_provider_timeout_seconds,
    phase2_parallel_scene_concurrency,
    phase2_parallel_scene_max_tokens,
)

logger = logging.getLogger(__name__)


def _accepts_keyword(callable_obj: Any, keyword: str) -> bool:
    """Preserve test/monkeypatch seams while adding optional v2 context."""
    try:
        parameters = inspect.signature(callable_obj).parameters.values()
    except (TypeError, ValueError):
        return True
    return any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        or parameter.name == keyword
        for parameter in parameters
    )


class ParallelSceneEntityExtractionMixin:
    """Internal concurrent LLM and ordered persistence implementation."""

    async def _process_scenes_parallel_llm(
        self,
        db: AsyncSession,
        nid,
        scenes: list[dict[str, Any]],
        existing_context: str,
        *,
        workflow_id: str | None,
        authorization_snapshot: dict[str, Any] | None = None,
        on_scene_progress: Callable[[int, int], Awaitable[None]] | None,
        bulk_error_kind: str | None,
        include_alias_relations: bool = True,
        existing_checkpoints: dict[str, dict[str, Any]] | None = None,
        existing_alias_relation_checkpoints: dict[str, Any] | None = None,
        visible_until_chapter: int | None = None,
    ) -> dict[str, Any]:
        service = self
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
                context_fingerprint = str(
                    getattr(activation, "context_fingerprint", "") or ""
                )
                identity_candidates = list(
                    getattr(activation, "identity_candidates", []) or []
                )
                outline_context = dict(
                    getattr(activation, "outline_context", {}) or {}
                )
                scene_card = dict(getattr(activation, "scene_card", {}) or {})
                activation_metadata = {
                    "activation_version": activation.activation_version,
                    "prompt_contract_version": PHASE2A_PROMPT_CONTRACT_VERSION,
                    "sources": activation.sources,
                    "budget_events": activation.budget_events,
                    "warnings": activation.warnings,
                    "context_fingerprint": context_fingerprint,
                    "identity_candidate_refs": [
                        item.get("prompt_ref")
                        for item in identity_candidates
                        if item.get("prompt_ref")
                    ],
                    "identity_candidate_count": len(identity_candidates),
                    "outline_counts": {
                        key: len(outline_context.get(key, []))
                        for key in ("scenes", "arcs", "plot_threads")
                    },
                    "scene_card": scene_card,
                    "outline_context": outline_context,
                    "identity_candidates": identity_candidates,
                    "previous_scene_briefs": list(
                        getattr(activation, "previous_briefs", []) or []
                    ),
                    "previous_scene_evidence": list(
                        getattr(activation, "previous_evidence", []) or []
                    ),
                    "current_scene_sources": list(
                        getattr(activation, "current_scene_sources", []) or []
                    ),
                }
                context_bundle = {
                    "activation_version": activation.activation_version,
                    "prompt_contract_version": PHASE2A_PROMPT_CONTRACT_VERSION,
                    "context_fingerprint": context_fingerprint,
                    "scene_card": scene_card,
                    "outline_context": outline_context,
                    "identity_candidates": identity_candidates,
                    "previous_scene_briefs": list(
                        getattr(activation, "previous_briefs", []) or []
                    ),
                    "previous_scene_evidence": list(
                        getattr(activation, "previous_evidence", []) or []
                    ),
                    # Audit/source IDs are intentionally local-only. The adapter
                    # strips underscore-prefixed keys before serializing prompt data.
                    "_current_scene_sources": list(
                        getattr(activation, "current_scene_sources", []) or []
                    ),
                }
            else:
                source_chapter_index = service._scene_source_chapter_index(scene)
                chapters_text = await service._load_scene_chapters(db, scene)
                world_context = existing_context
                memory_context = service._parallel_scene_memory_context(scene, scene_idx)
                activation_metadata = {
                    "activation_version": "legacy-transient-scene",
                    "prompt_contract_version": PHASE2A_PROMPT_CONTRACT_VERSION,
                    "sources": [],
                    "budget_events": [],
                    "warnings": ["transient_scene_compatibility_adapter"],
                    "context_fingerprint": "",
                }
                context_bundle = {
                    "activation_version": "legacy-transient-scene",
                    "prompt_contract_version": PHASE2A_PROMPT_CONTRACT_VERSION,
                    "scene_card": scene,
                    "legacy_existing_context": world_context,
                    "legacy_previous_context": memory_context,
                }
            context_fingerprint = str(
                activation_metadata.get("context_fingerprint") or ""
            )
            base_fingerprint = service._scene_input_fingerprint(scene, chapters_text)
            input_fingerprint = phase2a_input_fingerprint(
                scene,
                chapters_text,
                context_fingerprint=context_fingerprint,
                base_fingerprint=base_fingerprint,
            )
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
                        "context_bundle": context_bundle,
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
                    "context_bundle": context_bundle,
                    "snapshot_id": snapshot.id,
                    "input_fingerprint": input_fingerprint,
                }
            )

        # Context assembly and snapshot creation are complete. Provider calls must
        # not hold a database transaction open across network waits.
        commit_result = db.commit()
        if inspect.isawaitable(commit_result):
            await commit_result
        if isinstance(db, AsyncSession) and db.in_transaction():
            raise RuntimeError("phase2_provider_call_requires_closed_transaction")

        async def extract_scene(item: dict[str, Any]) -> dict[str, Any]:
            if not item["chapters_text"]:
                return {**item, "extraction": None, "error": None}
            format_diagnostics: list[dict[str, Any]] = []
            try:
                call_kwargs: dict[str, Any] = {
                    "max_tokens": scene_max_tokens,
                    "client_timeout": provider_timeout_seconds,
                    "transport_retries": False,
                    "diagnostics": format_diagnostics,
                }
                if _accepts_keyword(
                    service._call_llm_extraction,
                    "context_bundle",
                ):
                    call_kwargs["context_bundle"] = item["context_bundle"]
                extraction = await asyncio.wait_for(
                    service._call_llm_extraction(
                        item["chapters_text"],
                        item["world_context"],
                        item["memory_context"],
                        **call_kwargs,
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
        provider_completed = len(skipped_checkpoints)
        if provider_completed and on_scene_progress is not None:
            await on_scene_progress(provider_completed, len(scenes))
        cursor = 0
        while cursor < len(prepared):
            wave = prepared[cursor : cursor + concurrency]
            pending = {
                asyncio.create_task(extract_scene(item))
                for item in wave
            }
            results: list[dict[str, Any]] = []
            while pending:
                done, pending = await asyncio.wait(
                    pending,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in done:
                    results.append(task.result())
                    provider_completed += 1
                    if on_scene_progress is not None:
                        await on_scene_progress(provider_completed, len(scenes))
            extracted.extend(results)
            cursor += len(wave)
            transport_errors = [
                item["error"]
                for item in results
                if item.get("error") is not None
                and service._is_transport_failure(item["error"])
            ]
            rate_limit_failures = sum(
                1
                for error in transport_errors
                if service._error_kind(error) == "rate_limit"
            )
            if rate_limit_failures >= 1 or len(transport_errors) >= 2:
                next_concurrency = max(1, concurrency // 2)
                if next_concurrency < concurrency:
                    throttle_reasons.append(
                        "rate_limit_window"
                        if rate_limit_failures
                        else "transport_failure_window"
                    )
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
        total_uncertain_items = 0
        map_candidate_created = 0
        map_candidate_reused = 0
        completed_scenes = 0
        failed_scene_indices: list[int] = []
        unresolved_scene_indices: list[int] = []
        unresolved_scene_ids: list[str] = []
        scene_checkpoints: list[dict[str, Any]] = list(skipped_checkpoints)
        seen_entity_keys: set[tuple[str, str]] = set()
        accumulated_memory: list[dict] = []
        updated_context = existing_context
        persistence_stats = service._empty_phase2_persistence_stats()
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
                    persistence_stats=persistence_stats,
                )
                # P13 no longer owns relations. P14 Phase 2b extracts and persists
                # aliases/relations after the entity identity index is available.
                relation_count = 0
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
                proposals = getattr(extraction, "map_observation_proposals", None)
                if isinstance(proposals, list) and proposals:
                    counts = await service._record_map_observation_proposals(
                        db,
                        nid,
                        proposals,
                        scene_index=scene_index,
                        source_chapter_index=item["source_chapter_index"],
                        workflow_id=workflow_id,
                        scene_id=scene_id,
                        scene_source_fingerprint=item["input_fingerprint"],
                        authorization_snapshot=authorization_snapshot,
                        context_snapshot_id=snapshot_id,
                        result_refs=result_refs,
                    )
                    map_candidate_created += counts["created"]
                    map_candidate_reused += counts["reused"]
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
                continue

            total_created += created_count
            total_relations += relation_count
            total_deltas += delta_count
            total_uncertain_items += len(getattr(extraction, "uncertain_items", []))
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
            "total_uncertain_items": total_uncertain_items,
            "map_observation_candidates_created": map_candidate_created,
            "map_observation_candidates_reused": map_candidate_reused,
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
            "activation_version": "import-context-v2",
            "prompt_contract_version": PHASE2A_PROMPT_CONTRACT_VERSION,
            "phase2_effective_concurrency": configured_concurrency,
            "phase2_scene_max_tokens": scene_max_tokens,
            "phase2_provider_timeout_seconds": provider_timeout_seconds,
            "phase2_llm_timeout_seconds": llm_timeout_seconds,
            "phase2_throttle_reasons": throttle_reasons,
            "phase2_action_counts": persistence_stats["action_counts"],
            "phase2_dedup_counts": persistence_stats["dedup_counts"],
            "phase2_linked_to_existing": persistence_stats["linked_to_existing"],
            "phase2_ignored": persistence_stats["ignored"],
            "phase2_temporary_only": persistence_stats["temporary_only"],
            "phase2_low_confidence": persistence_stats["low_confidence"],
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
                on_scene_progress=on_scene_progress,
                existing_checkpoints=existing_alias_relation_checkpoints,
            )
        else:
            alias_result = {"alias_relation_skipped": True}
        return service._merge_alias_relation_result(phase2_result, alias_result)


class ParallelSceneEntityExtractor(ParallelSceneEntityExtractionMixin):
    """Compatibility adapter for the former helper class."""

    def __init__(self, service) -> None:
        self.service = service

    def __getattr__(self, name):
        return getattr(self.service, name)

    async def run(self, *args, **kwargs):
        return await ParallelSceneEntityExtractionMixin._process_scenes_parallel_llm(
            self.service,
            *args,
            **kwargs,
        )
