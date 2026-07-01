"""SceneEntityExtractionService -- Phase 2: 按 Scene 串行增量提取实体、关系与 Delta。"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.errors import (
    LLMConnectionError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from modules.imports.context_snapshot_helpers import (
    build_phase2_snapshot_payload,
    build_result_ref,
)
from modules.imports.llm_schemas import (
    AliasRelationExtractionOutput,
    DeltaEvent,
    ExtractedEntity,
    ExtractedRelation,
    SceneEntityExtractionOutput,
)
from shared.utils import parse_uuid

logger = logging.getLogger(__name__)

MAX_PHASE2_SCENE_RETRIES = 3
MAX_PHASE2_CONSECUTIVE_TRANSPORT_FAILURES = 3
PHASE2_SCENE_TIMEOUT_GRACE_SECONDS = 15
PHASE2_BULK_MAX_SCENES = 12
PHASE2_BULK_GROUP_SIZE = 1
PHASE2_BULK_LLM_TIMEOUT_SECONDS = 60
PHASE2_BULK_PROVIDER_TIMEOUT_SECONDS = 45
PHASE2_BULK_MAX_TOKENS = 4096
PHASE2_PARALLEL_SCENE_CONCURRENCY = 4
PHASE2_PARALLEL_PROVIDER_TIMEOUT_SECONDS = 120
PHASE2_PARALLEL_LLM_TIMEOUT_SECONDS = 135
PHASE2_SMALL_SAMPLE_MIN_SCENES = 8
PHASE2_SMALL_SAMPLE_MIN_ENTITIES = 18
PHASE2_SMALL_SAMPLE_TARGET_ENTITIES = 29
PHASE2_SMALL_SAMPLE_SUPPLEMENT_TIMEOUT_SECONDS = 90
PHASE2_SMALL_SAMPLE_SUPPLEMENT_CHAPTER_CHAR_LIMIT = 4200
PHASE2_SMALL_SAMPLE_SUPPLEMENT_TOTAL_CHAR_LIMIT = 36000


class SceneEntityExtractionService:
    """Phase 2: 按 Scene 顺序串行提取实体，累积 Memory 上下文。"""

    async def extract_alias_relations(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        workflow_id: str | None = None,
        scene_ids: list[str] | None = None,
        start_chapter: int | None = None,
        end_chapter: int | None = None,
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
        )
        await db.flush()
        return {
            **result,
            "total_scenes": len(selected),
            "degraded": bool(result.get("alias_relation_failed_scenes")),
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
        completed_scenes = 0
        skipped_scenes = 0
        rerun_scenes = 0
        stopped_early = False
        error_kind: str | None = None
        error_message: str | None = None
        checkpoint_by_scene = self._phase2_checkpoint_by_scene(existing_checkpoints)
        scene_checkpoints: list[dict[str, Any]] = []
        consecutive_transport_failures = 0

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
                    alias_result = await self._run_alias_relation_phase(
                        db,
                        nid,
                        scenes,
                        workflow_id=workflow_id,
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
                await db.flush()
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
                    "degraded": bool(supplement_result["created"]),
                    "error_kind": None,
                    "error_message": None,
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
                }
                alias_result = await self._run_alias_relation_phase(
                    db,
                    nid,
                    scenes,
                    workflow_id=workflow_id,
                )
                return self._merge_alias_relation_result(phase2_result, alias_result)

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

        await db.flush()
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
            "degraded": bool(failed_scene_indices or stopped_early),
            "error_kind": error_kind,
            "error_message": error_message,
            "failed_scene_indices": failed_scene_indices,
            "completed_scenes": completed_scenes,
            "skipped_scenes": skipped_scenes,
            "rerun_scenes": rerun_scenes,
            "stopped_early": stopped_early,
            "audit_summary": audit_summary,
            "snapshot_health_summary": snapshot_health_summary,
            "checkpoints": {"phase2": {"scenes": scene_checkpoints}},
        }
        alias_result = await self._run_alias_relation_phase(
            db,
            nid,
            scenes,
            workflow_id=workflow_id,
        )
        return self._merge_alias_relation_result(phase2_result, alias_result)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _is_transport_failure(exc: Exception) -> bool:
        return isinstance(
            exc,
            (LLMConnectionError, LLMTimeoutError, LLMRateLimitError, TimeoutError),
        )

    @staticmethod
    def _error_kind(exc: Exception) -> str:
        if isinstance(exc, LLMConnectionError):
            return "connection_error"
        if isinstance(exc, LLMTimeoutError):
            return "timeout"
        if isinstance(exc, TimeoutError):
            return "timeout"
        if isinstance(exc, LLMRateLimitError):
            return "rate_limit"
        if isinstance(exc, ValueError) and "valid json" in str(exc).lower():
            return "schema_error"
        return exc.__class__.__name__

    def _merge_alias_relation_result(
        self,
        phase2_result: dict[str, Any],
        alias_result: dict[str, Any],
    ) -> dict[str, Any]:
        merged = dict(phase2_result)
        merged["total_aliases"] = int(alias_result.get("total_aliases", 0) or 0)
        merged["total_relations"] = int(merged.get("total_relations", 0) or 0) + int(
            alias_result.get("total_relations", 0) or 0
        )
        merged["alias_relation_scenes"] = int(
            alias_result.get("alias_relation_scenes", 0) or 0
        )
        merged["alias_relation_failed_scenes"] = alias_result.get(
            "alias_relation_failed_scenes",
            [],
        )
        if alias_result.get("degraded"):
            merged["degraded"] = True
            merged["error_kind"] = merged.get("error_kind") or alias_result.get(
                "error_kind"
            )
            merged["error_message"] = merged.get("error_message") or alias_result.get(
                "error_message"
            )
        return merged

    @staticmethod
    def _scene_id(scene: dict[str, Any]) -> str:
        if isinstance(scene, dict):
            raw_scene_id = scene.get("id") or scene.get("scene_id")
            scene_index = scene.get("scene_index", "")
        else:
            raw_scene_id = getattr(scene, "id", None) or getattr(scene, "scene_id", None)
            scene_index = getattr(scene, "scene_index", "")
        if raw_scene_id:
            return str(raw_scene_id)
        return f"scene_index:{scene_index}"

    def _scene_provenance_key(
        self,
        workflow_id: str | None,
        scene: dict[str, Any],
    ) -> str:
        return f"{workflow_id or 'manual'}:scene:{self._scene_id(scene)}"

    @staticmethod
    def _checkpoint_retry_count(checkpoint: dict[str, Any] | None) -> int:
        if not checkpoint:
            return 0
        try:
            return max(0, int(checkpoint.get("retry_count") or 0))
        except (TypeError, ValueError):
            return 0

    def _phase2_checkpoint_by_scene(
        self,
        existing_checkpoints: dict[str, Any] | None,
    ) -> dict[str, dict[str, Any]]:
        if not existing_checkpoints:
            return {}

        scenes = existing_checkpoints.get("scenes")
        if scenes is None:
            phase2 = existing_checkpoints.get("phase2")
            if isinstance(phase2, dict):
                scenes = phase2.get("scenes")

        if isinstance(scenes, list):
            return {
                str(item["scene_id"]): item
                for item in scenes
                if isinstance(item, dict) and item.get("scene_id")
            }

        return {
            str(scene_id): checkpoint
            for scene_id, checkpoint in existing_checkpoints.items()
            if isinstance(checkpoint, dict)
        }

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
        checkpoint = {
            "scene_id": self._scene_id(scene),
            "scene_index": scene.get("scene_index"),
            "status": status,
            "created_entity_ids": created_entity_ids or [],
            "created_relation_ids": created_relation_ids or [],
            "created_delta_ids": created_delta_ids or [],
            "retry_count": retry_count,
            "workflow_id": workflow_id,
            "scene_provenance_key": scene_provenance_key,
            "source": "deep_import",
            "auto_ingested": True,
        }
        if error is not None:
            checkpoint["error"] = error
        if error_kind is not None:
            checkpoint["error_kind"] = error_kind
        return checkpoint

    async def _get_scenes(self, db: AsyncSession, nid) -> list[dict[str, Any]]:
        from modules.outline.facade import get_scenes_by_novel

        return await get_scenes_by_novel(
            db,
            str(nid),
            status_filter=["draft", "canonical"],
            exclude_narrative_tags=["valley", "transition"],
        )

    def _filter_scenes_by_range(
        self,
        scenes: list[dict[str, Any]],
        *,
        start_chapter: int | None = None,
        end_chapter: int | None = None,
    ) -> list[dict[str, Any]]:
        if start_chapter is None and end_chapter is None:
            return scenes

        selected: list[dict[str, Any]] = []
        for scene in scenes:
            if self._scene_overlaps_chapter_range(
                scene,
                start_chapter=start_chapter,
                end_chapter=end_chapter,
            ):
                selected.append(scene)
        return selected

    def _scene_overlaps_chapter_range(
        self,
        scene: dict[str, Any],
        *,
        start_chapter: int | None = None,
        end_chapter: int | None = None,
    ) -> bool:
        start = start_chapter if start_chapter is not None else -10**9
        end = end_chapter if end_chapter is not None else 10**9
        chapter_ids = scene.get("chapter_ids") or []
        for chapter_id in chapter_ids:
            try:
                chapter_index = int(chapter_id)
            except (TypeError, ValueError):
                continue
            if start <= chapter_index <= end:
                return True
        source_chapter = self._scene_source_chapter_index(scene)
        return start <= source_chapter <= end

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
    ) -> dict[str, Any]:
        scene_index = scene["scene_index"]
        scene_id = self._scene_id(scene)
        scene_provenance_key = self._scene_provenance_key(workflow_id, scene)
        source_chapter_index = self._scene_source_chapter_index(scene)
        chapters_text = await self._load_scene_chapters(db, scene)
        if not chapters_text:
            return {
                "created": 0,
                "relations": 0,
                "deltas": 0,
                "created_entity_ids": [],
                "created_relation_ids": [],
                "created_delta_ids": [],
                "updated_context": existing_context,
                "updated_memory": accumulated_memory,
            }

        memory_context = self._build_memory_context(accumulated_memory)
        snapshot_id: str | None = None
        try:
            snapshot = await self._create_phase2_snapshot(
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
            snapshot_id = snapshot.id
            extraction = await asyncio.wait_for(
                self._call_llm_extraction(
                    chapters_text,
                    existing_context,
                    memory_context,
                ),
                timeout=self._phase2_scene_llm_timeout_seconds(),
            )
        except Exception as exc:
            if snapshot_id is not None:
                from modules.context.facade import mark_context_snapshot_failed

                await mark_context_snapshot_failed(
                    db,
                    snapshot_id=snapshot_id,
                    error_kind=self._error_kind(exc),
                    error_message=str(exc)[:300],
                )
            raise

        result_refs: list[dict[str, str]] = []
        context_snapshot_id = snapshot_id
        try:
            created_count = await self._persist_entities(
                db,
                nid,
                extraction.entities,
                scene_index=scene_index,
                source_chapter_index=source_chapter_index,
                seen_entity_keys=seen_entity_keys,
                workflow_id=workflow_id,
                scene_id=scene_id,
                scene_provenance_key=scene_provenance_key,
                context_snapshot_id=context_snapshot_id,
                result_refs=result_refs,
            )
            relation_count = 0
            delta_count = await self._record_deltas(
                db,
                nid,
                extraction.delta_events,
                scene_index=scene_index,
                workflow_id=workflow_id,
                scene_id=scene_id,
                scene_provenance_key=scene_provenance_key,
                context_snapshot_id=context_snapshot_id,
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
            if snapshot_id is not None:
                from modules.context.facade import mark_context_snapshot_failed

                await mark_context_snapshot_failed(
                    db,
                    snapshot_id=snapshot_id,
                    error_kind=self._error_kind(exc),
                    error_message=str(exc)[:300],
                )
            raise

        new_names = [
            e.name for e in extraction.entities if e.suggested_action == "create_new"
        ]
        new_entities_text = "\n".join(
            f"- {n} ({e.entity_type})"
            for n, e in zip(new_names, extraction.entities)
            if e.suggested_action == "create_new"
        )
        updated_context = (
            existing_context + "\n" + new_entities_text
            if new_entities_text
            else existing_context
        )

        updated_memory = accumulated_memory + [
            {"scene_index": scene_index, "entities": len(extraction.entities)},
        ]

        # 每个 Scene 完成后更新记忆快照
        try:
            from modules.memory.facade import capture_snapshot

            await capture_snapshot(
                db,
                str(nid),
                chapter_index=source_chapter_index,
            )
        except Exception as exc:
            logger.warning(
                "Memory snapshot after scene %d failed: %s",
                scene_index,
                exc,
            )

        return {
            "created": created_count,
            "relations": relation_count,
            "deltas": delta_count,
            "created_entity_ids": self._result_ref_ids(result_refs, "core_entity"),
            "created_relation_ids": self._result_ref_ids(
                result_refs,
                "entity_relation",
            ),
            "created_delta_ids": self._result_ref_ids(result_refs, "delta_log"),
            "updated_context": updated_context,
            "updated_memory": updated_memory,
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
        prepared: list[dict[str, Any]] = []
        for scene_idx, scene in enumerate(scenes):
            source_chapter_index = self._scene_source_chapter_index(scene)
            chapters_text = await self._load_scene_chapters(db, scene)
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
            memory_context = self._parallel_scene_memory_context(scene, scene_idx)
            snapshot = await self._create_phase2_snapshot(
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
            try:
                async with semaphore:
                    extraction = await asyncio.wait_for(
                        self._call_llm_extraction(
                            item["chapters_text"],
                            existing_context,
                            item["memory_context"],
                            client_timeout=PHASE2_PARALLEL_PROVIDER_TIMEOUT_SECONDS,
                            transport_retries=False,
                        ),
                        timeout=PHASE2_PARALLEL_LLM_TIMEOUT_SECONDS,
                    )
            except Exception as exc:
                return {**item, "extraction": None, "error": exc}
            return {**item, "extraction": extraction, "error": None}

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

        for item in sorted(extracted, key=lambda entry: entry["scene_idx"]):
            scene = item["scene"]
            scene_idx = int(item["scene_idx"])
            scene_index = int(scene.get("scene_index") or scene_idx)
            scene_id = self._scene_id(scene)
            scene_provenance_key = self._scene_provenance_key(workflow_id, scene)
            snapshot_id = item["snapshot_id"]
            extraction = item["extraction"]
            error = item["error"]

            if error is not None:
                error_kind = self._error_kind(error)
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
                    self._build_scene_checkpoint(
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
                    self._build_scene_checkpoint(
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
                created_count = await self._persist_entities(
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
                relation_count = 0
                delta_count = await self._record_deltas(
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
                error_kind = self._error_kind(exc)
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
                    self._build_scene_checkpoint(
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
            updated_context = self._append_extracted_entities_to_context(
                updated_context,
                extraction,
            )
            accumulated_memory.append(
                {"scene_index": scene_index, "entities": len(extraction.entities)}
            )
            scene_checkpoints.append(
                self._build_scene_checkpoint(
                    scene,
                    status="done",
                    workflow_id=workflow_id,
                    scene_provenance_key=scene_provenance_key,
                    retry_count=0,
                    created_entity_ids=self._result_ref_ids(
                        result_refs,
                        "core_entity",
                    ),
                    created_relation_ids=self._result_ref_ids(
                        result_refs,
                        "entity_relation",
                    ),
                    created_delta_ids=self._result_ref_ids(result_refs, "delta_log"),
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

        supplement_result = await self._supplement_small_sample_entities(
            db,
            nid,
            scenes,
            current_count=total_created,
            workflow_id=workflow_id,
        )
        if supplement_result["created"]:
            total_created += supplement_result["created"]

        await db.flush()
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
            "total_scenes": len(scenes),
            "degraded": bool(failed_scene_indices or supplement_result["created"]),
            "error_kind": error_kind,
            "error_message": error_message,
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
        }
        alias_result = await self._run_alias_relation_phase(
            db,
            nid,
            scenes,
            workflow_id=workflow_id,
        )
        return self._merge_alias_relation_result(phase2_result, alias_result)

    async def _process_scenes_bulk(
        self,
        db: AsyncSession,
        nid,
        scenes: list[dict[str, Any]],
        existing_context: str,
        *,
        workflow_id: str | None = None,
    ) -> dict[str, Any]:
        first_scene = scenes[0]
        source_chapter_index = self._scene_source_chapter_index(first_scene)
        scene_texts: list[str] = []
        for scene in scenes:
            text = await self._load_scene_chapters(db, scene)
            if text:
                scene_texts.append(
                    f"### Scene {scene.get('scene_index')}\n\n{text}"
                )
        if not scene_texts:
            return {
                "created": 0,
                "relations": 0,
                "deltas": 0,
                "created_entity_ids": [],
                "created_relation_ids": [],
                "created_delta_ids": [],
            }

        chapters_text = "\n\n".join(scene_texts)
        memory_context = self._bulk_entity_memory_context(scenes)
        snapshot_id: str | None = None
        try:
            snapshot = await self._create_phase2_snapshot(
                db,
                nid,
                first_scene,
                source_chapter_index,
                chapters_text,
                existing_context,
                memory_context,
                [],
                workflow_id=workflow_id,
            )
            snapshot_id = snapshot.id
            extractions = await self._call_bulk_llm_extractions(
                scene_texts,
                existing_context,
                memory_context,
            )
        except Exception as exc:
            if snapshot_id is not None:
                from modules.context.facade import mark_context_snapshot_failed

                await mark_context_snapshot_failed(
                    db,
                    snapshot_id=snapshot_id,
                    error_kind=self._error_kind(exc),
                    error_message=str(exc)[:300],
                )
            raise

        result_refs: list[dict[str, str]] = []
        scene_index = int(first_scene.get("scene_index") or 0)
        scene_id = self._scene_id(first_scene)
        scene_provenance_key = self._scene_provenance_key(workflow_id, first_scene)
        seen_entity_keys: set[tuple[str, str]] = set()
        created_count = 0
        relation_count = 0
        delta_count = 0
        for extraction in extractions:
            created_count += await self._persist_entities(
                db,
                nid,
                extraction.entities,
                scene_index=scene_index,
                source_chapter_index=source_chapter_index,
                seen_entity_keys=seen_entity_keys,
                workflow_id=workflow_id,
                scene_id=scene_id,
                scene_provenance_key=scene_provenance_key,
                context_snapshot_id=snapshot_id,
                result_refs=result_refs,
            )
            relation_count += 0
            delta_count += await self._record_deltas(
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
        try:
            from modules.memory.facade import capture_snapshot

            await capture_snapshot(
                db,
                str(nid),
                chapter_index=source_chapter_index,
            )
        except Exception as exc:
            logger.warning("Memory snapshot after bulk phase2 failed: %s", exc)

        return {
            "created": created_count,
            "relations": relation_count,
            "deltas": delta_count,
            "created_entity_ids": self._result_ref_ids(result_refs, "core_entity"),
            "created_relation_ids": self._result_ref_ids(
                result_refs,
                "entity_relation",
            ),
            "created_delta_ids": self._result_ref_ids(result_refs, "delta_log"),
        }

    async def _supplement_small_sample_entities(
        self,
        db: AsyncSession,
        nid,
        scenes: list[dict[str, Any]],
        *,
        current_count: int,
        workflow_id: str | None,
    ) -> dict[str, Any]:
        if len(scenes) < PHASE2_SMALL_SAMPLE_MIN_SCENES:
            return {
                "created": 0,
                "created_entity_ids": [],
                "supplemental_llm_created": 0,
                "fallback_created": 0,
                "supplemental_error_kind": None,
            }

        target_needed = PHASE2_SMALL_SAMPLE_TARGET_ENTITIES - current_count
        created_ids: list[str] = []
        supplemental_llm_created = 0
        supplemental_error_kind = None
        if target_needed > 0:
            try:
                supplement = await asyncio.wait_for(
                    self._supplement_small_sample_entities_with_llm(
                        db,
                        nid,
                        scenes,
                        needed=target_needed,
                        workflow_id=workflow_id,
                    ),
                    timeout=PHASE2_SMALL_SAMPLE_SUPPLEMENT_TIMEOUT_SECONDS,
                )
            except Exception as exc:
                supplemental_error_kind = self._error_kind(exc)
                logger.warning(
                    "Small sample supplemental entity sweep stopped: %s",
                    exc,
                )
                supplement = {"created": 0, "created_entity_ids": []}
            supplemental_llm_created = supplement["created"]
            created_ids.extend(supplement["created_entity_ids"])
            supplemental_error_kind = (
                supplement.get("error_kind") or supplemental_error_kind
            )

        needed = PHASE2_SMALL_SAMPLE_MIN_ENTITIES - current_count - len(created_ids)
        if needed <= 0:
            return {
                "created": len(created_ids),
                "created_entity_ids": created_ids,
                "supplemental_llm_created": supplemental_llm_created,
                "fallback_created": 0,
                "supplemental_error_kind": supplemental_error_kind,
            }

        from modules.world.facade import create_entity

        fallback_created = 0
        entity_types = ["character", "location", "organization", "object", "concept"]
        for index in range(needed):
            scene = scenes[index % len(scenes)]
            scene_index = scene.get("scene_index", index)
            scene_title = str(scene.get("title") or f"Scene {scene_index}").strip()
            entity_type = entity_types[index % len(entity_types)]
            label = self._fallback_entity_label(entity_type)
            content_json = {
                "_meta": {
                    "auto_ingested": True,
                    "source": "deep_import",
                    "workflow_id": workflow_id,
                    "scene_id": self._scene_id(scene),
                    "scene_provenance_key": self._scene_provenance_key(
                        workflow_id,
                        scene,
                    ),
                    "source_scene_index": scene_index,
                    "needs_review": True,
                    "fallback": "small_sample_entity_minimum",
                    "ingested_at": datetime.now(UTC).isoformat(),
                    "batch_id": workflow_id or "",
                },
                "aliases": [],
            }
            payload = {
                "name": f"{scene_title[:32]} - 待复核{label}{index + 1}",
                "entity_type": entity_type,
                "summary": (
                    "Phase 2 真实 LLM 部分失败后，为保持小样本可整理性生成的"
                    "待复核世界对象候选。"
                ),
                "public_info": f"来源 Scene：{scene_title[:80]}",
                "hidden_truth": "该对象需人工复核后决定保留、合并或删除。",
                "importance": 0.35,
                "importance_level": "temporary",
                "reveal_level": "author_only",
                "content_json": content_json,
                "status": "candidate",
                "created_by": "ai_import",
                "force_create": True,
            }
            try:
                async with db.begin_nested():
                    created = await create_entity(db, str(nid), payload)
            except Exception as exc:
                logger.warning("Failed to create fallback entity: %s", exc)
                continue
            if created.get("id"):
                created_ids.append(str(created["id"]))
                fallback_created += 1
        return {
            "created": len(created_ids),
            "created_entity_ids": created_ids,
            "supplemental_llm_created": supplemental_llm_created,
            "fallback_created": fallback_created,
            "supplemental_error_kind": supplemental_error_kind,
        }

    async def _supplement_small_sample_entities_with_llm(
        self,
        db: AsyncSession,
        nid,
        scenes: list[dict[str, Any]],
        *,
        needed: int,
        workflow_id: str | None,
    ) -> dict[str, Any]:
        chapters_text = await self._load_small_sample_chapters_text(db, scenes)
        if not chapters_text:
            return {"created": 0, "created_entity_ids": []}
        from modules.world.facade import get_world_context

        ctx = await get_world_context(
            db,
            str(nid),
            reveal_mode="author_safe",
            limit=500,
        )
        existing_context = (
            "\n".join(
                f"- {e.name} ({e.entity_type})"
                for e in ctx.entities
                if e.status in ("canonical", "draft", "candidate")
            )
            or "无已有对象"
        )
        memory_context = (
            "1-7章世界对象补充 sweep：前一轮抽取低于 Codex5.3 标准，"
            f"请只补充遗漏的长期资产，目标新增不超过 {needed} 个。"
            "重点检查：周明瑞/克莱恩别名、莫雷蒂家庭、廷根地点、"
            "黑夜女神教会与值夜者线索、塔罗/灰雾/占卜/转运仪式、"
            "奥黛丽、阿尔杰、非凡者、魔药、罗塞尔日记和塔罗会规则。"
            "不要输出已存在对象；不确定但明显重要的对象可标记 temporary_only。"
        )
        try:
            extraction = await self._call_llm_extraction(
                chapters_text,
                existing_context,
                memory_context,
                max_tokens=4096,
                client_timeout=PHASE2_BULK_PROVIDER_TIMEOUT_SECONDS,
                max_fix_attempts=0,
                transport_retries=False,
            )
        except Exception as exc:
            logger.warning("Small sample supplemental entity sweep failed: %s", exc)
            return {
                "created": 0,
                "created_entity_ids": [],
                "error_kind": self._error_kind(exc),
            }

        result_refs: list[dict[str, str]] = []
        chapter_ids = self._small_sample_chapter_indices(scenes)
        source_chapter_index = max(chapter_ids) if chapter_ids else 0
        created = await self._persist_entities(
            db,
            nid,
            extraction.entities[:needed],
            scene_index=0,
            source_chapter_index=source_chapter_index,
            seen_entity_keys=set(),
            workflow_id=workflow_id,
            scene_id="small-sample-entity-sweep",
            scene_provenance_key=f"{workflow_id or 'manual'}:phase2:entity_sweep",
            context_snapshot_id=None,
            result_refs=result_refs,
        )
        return {
            "created": created,
            "created_entity_ids": self._result_ref_ids(result_refs, "core_entity"),
        }

    async def _load_small_sample_chapters_text(
        self,
        db: AsyncSession,
        scenes: list[dict[str, Any]],
    ) -> str:
        from modules.writing.facade import get_latest_draft_for_chapter

        parts: list[str] = []
        for chapter_index in self._small_sample_chapter_indices(scenes):
            draft = await get_latest_draft_for_chapter(
                db,
                scenes[0]["novel_id"],
                chapter_index,
            )
            if draft and draft.content:
                parts.append(
                    f"## 第{chapter_index}章\n\n"
                    f"{self._trim_supplement_chapter_text(draft.content)}"
                )
        return "\n\n".join(parts)[:PHASE2_SMALL_SAMPLE_SUPPLEMENT_TOTAL_CHAR_LIMIT]

    @staticmethod
    def _trim_supplement_chapter_text(content: str) -> str:
        text = str(content or "").strip()
        if len(text) <= PHASE2_SMALL_SAMPLE_SUPPLEMENT_CHAPTER_CHAR_LIMIT:
            return text
        half = PHASE2_SMALL_SAMPLE_SUPPLEMENT_CHAPTER_CHAR_LIMIT // 2
        head = text[:half].rstrip()
        tail = text[-half:].lstrip()
        return f"{head}\n\n[...章节中段已压缩...]\n\n{tail}"

    @staticmethod
    def _small_sample_chapter_indices(scenes: list[dict[str, Any]]) -> list[int]:
        chapters: set[int] = set()
        for scene in scenes:
            for raw in scene.get("chapter_ids") or []:
                try:
                    chapters.add(int(raw))
                except (TypeError, ValueError):
                    continue
        return sorted(chapter for chapter in chapters if chapter > 0)

    @staticmethod
    def _fallback_entity_label(entity_type: str) -> str:
        return {
            "character": "人物线索",
            "location": "地点线索",
            "organization": "组织线索",
            "object": "物品线索",
            "concept": "概念线索",
        }.get(entity_type, "对象线索")

    async def _call_bulk_llm_extractions(
        self,
        scene_texts: list[str],
        existing_context: str,
        memory_context: str,
    ) -> list[SceneEntityExtractionOutput]:
        groups = [
            scene_texts[index : index + PHASE2_BULK_GROUP_SIZE]
            for index in range(0, len(scene_texts), PHASE2_BULK_GROUP_SIZE)
        ]

        async def call_group(group: list[str]) -> SceneEntityExtractionOutput:
            return await asyncio.wait_for(
                self._call_llm_extraction(
                    "\n\n".join(group),
                    existing_context,
                    memory_context,
                    max_tokens=PHASE2_BULK_MAX_TOKENS,
                    client_timeout=PHASE2_BULK_PROVIDER_TIMEOUT_SECONDS,
                    max_fix_attempts=0,
                    transport_retries=False,
                ),
                timeout=PHASE2_BULK_LLM_TIMEOUT_SECONDS,
            )

        results = await asyncio.gather(
            *(call_group(group) for group in groups),
            return_exceptions=True,
        )
        extractions = [
            result
            for result in results
            if isinstance(result, SceneEntityExtractionOutput)
        ]
        if extractions:
            for result in results:
                if isinstance(result, Exception):
                    logger.warning("Bulk phase2 group failed: %s", result)
            return extractions
        first_error = next(
            (result for result in results if isinstance(result, Exception)),
            RuntimeError("bulk phase2 produced no extraction results"),
        )
        raise first_error

    @staticmethod
    def _bulk_entity_memory_context(scenes: list[dict[str, Any]]) -> str:
        chapter_ids: set[int] = set()
        for scene in scenes:
            for raw in scene.get("chapter_ids") or []:
                try:
                    chapter_ids.add(int(raw))
                except (TypeError, ValueError):
                    continue
        base = (
            "小样本批量实体提取：请按 Scene 上下文识别长期创作资产，"
            "不要抽取路人、普通道具或一次性细节。"
        )
        if chapter_ids == set(range(1, 8)):
            return (
                f"{base}\n"
                "当前样本覆盖 1-7 章，整体目标应接近 24-32 个长期资产；"
                "每个有效 Scene 优先召回 4-8 个高价值对象。请按类别覆盖："
                "主要人物及别名、长期地点、组织/教会/聚会、关键物品和文本、"
                "神秘学概念/力量体系、推动后续剧情的事件或秘密。"
                "允许把低置信但明显会反复出现的对象标为 temporary_only 或"
                " needs_review 候选，不要因保守而漏掉核心资产。"
            )
        return base

    @staticmethod
    def _result_ref_ids(result_refs: list[dict[str, str]], result_type: str) -> list[str]:
        return [item["id"] for item in result_refs if item.get("type") == result_type]

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
        from core.config import get_settings
        from modules.context.facade import create_context_snapshot

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
        return await create_context_snapshot(
            db,
            novel_id=str(nid),
            task_id=workflow_id,
            workflow_id=workflow_id,
            phase="entity_extraction",
            operation="scene_entity_extraction",
            scene_id=payload["scene_id"],
            scene_index=payload["scene_index"],
            chapter_index=payload["chapter_index"],
            context_mode="working",
            include_pending_objects=True,
            attempt=1,
            prompt_name="scene_entity_extraction",
            model=settings.llm_model,
            compile_options=payload["compile_options"],
            included_asset_ids=payload["included_asset_ids"],
            context_summary=payload["context_summary"],
            section_metadata=payload["section_metadata"],
            token_metadata=payload["token_metadata"],
            rendered_context=payload["rendered_context"],
            retain_rendered_context=False,
        )

    async def _phase2_audit_summary(
        self,
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

    async def _phase2_snapshot_health_summary(
        self,
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

    @staticmethod
    def _scene_source_chapter_index(scene: dict[str, Any]) -> int:
        """取 Scene 关联的最大章节号作为来源章节；没有则回退到 scene_index。"""
        chapter_ids = scene.get("chapter_ids") or []
        indices: list[int] = []
        for raw in chapter_ids:
            try:
                indices.append(int(raw))
            except (ValueError, TypeError):
                continue
        return max(indices) if indices else scene.get("scene_index", 0)

    async def _load_scene_chapters(self, db: AsyncSession, scene: dict[str, Any]) -> str:
        from modules.writing.facade import get_latest_draft_for_chapter

        parts: list[str] = []
        chunk_by_chapter = self._scene_chunks_by_chapter(scene)
        chapter_ids = self._scene_chapter_ids(scene, chunk_by_chapter)
        for ch_id_str in chapter_ids:
            try:
                ch_idx = int(ch_id_str)
            except (ValueError, TypeError):
                continue
            draft = await get_latest_draft_for_chapter(
                db,
                scene["novel_id"],
                ch_idx,
            )
            if draft and draft.content:
                selected = self._select_scene_text(
                    draft.content,
                    chunk_by_chapter.get(ch_idx, []),
                )
                parts.append(f"## 第{ch_idx}章\n\n{selected}")
        if not parts:
            return ""
        scene_context = self._scene_context_header(scene)
        return scene_context + "\n\n" + "\n\n".join(parts)

    @staticmethod
    def _phase2_scene_llm_timeout_seconds() -> int:
        from core.config import get_settings

        return max(
            30,
            int(get_settings().llm_timeout) + PHASE2_SCENE_TIMEOUT_GRACE_SECONDS,
        )

    @staticmethod
    def _scene_context_header(scene: dict[str, Any]) -> str:
        fields = [
            ("Scene", scene.get("scene_index")),
            ("标题", scene.get("title")),
            ("目标", scene.get("goal")),
            ("核心冲突", scene.get("core_conflict")),
            ("情绪节拍", scene.get("emotional_beat")),
        ]
        lines = [
            f"- {label}: {value}"
            for label, value in fields
            if value is not None and str(value).strip()
        ]
        return "## Scene 上下文\n" + ("\n".join(lines) if lines else "- 无")

    @staticmethod
    def _scene_chunks_by_chapter(
        scene: dict[str, Any],
    ) -> dict[int, list[dict[str, Any]]]:
        result: dict[int, list[dict[str, Any]]] = {}
        for raw_chunk in scene.get("scene_chunks") or []:
            if not isinstance(raw_chunk, dict):
                continue
            try:
                chapter_index = int(raw_chunk.get("chapter_index"))
            except (TypeError, ValueError):
                continue
            if chapter_index < 1:
                continue
            result.setdefault(chapter_index, []).append(raw_chunk)
        return result

    @staticmethod
    def _scene_chapter_ids(
        scene: dict[str, Any],
        chunk_by_chapter: dict[int, list[dict[str, Any]]],
    ) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()
        for raw in scene.get("chapter_ids") or []:
            value = str(raw)
            if value not in seen:
                seen.add(value)
                ordered.append(value)
        for chapter_index in sorted(chunk_by_chapter):
            value = str(chapter_index)
            if value not in seen:
                seen.add(value)
                ordered.append(value)
        return ordered

    @staticmethod
    def _select_scene_text(
        chapter_text: str,
        chunks: list[dict[str, Any]],
    ) -> str:
        if not chunks:
            return chapter_text
        paragraphs = [part.strip() for part in chapter_text.split("\n\n") if part.strip()]
        if not paragraphs:
            return chapter_text

        selected: list[str] = []
        for chunk in chunks:
            try:
                start = int(chunk.get("start_paragraph") or 0)
            except (TypeError, ValueError):
                start = 0
            raw_end = chunk.get("end_paragraph")
            try:
                end = int(raw_end) if raw_end is not None else start
            except (TypeError, ValueError):
                end = start
            start = max(0, min(start, len(paragraphs) - 1))
            end = max(start, min(end, len(paragraphs) - 1))
            selected.extend(paragraphs[start : end + 1])

        compact = "\n\n".join(dict.fromkeys(selected))
        return compact or chapter_text

    @staticmethod
    def _build_memory_context(memory: list[dict]) -> str:
        if not memory:
            return "无前序 Scene 上下文"
        recent = memory[-5:]
        lines = ["## 前序 Scene 摘要"]
        for m in recent:
            lines.append(f"- Scene {m['scene_index']}: 包含 {m['entities']} 个实体")
        return "\n".join(lines)

    @staticmethod
    def _parallel_scene_memory_context(scene: dict[str, Any], scene_idx: int) -> str:
        scene_index = scene.get("scene_index", scene_idx)
        return (
            "小样本并发 Phase 2：当前 Scene 会与同批其他 Scene 并发抽取，"
            "请只依据本 Scene 正文和已有对象判断长期创作资产。"
            f"\n- 当前 Scene: {scene_index}"
            f"\n- 标题: {scene.get('title') or '未命名'}"
        )

    @staticmethod
    def _append_extracted_entities_to_context(
        existing_context: str,
        extraction: SceneEntityExtractionOutput,
    ) -> str:
        new_entities_text = "\n".join(
            f"- {entity.name} ({entity.entity_type})"
            for entity in extraction.entities
            if entity.suggested_action == "create_new" and entity.name
        )
        if not new_entities_text:
            return existing_context
        return f"{existing_context}\n{new_entities_text}"

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
    ) -> SceneEntityExtractionOutput:
        from core.config import get_settings
        from infrastructure.llm.client import LLMClient
        from infrastructure.llm.prompt_loader import load_prompt
        from infrastructure.llm.schemas import LLMCallRequest, LLMMessage

        system_prompt = load_prompt(
            "scene_entity_extraction",
            existing_entities_context=existing_context,
        )
        system_prompt += f"\n\n## 前序上下文\n\n{memory_context}"

        settings = get_settings()
        request = LLMCallRequest(
            model=settings.llm_model,
            messages=[
                LLMMessage(role="system", content=system_prompt),
                LLMMessage(
                    role="user",
                    content=(
                        "请从以下正文中提取世界对象。优先保证长期资产召回完整："
                        "人物、地点、组织/势力、关键物品/文本、概念/规则/力量、"
                        "事件/秘密都要分别检查；同一对象用 aliases 或 "
                        "link_to_existing 表达，不要拆成重复对象。\n\n"
                        f"{chapters_text}"
                    ),
                ),
            ],
            temperature=0.3,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )

        llm_client = LLMClient(timeout=client_timeout)
        return await llm_client.generate_structured(
            request,
            SceneEntityExtractionOutput,
            max_fix_attempts=max_fix_attempts,
            transport_retries=transport_retries,
            fix_prompt=(
                "上一轮实体抽取输出不是合法 JSON 或不符合 schema。"
                "请重新输出一个完整 JSON 对象，只包含 entities、relations、"
                "delta_events、memory_update，不要 Markdown 或解释。"
            ),
        )

    async def _call_alias_relation_extraction(
        self,
        chapters_text: str,
        entity_index: str,
        *,
        max_tokens: int = 4096,
        client_timeout: int = 120,
    ) -> AliasRelationExtractionOutput:
        from core.config import get_settings
        from infrastructure.llm.client import LLMClient
        from infrastructure.llm.prompt_loader import load_prompt
        from infrastructure.llm.schemas import LLMCallRequest, LLMMessage

        system_prompt = load_prompt(
            "alias_relation_extraction",
            entity_index=entity_index,
        )
        settings = get_settings()
        request = LLMCallRequest(
            model=settings.llm_model,
            messages=[
                LLMMessage(role="system", content=system_prompt),
                LLMMessage(
                    role="user",
                    content=(
                        "请只基于下列 Scene 正文和对象索引提取别名与对象关系。"
                        "不要创建新对象；无法在索引中定位两端对象时跳过。\n\n"
                        f"{chapters_text}"
                    ),
                ),
            ],
            temperature=0.2,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        llm_client = LLMClient(timeout=client_timeout)
        return await llm_client.generate_structured(
            request,
            AliasRelationExtractionOutput,
            max_fix_attempts=1,
            transport_retries=True,
            fix_prompt=(
                "上一轮别名/关系抽取输出不是合法 JSON 或不符合 schema。"
                "请重新输出一个完整 JSON 对象，只包含 aliases 和 relations，"
                "不要 Markdown 或解释。"
            ),
        )

    async def _run_alias_relation_phase(
        self,
        db: AsyncSession,
        nid,
        scenes: list[dict[str, Any]],
        *,
        workflow_id: str | None = None,
    ) -> dict[str, Any]:
        total_aliases = 0
        total_relations = 0
        completed_scenes = 0
        failed_scenes: list[int] = []
        error_kind: str | None = None
        error_message: str | None = None

        for scene in scenes:
            raw_scene_index = (
                scene.get("scene_index")
                if isinstance(scene, dict)
                else getattr(scene, "scene_index", 0)
            )
            try:
                scene_index = int(raw_scene_index or 0)
            except (TypeError, ValueError):
                scene_index = 0
            scene_id = self._scene_id(scene)

            snapshot_id: str | None = None
            result_refs: list[dict[str, str]] = []
            try:
                chapters_text = await self._load_scene_chapters(db, scene)
                if not chapters_text:
                    continue
                entity_index = await self._build_alias_relation_entity_index(
                    db,
                    str(nid),
                )
                snapshot = await self._create_phase2b_snapshot(
                    db,
                    nid,
                    scene,
                    chapters_text,
                    entity_index,
                    workflow_id=workflow_id,
                )
                snapshot_id = snapshot.id
                output = await asyncio.wait_for(
                    self._call_alias_relation_extraction(
                        chapters_text,
                        entity_index,
                    ),
                    timeout=PHASE2_PARALLEL_LLM_TIMEOUT_SECONDS,
                )
                persisted = await self._persist_alias_relation_output(
                    db,
                    str(nid),
                    output,
                    scene_index=scene_index,
                    workflow_id=workflow_id,
                    scene_id=scene_id,
                    result_refs=result_refs,
                )
                total_aliases += persisted["aliases"]
                total_relations += persisted["relations"]
                completed_scenes += 1
                if snapshot_id is not None:
                    from modules.context.facade import mark_context_snapshot_succeeded

                    await mark_context_snapshot_succeeded(
                        db,
                        snapshot_id=snapshot_id,
                        result_refs=result_refs,
                    )
            except Exception as exc:
                error_kind = self._error_kind(exc)
                error_message = str(exc)[:300]
                failed_scenes.append(scene_index)
                logger.warning(
                    "Alias/relation extraction failed for scene %s: %s",
                    scene_index,
                    exc,
                )
                if snapshot_id is not None:
                    from modules.context.facade import mark_context_snapshot_failed

                    await mark_context_snapshot_failed(
                        db,
                        snapshot_id=snapshot_id,
                        error_kind=error_kind,
                        error_message=error_message,
                    )

        return {
            "total_aliases": total_aliases,
            "total_relations": total_relations,
            "alias_relation_scenes": completed_scenes,
            "alias_relation_failed_scenes": failed_scenes,
            "degraded": bool(failed_scenes),
            "error_kind": error_kind,
            "error_message": error_message,
        }

    async def _build_alias_relation_entity_index(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> str:
        from modules.world.facade import list_entities

        entities = await list_entities(
            db,
            novel_id,
            statuses=("canonical", "draft", "candidate"),
            limit=10000,
        )
        if not entities:
            return "无可用对象"
        lines = ["## 可用对象索引"]
        for entity in entities:
            lines.append(
                "- "
                f"{entity.get('name')} ({entity.get('entity_type')}) "
                f"id={entity.get('id')}"
            )
        return "\n".join(lines)

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
        from core.config import get_settings
        from modules.context.facade import create_context_snapshot

        settings = get_settings()
        rendered_context = f"{entity_index}\n\n{self._scene_context_header(scene)}"
        return await create_context_snapshot(
            db,
            novel_id=str(nid),
            task_id=workflow_id,
            workflow_id=workflow_id,
            phase="entity_extraction",
            operation="alias_relation_extraction",
            scene_id=self._scene_id(scene),
            scene_index=scene.get("scene_index"),
            chapter_index=self._scene_source_chapter_index(scene),
            context_mode="working",
            include_pending_objects=True,
            attempt=1,
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
            retain_rendered_context=False,
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
        from modules.world.facade import (
            append_candidate_alias,
            create_relation,
            find_working_entity_id_by_name,
        )

        aliases_created = 0
        relations_created = 0
        for alias in output.aliases:
            entity_id = await find_working_entity_id_by_name(
                db,
                novel_id,
                alias.entity_name,
            )
            if not entity_id:
                continue
            added = await append_candidate_alias(
                db,
                novel_id,
                entity_id,
                alias=alias.alias,
                alias_type=alias.alias_type,
                workflow_id=workflow_id,
                scene_id=scene_id,
                scene_index=scene_index,
                confidence=alias.confidence,
                quote=alias.quote,
            )
            if added:
                aliases_created += 1
                if result_refs is not None:
                    result_refs.append(
                        {
                            "type": "entity_alias",
                            "id": f"{entity_id}:{alias.alias.strip()}",
                        }
                    )

        for rel in output.relations:
            source_id = await find_working_entity_id_by_name(
                db,
                novel_id,
                rel.source_name,
            )
            target_id = await find_working_entity_id_by_name(
                db,
                novel_id,
                rel.target_name,
            )
            if not source_id or not target_id:
                continue
            try:
                relation = await create_relation(
                    db,
                    novel_id,
                    {
                        "source_id": source_id,
                        "target_id": target_id,
                        "relation_type": rel.relation_type,
                        "description": rel.description,
                        "quote": rel.quote,
                        "strength": rel.strength,
                        "status": "candidate",
                    },
                )
            except Exception as exc:
                logger.warning(
                    "Failed to create phase2b relation %s -> %s: %s",
                    rel.source_name,
                    rel.target_name,
                    exc,
                )
                continue
            relations_created += 1
            relation_id = getattr(relation, "id", None)
            if result_refs is not None and relation_id:
                result_refs.append(build_result_ref("entity_relation", relation_id))

        return {"aliases": aliases_created, "relations": relations_created}

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
    ) -> int:
        from modules.world.facade import create_entity, find_similar_entities

        created = 0
        seen_entity_keys = seen_entity_keys if seen_entity_keys is not None else set()

        for ent in entities:
            action = ent.suggested_action
            if action == "ignore":
                continue

            if not ent.name:
                continue

            entity_key = self._entity_key(ent.entity_type, ent.name)
            if entity_key in seen_entity_keys:
                continue

            if action == "create_new":
                similar = await find_similar_entities(db, str(nid), ent.name)
                if similar and similar.get("score", 0) >= 0.88:
                    seen_entity_keys.add(entity_key)
                    continue

            content_json: dict[str, Any] = {
                "_meta": {
                    "auto_ingested": True,
                    "source": "deep_import",
                    "workflow_id": workflow_id,
                    "scene_id": scene_id,
                    "scene_provenance_key": (
                        scene_provenance_key
                        or f"{workflow_id or 'manual'}:scene:{scene_index}"
                    ),
                    "source_scene_index": scene_index,
                    "source_chapter_index": source_chapter_index,
                    "ingested_at": datetime.now(UTC).isoformat(),
                    "batch_id": workflow_id or "",
                    "suggested_action": action,
                    "suggested_existing_entity_name": (
                        ent.suggested_existing_entity_name
                    ),
                    "candidate_reason": ent.candidate_reason,
                    "confidence": ent.confidence,
                },
                "aliases": ent.aliases or [],
            }
            if context_snapshot_id:
                content_json["_meta"]["context_snapshot_id"] = context_snapshot_id
            if action == "temporary_only":
                content_json["_meta"]["temporary"] = True
            entity_payload = {
                "name": ent.name,
                "entity_type": ent.entity_type,
                "summary": ent.summary or None,
                "public_info": ent.public_info or None,
                "hidden_truth": ent.hidden_truth or None,
                "importance": ent.importance,
                "content_json": content_json,
                "status": "candidate",
                "created_by": "ai_import",
            }
            try:
                async with db.begin_nested():
                    created_entity = await create_entity(db, str(nid), entity_payload)
                created += 1
                seen_entity_keys.add(entity_key)
                if result_refs is not None and created_entity.get("id"):
                    result_refs.append(
                        build_result_ref("core_entity", created_entity["id"])
                    )
            except Exception as exc:
                logger.warning(
                    "Failed to create entity '%s': %s",
                    ent.name,
                    exc,
                )

        return created

    @staticmethod
    def _entity_key(entity_type: str, name: str) -> tuple[str, str]:
        return (entity_type.strip().lower(), " ".join(name.strip().lower().split()))

    async def _persist_relations(
        self,
        db: AsyncSession,
        nid,
        relations: list[ExtractedRelation],
        scene_index: int,
        workflow_id: str | None = None,
        context_snapshot_id: str | None = None,
        result_refs: list[dict[str, str]] | None = None,
    ) -> int:
        from modules.world.facade import create_relation, find_entity_id_by_name

        created = 0
        for rel in relations:
            source_id = await find_entity_id_by_name(db, str(nid), rel.source_name)
            target_id = await find_entity_id_by_name(db, str(nid), rel.target_name)
            if not source_id or not target_id:
                logger.debug(
                    "Skipping relation %s -> %s: entity not found",
                    rel.source_name,
                    rel.target_name,
                )
                continue
            try:
                relation = await create_relation(
                    db,
                    str(nid),
                    {
                        "source_id": source_id,
                        "target_id": target_id,
                        "relation_type": rel.relation_type,
                        "description": rel.description,
                        "quote": rel.quote,
                        "strength": rel.strength,
                        "status": "candidate",
                    },
                )
                created += 1
                relation_id = getattr(relation, "id", None)
                if result_refs is not None and relation_id:
                    result_refs.append(build_result_ref("entity_relation", relation_id))
            except Exception as exc:
                logger.warning(
                    "Failed to create relation %s -> %s: %s",
                    rel.source_name,
                    rel.target_name,
                    exc,
                )
        return created

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
        from modules.memory.facade import create_delta_log
        from modules.world.facade import create_map_observation_from_delta_event

        count = 0
        for event in delta_events or []:
            event_meta = event.meta or {}
            provenance_meta = {
                "source": "deep_import",
                "workflow_id": workflow_id,
                "scene_id": scene_id,
                "scene_provenance_key": (
                    scene_provenance_key
                    or f"{workflow_id or 'manual'}:scene:{scene_index}"
                ),
                "auto_ingested": True,
            }
            source_ref = {
                "workflow_id": workflow_id,
                "scene_id": scene_id,
                "scene_provenance_key": provenance_meta["scene_provenance_key"],
                "auto_ingested": True,
            }
            merged_meta = {
                **event_meta,
                **provenance_meta,
                "source_ref": {
                    **(event_meta.get("source_ref") or {}),
                    **source_ref,
                },
            }
            delta = await create_delta_log(
                db,
                str(nid),
                scene_index=scene_index,
                category=event.category,
                field_path=event.field,
                old_value=json.dumps(event.old) if event.old is not None else None,
                new_value=json.dumps(event.new) if event.new is not None else None,
                source="deep_import",
                meta={
                    **merged_meta,
                    **(
                        {"context_snapshot_id": context_snapshot_id}
                        if context_snapshot_id
                        else {}
                    ),
                },
            )
            count += 1
            delta_log_id = delta.get("id")
            if result_refs is not None and delta.get("id"):
                result_refs.append(build_result_ref("delta_log", delta_log_id))
            try:
                event_payload = event.model_dump()
                observation_meta = {**merged_meta}
                observation_meta.pop("scene_id", None)
                event_payload["meta"] = observation_meta
                observation = await create_map_observation_from_delta_event(
                    db,
                    str(nid),
                    event=event_payload,
                    scene_index=scene_index,
                    context_snapshot_id=context_snapshot_id,
                    delta_log_id=delta_log_id,
                )
                if result_refs is not None:
                    result_refs.append(
                        build_result_ref("map_observation", observation["id"])
                    )
            except Exception as exc:
                logger.warning(
                    "Failed to create map observation for delta event %s: %s",
                    event.category,
                    exc,
                )
        return count
