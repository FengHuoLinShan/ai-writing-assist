"""Deterministic task workflow for map-only Scene observation enrichment."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections import defaultdict
from typing import Any

from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.adoption_policy import (
    DEFAULT_ADOPTION_POLICY,
    build_authorization_snapshot,
)
from modules.imports.llm_schemas import (
    ExtractedMapObservationProposal,
    MapSceneObservationEnrichmentOutput,
)
from modules.imports.map_observation_candidates import (
    MapObservationProposalPosition,
    build_map_observation_candidates,
)
from modules.imports.map_observation_enrichment import (
    MAP_OBSERVATION_ENRICHMENT_CONTRACT_VERSION,
    call_map_observation_enrichment,
    materialize_map_observation_enrichment,
    resolve_map_observation_evidence,
)

MAP_OBSERVATION_ENRICHMENT_TASK_TYPE = "map_observation_enrichment"
MAP_OBSERVATION_ENRICHMENT_STAGE = "map_observations"
MAP_OBSERVATION_ENRICHMENT_WORKFLOW_VERSION = 1
MAP_OBSERVATION_ENRICHMENT_MAX_CONCURRENCY = 8
_MAP_ENRICHMENT_STATE_KEY = "_map_observation_enrichment_v1"

_extracted_proposal_adapter = TypeAdapter(ExtractedMapObservationProposal)
logger = logging.getLogger(__name__)


async def submit_map_observation_enrichment(
    db: AsyncSession,
    *,
    novel_id: str,
    start_chapter: int,
    end_chapter: int,
    high_quality: bool = True,
    adoption_policy: str = DEFAULT_ADOPTION_POLICY,
    authorization_confirmed: bool = False,
) -> dict[str, Any]:
    """Queue map-only enrichment without invoking any deep-import stage."""
    from infrastructure.tasks.enqueuer import enqueue_task
    from infrastructure.tasks.models import AsyncTask
    from modules.project.facade import (
        build_project_llm_execution_snapshot,
        require_active_project,
    )
    from shared.utils import parse_uuid

    if start_chapter < 1 or end_chapter < start_chapter:
        raise ValueError("invalid map enrichment chapter range")
    await require_active_project(db, novel_id)
    authorization_snapshot = build_authorization_snapshot(
        novel_id=novel_id,
        start_chapter=start_chapter,
        end_chapter=end_chapter,
        adoption_policy=adoption_policy,
        authorization_confirmed=authorization_confirmed,
        stage=MAP_OBSERVATION_ENRICHMENT_STAGE,
    )
    llm_execution_snapshot = await build_project_llm_execution_snapshot(db, novel_id)
    task_id = enqueue_task(
        db,
        MAP_OBSERVATION_ENRICHMENT_TASK_TYPE,
        meta={
            "novel_id": novel_id,
            "start_chapter": start_chapter,
            "end_chapter": end_chapter,
            "high_quality": high_quality,
            "stage": MAP_OBSERVATION_ENRICHMENT_STAGE,
            "adoption_policy": adoption_policy,
            "authorization_confirmed": True,
            "authorization_snapshot": authorization_snapshot,
            "llm_execution_snapshot": llm_execution_snapshot,
        },
    )
    task = await db.get(AsyncTask, parse_uuid(str(task_id)))
    if task is not None:
        task.result = {
            "workflow_type": MAP_OBSERVATION_ENRICHMENT_TASK_TYPE,
            "authorization_snapshot": authorization_snapshot,
            "llm_execution_snapshot": llm_execution_snapshot,
        }
    await db.flush()
    return {
        "workflow_id": str(task_id),
        "task_id": str(task_id),
        "workflow_type": MAP_OBSERVATION_ENRICHMENT_TASK_TYPE,
        "stage": MAP_OBSERVATION_ENRICHMENT_STAGE,
        "status": "pending",
        "requires_confirmation": False,
        "authorization_snapshot": authorization_snapshot,
        "message": (
            f"地图事实补充任务已提交（第{start_chapter}-{end_chapter}章，不重跑深度导入）"
        ),
    }


async def _commit_map_enrichment_checkpoint(
    db: Any,
    task: Any,
    *,
    result: dict[str, Any],
    progress: float,
) -> None:
    previous_result = getattr(task, "result", None)
    previous_progress = getattr(task, "progress", None)
    missing = object()
    previous_heartbeat = getattr(task, "heartbeat_at", missing)
    task.result = result
    task.update_progress(progress)
    try:
        await db.commit()
    except BaseException:
        task.result = previous_result
        task.progress = previous_progress
        if previous_heartbeat is not missing:
            task.heartbeat_at = previous_heartbeat
        raise
    if db.in_transaction():
        raise RuntimeError("map enrichment checkpoint left a transaction")
    db.expire_all()


def _validate_map_enrichment_task(task: Any) -> dict[str, Any]:
    if str(getattr(task, "task_type", "") or "") != (
        MAP_OBSERVATION_ENRICHMENT_TASK_TYPE
    ):
        raise ValueError("map enrichment task type mismatch")
    if str(getattr(task, "status", "") or "") != "running":
        raise ValueError("map enrichment task must be running")
    if int(getattr(task, "attempt", 0) or 0) < 1:
        raise ValueError("map enrichment task attempt is invalid")
    if not str(getattr(task, "lease_id", "") or ""):
        raise ValueError("map enrichment task lease is required")
    meta = dict(task.meta or {})
    novel_id = str(meta.get("novel_id") or "")
    start_chapter = int(meta.get("start_chapter", 0) or 0)
    end_chapter = int(meta.get("end_chapter", 0) or 0)
    if not novel_id or start_chapter < 1 or end_chapter < start_chapter:
        raise ValueError("map enrichment task scope is invalid")
    authorization = meta.get("authorization_snapshot")
    if not isinstance(authorization, dict):
        raise ValueError("map enrichment authorization snapshot is required")
    scope = authorization.get("scope")
    if (
        authorization.get("authorization_confirmed") is not True
        or authorization.get("adoption_policy") != "user_authorized_pipeline"
        or not isinstance(scope, dict)
        or str(scope.get("novel_id") or "") != novel_id
        or int(scope.get("start_chapter", 0) or 0) != start_chapter
        or int(scope.get("end_chapter", 0) or 0) != end_chapter
        or scope.get("stage") != MAP_OBSERVATION_ENRICHMENT_STAGE
    ):
        raise ValueError("map enrichment authorization scope is invalid")
    snapshot = meta.get("llm_execution_snapshot")
    if not isinstance(snapshot, dict) or not snapshot:
        raise ValueError("map enrichment LLM execution snapshot is required")
    return meta


class MapObservationEnrichmentTaskOrchestrator:
    """Own task checkpoints and fences around the map enrichment workflow."""

    async def run_task(self, db: AsyncSession, task: Any) -> dict[str, Any]:
        from infrastructure.tasks.facade import (
            require_running_task_attempt,
            require_task_checkpoint_session,
        )
        from modules.project.facade import require_active_project_exclusive

        require_task_checkpoint_session(db)
        meta = _validate_map_enrichment_task(task)
        novel_id = str(meta["novel_id"])
        task_id = str(task.id)
        start_chapter = int(meta["start_chapter"])
        end_chapter = int(meta["end_chapter"])
        lease_id = str(task.lease_id)
        attempt = int(task.attempt)
        result_checkpoint = dict(task.result or {})
        state = dict(result_checkpoint.get(_MAP_ENRICHMENT_STATE_KEY) or {})
        if state and state.get("version") != 1:
            raise ValueError("unsupported map enrichment task checkpoint version")
        if state and state.get("stage") not in {"prepared", "llm_complete", "done"}:
            raise ValueError("map enrichment task checkpoint stage is invalid")
        if state.get("stage") == "done":
            final_result = state.get("final_result")
            if not isinstance(final_result, dict):
                raise ValueError("map enrichment final checkpoint is invalid")
            return dict(final_result)

        workflow = MapObservationEnrichmentWorkflow()
        existing_manifest = state.get("manifest") if state else None
        if existing_manifest is not None and not isinstance(existing_manifest, dict):
            raise ValueError("map enrichment prepared checkpoint is invalid")
        prepared = await workflow.prepare(
            db,
            novel_id=novel_id,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            llm_execution_snapshot=meta["llm_execution_snapshot"],
            existing_manifest=existing_manifest,
        )
        manifest = prepared["manifest"]
        runtime_plan = prepared["runtime_plan"]
        project_settings = prepared["project_settings"]
        receipt = state.get("receipt") if state.get("stage") == "llm_complete" else None
        if receipt is None:
            await _commit_map_enrichment_checkpoint(
                db,
                task,
                result={
                    **result_checkpoint,
                    _MAP_ENRICHMENT_STATE_KEY: {
                        "version": 1,
                        "stage": "prepared",
                        "manifest": manifest,
                    },
                },
                progress=0.2,
            )
            receipt = await workflow.execute(
                runtime_plan=runtime_plan,
                project_settings=project_settings,
                novel_id=novel_id,
                high_quality=bool(meta.get("high_quality", True)),
            )
            await _commit_map_enrichment_checkpoint(
                db,
                task,
                result={
                    **dict(task.result or {}),
                    _MAP_ENRICHMENT_STATE_KEY: {
                        "version": 1,
                        "stage": "llm_complete",
                        "manifest": manifest,
                        "receipt": receipt,
                    },
                },
                progress=0.75,
            )
        elif not isinstance(receipt, dict):
            raise ValueError("map enrichment provider receipt is invalid")
        else:
            await db.commit()
            if db.in_transaction():
                raise RuntimeError("map enrichment retry left a transaction")
            db.expire_all()

        await require_active_project_exclusive(db, novel_id)
        await require_running_task_attempt(
            db,
            task_id=task_id,
            task_type=MAP_OBSERVATION_ENRICHMENT_TASK_TYPE,
            novel_id=novel_id,
            lease_id=lease_id,
            attempt=attempt,
        )
        final_result = await workflow.finalize(
            db,
            novel_id=novel_id,
            task_id=task_id,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            authorization_snapshot=meta["authorization_snapshot"],
            llm_execution_snapshot=meta["llm_execution_snapshot"],
            manifest=manifest,
            receipt=receipt,
        )
        await _commit_map_enrichment_checkpoint(
            db,
            task,
            result={
                **final_result,
                "authorization_snapshot": meta["authorization_snapshot"],
                "llm_execution_snapshot": meta["llm_execution_snapshot"],
                _MAP_ENRICHMENT_STATE_KEY: {
                    "version": 1,
                    "stage": "done",
                    "manifest": manifest,
                    "final_result": final_result,
                },
            },
            progress=1.0,
        )
        logger.info(
            "Map observation enrichment complete — scenes=%s, candidates=%s",
            final_result["scene_count"],
            final_result["candidate_created_count"],
        )
        return final_result


class MapObservationEnrichmentWorkflow:
    """Prepare, execute and finalize a resumable map-only extraction task."""

    async def prepare(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        llm_execution_snapshot: dict[str, Any],
        existing_manifest: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from modules.project.facade import (
            require_active_project,
            restore_project_llm_execution_settings,
        )

        await require_active_project(db, novel_id)
        project_settings = await restore_project_llm_execution_settings(
            db,
            novel_id,
            llm_execution_snapshot,
        )
        manifest, runtime_plan = await self._build_runtime_plan(
            db,
            novel_id=novel_id,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
        )
        if existing_manifest is not None and existing_manifest != manifest:
            raise RuntimeError("map enrichment source inputs changed after preparation")
        return {
            "manifest": manifest,
            "runtime_plan": runtime_plan,
            "project_settings": project_settings,
        }

    async def execute(
        self,
        *,
        runtime_plan: dict[str, Any],
        project_settings: dict[str, Any],
        novel_id: str,
        high_quality: bool,
    ) -> dict[str, Any]:
        """Run provider calls without accepting or retaining a DB session."""
        scene_plans = runtime_plan.get("scenes")
        if not isinstance(scene_plans, list):
            raise ValueError("map enrichment runtime plan is invalid")
        semaphore = asyncio.Semaphore(MAP_OBSERVATION_ENRICHMENT_MAX_CONCURRENCY)

        async def extract(scene_plan: dict[str, Any]) -> dict[str, Any]:
            async with semaphore:
                diagnostics: list[dict[str, Any]] = []
                result = await call_map_observation_enrichment(
                    str(scene_plan["scene_text"]),
                    source_parts=scene_plan["source_parts"],
                    prompt_context={
                        "scene_card": scene_plan["scene_card"],
                        "known_map_entities": scene_plan["known_map_entities"],
                    },
                    project_settings=project_settings,
                    novel_id=novel_id,
                    high_quality=high_quality,
                    diagnostics=diagnostics,
                )
                return {
                    "scene_id": scene_plan["scene_id"],
                    "scene_index": scene_plan["scene_index"],
                    "input_fingerprint": scene_plan["input_fingerprint"],
                    "output": result.model_dump(mode="json"),
                    "diagnostics": diagnostics,
                }

        results = await asyncio.gather(
            *(extract(scene_plan) for scene_plan in scene_plans),
            return_exceptions=True,
        )
        failures = [item for item in results if isinstance(item, BaseException)]
        if failures:
            names = ", ".join(type(item).__name__ for item in failures[:5])
            raise RuntimeError(
                f"map enrichment provider failed for {len(failures)} Scene(s): {names}"
            )
        receipts = [item for item in results if isinstance(item, dict)]
        receipts.sort(key=lambda item: (item["scene_index"], item["scene_id"]))
        return {
            "version": MAP_OBSERVATION_ENRICHMENT_WORKFLOW_VERSION,
            "scenes": receipts,
        }

    async def finalize(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        task_id: str,
        start_chapter: int,
        end_chapter: int,
        authorization_snapshot: dict[str, Any],
        llm_execution_snapshot: dict[str, Any],
        manifest: dict[str, Any],
        receipt: dict[str, Any],
    ) -> dict[str, Any]:
        from modules.project.facade import restore_project_llm_execution_settings
        from modules.world.facade import create_map_observation_candidates

        await restore_project_llm_execution_settings(
            db,
            novel_id,
            llm_execution_snapshot,
        )
        current_manifest, runtime_plan = await self._build_runtime_plan(
            db,
            novel_id=novel_id,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
        )
        if current_manifest != manifest:
            raise RuntimeError("map enrichment source inputs changed before finalization")
        if receipt.get("version") != MAP_OBSERVATION_ENRICHMENT_WORKFLOW_VERSION:
            raise ValueError("map enrichment receipt version is invalid")

        scene_plans = {
            str(item["scene_id"]): item for item in runtime_plan.get("scenes", [])
        }
        receipt_scenes = receipt.get("scenes")
        if not isinstance(receipt_scenes, list):
            raise ValueError("map enrichment receipt scenes are invalid")
        expected_scene_ids = set(scene_plans)
        receipt_scene_ids = [
            str(item.get("scene_id") or "")
            for item in receipt_scenes
            if isinstance(item, dict)
        ]
        if (
            len(receipt_scene_ids) != len(receipt_scenes)
            or len(receipt_scene_ids) != len(set(receipt_scene_ids))
            or set(receipt_scene_ids) != expected_scene_ids
        ):
            raise ValueError(
                "map enrichment receipt must contain every prepared Scene exactly once"
            )
        all_candidates = []
        uncertain_count = 0
        uncertain_items: list[dict[str, Any]] = []
        proposal_count = 0
        for scene_receipt in receipt_scenes:
            if not isinstance(scene_receipt, dict):
                raise ValueError("map enrichment scene receipt is invalid")
            scene_id = str(scene_receipt.get("scene_id") or "")
            scene_plan = scene_plans.get(scene_id)
            if scene_plan is None:
                raise ValueError("map enrichment receipt references an unknown Scene")
            if scene_receipt.get("input_fingerprint") != scene_plan.get(
                "input_fingerprint"
            ):
                raise RuntimeError("map enrichment receipt input fingerprint mismatch")
            if int(scene_receipt.get("scene_index", -1)) != int(
                scene_plan["scene_index"]
            ):
                raise RuntimeError("map enrichment receipt Scene index mismatch")
            output = MapSceneObservationEnrichmentOutput.model_validate(
                scene_receipt.get("output")
            )
            output = materialize_map_observation_enrichment(
                output,
                current_scene_text=scene_plan["scene_text"],
                source_parts=scene_plan["source_parts"],
                known_map_entities=scene_plan["known_map_entities"],
            )
            entity_ids = {
                (str(item["entity_type"]), str(item["name"])): str(item["id"])
                for item in scene_plan["canonical_entity_refs"]
            }
            uncertain_count += len(output.uncertain_items)
            uncertain_items.extend(
                {
                    "scene_id": scene_id,
                    "scene_index": int(scene_plan["scene_index"]),
                    **item.model_dump(mode="json"),
                }
                for item in output.uncertain_items
            )
            proposal_count += len(output.map_observation_proposals)
            resolved: list[tuple[int, int, int, Any, str, str | None, str | None]] = []
            for proposal in output.map_observation_proposals:
                position, evidence_issue = resolve_map_observation_evidence(
                    proposal.quote,
                    source_parts=scene_plan["source_parts"],
                )
                if position is None:
                    uncertain_count += 1
                    uncertain_items.append(
                        {
                            "scene_id": scene_id,
                            "scene_index": int(scene_plan["scene_index"]),
                            "description": (
                                f"无法物化地图观察：{proposal.proposal_type}"
                            ),
                            "reason": evidence_issue,
                            "evidence_quotes": [],
                        }
                    )
                    continue
                source_chapter = position.source_chapter_index
                source_start = position.source_start_offset
                source_end = position.source_end_offset
                materialized = _extracted_proposal_adapter.validate_python(
                    {
                        **proposal.model_dump(mode="json"),
                        "supporting_scene_ids": [scene_id],
                    }
                )
                stable_tiebreaker = json.dumps(
                    materialized.model_dump(mode="json"),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                target_entity_id, location_entity_id = _proposal_entity_ids(
                    materialized,
                    entity_ids,
                )
                resolved.append(
                    (
                        source_chapter,
                        source_start,
                        source_end,
                        materialized,
                        stable_tiebreaker,
                        target_entity_id,
                        location_entity_id,
                    )
                )
            resolved.sort(key=lambda item: (item[0], item[1], item[2], item[4]))
            sequence_by_position: dict[tuple[int, int, int], int] = {}
            by_chapter: dict[
                int,
                list[
                    tuple[
                        Any,
                        MapObservationProposalPosition,
                        str | None,
                        str | None,
                    ]
                ],
            ] = defaultdict(list)
            for (
                source_chapter,
                source_start,
                source_end,
                proposal,
                _,
                target_entity_id,
                location_entity_id,
            ) in resolved:
                position_key = (source_chapter, source_start, source_end)
                scene_sequence = sequence_by_position.setdefault(
                    position_key,
                    len(sequence_by_position),
                )
                by_chapter[source_chapter].append(
                    (
                        proposal,
                        MapObservationProposalPosition(
                            scene_sequence=scene_sequence,
                            source_start_offset=source_start,
                            source_end_offset=source_end,
                        ),
                        target_entity_id,
                        location_entity_id,
                    )
                )
            for source_chapter, positioned_proposals in sorted(by_chapter.items()):
                all_candidates.extend(
                    build_map_observation_candidates(
                        [item[0] for item in positioned_proposals],
                        novel_id=novel_id,
                        workflow_id=task_id,
                        task_id=task_id,
                        scene_id=scene_id,
                        scene_index=int(scene_plan["scene_index"]),
                        source_chapter_index=source_chapter,
                        scene_source_fingerprint=scene_plan["input_fingerprint"],
                        source_workflow="map_enrichment",
                        proposal_positions=[item[1] for item in positioned_proposals],
                        target_entity_ids=[item[2] for item in positioned_proposals],
                        location_entity_ids=[item[3] for item in positioned_proposals],
                        authorization_snapshot=authorization_snapshot,
                    )
                )

        batch = await create_map_observation_candidates(
            db,
            novel_id,
            candidates=all_candidates,
        )
        coverage = dict(manifest.get("coverage") or {})
        return {
            "workflow_id": task_id,
            "workflow_type": MAP_OBSERVATION_ENRICHMENT_TASK_TYPE,
            "stage": MAP_OBSERVATION_ENRICHMENT_STAGE,
            "status": "done",
            "scene_count": len(receipt_scenes),
            "proposal_count": proposal_count,
            "candidate_created_count": batch.created_count,
            "candidate_reused_count": batch.reused_count,
            "uncertain_count": uncertain_count,
            "uncertain_items": uncertain_items,
            "coverage": coverage,
            "candidate_ids": [item.observation_id for item in batch.items],
            "message": "地图事实补充完成；结果已进入地图待处理队列",
        }

    async def _build_runtime_plan(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        from modules.outline.facade import (
            get_scene_spans_for_scene,
            get_scenes_by_novel,
        )
        from modules.world.facade import list_entity_terms
        from modules.writing.facade import get_draft

        scenes = await get_scenes_by_novel(
            db,
            novel_id,
            status_filter=["canonical", "draft"],
        )
        scoped_scenes: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for scene in scenes:
            chapter_indices = _chapter_indices(scene.get("chapter_ids"))
            if not any(
                start_chapter <= value <= end_chapter for value in chapter_indices
            ):
                continue
            if not chapter_indices or any(
                value < start_chapter or value > end_chapter for value in chapter_indices
            ):
                skipped.append(
                    {
                        "scene_id": str(scene["id"]),
                        "scene_index": int(scene["scene_index"]),
                        "reason": "scene_crosses_authorized_range",
                    }
                )
                continue
            scoped_scenes.append(scene)

        draft_cache: dict[str, Any] = {}
        claims_by_scene: dict[str, list[dict[str, Any]]] = defaultdict(list)
        claims_by_chapter: dict[int, list[dict[str, Any]]] = defaultdict(list)
        invalid_scenes: dict[str, str] = {}
        for scene in scoped_scenes:
            scene_id = str(scene["id"])
            spans = await get_scene_spans_for_scene(
                db,
                novel_id,
                scene_id,
                status_filter=["canonical", "draft"],
            )
            if not spans:
                invalid_scenes[scene_id] = "scene_has_no_source_spans"
                continue
            for span in sorted(
                spans,
                key=lambda item: (item.chapter_index, item.part_no, item.id),
            ):
                if (
                    span.mapping_status != "exact"
                    or span.start_offset is None
                    or span.end_offset is None
                ):
                    invalid_scenes[scene_id] = "scene_span_is_not_exact"
                    break
                if not span.source_draft_id or not span.source_content_hash:
                    invalid_scenes[scene_id] = "scene_source_draft_missing"
                    break
                draft_id = str(span.source_draft_id)
                draft = draft_cache.get(draft_id)
                if draft is None:
                    draft = await get_draft(db, novel_id, draft_id)
                    draft_cache[draft_id] = draft
                if draft is None or draft.content is None or not draft.content_hash:
                    invalid_scenes[scene_id] = "scene_source_draft_missing"
                    break
                if str(span.source_content_hash) != str(draft.content_hash):
                    invalid_scenes[scene_id] = "scene_source_hash_drift"
                    break
                start_offset = int(span.start_offset)
                end_offset = int(span.end_offset)
                if not 0 <= start_offset < end_offset <= len(draft.content):
                    invalid_scenes[scene_id] = "scene_span_is_not_exact"
                    break
                claim = {
                    "scene_id": scene_id,
                    "scene_index": int(scene["scene_index"]),
                    "chapter_index": int(span.chapter_index),
                    "draft_id": draft_id,
                    "content_hash": str(draft.content_hash),
                    "chapter_length": len(draft.content),
                    "start_offset": start_offset,
                    "end_offset": end_offset,
                    "part_no": int(span.part_no),
                    "allocation_kind": "authoritative_exact_span",
                    "text": draft.content[start_offset:end_offset],
                }
                claims_by_scene[scene_id].append(claim)
                claims_by_chapter[int(span.chapter_index)].append(claim)

        overlapping_scene_ids: set[str] = set()
        ordered_claims_by_chapter: dict[int, list[dict[str, Any]]] = {}
        for chapter_index, raw_claims in sorted(claims_by_chapter.items()):
            claims = [
                item for item in raw_claims if item["scene_id"] not in invalid_scenes
            ]
            if not claims:
                continue
            draft_keys = {(item["draft_id"], item["content_hash"]) for item in claims}
            if len(draft_keys) != 1:
                for item in claims:
                    invalid_scenes[item["scene_id"]] = "chapter_source_versions_conflict"
                continue
            ordered_claims = sorted(
                claims,
                key=lambda item: (
                    item["start_offset"],
                    item["end_offset"],
                    item["scene_index"],
                    item["scene_id"],
                ),
            )
            ordered_claims_by_chapter[chapter_index] = ordered_claims
            for index, current in enumerate(ordered_claims):
                for other in ordered_claims[index + 1 :]:
                    if int(other["start_offset"]) >= int(current["end_offset"]):
                        break
                    if other["scene_id"] != current["scene_id"]:
                        overlapping_scene_ids.update(
                            {str(current["scene_id"]), str(other["scene_id"])}
                        )
        for scene_id in overlapping_scene_ids:
            invalid_scenes[scene_id] = "scene_source_spans_overlap"

        unassigned_ranges: list[dict[str, int]] = []
        for chapter_index, ordered_claims in sorted(ordered_claims_by_chapter.items()):
            covered = _merge_intervals(
                [
                    (int(item["start_offset"]), int(item["end_offset"]))
                    for item in ordered_claims
                    if item["scene_id"] not in invalid_scenes
                ]
            )
            for gap_start, gap_end in _subtract_intervals(
                [(0, int(ordered_claims[0]["chapter_length"]))],
                covered,
            ):
                unassigned_ranges.append(
                    {
                        "chapter_index": chapter_index,
                        "start_offset": gap_start,
                        "end_offset": gap_end,
                    }
                )

        terms = await list_entity_terms(db, novel_id, limit=10_000)
        selected = []
        for scene in scoped_scenes:
            scene_id = str(scene["id"])
            source_parts = sorted(
                claims_by_scene.get(scene_id, []),
                key=lambda item: (
                    item["chapter_index"],
                    item["start_offset"],
                    item["end_offset"],
                    item["part_no"],
                ),
            )
            invalid_reason = invalid_scenes.get(scene_id)
            if invalid_reason is None and not source_parts:
                invalid_reason = "scene_has_no_source_spans"
            if invalid_reason is not None:
                skipped.append(
                    {
                        "scene_id": scene_id,
                        "scene_index": int(scene["scene_index"]),
                        "reason": invalid_reason,
                    }
                )
                continue
            scene_text = "\n".join(item["text"] for item in source_parts)
            scene_terms = _select_map_entities(scene_text, terms)
            known_entities = [
                {
                    "name": str(item["name"]),
                    "entity_type": str(item["entity_type"]),
                    "terms": [str(value) for value in item.get("terms") or []],
                }
                for item in scene_terms
            ]
            canonical_entity_refs = [
                {
                    "id": str(item["id"]),
                    "name": str(item["name"]),
                    "entity_type": str(item["entity_type"]),
                }
                for item in scene_terms
            ]
            fingerprint_payload = {
                "contract_version": MAP_OBSERVATION_ENRICHMENT_CONTRACT_VERSION,
                "scene_id": scene_id,
                "scene_index": int(scene["scene_index"]),
                "title": scene.get("title"),
                "goal": scene.get("goal"),
                "status": scene.get("status"),
                "sources": [
                    {key: value for key, value in item.items() if key != "text"}
                    | {"text_hash": _stable_hash(item["text"])}
                    for item in source_parts
                ],
                "known_map_entities": known_entities,
                "canonical_entity_refs": canonical_entity_refs,
            }
            selected.append(
                {
                    "scene_id": scene_id,
                    "scene_index": int(scene["scene_index"]),
                    "scene_card": {
                        "scene_index": int(scene["scene_index"]),
                        "title": scene.get("title"),
                        "goal": scene.get("goal"),
                        "source_chapters": _chapter_indices(scene.get("chapter_ids")),
                    },
                    "source_parts": source_parts,
                    "scene_text": scene_text,
                    "known_map_entities": known_entities,
                    "canonical_entity_refs": canonical_entity_refs,
                    "input_fingerprint": _stable_hash(fingerprint_payload),
                }
            )

        selected.sort(key=lambda item: (item["scene_index"], item["scene_id"]))
        skipped.sort(key=lambda item: (item["scene_index"], item["scene_id"]))
        manifest = {
            "version": MAP_OBSERVATION_ENRICHMENT_WORKFLOW_VERSION,
            "contract_version": MAP_OBSERVATION_ENRICHMENT_CONTRACT_VERSION,
            "novel_id": novel_id,
            "start_chapter": start_chapter,
            "end_chapter": end_chapter,
            "scenes": [
                {
                    "scene_id": item["scene_id"],
                    "scene_index": item["scene_index"],
                    "input_fingerprint": item["input_fingerprint"],
                }
                for item in selected
            ],
            "coverage": {
                "selected_scene_count": len(selected),
                "skipped_scene_count": len(skipped),
                "skipped_scenes": skipped,
                "overlap_conflict_scene_count": len(overlapping_scene_ids),
                "unassigned_range_count": len(unassigned_ranges),
                "unassigned_ranges": unassigned_ranges,
            },
        }
        return manifest, {"scenes": selected}


def _merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
            continue
        previous_start, previous_end = merged[-1]
        merged[-1] = (previous_start, max(previous_end, end))
    return merged


def _subtract_intervals(
    intervals: list[tuple[int, int]],
    excluded: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    result = _merge_intervals(intervals)
    for excluded_start, excluded_end in _merge_intervals(excluded):
        next_result: list[tuple[int, int]] = []
        for start, end in result:
            if excluded_end <= start or excluded_start >= end:
                next_result.append((start, end))
                continue
            if start < excluded_start:
                next_result.append((start, excluded_start))
            if excluded_end < end:
                next_result.append((excluded_end, end))
        result = next_result
    return result


def _chapter_indices(value: Any) -> list[int]:
    values = value if isinstance(value, list) else []
    result = []
    for item in values:
        try:
            chapter_index = int(item)
        except (TypeError, ValueError):
            continue
        if chapter_index >= 1:
            result.append(chapter_index)
    return sorted(set(result))


def _select_map_entities(
    scene_text: str,
    entity_terms: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep canonical entities whose name or confirmed alias occurs in this Scene."""
    folded_text = scene_text.casefold()
    selected = []
    for item in entity_terms:
        name = str(item.get("name") or "").strip()
        entity_type = str(item.get("entity_type") or "").strip()
        terms = [
            str(value).strip() for value in item.get("terms") or [] if str(value).strip()
        ]
        if not name or not entity_type:
            continue
        if not any(term.casefold() in folded_text for term in [name, *terms]):
            continue
        selected.append(
            {
                "id": str(item["id"]),
                "name": name,
                "entity_type": entity_type,
                "terms": sorted(set([name, *terms]), key=lambda value: value.casefold()),
            }
        )
    selected.sort(key=lambda item: (item["entity_type"], item["name"], item["id"]))
    return selected


def _proposal_entity_ids(
    proposal: Any,
    entity_ids: dict[tuple[str, str], str],
) -> tuple[str | None, str | None]:
    target_entity_id = None
    location_entity_id = None
    if proposal.proposal_type == "character_location":
        target_entity_id = entity_ids.get(("character", str(proposal.character_name)))
        if proposal.location_name:
            location_entity_id = entity_ids.get(("location", str(proposal.location_name)))
    elif proposal.proposal_type == "event_location":
        target_entity_id = entity_ids.get(("event", str(proposal.event_name)))
        if proposal.location_name:
            location_entity_id = entity_ids.get(("location", str(proposal.location_name)))
    elif proposal.proposal_type == "boundary" and proposal.controller_name:
        for entity_type in ("organization", "faction"):
            target_entity_id = entity_ids.get(
                (entity_type, str(proposal.controller_name))
            )
            if target_entity_id:
                break
    return target_entity_id, location_entity_id


def _stable_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = [
    "MAP_OBSERVATION_ENRICHMENT_STAGE",
    "MAP_OBSERVATION_ENRICHMENT_TASK_TYPE",
    "MapObservationEnrichmentTaskOrchestrator",
    "MapObservationEnrichmentWorkflow",
    "submit_map_observation_enrichment",
]
