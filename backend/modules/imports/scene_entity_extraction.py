"""SceneEntityExtractionService -- Phase 2 coordinator."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports import scene_entity_config as _phase2_config
from modules.imports.llm_schemas import (
    AliasRelationExtractionOutput,
    DeltaEvent,
    ExtractedEntity,
    ExtractedRelation,
    SceneEntityExtractionOutput,
)
from modules.imports.scene_entity_alias_relation import (
    AliasRelationExtractor,
    _effective_alias_relation_total_timeout_seconds,
)
from modules.imports.scene_entity_bulk import (
    BulkSceneEntityExtractor,
    bulk_entity_memory_context,
    fallback_entity_label,
)
from modules.imports.scene_entity_checkpoint import (
    build_scene_checkpoint,
    checkpoint_retry_count,
    error_kind,
    filter_scenes_by_range,
    is_transport_failure,
    merge_alias_relation_result,
    phase2_checkpoint_by_scene,
    scene_id,
    scene_overlaps_chapter_range,
    scene_provenance_key,
)
from modules.imports.scene_entity_llm_adapters import (
    call_alias_relation_extraction,
    call_llm_extraction,
)
from modules.imports.scene_entity_parallel import ParallelSceneEntityExtractor
from modules.imports.scene_entity_persistence import (
    SceneEntityPersistenceGateway,
    entity_key,
)
from modules.imports.scene_entity_single_scene import SingleSceneEntityExtractor
from modules.imports.scene_entity_snapshots import (
    create_phase2_snapshot,
    create_phase2b_snapshot,
    phase2_audit_summary,
    phase2_snapshot_health_summary,
)
from modules.imports.scene_entity_text import (
    append_extracted_entities_to_context,
    build_memory_context,
    get_scenes,
    load_scene_chapters,
    load_small_sample_chapters_text,
    parallel_scene_memory_context,
    phase2_scene_llm_timeout_seconds,
    result_ref_ids,
    scene_chapter_ids,
    scene_chunks_by_chapter,
    scene_context_header,
    scene_source_chapter_index,
    select_scene_text,
    small_sample_chapter_indices,
    trim_supplement_chapter_text,
)
from shared.utils import parse_uuid

logger = logging.getLogger(__name__)


def _alias_relation_failure_scene_index(scene: dict[str, Any], fallback: int) -> int:
    try:
        scene_index = int(scene.get("scene_index") or 0)
    except (AttributeError, TypeError, ValueError):
        scene_index = 0
    return scene_index if scene_index > 0 else fallback


MAX_PHASE2_SCENE_RETRIES = _phase2_config.MAX_PHASE2_SCENE_RETRIES
MAX_PHASE2_CONSECUTIVE_TRANSPORT_FAILURES = (
    _phase2_config.MAX_PHASE2_CONSECUTIVE_TRANSPORT_FAILURES
)
PHASE2_SCENE_TIMEOUT_GRACE_SECONDS = _phase2_config.PHASE2_SCENE_TIMEOUT_GRACE_SECONDS
PHASE2_BULK_MAX_SCENES = _phase2_config.PHASE2_BULK_MAX_SCENES
PHASE2_BULK_GROUP_SIZE = _phase2_config.PHASE2_BULK_GROUP_SIZE
PHASE2_BULK_LLM_TIMEOUT_SECONDS = _phase2_config.PHASE2_BULK_LLM_TIMEOUT_SECONDS
PHASE2_BULK_PROVIDER_TIMEOUT_SECONDS = (
    _phase2_config.PHASE2_BULK_PROVIDER_TIMEOUT_SECONDS
)
PHASE2_BULK_MAX_TOKENS = _phase2_config.PHASE2_BULK_MAX_TOKENS
PHASE2_BATCH_SIZE_SCENES = _phase2_config.PHASE2_BATCH_SIZE_SCENES
PHASE2_BATCH_CONCURRENCY = _phase2_config.PHASE2_BATCH_CONCURRENCY
PHASE2_BOUNDARY_SCENES = _phase2_config.PHASE2_BOUNDARY_SCENES
PHASE2_PARALLEL_SCENE_CONCURRENCY = _phase2_config.PHASE2_PARALLEL_SCENE_CONCURRENCY
PHASE2_PARALLEL_PROVIDER_TIMEOUT_SECONDS = (
    _phase2_config.PHASE2_PARALLEL_PROVIDER_TIMEOUT_SECONDS
)
PHASE2_PARALLEL_LLM_TIMEOUT_SECONDS = _phase2_config.PHASE2_PARALLEL_LLM_TIMEOUT_SECONDS
PHASE2_SMALL_SAMPLE_MIN_SCENES = _phase2_config.PHASE2_SMALL_SAMPLE_MIN_SCENES
PHASE2_SMALL_SAMPLE_MIN_ENTITIES = _phase2_config.PHASE2_SMALL_SAMPLE_MIN_ENTITIES
PHASE2_SMALL_SAMPLE_TARGET_ENTITIES = _phase2_config.PHASE2_SMALL_SAMPLE_TARGET_ENTITIES
PHASE2_SMALL_SAMPLE_SUPPLEMENT_TIMEOUT_SECONDS = (
    _phase2_config.PHASE2_SMALL_SAMPLE_SUPPLEMENT_TIMEOUT_SECONDS
)
PHASE2_SMALL_SAMPLE_SUPPLEMENT_CHAPTER_CHAR_LIMIT = (
    _phase2_config.PHASE2_SMALL_SAMPLE_SUPPLEMENT_CHAPTER_CHAR_LIMIT
)
PHASE2_SMALL_SAMPLE_SUPPLEMENT_TOTAL_CHAR_LIMIT = (
    _phase2_config.PHASE2_SMALL_SAMPLE_SUPPLEMENT_TOTAL_CHAR_LIMIT
)


class SceneEntityExtractionService:
    """Phase 2: coordinates scene entity, delta, alias, and relation extraction."""

    async def extract_alias_relations(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        workflow_id: str | None = None,
        scene_ids: list[str] | None = None,
        start_chapter: int | None = None,
        end_chapter: int | None = None,
        on_scene_progress: Callable[[int, int], Awaitable[None]] | None = None,
        existing_checkpoints: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        nid = parse_uuid(novel_id, "novel_id")
        scenes = await self._get_scenes(db, nid)
        selected: list[dict[str, Any]] = []
        scene_id_filter = set(scene_ids or [])
        for scene in scenes:
            if scene_id_filter and self._scene_id(scene) not in scene_id_filter:
                continue
            chapter_index = self._scene_source_chapter_index(scene)
            if start_chapter is not None and chapter_index < start_chapter:
                continue
            if end_chapter is not None and chapter_index > end_chapter:
                continue
            selected.append(scene)
        result = await self._run_alias_relation_phase(
            db,
            nid,
            selected,
            workflow_id=workflow_id,
            on_scene_progress=on_scene_progress,
            existing_checkpoints=existing_checkpoints,
        )
        flush_status = await self._phase2_flush_with_timeout(db)
        return {
            **result,
            "total_scenes": len(selected),
            "degraded": bool(
                result.get("alias_relation_failed_scenes")
                or flush_status["degraded"]
            ),
            "error_kind": result.get("error_kind") or flush_status["error_kind"],
            "error_message": (
                result.get("error_message") or flush_status["error_message"]
            ),
        }

    async def extract_by_scenes(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        workflow_id: str | None = None,
        on_scene_progress: Callable[[int, int], Awaitable[None]] | None = None,
        existing_checkpoints: dict[str, Any] | None = None,
        start_chapter: int | None = None,
        end_chapter: int | None = None,
        include_alias_relations: bool = True,
    ) -> dict[str, Any]:
        nid = parse_uuid(novel_id, "novel_id")

        scenes = self._filter_scenes_by_range(
            await self._get_scenes(db, nid),
            start_chapter=start_chapter,
            end_chapter=end_chapter,
        )
        if not scenes:
            return {
                "total_created": 0,
                "total_relations": 0,
                "total_aliases": 0,
                "total_deltas": 0,
                "total_scenes": 0,
                "degraded": False,
                "error_kind": None,
                "error_message": None,
                "failed_scene_indices": [],
                "completed_scenes": 0,
                "skipped_scenes": 0,
                "rerun_scenes": 0,
                "stopped_early": False,
                "checkpoints": {"phase2": {"scenes": []}},
            }

        from modules.world.facade import get_world_context

        ctx = await get_world_context(
            db,
            novel_id,
            reveal_mode="author_safe",
            limit=500,
        )
        existing_context = (
            "\n".join(
                f"- {e.name} ({e.entity_type})"
                for e in ctx.entities
                if e.status in ("canonical", "draft")
            )
            or "无已有对象"
        )

        total_created = 0
        total_relations = 0
        total_deltas = 0
        total_scenes = len(scenes)
        accumulated_memory: list[dict] = []
        seen_entity_keys: set[tuple[str, str]] = set()
        failed_scene_indices: list[int] = []
        failed_scene_ids: list[str] = []
        completed_scenes = 0
        skipped_scenes = 0
        rerun_scenes = 0
        stopped_early = False
        error_kind: str | None = None
        error_message: str | None = None
        checkpoint_by_scene = self._phase2_checkpoint_by_scene(existing_checkpoints)
        scene_checkpoints: list[dict[str, Any]] = []
        consecutive_transport_failures = 0
        structured_format_diagnostics: list[dict[str, Any]] = []

        if on_scene_progress is not None:
            await on_scene_progress(0, total_scenes)

        if (
            PHASE2_SMALL_SAMPLE_MIN_SCENES <= total_scenes <= PHASE2_BULK_MAX_SCENES
            and not checkpoint_by_scene
        ):
            return await self._process_scenes_parallel_llm(
                db,
                nid,
                scenes,
                existing_context,
                workflow_id=workflow_id,
                on_scene_progress=on_scene_progress,
                bulk_error_kind="small_sample_parallel_default",
            )

        if total_scenes <= PHASE2_BULK_MAX_SCENES and not checkpoint_by_scene:
            try:
                bulk_result = await self._process_scenes_bulk(
                    db,
                    nid,
                    scenes,
                    existing_context,
                    workflow_id=workflow_id,
                )
            except Exception as exc:
                bulk_error_kind = self._error_kind(exc)
                logger.warning(
                    "Bulk scene entity extraction failed; falling back to "
                    "parallel scene LLM extraction: %s",
                    exc,
                )
                parallel_result = await self._process_scenes_parallel_llm(
                    db,
                    nid,
                    scenes,
                    existing_context,
                    workflow_id=workflow_id,
                    on_scene_progress=on_scene_progress,
                    bulk_error_kind=bulk_error_kind,
                )
                if (
                    parallel_result["completed_scenes"] > 0
                    or parallel_result["failed_scene_indices"]
                ):
                    alias_result = await self._phase2_alias_relation_result(
                        db,
                        nid,
                        scenes,
                        workflow_id=workflow_id,
                        include_alias_relations=include_alias_relations,
                    )
                    return self._merge_alias_relation_result(
                        parallel_result,
                        alias_result,
                    )
            else:
                supplement_result = await self._supplement_small_sample_entities(
                    db,
                    nid,
                    scenes,
                    current_count=int(bulk_result.get("created", 0) or 0),
                    workflow_id=workflow_id,
                )
                if supplement_result["created"]:
                    bulk_result["created"] += supplement_result["created"]
                    bulk_result.setdefault("created_entity_ids", []).extend(
                        supplement_result["created_entity_ids"]
                    )
                checkpoints = [
                    self._build_scene_checkpoint(
                        scene,
                        status="done",
                        workflow_id=workflow_id,
                        scene_provenance_key=self._scene_provenance_key(
                            workflow_id,
                            scene,
                        ),
                        retry_count=0,
                        created_entity_ids=bulk_result.get("created_entity_ids", []),
                        created_relation_ids=bulk_result.get("created_relation_ids", []),
                        created_delta_ids=bulk_result.get("created_delta_ids", []),
                    )
                    for scene in scenes
                ]
                if on_scene_progress is not None:
                    await on_scene_progress(total_scenes, total_scenes)
                flush_status = await self._phase2_flush_with_timeout(db)
                audit_summary = await self._phase2_audit_summary(
                    db,
                    novel_id,
                    workflow_id=workflow_id,
                )
                snapshot_health_summary = await self._phase2_snapshot_health_summary(
                    db,
                    novel_id,
                    workflow_id=workflow_id,
                )
                phase2_result = {
                    "total_created": bulk_result["created"],
                    "total_relations": bulk_result["relations"],
                    "total_aliases": 0,
                    "total_deltas": bulk_result["deltas"],
                    "total_scenes": total_scenes,
                    "degraded": bool(
                        supplement_result["created"] or flush_status["degraded"]
                    ),
                    "error_kind": flush_status["error_kind"],
                    "error_message": flush_status["error_message"],
                    "failed_scene_indices": [],
                    "completed_scenes": total_scenes,
                    "skipped_scenes": 0,
                    "rerun_scenes": 0,
                    "stopped_early": False,
                    "audit_summary": audit_summary,
                    "snapshot_health_summary": snapshot_health_summary,
                    "checkpoints": {"phase2": {"scenes": checkpoints}},
                    "supplemental_llm_created": supplement_result[
                        "supplemental_llm_created"
                    ],
                    "fallback_created": supplement_result["fallback_created"],
                    "supplemental_error_kind": supplement_result[
                        "supplemental_error_kind"
                    ],
                    "structured_format_diagnostics": bulk_result.get(
                        "structured_format_diagnostics",
                        [],
                    ),
                }
                alias_result = await self._phase2_alias_relation_result(
                    db,
                    nid,
                    scenes,
                    workflow_id=workflow_id,
                    include_alias_relations=include_alias_relations,
                )
                return self._merge_alias_relation_result(phase2_result, alias_result)

        if total_scenes > PHASE2_BULK_MAX_SCENES and not checkpoint_by_scene:
            return await self._process_scenes_batched(
                db,
                nid,
                scenes,
                existing_context,
                workflow_id=workflow_id,
                on_scene_progress=on_scene_progress,
                include_alias_relations=include_alias_relations,
            )

        for scene_idx, scene in enumerate(scenes):
            scene_id = self._scene_id(scene)
            scene_provenance_key = self._scene_provenance_key(workflow_id, scene)
            existing_checkpoint = checkpoint_by_scene.get(scene_id)
            existing_status = (
                existing_checkpoint.get("status") if existing_checkpoint else None
            )
            existing_retry_count = self._checkpoint_retry_count(existing_checkpoint)
            retry_count = 0

            if existing_status == "done":
                skipped_scenes += 1
                scene_checkpoints.append(
                    self._build_scene_checkpoint(
                        scene,
                        status="skipped",
                        workflow_id=workflow_id,
                        scene_provenance_key=scene_provenance_key,
                        retry_count=existing_retry_count,
                        created_entity_ids=existing_checkpoint.get(
                            "created_entity_ids", []
                        ),
                        created_relation_ids=existing_checkpoint.get(
                            "created_relation_ids", []
                        ),
                        created_delta_ids=existing_checkpoint.get(
                            "created_delta_ids", []
                        ),
                    )
                )
                if on_scene_progress is not None:
                    await on_scene_progress(scene_idx + 1, total_scenes)
                continue

            if existing_status == "failed":
                if existing_retry_count >= MAX_PHASE2_SCENE_RETRIES:
                    skipped_scenes += 1
                    scene_checkpoints.append(
                        self._build_scene_checkpoint(
                            scene,
                            status="skipped",
                            workflow_id=workflow_id,
                            scene_provenance_key=scene_provenance_key,
                            retry_count=existing_retry_count,
                            error="retry_exhausted",
                            error_kind="retry_exhausted",
                        )
                    )
                    if on_scene_progress is not None:
                        await on_scene_progress(scene_idx + 1, total_scenes)
                    continue
                rerun_scenes += 1
                retry_count = existing_retry_count + 1

            try:
                scene_result = await self._process_scene(
                    db,
                    nid,
                    scene,
                    scene_idx,
                    existing_context,
                    accumulated_memory,
                    seen_entity_keys,
                    workflow_id=workflow_id,
                )
                total_created += scene_result["created"]
                total_relations += scene_result["relations"]
                total_deltas += scene_result["deltas"]
                structured_format_diagnostics.extend(
                    scene_result.get("structured_format_diagnostics") or []
                )
                existing_context = scene_result["updated_context"]
                accumulated_memory = scene_result["updated_memory"]
                completed_scenes += 1
                consecutive_transport_failures = 0
                scene_checkpoints.append(
                    self._build_scene_checkpoint(
                        scene,
                        status="done",
                        workflow_id=workflow_id,
                        scene_provenance_key=scene_provenance_key,
                        retry_count=retry_count,
                        created_entity_ids=scene_result.get("created_entity_ids", []),
                        created_relation_ids=scene_result.get(
                            "created_relation_ids", []
                        ),
                        created_delta_ids=scene_result.get("created_delta_ids", []),
                    )
                )
            except Exception as exc:
                scene_index_value = (
                    scene.get("scene_index")
                    if isinstance(scene, dict)
                    else getattr(scene, "scene_index", scene_idx)
                )
                failed_scene_indices.append(scene_index_value)
                failed_scene_ids.append(self._scene_id(scene))
                error_kind = self._error_kind(exc)
                error_message = str(exc)[:300]
                scene_checkpoints.append(
                    self._build_scene_checkpoint(
                        scene,
                        status="failed",
                        workflow_id=workflow_id,
                        scene_provenance_key=scene_provenance_key,
                        retry_count=retry_count + 1,
                        error=error_message,
                        error_kind=error_kind,
                    )
                )
                logger.warning(
                    "Scene idx=%d scene_index=%r extraction failed: %s",
                    scene_idx,
                    scene_index_value,
                    exc,
                )
                if self._is_transport_failure(exc):
                    consecutive_transport_failures += 1
                    if (
                        consecutive_transport_failures
                        < MAX_PHASE2_CONSECUTIVE_TRANSPORT_FAILURES
                    ):
                        if on_scene_progress is not None:
                            await on_scene_progress(scene_idx + 1, total_scenes)
                        continue
                    logger.warning(
                        "Stopping scene entity extraction after %d consecutive "
                        "transport failures; remaining scenes will be skipped.",
                        consecutive_transport_failures,
                    )
                    stopped_early = True
                    skipped_scenes += total_scenes - scene_idx - 1
                    for remaining_scene in scenes[scene_idx + 1 :]:
                        scene_checkpoints.append(
                            self._build_scene_checkpoint(
                                remaining_scene,
                                status="skipped",
                                workflow_id=workflow_id,
                                scene_provenance_key=self._scene_provenance_key(
                                    workflow_id,
                                    remaining_scene,
                                ),
                                retry_count=0,
                                error="stopped_after_transport_failure",
                                error_kind=error_kind,
                            )
                        )
                    if on_scene_progress is not None:
                        await on_scene_progress(total_scenes, total_scenes)
                    break
                if on_scene_progress is not None:
                    await on_scene_progress(scene_idx + 1, total_scenes)
                continue

            if on_scene_progress is not None:
                await on_scene_progress(scene_idx + 1, total_scenes)

        flush_status = await self._phase2_flush_with_timeout(db)
        audit_summary = await self._phase2_audit_summary(
            db,
            novel_id,
            workflow_id=workflow_id,
        )
        snapshot_health_summary = await self._phase2_snapshot_health_summary(
            db,
            novel_id,
            workflow_id=workflow_id,
        )
        phase2_result = {
            "total_created": total_created,
            "total_relations": total_relations,
            "total_aliases": 0,
            "total_deltas": total_deltas,
            "total_scenes": total_scenes,
            "degraded": bool(
                failed_scene_indices or stopped_early or flush_status["degraded"]
            ),
            "error_kind": error_kind or flush_status["error_kind"],
            "error_message": error_message or flush_status["error_message"],
            "failed_scene_indices": failed_scene_indices,
            "failed_scene_ids": failed_scene_ids,
            "completed_scenes": completed_scenes,
            "skipped_scenes": skipped_scenes,
            "rerun_scenes": rerun_scenes,
            "stopped_early": stopped_early,
            "audit_summary": audit_summary,
            "snapshot_health_summary": snapshot_health_summary,
            "checkpoints": {"phase2": {"scenes": scene_checkpoints}},
            "structured_format_diagnostics": structured_format_diagnostics[:20],
        }
        alias_result = await self._phase2_alias_relation_result(
            db,
            nid,
            scenes,
            workflow_id=workflow_id,
            include_alias_relations=include_alias_relations,
        )
        return self._merge_alias_relation_result(phase2_result, alias_result)


    # ------------------------------------------------------------------
    # Compatibility wrappers for existing tests and monkeypatches
    # ------------------------------------------------------------------

    @staticmethod
    def _is_transport_failure(exc: Exception) -> bool:
        return is_transport_failure(exc)

    @staticmethod
    def _error_kind(exc: Exception) -> str:
        return error_kind(exc)

    def _merge_alias_relation_result(
        self,
        phase2_result: dict[str, Any],
        alias_result: dict[str, Any],
    ) -> dict[str, Any]:
        return merge_alias_relation_result(self, phase2_result, alias_result)

    @staticmethod
    def _scene_id(scene: dict[str, Any]) -> str:
        return scene_id(scene)

    def _scene_provenance_key(
        self,
        workflow_id: str | None,
        scene: dict[str, Any],
    ) -> str:
        return scene_provenance_key(self, workflow_id, scene)

    @staticmethod
    def _checkpoint_retry_count(checkpoint: dict[str, Any] | None) -> int:
        return checkpoint_retry_count(checkpoint)

    def _phase2_checkpoint_by_scene(
        self,
        existing_checkpoints: dict[str, Any] | None,
    ) -> dict[str, dict[str, Any]]:
        return phase2_checkpoint_by_scene(existing_checkpoints)

    @staticmethod
    def _scene_index_value(scene: dict[str, Any], fallback: int = 0) -> int:
        if isinstance(scene, dict):
            raw_value = scene.get("scene_index")
        else:
            raw_value = getattr(scene, "scene_index", None)
        try:
            scene_index = int(raw_value or 0)
        except (TypeError, ValueError):
            scene_index = 0
        return scene_index if scene_index > 0 else fallback

    @staticmethod
    def _phase2_batch_size_scenes() -> int:
        return _phase2_config.phase2_batch_size_scenes()

    @staticmethod
    def _phase2_batch_concurrency() -> int:
        return _phase2_config.phase2_batch_concurrency()

    @classmethod
    def _split_scene_batches(
        cls,
        scenes: list[dict[str, Any]],
        *,
        batch_size: int | None = None,
    ) -> list[list[dict[str, Any]]]:
        ordered = sorted(scenes, key=cls._scene_index_value)
        size = max(1, int(batch_size or _phase2_config.phase2_batch_size_scenes()))
        return [ordered[index : index + size] for index in range(0, len(ordered), size)]

    @staticmethod
    def _phase2_boundary_windows(
        batches: list[list[dict[str, Any]]],
        *,
        boundary_size: int | None = None,
    ) -> list[dict[str, Any]]:
        size = max(1, int(boundary_size or _phase2_config.phase2_boundary_scenes()))
        windows: list[dict[str, Any]] = []
        for index in range(len(batches) - 1):
            scenes = [*batches[index][-size:], *batches[index + 1][:size]]
            if not scenes:
                continue
            windows.append(
                {
                    "window_index": len(windows),
                    "left_batch_index": index,
                    "right_batch_index": index + 1,
                    "scenes": scenes,
                }
            )
        return windows

    @staticmethod
    def _empty_phase2_persistence_stats() -> dict[str, Any]:
        return {
            "action_counts": {
                "create_new": 0,
                "link_to_existing": 0,
                "ignore": 0,
                "temporary_only": 0,
            },
            "dedup_counts": {
                "checked": 0,
                "skipped": 0,
                "degraded": 0,
                "auto_merged": 0,
                "candidate_created": 0,
                "review_suggested": 0,
                "relation_merged": 0,
                "relation_duplicate_skipped": 0,
            },
            "linked_to_existing": 0,
            "ignored": 0,
            "temporary_only": 0,
            "low_confidence": 0,
        }

    @staticmethod
    def _merge_phase2_persistence_stats(
        target: dict[str, Any],
        source: dict[str, Any],
    ) -> dict[str, Any]:
        for key, value in (source.get("action_counts") or {}).items():
            target.setdefault("action_counts", {}).setdefault(key, 0)
            target["action_counts"][key] += int(value or 0)
        for key, value in (source.get("dedup_counts") or {}).items():
            target.setdefault("dedup_counts", {}).setdefault(key, 0)
            target["dedup_counts"][key] += int(value or 0)
        for key in ("linked_to_existing", "ignored", "temporary_only", "low_confidence"):
            target[key] = int(target.get(key, 0) or 0) + int(source.get(key, 0) or 0)
        return target

    def _build_scene_checkpoint(
        self,
        scene: dict[str, Any],
        *,
        status: str,
        workflow_id: str | None,
        scene_provenance_key: str,
        retry_count: int,
        created_entity_ids: list[str] | None = None,
        created_relation_ids: list[str] | None = None,
        created_delta_ids: list[str] | None = None,
        error: str | None = None,
        error_kind: str | None = None,
    ) -> dict[str, Any]:
        return build_scene_checkpoint(
            self,
            scene,
            status=status,
            workflow_id=workflow_id,
            scene_provenance_key=scene_provenance_key,
            retry_count=retry_count,
            created_entity_ids=created_entity_ids,
            created_relation_ids=created_relation_ids,
            created_delta_ids=created_delta_ids,
            error=error,
            error_kind=error_kind,
        )

    async def _get_scenes(self, db: AsyncSession, nid) -> list[dict[str, Any]]:
        return await get_scenes(db, nid)

    def _filter_scenes_by_range(
        self,
        scenes: list[dict[str, Any]],
        *,
        start_chapter: int | None = None,
        end_chapter: int | None = None,
    ) -> list[dict[str, Any]]:
        return filter_scenes_by_range(
            self,
            scenes,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
        )

    def _scene_overlaps_chapter_range(
        self,
        scene: dict[str, Any],
        *,
        start_chapter: int | None = None,
        end_chapter: int | None = None,
    ) -> bool:
        return scene_overlaps_chapter_range(
            scene,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
        )

    async def _process_scene(
        self,
        db: AsyncSession,
        nid,
        scene: dict[str, Any],
        scene_idx: int,
        existing_context: str,
        accumulated_memory: list[dict],
        seen_entity_keys: set[tuple[str, str]],
        workflow_id: str | None = None,
        persistence_stats: dict[str, Any] | None = None,
        db_lock: asyncio.Lock | None = None,
    ) -> dict[str, Any]:
        return await SingleSceneEntityExtractor(self).process(
            db,
            nid,
            scene,
            scene_idx,
            existing_context,
            accumulated_memory,
            seen_entity_keys,
            workflow_id=workflow_id,
            persistence_stats=persistence_stats,
            db_lock=db_lock,
        )

    async def _process_scenes_batched(
        self,
        db: AsyncSession,
        nid,
        scenes: list[dict[str, Any]],
        existing_context: str,
        *,
        workflow_id: str | None,
        on_scene_progress: Callable[[int, int], Awaitable[None]] | None,
        include_alias_relations: bool = True,
    ) -> dict[str, Any]:
        batch_size = self._phase2_batch_size_scenes()
        batch_concurrency = self._phase2_batch_concurrency()
        batches = self._split_scene_batches(scenes, batch_size=batch_size)
        semaphore = asyncio.Semaphore(batch_concurrency)
        progress_lock = asyncio.Lock()
        db_lock = asyncio.Lock()
        completed_counter = {"value": 0}
        total_scenes = len(scenes)

        async def run_batch(
            batch_index: int,
            batch: list[dict[str, Any]],
        ) -> dict[str, Any]:
            async with semaphore:
                return await self._process_scene_batch_serial(
                    db,
                    nid,
                    batch,
                    batch_index=batch_index,
                    existing_context=existing_context,
                    workflow_id=workflow_id,
                    completed_counter=completed_counter,
                    progress_lock=progress_lock,
                    db_lock=db_lock,
                    total_scenes=total_scenes,
                    on_scene_progress=on_scene_progress,
                )

        batch_results = await asyncio.gather(
            *(run_batch(index, batch) for index, batch in enumerate(batches)),
            return_exceptions=True,
        )

        total_created = 0
        total_relations = 0
        total_deltas = 0
        failed_scene_indices: list[int] = []
        failed_scene_ids: list[str] = []
        scene_checkpoints: list[dict[str, Any]] = []
        failed_batches: list[int] = []
        degraded_batches: list[int] = []
        error_kind: str | None = None
        error_message: str | None = None
        persistence_stats = self._empty_phase2_persistence_stats()

        for batch_index, result in enumerate(batch_results):
            if isinstance(result, Exception):
                failed_batches.append(batch_index)
                degraded_batches.append(batch_index)
                error_kind = self._error_kind(result)
                error_message = str(result)[:300]
                for scene_position, scene in enumerate(batches[batch_index]):
                    failed_scene_indices.append(
                        self._scene_index_value(
                            scene,
                            fallback=batch_index * batch_size + scene_position + 1,
                        )
                    )
                    failed_scene_ids.append(self._scene_id(scene))
                    scene_checkpoints.append(
                        self._build_scene_checkpoint(
                            scene,
                            status="failed",
                            workflow_id=workflow_id,
                            scene_provenance_key=self._scene_provenance_key(
                                workflow_id,
                                scene,
                            ),
                            retry_count=1,
                            error=error_message,
                            error_kind=error_kind,
                        )
                    )
                continue

            total_created += int(result.get("created", 0) or 0)
            total_relations += int(result.get("relations", 0) or 0)
            total_deltas += int(result.get("deltas", 0) or 0)
            failed_scene_indices.extend(result.get("failed_scene_indices") or [])
            failed_scene_ids.extend(result.get("failed_scene_ids") or [])
            scene_checkpoints.extend(result.get("checkpoints") or [])
            self._merge_phase2_persistence_stats(
                persistence_stats,
                result.get("persistence_stats")
                or self._empty_phase2_persistence_stats(),
            )
            if result.get("degraded"):
                degraded_batches.append(batch_index)
            if result.get("error_kind"):
                error_kind = result.get("error_kind")
                error_message = result.get("error_message")

        scene_checkpoints.sort(
            key=lambda checkpoint: int(checkpoint.get("scene_index") or 0),
        )

        boundary_result = await self._run_boundary_supplements(
            db,
            nid,
            batches,
            workflow_id=workflow_id,
        )
        total_created += int(
            boundary_result["phase2_boundary_supplement_counts"].get("created", 0)
            or 0
        )

        flush_status = await self._phase2_flush_with_timeout(db)
        audit_summary = await self._phase2_audit_summary(
            db,
            str(nid),
            workflow_id=workflow_id,
        )
        snapshot_health_summary = await self._phase2_snapshot_health_summary(
            db,
            str(nid),
            workflow_id=workflow_id,
        )
        phase2_result = {
            "total_created": total_created,
            "total_relations": total_relations,
            "total_aliases": 0,
            "total_deltas": total_deltas,
            "total_scenes": total_scenes,
            "degraded": bool(
                failed_scene_indices
                or degraded_batches
                or boundary_result.get("degraded")
                or flush_status["degraded"]
            ),
            "error_kind": (
                error_kind
                or boundary_result.get("error_kind")
                or flush_status["error_kind"]
            ),
            "error_message": (
                error_message
                or boundary_result.get("error_message")
                or flush_status["error_message"]
            ),
            "failed_scene_indices": failed_scene_indices,
            "failed_scene_ids": failed_scene_ids,
            "completed_scenes": total_scenes - len(failed_scene_indices),
            "skipped_scenes": 0,
            "rerun_scenes": 0,
            "stopped_early": False,
            "audit_summary": audit_summary,
            "snapshot_health_summary": snapshot_health_summary,
            "checkpoints": {"phase2": {"scenes": scene_checkpoints}},
            "phase2_batches_total": len(batches),
            "phase2_batches_completed": len(batches) - len(failed_batches),
            "phase2_batch_size_scenes": batch_size,
            "phase2_batch_concurrency": batch_concurrency,
            "phase2_failed_batches": failed_batches,
            "phase2_degraded_batches": degraded_batches,
            "phase2_boundary_windows_total": boundary_result[
                "phase2_boundary_windows_total"
            ],
            "phase2_boundary_windows_completed": boundary_result[
                "phase2_boundary_windows_completed"
            ],
            "phase2_boundary_supplement_counts": boundary_result[
                "phase2_boundary_supplement_counts"
            ],
            "phase2_action_counts": persistence_stats["action_counts"],
            "phase2_dedup_counts": persistence_stats["dedup_counts"],
            "phase2_linked_to_existing": persistence_stats["linked_to_existing"],
            "phase2_ignored": persistence_stats["ignored"],
            "phase2_temporary_only": persistence_stats["temporary_only"],
            "phase2_low_confidence": persistence_stats["low_confidence"],
        }
        alias_result = await self._phase2_alias_relation_result(
            db,
            nid,
            scenes,
            workflow_id=workflow_id,
            include_alias_relations=include_alias_relations,
        )
        return self._merge_alias_relation_result(phase2_result, alias_result)

    async def _process_scene_batch_serial(
        self,
        db: AsyncSession,
        nid,
        batch: list[dict[str, Any]],
        *,
        batch_index: int,
        existing_context: str,
        workflow_id: str | None,
        completed_counter: dict[str, int],
        progress_lock: asyncio.Lock,
        db_lock: asyncio.Lock,
        total_scenes: int,
        on_scene_progress: Callable[[int, int], Awaitable[None]] | None,
    ) -> dict[str, Any]:
        local_context = existing_context
        local_memory: list[dict[str, Any]] = []
        seen_entity_keys: set[tuple[str, str]] = set()
        created = 0
        relations = 0
        deltas = 0
        failed_scene_indices: list[int] = []
        failed_scene_ids: list[str] = []
        checkpoints: list[dict[str, Any]] = []
        error_kind_value: str | None = None
        error_message: str | None = None
        persistence_stats = self._empty_phase2_persistence_stats()

        for scene_idx, scene in enumerate(batch):
            scene_provenance_key = self._scene_provenance_key(workflow_id, scene)
            retry_count = 0
            try:
                scene_result = await self._process_scene(
                    db,
                    nid,
                    scene,
                    scene_idx,
                    local_context,
                    local_memory,
                    seen_entity_keys,
                    workflow_id=workflow_id,
                    persistence_stats=persistence_stats,
                    db_lock=db_lock,
                )
            except Exception as exc:
                error_kind_value = self._error_kind(exc)
                error_message = str(exc)[:300]
                failed_scene_indices.append(
                    self._scene_index_value(
                        scene,
                        fallback=batch_index
                        * max(1, _phase2_config.phase2_batch_size_scenes())
                        + scene_idx
                        + 1,
                    )
                )
                failed_scene_ids.append(self._scene_id(scene))
                checkpoints.append(
                    self._build_scene_checkpoint(
                        scene,
                        status="failed",
                        workflow_id=workflow_id,
                        scene_provenance_key=scene_provenance_key,
                        retry_count=retry_count + 1,
                        error=error_message,
                        error_kind=error_kind_value,
                    )
                )
            else:
                created += int(scene_result.get("created", 0) or 0)
                relations += int(scene_result.get("relations", 0) or 0)
                deltas += int(scene_result.get("deltas", 0) or 0)
                local_context = scene_result.get("updated_context") or local_context
                local_memory = scene_result.get("updated_memory") or local_memory
                checkpoint = scene_result.get("checkpoint")
                if checkpoint is not None:
                    checkpoints.append(checkpoint)
                else:
                    checkpoints.append(
                        self._build_scene_checkpoint(
                            scene,
                            status="done",
                            workflow_id=workflow_id,
                            scene_provenance_key=scene_provenance_key,
                            retry_count=retry_count,
                            created_entity_ids=scene_result.get(
                                "created_entity_ids",
                                [],
                            ),
                            created_relation_ids=scene_result.get(
                                "created_relation_ids",
                                [],
                            ),
                            created_delta_ids=scene_result.get(
                                "created_delta_ids",
                                [],
                            ),
                        )
                    )

            async with progress_lock:
                completed_counter["value"] += 1
                completed = completed_counter["value"]
            if on_scene_progress is not None:
                async with db_lock:
                    await on_scene_progress(completed, total_scenes)

        return {
            "batch_index": batch_index,
            "created": created,
            "relations": relations,
            "deltas": deltas,
            "failed_scene_indices": failed_scene_indices,
            "failed_scene_ids": failed_scene_ids,
            "checkpoints": checkpoints,
            "degraded": bool(failed_scene_indices),
            "error_kind": error_kind_value,
            "error_message": error_message,
            "persistence_stats": persistence_stats,
        }

    async def _run_boundary_supplements(
        self,
        db: AsyncSession,
        nid,
        batches: list[list[dict[str, Any]]],
        *,
        workflow_id: str | None,
    ) -> dict[str, Any]:
        windows = self._phase2_boundary_windows(batches)
        if not _phase2_config.phase2_boundary_supplement_enabled():
            return {
                "phase2_boundary_windows_total": len(windows),
                "phase2_boundary_windows_completed": 0,
                "phase2_boundary_supplement_counts": {
                    "created": 0,
                    "aliases": 0,
                    "relations": 0,
                    "link_suggestions": 0,
                    "conflicts": 0,
                    "failed": 0,
                },
                "degraded": False,
                "error_kind": None,
                "error_message": None,
                "phase2_boundary_elapsed_s": 0.0,
                "phase2_boundary_total_timeout_s": (
                    _phase2_config.phase2_boundary_total_timeout_seconds()
                ),
                "phase2_boundary_skipped": True,
                "phase2_boundary_skip_reason": "disabled",
            }
        started_at = time.monotonic()
        total_timeout_seconds = _phase2_config.phase2_boundary_total_timeout_seconds()
        counts = {
            "created": 0,
            "aliases": 0,
            "relations": 0,
            "link_suggestions": 0,
            "conflicts": 0,
            "failed": 0,
        }
        completed = 0
        error_kind_value: str | None = None
        error_message: str | None = None

        for window_index, window in enumerate(windows):
            remaining_s = total_timeout_seconds - (time.monotonic() - started_at)
            if remaining_s <= 0:
                counts["failed"] += len(windows) - window_index
                error_kind_value = "timeout"
                error_message = (
                    "Phase 2 boundary supplement exceeded total timeout "
                    f"budget ({total_timeout_seconds}s)"
                )
                break
            try:
                result = await asyncio.wait_for(
                    self._process_boundary_window(
                        db,
                        nid,
                        window,
                        workflow_id=workflow_id,
                    ),
                    timeout=remaining_s,
                )
            except Exception as exc:
                counts["failed"] += 1
                error_kind_value = self._error_kind(exc)
                error_message = str(exc)[:300]
                continue
            completed += 1
            counts["created"] += int(result.get("created", 0) or 0)
            counts["aliases"] += int(result.get("aliases", 0) or 0)
            counts["relations"] += int(result.get("relations", 0) or 0)
            counts["link_suggestions"] += int(result.get("link_suggestions", 0) or 0)
            counts["conflicts"] += int(result.get("conflicts", 0) or 0)
            if result.get("failed"):
                counts["failed"] += 1

        return {
            "phase2_boundary_windows_total": len(windows),
            "phase2_boundary_windows_completed": completed,
            "phase2_boundary_supplement_counts": counts,
            "degraded": counts["failed"] > 0,
            "error_kind": error_kind_value,
            "error_message": error_message,
            "phase2_boundary_elapsed_s": round(time.monotonic() - started_at, 2),
            "phase2_boundary_total_timeout_s": total_timeout_seconds,
        }

    async def _process_boundary_window(
        self,
        db: AsyncSession,
        nid,
        window: dict[str, Any],
        *,
        workflow_id: str | None,
    ) -> dict[str, Any]:
        scenes = window["scenes"]
        entity_result = await self._process_scenes_bulk(
            db,
            nid,
            scenes,
            "边界补充：仅补相邻 batch 边界漏抽对象，不重写主 batch 结果。",
            workflow_id=workflow_id,
        )
        return {
            "created": int(entity_result.get("created", 0) or 0),
            "aliases": 0,
            "relations": 0,
            "link_suggestions": 0,
            "conflicts": 0,
            "failed": False,
        }

    async def _process_scenes_parallel_llm(
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
        return await ParallelSceneEntityExtractor(self).run(
            db,
            nid,
            scenes,
            existing_context,
            workflow_id=workflow_id,
            on_scene_progress=on_scene_progress,
            bulk_error_kind=bulk_error_kind,
        )

    async def _process_scenes_bulk(
        self,
        db: AsyncSession,
        nid,
        scenes: list[dict[str, Any]],
        existing_context: str,
        *,
        workflow_id: str | None = None,
    ) -> dict[str, Any]:
        return await BulkSceneEntityExtractor(self).run(
            db,
            nid,
            scenes,
            existing_context,
            workflow_id=workflow_id,
        )

    async def _supplement_small_sample_entities(
        self,
        db: AsyncSession,
        nid,
        scenes: list[dict[str, Any]],
        *,
        current_count: int,
        workflow_id: str | None,
    ) -> dict[str, Any]:
        return await BulkSceneEntityExtractor(self).supplement_small_sample(
            db,
            nid,
            scenes,
            current_count=current_count,
            workflow_id=workflow_id,
        )

    async def _supplement_small_sample_entities_with_llm(
        self,
        db: AsyncSession,
        nid,
        scenes: list[dict[str, Any]],
        *,
        needed: int,
        workflow_id: str | None,
    ) -> dict[str, Any]:
        return await BulkSceneEntityExtractor(self).supplement_with_llm(
            db,
            nid,
            scenes,
            needed=needed,
            workflow_id=workflow_id,
        )

    async def _load_small_sample_chapters_text(
        self,
        db: AsyncSession,
        scenes: list[dict[str, Any]],
    ) -> str:
        return await load_small_sample_chapters_text(self, db, scenes)

    @staticmethod
    def _trim_supplement_chapter_text(content: str) -> str:
        return trim_supplement_chapter_text(content)

    @staticmethod
    def _small_sample_chapter_indices(scenes: list[dict[str, Any]]) -> list[int]:
        return small_sample_chapter_indices(scenes)

    @staticmethod
    def _fallback_entity_label(entity_type: str) -> str:
        return fallback_entity_label(entity_type)

    async def _call_bulk_llm_extractions(
        self,
        scene_texts: list[str],
        existing_context: str,
        memory_context: str,
        *,
        diagnostics: list[dict[str, Any]] | None = None,
    ) -> list[SceneEntityExtractionOutput]:
        return await BulkSceneEntityExtractor(self).call_bulk_llm_extractions(
            scene_texts,
            existing_context,
            memory_context,
            diagnostics=diagnostics,
        )

    @staticmethod
    def _bulk_entity_memory_context(scenes: list[dict[str, Any]]) -> str:
        return bulk_entity_memory_context(scenes)

    @staticmethod
    def _result_ref_ids(result_refs: list[dict[str, str]], result_type: str) -> list[str]:
        return result_ref_ids(result_refs, result_type)

    async def _create_phase2_snapshot(
        self,
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
        return await create_phase2_snapshot(
            self,
            db,
            nid,
            scene,
            source_chapter_index,
            chapters_text,
            existing_context,
            memory_context,
            accumulated_memory,
            workflow_id=workflow_id,
        )

    async def _phase2_audit_summary(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        workflow_id: str | None,
    ) -> dict[str, Any]:
        return await self._phase2_postprocess_with_timeout(
            "audit_summary",
            phase2_audit_summary(
                self,
                db,
                novel_id,
                workflow_id=workflow_id,
            ),
            fallback={
                "entity_extraction": {
                    "snapshot_count": 0,
                    "succeeded": 0,
                    "failed": 0,
                    "failed_scenes": [],
                    "retained_rendered_context_count": 0,
                    "rendered_context_expires_at": [],
                    "degraded": True,
                }
            },
        )

    async def _phase2_snapshot_health_summary(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        workflow_id: str | None,
    ) -> dict[str, Any]:
        return await self._phase2_postprocess_with_timeout(
            "snapshot_health_summary",
            phase2_snapshot_health_summary(
                self,
                db,
                novel_id,
                workflow_id=workflow_id,
            ),
            fallback={"degraded": True},
        )

    async def _phase2_postprocess_with_timeout(
        self,
        label: str,
        operation: Awaitable[dict[str, Any]],
        *,
        fallback: dict[str, Any],
    ) -> dict[str, Any]:
        timeout_seconds = _phase2_config.phase2_postprocess_timeout_seconds()
        try:
            return await asyncio.wait_for(operation, timeout=timeout_seconds)
        except TimeoutError:
            error_message = (
                f"Phase 2 {label} exceeded postprocess timeout "
                f"({timeout_seconds}s)"
            )
            logger.warning(error_message)
            return {
                **fallback,
                "error_kind": "timeout",
                "error_message": error_message,
            }
        except Exception as exc:
            error_kind_value = self._error_kind(exc)
            error_message = str(exc)[:300]
            logger.warning("Phase 2 %s failed: %s", label, exc)
            return {
                **fallback,
                "error_kind": error_kind_value,
                "error_message": error_message,
            }

    async def _phase2_flush_with_timeout(self, db: AsyncSession) -> dict[str, Any]:
        timeout_seconds = _phase2_config.phase2_postprocess_timeout_seconds()
        try:
            await asyncio.wait_for(db.flush(), timeout=timeout_seconds)
            return {"degraded": False, "error_kind": None, "error_message": None}
        except TimeoutError:
            error_message = (
                "Phase 2 db.flush exceeded postprocess timeout "
                f"({timeout_seconds}s)"
            )
            logger.warning(error_message)
            return {
                "degraded": True,
                "error_kind": "timeout",
                "error_message": error_message,
            }
        except Exception as exc:
            error_kind_value = self._error_kind(exc)
            error_message = str(exc)[:300]
            logger.warning("Phase 2 db.flush failed: %s", exc)
            return {
                "degraded": True,
                "error_kind": error_kind_value,
                "error_message": error_message,
            }

    @staticmethod
    def _scene_source_chapter_index(scene: dict[str, Any]) -> int:
        return scene_source_chapter_index(scene)

    async def _load_scene_chapters(self, db: AsyncSession, scene: dict[str, Any]) -> str:
        return await load_scene_chapters(self, db, scene)

    @staticmethod
    def _phase2_scene_llm_timeout_seconds() -> int:
        return phase2_scene_llm_timeout_seconds()

    @staticmethod
    def _scene_context_header(scene: dict[str, Any]) -> str:
        return scene_context_header(scene)

    @staticmethod
    def _scene_chunks_by_chapter(
        scene: dict[str, Any],
    ) -> dict[int, list[dict[str, Any]]]:
        return scene_chunks_by_chapter(scene)

    @staticmethod
    def _scene_chapter_ids(
        scene: dict[str, Any],
        chunk_by_chapter: dict[int, list[dict[str, Any]]],
    ) -> list[str]:
        return scene_chapter_ids(scene, chunk_by_chapter)

    @staticmethod
    def _select_scene_text(
        chapter_text: str,
        chunks: list[dict[str, Any]],
    ) -> str:
        return select_scene_text(chapter_text, chunks)

    @staticmethod
    def _build_memory_context(memory: list[dict]) -> str:
        return build_memory_context(memory)

    @staticmethod
    def _parallel_scene_memory_context(scene: dict[str, Any], scene_idx: int) -> str:
        return parallel_scene_memory_context(scene, scene_idx)

    @staticmethod
    def _append_extracted_entities_to_context(
        existing_context: str,
        extraction: SceneEntityExtractionOutput,
    ) -> str:
        return append_extracted_entities_to_context(existing_context, extraction)

    async def _call_llm_extraction(
        self,
        chapters_text: str,
        existing_context: str,
        memory_context: str,
        *,
        max_tokens: int = 8192,
        client_timeout: int = 180,
        max_fix_attempts: int = 1,
        transport_retries: bool = True,
        diagnostics: list[dict[str, Any]] | None = None,
    ) -> SceneEntityExtractionOutput:
        return await call_llm_extraction(
            chapters_text,
            existing_context,
            memory_context,
            max_tokens=max_tokens,
            client_timeout=client_timeout,
            max_fix_attempts=max_fix_attempts,
            transport_retries=transport_retries,
            diagnostics=diagnostics,
        )

    async def _call_alias_relation_extraction(
        self,
        chapters_text: str,
        entity_index: str,
        *,
        max_tokens: int = 3072,
        client_timeout: int = 120,
        diagnostics: list[dict[str, Any]] | None = None,
    ) -> AliasRelationExtractionOutput:
        return await call_alias_relation_extraction(
            chapters_text,
            entity_index,
            max_tokens=max_tokens,
            client_timeout=client_timeout,
            diagnostics=diagnostics,
        )

    async def _phase2_alias_relation_result(
        self,
        db: AsyncSession,
        nid,
        scenes: list[dict[str, Any]],
        *,
        workflow_id: str | None = None,
        include_alias_relations: bool = True,
    ) -> dict[str, Any]:
        if not include_alias_relations:
            return self._skipped_alias_relation_result(
                len(scenes),
                reason="phase2a_only",
            )
        return await self._run_optional_alias_relation_phase(
            db,
            nid,
            scenes,
            workflow_id=workflow_id,
        )

    @staticmethod
    def _skipped_alias_relation_result(
        scene_count: int,
        *,
        reason: str,
    ) -> dict[str, Any]:
        concurrency = _phase2_config.phase2_alias_relation_concurrency()
        total_timeout_seconds = _effective_alias_relation_total_timeout_seconds(
            scene_count=scene_count,
            concurrency=concurrency,
            configured_timeout_seconds=(
                _phase2_config.phase2_alias_relation_total_timeout_seconds()
            ),
        )
        return {
            "total_aliases": 0,
            "total_relations": 0,
            "alias_relation_scenes": 0,
            "alias_relation_failed_scenes": [],
            "degraded": False,
            "error_kind": None,
            "error_message": None,
            "alias_relation_elapsed_s": 0.0,
            "alias_relation_total_timeout_s": total_timeout_seconds,
            "alias_relation_concurrency": concurrency,
            "alias_relation_skipped": True,
            "alias_relation_skip_reason": reason,
        }

    async def _run_optional_alias_relation_phase(
        self,
        db: AsyncSession,
        nid,
        scenes: list[dict[str, Any]],
        *,
        workflow_id: str | None = None,
    ) -> dict[str, Any]:
        if _phase2_config.phase2_alias_relation_supplement_enabled():
            return await self._run_alias_relation_phase(
                db,
                nid,
                scenes,
                workflow_id=workflow_id,
            )
        return self._skipped_alias_relation_result(
            len(scenes),
            reason="phase2_alias_relation_supplement_disabled",
        )

    async def _run_alias_relation_phase(
        self,
        db: AsyncSession,
        nid,
        scenes: list[dict[str, Any]],
        *,
        workflow_id: str | None = None,
        on_scene_progress: Callable[[int, int], Awaitable[None]] | None = None,
        existing_checkpoints: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        started_at = time.monotonic()
        concurrency = _phase2_config.phase2_alias_relation_concurrency()
        total_timeout_seconds = _effective_alias_relation_total_timeout_seconds(
            scene_count=len(scenes),
            concurrency=concurrency,
            configured_timeout_seconds=(
                _phase2_config.phase2_alias_relation_total_timeout_seconds()
            ),
        )
        watchdog_seconds = (
            total_timeout_seconds + PHASE2_SCENE_TIMEOUT_GRACE_SECONDS
        )
        try:
            return await asyncio.wait_for(
                AliasRelationExtractor(self).run(
                    db,
                    nid,
                    scenes,
                    workflow_id=workflow_id,
                    on_scene_progress=on_scene_progress,
                    existing_checkpoints=existing_checkpoints,
                ),
                timeout=watchdog_seconds,
            )
        except TimeoutError:
            error_message = (
                "Phase 2b alias/relation extraction exceeded watchdog budget "
                f"({watchdog_seconds}s)"
            )
            logger.warning(error_message)
            return {
                "total_aliases": 0,
                "total_relations": 0,
                "alias_relation_scenes": 0,
                "alias_relation_failed_scenes": [
                    _alias_relation_failure_scene_index(scene, position + 1)
                    for position, scene in enumerate(scenes)
                ],
                "degraded": True,
                "error_kind": "timeout",
                "error_message": error_message,
                "alias_relation_elapsed_s": round(time.monotonic() - started_at, 2),
                "alias_relation_total_timeout_s": total_timeout_seconds,
                "alias_relation_concurrency": concurrency,
            }

    async def _build_alias_relation_entity_index(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> str:
        return await AliasRelationExtractor(self).build_entity_index(db, novel_id)

    async def _create_phase2b_snapshot(
        self,
        db: AsyncSession,
        nid,
        scene: dict[str, Any],
        chapters_text: str,
        entity_index: str,
        *,
        workflow_id: str | None = None,
    ):
        return await create_phase2b_snapshot(
            self,
            db,
            nid,
            scene,
            chapters_text,
            entity_index,
            workflow_id=workflow_id,
        )

    async def _persist_alias_relation_output(
        self,
        db: AsyncSession,
        novel_id: str,
        output: AliasRelationExtractionOutput,
        *,
        scene_index: int,
        workflow_id: str | None = None,
        scene_id: str | None = None,
        result_refs: list[dict[str, str]] | None = None,
    ) -> dict[str, int]:
        return await SceneEntityPersistenceGateway(self).persist_alias_relation_output(
            db,
            novel_id,
            output,
            scene_index=scene_index,
            workflow_id=workflow_id,
            scene_id=scene_id,
            result_refs=result_refs,
        )

    async def _persist_entities(
        self,
        db: AsyncSession,
        nid,
        entities: list[ExtractedEntity],
        scene_index: int,
        source_chapter_index: int,
        seen_entity_keys: set[tuple[str, str]] | None = None,
        workflow_id: str | None = None,
        scene_id: str | None = None,
        scene_provenance_key: str | None = None,
        context_snapshot_id: str | None = None,
        result_refs: list[dict[str, str]] | None = None,
        persistence_stats: dict[str, Any] | None = None,
    ) -> int:
        return await SceneEntityPersistenceGateway(self).persist_entities(
            db,
            nid,
            entities,
            scene_index,
            source_chapter_index,
            seen_entity_keys=seen_entity_keys,
            workflow_id=workflow_id,
            scene_id=scene_id,
            scene_provenance_key=scene_provenance_key,
            context_snapshot_id=context_snapshot_id,
            result_refs=result_refs,
            persistence_stats=persistence_stats,
        )

    @staticmethod
    def _entity_key(entity_type: str, name: str) -> tuple[str, str]:
        return entity_key(entity_type, name)

    async def _persist_relations(
        self,
        db: AsyncSession,
        nid,
        relations: list[ExtractedRelation],
        scene_index: int,
        workflow_id: str | None = None,
        context_snapshot_id: str | None = None,
        result_refs: list[dict[str, str]] | None = None,
        persistence_stats: dict[str, Any] | None = None,
    ) -> int:
        return await SceneEntityPersistenceGateway(self).persist_relations(
            db,
            nid,
            relations,
            scene_index,
            workflow_id=workflow_id,
            context_snapshot_id=context_snapshot_id,
            result_refs=result_refs,
            persistence_stats=persistence_stats,
        )

    async def _record_deltas(
        self,
        db: AsyncSession,
        nid,
        delta_events: list[DeltaEvent],
        scene_index: int,
        workflow_id: str | None = None,
        scene_id: str | None = None,
        scene_provenance_key: str | None = None,
        context_snapshot_id: str | None = None,
        result_refs: list[dict[str, str]] | None = None,
    ) -> int:
        return await SceneEntityPersistenceGateway(self).record_deltas(
            db,
            nid,
            delta_events,
            scene_index,
            workflow_id=workflow_id,
            scene_id=scene_id,
            scene_provenance_key=scene_provenance_key,
            context_snapshot_id=context_snapshot_id,
            result_refs=result_refs,
        )
