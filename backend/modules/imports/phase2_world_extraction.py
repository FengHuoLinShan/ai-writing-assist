"""Simplified window-level Phase 2 world extraction for deep import."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.deep_import_retry import (
    DeepImportRetryResult,
    run_deep_import_llm_with_retry,
)
from modules.imports.llm_schemas import (
    DeltaEvent,
    ExtractedEntity,
    ExtractedRelation,
    Phase2WorldDelta,
    Phase2WorldExtractionOutput,
    Phase2WorldObject,
    Phase2WorldRelation,
)
from modules.imports.scene_entity_config import current_phase2_project_settings
from modules.imports.scene_entity_extraction import SceneEntityExtractionService
from modules.imports.scene_planning import (
    PHASE0_MAX_MAX_TOKENS,
    PHASE0_TARGET_INPUT_CHARS,
    SceneWindowPlan,
    build_scene_import_plan,
)
from shared.deep_import_settings import (
    deep_import_float_setting,
    deep_import_int_setting,
)
from shared.utils import parse_uuid

PHASE2_WORLD_INPUT_MODE = "scenes_plus_text"
PHASE2_WORLD_PROMPT_LEVEL = "strict"
PHASE2_WORLD_MAX_TOKENS_PER_SOURCE_CHAR = 0.36
PHASE2_WORLD_MIN_MAX_TOKENS = 24_576
PHASE2_WORLD_MAX_MAX_TOKENS = PHASE0_MAX_MAX_TOKENS
PHASE2_WORLD_WINDOW_CONCURRENCY = 3

Phase2WorldLLMCallable = Callable[[dict[str, Any]], Awaitable[Any]]


class Phase2WorldExtractionResult(BaseModel):
    """Production Phase 2 result shape consumed by workflow quality stats."""

    payload: dict[str, Any] = Field(default_factory=dict)
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)


class _WindowWorldResult(BaseModel):
    window: SceneWindowPlan
    output: Phase2WorldExtractionOutput = Field(
        default_factory=Phase2WorldExtractionOutput
    )
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    final_status: str = "failed"
    final_error_type: str | None = None
    invalid_scene_ref_count: int = 0
    overlap_only_count: int = 0
    owned_scene_ids: list[str] = Field(default_factory=list)


class Phase2WorldExtractor:
    """Extract durable world assets from Phase1b Scenes and chapter text."""

    def __init__(
        self,
        llm: Phase2WorldLLMCallable | Any,
        *,
        concurrency: int | None = None,
    ) -> None:
        self.llm = llm
        self.concurrency = max(
            1,
            concurrency
            if concurrency is not None
            else deep_import_int_setting(
                current_phase2_project_settings(),
                "phase2",
                "world_window_concurrency",
                env_name="PHASE2_WORLD_WINDOW_CONCURRENCY",
                default=PHASE2_WORLD_WINDOW_CONCURRENCY,
            ),
        )
        self._legacy = SceneEntityExtractionService()

    async def run(
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
        del existing_checkpoints
        nid = parse_uuid(novel_id, "novel_id")
        scenes = self._legacy._filter_scenes_by_range(
            await self._legacy._get_scenes(db, nid),
            start_chapter=start_chapter,
            end_chapter=end_chapter,
        )
        if not scenes:
            return _empty_result()

        chapter_start, chapter_end = _chapter_range_from_inputs(
            scenes,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
        )
        chapters = await _load_chapters(
            db,
            novel_id,
            chapter_start=chapter_start,
            chapter_end=chapter_end,
        )
        plan = build_scene_import_plan(
            chapters,
            start_chapter=chapter_start,
            end_chapter=chapter_end,
            project_settings=current_phase2_project_settings(),
        )
        if plan.blocked or not plan.windows:
            return {
                **_empty_result(total_scenes=len(scenes)),
                "degraded": True,
                "error_kind": plan.block_reason or "phase2_world_no_windows",
                "error_message": "Phase2 world extraction could not build windows.",
            }

        total_owned_scenes = len(scenes)
        if on_scene_progress is not None:
            await on_scene_progress(0, total_owned_scenes)

        window_results = await self._run_windows(plan.windows, plan.chapters, scenes)

        completed_scene_ids: set[str] = set()
        completed_units = 0
        for result in window_results:
            if result.final_status == "success":
                completed_scene_ids.update(result.owned_scene_ids)
                completed_units = min(total_owned_scenes, len(completed_scene_ids))
            if on_scene_progress is not None:
                await on_scene_progress(completed_units, total_owned_scenes)

        persist_result = await self._persist_outputs(
            db,
            nid,
            window_results,
            scenes,
            workflow_id=workflow_id,
        )
        flush_status = await self._legacy._phase2_flush_with_timeout(db)
        audit_summary = await self._legacy._phase2_audit_summary(
            db,
            str(nid),
            workflow_id=workflow_id,
        )
        snapshot_health_summary = await self._legacy._phase2_snapshot_health_summary(
            db,
            str(nid),
            workflow_id=workflow_id,
        )

        failed_scene_ids = _failed_scene_ids(window_results)
        failed_scene_indices = _scene_indices_for_ids(scenes, failed_scene_ids)
        invalid_refs = sum(result.invalid_scene_ref_count for result in window_results)
        overlap_only = sum(result.overlap_only_count for result in window_results)
        failed_windows = [
            result.window.window_id
            for result in window_results
            if result.final_status != "success"
        ]
        completed_scenes = len(completed_scene_ids)
        checkpoints = _checkpoints(
            self._legacy,
            scenes,
            window_results,
            workflow_id=workflow_id,
            result_refs=persist_result["result_refs"],
        )
        degraded = bool(
            failed_windows
            or invalid_refs
            or overlap_only
            or flush_status.get("degraded")
        )
        error_kind = None
        if failed_windows:
            error_kind = "phase2_world_window_failed"
        elif flush_status.get("error_kind"):
            error_kind = flush_status.get("error_kind")
        elif invalid_refs:
            error_kind = "invalid_scene_refs"
        elif overlap_only:
            error_kind = "overlap_only_items"

        return {
            "parameter_version": "phase2_world_window_v1",
            "total_created": persist_result["total_created"],
            "total_relations": persist_result["total_relations"],
            "total_aliases": persist_result["total_aliases"],
            "total_deltas": persist_result["total_deltas"],
            "total_scenes": total_owned_scenes,
            "completed_scenes": completed_scenes,
            "skipped_scenes": 0,
            "failed_scene_indices": failed_scene_indices,
            "failed_scene_ids": failed_scene_ids,
            "fallback_created": 0,
            "rerun_scenes": 0,
            "stopped_early": False,
            "degraded": degraded,
            "error_kind": error_kind,
            "error_message": _phase2_error_message(error_kind, failed_windows),
            "checkpoints": {"phase2": {"scenes": checkpoints}},
            "audit_summary": audit_summary,
            "snapshot_health_summary": snapshot_health_summary,
            "structured_format_diagnostics": [
                result.diagnostics for result in window_results
            ],
            "alias_relation_skipped": True,
            "alias_relation_skip_reason": "phase2_world_window_v1_inline_output",
            "alias_relation_scenes": 0,
            "alias_relation_failed_scenes": [],
            "alias_relation_format_diagnostics": [],
            "phase2_batches_total": len(window_results),
            "phase2_batches_completed": sum(
                1 for result in window_results if result.final_status == "success"
            ),
            "phase2_batch_size_scenes": 0,
            "phase2_batch_concurrency": self.concurrency,
            "phase2_failed_batches": failed_windows,
            "phase2_degraded_batches": failed_windows,
            "phase2_action_counts": persist_result["action_counts"],
            "phase2_dedup_counts": persist_result["dedup_counts"],
            "phase2_low_confidence": persist_result["low_confidence"],
            "phase2_linked_to_existing": persist_result["linked_to_existing"],
            "phase2_ignored": persist_result["ignored"],
            "phase2_temporary_only": persist_result["temporary_only"],
            "window_count": len(window_results),
            "input_mode": PHASE2_WORLD_INPUT_MODE,
            "prompt_level": PHASE2_WORLD_PROMPT_LEVEL,
            "invalid_scene_ref_count": invalid_refs,
            "overlap_only_count": overlap_only,
            "uncertain_count": persist_result["uncertain_count"],
            "retry_count": sum(
                max(0, int(result.diagnostics.get("attempts", 1) or 1) - 1)
                for result in window_results
            ),
            "max_tokens_per_source_char": _max_tokens_per_source_char(),
            "min_max_tokens": _min_max_tokens(),
            "max_max_tokens": _max_max_tokens(),
        }

    async def _run_windows(
        self,
        windows: Sequence[SceneWindowPlan],
        chapters: Sequence[dict[str, Any]],
        scenes: Sequence[dict[str, Any]],
    ) -> list[_WindowWorldResult]:
        chapter_by_index = {
            int(chapter["chapter_index"]): chapter for chapter in chapters
        }
        semaphore = asyncio.Semaphore(self.concurrency)

        async def process(window: SceneWindowPlan) -> _WindowWorldResult:
            async with semaphore:
                return await self._process_window(window, chapter_by_index, scenes)

        results = await asyncio.gather(*(process(window) for window in windows))
        return sorted(results, key=lambda result: result.window.window_index)

    async def _process_window(
        self,
        window: SceneWindowPlan,
        chapter_by_index: dict[int, dict[str, Any]],
        scenes: Sequence[dict[str, Any]],
    ) -> _WindowWorldResult:
        selected_scenes = _scenes_in_range(
            scenes,
            start=window.covered_start,
            end=window.covered_end,
        )
        owned_scenes = [
            scene
            for scene in selected_scenes
            if window.owned_start <= _scene_start(scene) <= window.owned_end
        ]
        scenes_by_id = {_scene_id(scene): scene for scene in selected_scenes}
        owned_scene_ids = {_scene_id(scene) for scene in owned_scenes}
        chapters = [
            chapter_by_index[index]
            for index in window.chapter_indices
            if index in chapter_by_index
        ]
        attempts = _token_attempts(_phase2_window_max_tokens(window.input_chars))
        retry_results: list[DeepImportRetryResult] = []
        for max_tokens in attempts:
            payload = _window_payload(
                window,
                chapters,
                selected_scenes,
                owned_scenes,
                max_tokens=max_tokens,
            )
            retry_result = await run_deep_import_llm_with_retry(
                lambda payload=payload: self._call_and_validate(payload),
                is_empty_result=_empty_world_output,
                max_retries=1,
                retryable_error_types={
                    "network",
                    "rate_limit",
                    "timeout",
                    "empty_result",
                },
            )
            retry_results.append(retry_result)
            if retry_result.final_status == "success":
                output = retry_result.value
                if not isinstance(output, Phase2WorldExtractionOutput):
                    output = Phase2WorldExtractionOutput.model_validate(output)
                normalized, invalid_refs, overlap_only = _normalize_world_output(
                    output,
                    scenes_by_id=scenes_by_id,
                    owned_scene_ids=owned_scene_ids,
                )
                return _WindowWorldResult(
                    window=window,
                    output=normalized,
                    diagnostics=_diagnostics(window, retry_results, max_tokens),
                    final_status="success",
                    final_error_type=None,
                    invalid_scene_ref_count=invalid_refs,
                    overlap_only_count=overlap_only,
                    owned_scene_ids=sorted(owned_scene_ids),
                )
            if retry_result.final_error_type not in {"schema_error", "empty_result"}:
                break
        final = retry_results[-1] if retry_results else None
        return _WindowWorldResult(
            window=window,
            diagnostics=_diagnostics(window, retry_results, attempts[-1]),
            final_status="failed",
            final_error_type=final.final_error_type if final else "unknown",
            owned_scene_ids=sorted(owned_scene_ids),
        )

    async def _call_and_validate(
        self,
        payload: dict[str, Any],
    ) -> Phase2WorldExtractionOutput:
        output = await self.llm(payload)
        if isinstance(output, Phase2WorldExtractionOutput):
            return output
        return Phase2WorldExtractionOutput.model_validate(output)

    async def _persist_outputs(
        self,
        db: AsyncSession,
        nid,
        window_results: Sequence[_WindowWorldResult],
        scenes: Sequence[dict[str, Any]],
        *,
        workflow_id: str | None,
    ) -> dict[str, Any]:
        scenes_by_id = {_scene_id(scene): scene for scene in scenes}
        seen_entity_keys: set[tuple[str, str]] = set()
        persistence_stats: dict[str, Any] = {
            "action_counts": {},
            "dedup_counts": {
                "checked": 0,
                "auto_merged": 0,
                "candidate_created": 0,
                "review_suggested": 0,
                "relation_merged": 0,
                "degraded": 0,
            },
            "low_confidence": 0,
            "linked_to_existing": 0,
            "ignored": 0,
            "temporary_only": 0,
        }
        result_refs: list[dict[str, str]] = []
        total_created = 0
        total_relations = 0
        total_deltas = 0
        total_aliases = 0
        uncertain_count = 0

        for result in window_results:
            if result.final_status != "success":
                continue
            for item in result.output.objects:
                scene = _primary_scene(item.supporting_scene_ids, scenes_by_id)
                if scene is None:
                    uncertain_count += 1
                    continue
                entities = [_to_extracted_entity(item)]
                total_aliases += len(item.aliases or [])
                total_created += await self._legacy._persist_entities(
                    db,
                    nid,
                    entities,
                    _scene_index(scene),
                    _scene_start(scene),
                    seen_entity_keys=seen_entity_keys,
                    workflow_id=workflow_id,
                    scene_id=_scene_id(scene),
                    scene_provenance_key=self._legacy._scene_provenance_key(
                        workflow_id,
                        scene,
                    ),
                    result_refs=result_refs,
                    persistence_stats=persistence_stats,
                )

        await self._legacy._phase2_flush_with_timeout(db)

        for result in window_results:
            if result.final_status != "success":
                continue
            for relation in result.output.relations:
                scene = _primary_scene(relation.supporting_scene_ids, scenes_by_id)
                if scene is None:
                    uncertain_count += 1
                    continue
                total_relations += await self._legacy._persist_relations(
                    db,
                    nid,
                    [_to_extracted_relation(relation)],
                    _scene_index(scene),
                    workflow_id=workflow_id,
                    result_refs=result_refs,
                    persistence_stats=persistence_stats,
                )
            for delta in result.output.deltas:
                scene = _primary_scene(delta.supporting_scene_ids, scenes_by_id)
                if scene is None:
                    uncertain_count += 1
                    continue
                total_deltas += await self._legacy._record_deltas(
                    db,
                    nid,
                    [_to_delta_event(delta)],
                    _scene_index(scene),
                    workflow_id=workflow_id,
                    scene_id=_scene_id(scene),
                    scene_provenance_key=self._legacy._scene_provenance_key(
                        workflow_id,
                        scene,
                    ),
                    result_refs=result_refs,
                )
            uncertain_count += len(result.output.uncertain_items)

        return {
            "total_created": total_created,
            "total_relations": total_relations,
            "total_deltas": total_deltas,
            "total_aliases": total_aliases,
            "uncertain_count": uncertain_count,
            "result_refs": result_refs,
            **persistence_stats,
        }


def _window_payload(
    window: SceneWindowPlan,
    chapters: Sequence[dict[str, Any]],
    selected_scenes: Sequence[dict[str, Any]],
    owned_scenes: Sequence[dict[str, Any]],
    *,
    max_tokens: int,
) -> dict[str, Any]:
    return {
        "phase": "phase2_world_extraction",
        "input_mode": PHASE2_WORLD_INPUT_MODE,
        "prompt_level": PHASE2_WORLD_PROMPT_LEVEL,
        "window": window.model_dump(mode="json"),
        "chapters": [
            {
                "chapter_index": int(chapter["chapter_index"]),
                "title": str(chapter.get("title") or f"第{chapter['chapter_index']}章"),
                "content": str(chapter.get("content") or ""),
            }
            for chapter in chapters
        ],
        "scenes": [_scene_card(scene) for scene in selected_scenes],
        "owned_scene_ids": [_scene_id(scene) for scene in owned_scenes],
        "all_scene_ids": [_scene_id(scene) for scene in selected_scenes],
        "max_tokens": max_tokens,
    }


async def _load_chapters(
    db: AsyncSession,
    novel_id: str,
    *,
    chapter_start: int,
    chapter_end: int,
) -> list[dict[str, Any]]:
    from modules.writing.facade import list_latest_drafts_for_chapters

    chapter_indices = list(range(chapter_start, chapter_end + 1))
    drafts = await list_latest_drafts_for_chapters(db, novel_id, chapter_indices)
    draft_by_chapter = {int(draft.chapter_index): draft for draft in drafts}
    chapters: list[dict[str, Any]] = []
    for chapter_index in chapter_indices:
        draft = draft_by_chapter.get(chapter_index)
        chapters.append(
            {
                "chapter_index": chapter_index,
                "title": getattr(draft, "title", None) or f"第{chapter_index}章",
                "content": getattr(draft, "content", "") or "",
            }
        )
    return chapters


def _normalize_world_output(
    output: Phase2WorldExtractionOutput,
    *,
    scenes_by_id: dict[str, dict[str, Any]],
    owned_scene_ids: set[str],
) -> tuple[Phase2WorldExtractionOutput, int, int]:
    invalid_refs = 0
    overlap_only = 0
    objects: list[Phase2WorldObject] = []
    relations: list[Phase2WorldRelation] = []
    deltas: list[Phase2WorldDelta] = []
    uncertain = list(output.uncertain_items)

    def normalize_ids(raw_ids: Sequence[str]) -> tuple[list[str], int]:
        valid: list[str] = []
        invalid = 0
        for scene_id in raw_ids:
            if scene_id in scenes_by_id:
                if scene_id not in valid:
                    valid.append(scene_id)
            else:
                invalid += 1
        return valid, invalid

    for item in output.objects:
        scene_ids, invalid = normalize_ids(item.supporting_scene_ids)
        invalid_refs += invalid
        if not scene_ids:
            invalid_refs += 1
            continue
        if not any(scene_id in owned_scene_ids for scene_id in scene_ids):
            overlap_only += 1
            continue
        objects.append(
            item.model_copy(
                update={
                    "supporting_scene_ids": scene_ids,
                    "needs_review": item.needs_review or bool(invalid),
                }
            )
        )
    for item in output.relations:
        scene_ids, invalid = normalize_ids(item.supporting_scene_ids)
        invalid_refs += invalid
        if not scene_ids:
            invalid_refs += 1
            continue
        if not any(scene_id in owned_scene_ids for scene_id in scene_ids):
            overlap_only += 1
            continue
        relations.append(
            item.model_copy(
                update={
                    "supporting_scene_ids": scene_ids,
                    "needs_review": item.needs_review or bool(invalid),
                }
            )
        )
    for item in output.deltas:
        scene_ids, invalid = normalize_ids(item.supporting_scene_ids)
        invalid_refs += invalid
        if not scene_ids:
            invalid_refs += 1
            continue
        if not any(scene_id in owned_scene_ids for scene_id in scene_ids):
            overlap_only += 1
            continue
        deltas.append(
            item.model_copy(
                update={
                    "supporting_scene_ids": scene_ids,
                    "needs_review": item.needs_review or bool(invalid),
                }
            )
        )
    return (
        Phase2WorldExtractionOutput(
            objects=objects,
            relations=relations,
            deltas=deltas,
            uncertain_items=uncertain,
        ),
        invalid_refs,
        overlap_only,
    )


def _to_extracted_entity(item: Phase2WorldObject) -> ExtractedEntity:
    action = _phase2_action(item.suggested_action)
    aliases = [{"alias": alias, "type": "alias"} for alias in item.aliases if alias]
    return ExtractedEntity(
        name=item.name,
        entity_type=item.entity_type or "other",
        summary=item.summary,
        public_info=item.summary,
        hidden_truth="",
        importance=_importance_score(item.importance),
        suggested_action=action,
        suggested_existing_entity_name=item.suggested_existing_name or None,
        candidate_reason=_candidate_reason(item),
        confidence=item.confidence,
        aliases=aliases,
    )


def _to_extracted_relation(item: Phase2WorldRelation) -> ExtractedRelation:
    return ExtractedRelation(
        source_name=item.source_name,
        target_name=item.target_name,
        relation_type=item.relation_type or "related_to",
        description=item.description,
        quote=None,
        strength=item.confidence,
    )


def _to_delta_event(item: Phase2WorldDelta) -> DeltaEvent:
    return DeltaEvent(
        category=item.category or "other",
        field=item.field or None,
        old=item.old,
        new=item.new,
        meta={
            "subject_name": item.subject_name,
            "target_name": item.subject_name,
            "description": item.description,
            "confidence": item.confidence,
            "needs_review": item.needs_review,
            "review_reason": item.review_reason,
            "supporting_scene_ids": item.supporting_scene_ids,
            "source": "phase2_world_window_v1",
        },
    )


def _phase2_action(value: str) -> str:
    text = str(value or "").strip().lower()
    if text in {"ignore", "ignored"}:
        return "ignore"
    if text in {"temporary", "temporary_only"}:
        return "temporary_only"
    if text in {"merge", "update", "link", "link_to_existing"}:
        return "link_to_existing"
    return "create_new"


def _importance_score(value: str) -> float:
    text = str(value or "").strip().lower()
    scores = {
        "high": 0.9,
        "medium": 0.6,
        "mid": 0.6,
        "low": 0.3,
        "高": 0.9,
        "中": 0.6,
        "中等": 0.6,
        "低": 0.3,
    }
    return scores.get(text, 0.6)


def _candidate_reason(item: Phase2WorldObject) -> str:
    parts = []
    if item.needs_review:
        parts.append("needs_review")
    if item.review_reason:
        parts.append(item.review_reason)
    if item.supporting_scene_ids:
        parts.append("supporting_scene_ids=" + ",".join(item.supporting_scene_ids))
    return "；".join(parts)


def _empty_world_output(output: Phase2WorldExtractionOutput) -> bool:
    return not (output.objects or output.relations or output.deltas)


def _empty_result(total_scenes: int = 0) -> dict[str, Any]:
    return {
        "parameter_version": "phase2_world_window_v1",
        "total_created": 0,
        "total_relations": 0,
        "total_aliases": 0,
        "total_deltas": 0,
        "total_scenes": total_scenes,
        "completed_scenes": 0,
        "skipped_scenes": 0,
        "failed_scene_indices": [],
        "failed_scene_ids": [],
        "fallback_created": 0,
        "degraded": False,
        "error_kind": None,
        "error_message": None,
        "checkpoints": {"phase2": {"scenes": []}},
        "alias_relation_skipped": True,
        "alias_relation_skip_reason": "phase2_world_window_v1_no_scenes",
    }


def _chapter_range_from_inputs(
    scenes: Sequence[dict[str, Any]],
    *,
    start_chapter: int | None,
    end_chapter: int | None,
) -> tuple[int, int]:
    if start_chapter is not None and end_chapter is not None:
        return start_chapter, end_chapter
    starts = [_scene_start(scene) for scene in scenes]
    ends = [_scene_end(scene) for scene in scenes]
    return start_chapter or min(starts), end_chapter or max(ends)


def _scenes_in_range(
    scenes: Sequence[dict[str, Any]],
    *,
    start: int,
    end: int,
) -> list[dict[str, Any]]:
    return [
        scene
        for scene in scenes
        if _ranges_overlap(_scene_start(scene), _scene_end(scene), start, end)
    ]


def _ranges_overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start <= b_end and b_start <= a_end


def _scene_card(scene: dict[str, Any]) -> dict[str, Any]:
    return {
        "scene_id": _scene_id(scene),
        "scene_index": _scene_index(scene),
        "title": scene.get("title") or "",
        "goal": scene.get("goal") or "",
        "core_conflict": scene.get("core_conflict") or "",
        "emotional_beat": scene.get("emotional_beat") or "",
        "must_happen": scene.get("must_happen") or "",
        "must_not_happen": scene.get("must_not_happen") or "",
        "narrative_tag": scene.get("narrative_tag") or "",
        "start_chapter": _scene_start(scene),
        "end_chapter": _scene_end(scene),
    }


def _scene_id(scene: dict[str, Any]) -> str:
    return str(scene.get("id") or scene.get("scene_id") or _scene_index(scene))


def _scene_index(scene: dict[str, Any]) -> int:
    try:
        return int(scene.get("scene_index") or 0)
    except (TypeError, ValueError):
        return 0


def _scene_chapters(scene: dict[str, Any]) -> list[int]:
    chapters: set[int] = set()
    for raw in scene.get("chapter_ids") or []:
        try:
            chapters.add(int(raw))
        except (TypeError, ValueError):
            continue
    for chunk in scene.get("scene_chunks") or []:
        if not isinstance(chunk, dict):
            continue
        try:
            chapters.add(int(chunk.get("chapter_index")))
        except (TypeError, ValueError):
            continue
    if not chapters and _scene_index(scene) > 0:
        chapters.add(_scene_index(scene))
    return sorted(chapter for chapter in chapters if chapter > 0)


def _scene_start(scene: dict[str, Any]) -> int:
    chapters = _scene_chapters(scene)
    return chapters[0] if chapters else 1


def _scene_end(scene: dict[str, Any]) -> int:
    chapters = _scene_chapters(scene)
    return chapters[-1] if chapters else _scene_start(scene)


def _primary_scene(
    scene_ids: Sequence[str],
    scenes_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    for scene_id in scene_ids:
        if scene_id in scenes_by_id:
            return scenes_by_id[scene_id]
    return None


def _failed_scene_ids(window_results: Sequence[_WindowWorldResult]) -> list[str]:
    failed: list[str] = []
    for result in window_results:
        if result.final_status == "success":
            continue
        failed.extend(result.owned_scene_ids)
    return sorted(dict.fromkeys(failed))


def _scene_indices_for_ids(
    scenes: Sequence[dict[str, Any]],
    scene_ids: Sequence[str],
) -> list[int]:
    scene_by_id = {_scene_id(scene): scene for scene in scenes}
    return [
        _scene_index(scene_by_id[scene_id])
        for scene_id in scene_ids
        if scene_id in scene_by_id
    ]


def _checkpoints(
    legacy: SceneEntityExtractionService,
    scenes: Sequence[dict[str, Any]],
    window_results: Sequence[_WindowWorldResult],
    *,
    workflow_id: str | None,
    result_refs: list[dict[str, str]],
) -> list[dict[str, Any]]:
    failed_ids = set(_failed_scene_ids(window_results))
    completed_ids = {
        scene_id
        for result in window_results
        if result.final_status == "success"
        for scene_id in result.owned_scene_ids
    }
    checkpoints: list[dict[str, Any]] = []
    for scene in scenes:
        scene_id = _scene_id(scene)
        if scene_id not in failed_ids and scene_id not in completed_ids:
            continue
        status = "failed" if scene_id in failed_ids else "completed"
        checkpoints.append(
            legacy._build_scene_checkpoint(
                scene,
                status=status,
                workflow_id=workflow_id,
                scene_provenance_key=legacy._scene_provenance_key(workflow_id, scene),
                retry_count=0,
                created_entity_ids=legacy._result_ref_ids(result_refs, "core_entity"),
                created_relation_ids=legacy._result_ref_ids(
                    result_refs,
                    "entity_relation",
                ),
                created_delta_ids=legacy._result_ref_ids(result_refs, "memory_delta"),
                error_kind="phase2_world_window_failed" if status == "failed" else None,
            )
        )
    return checkpoints


def _phase2_error_message(
    error_kind: str | None,
    failed_windows: list[str],
) -> str | None:
    if not error_kind:
        return None
    if failed_windows:
        return "Phase2 world extraction failed windows: " + ", ".join(failed_windows)
    return "Phase2 world extraction completed with reviewable diagnostics."


def _token_attempts(initial_max_tokens: int) -> list[int]:
    tokens = [max(1, int(initial_max_tokens))]
    cap = _max_max_tokens()
    if cap > tokens[-1]:
        tokens.append(cap)
    return tokens


def _phase2_window_max_tokens(input_chars: int) -> int:
    estimated = _round_half_up(input_chars * _max_tokens_per_source_char())
    return max(_min_max_tokens(), min(estimated, _max_max_tokens()))


def _round_half_up(value: float) -> int:
    return int(math.floor(value + 0.5))


def _max_tokens_per_source_char() -> float:
    return deep_import_float_setting(
        current_phase2_project_settings(),
        "phase2",
        "world_max_tokens_per_source_char",
        env_name="PHASE2_WORLD_MAX_TOKENS_PER_SOURCE_CHAR",
        default=PHASE2_WORLD_MAX_TOKENS_PER_SOURCE_CHAR,
    )


def _min_max_tokens() -> int:
    return deep_import_int_setting(
        current_phase2_project_settings(),
        "phase2",
        "world_min_max_tokens",
        env_name="PHASE2_WORLD_MIN_MAX_TOKENS",
        default=PHASE2_WORLD_MIN_MAX_TOKENS,
    )


def _max_max_tokens() -> int:
    return deep_import_int_setting(
        current_phase2_project_settings(),
        "phase2",
        "world_max_max_tokens",
        env_name="PHASE2_WORLD_MAX_MAX_TOKENS",
        default=PHASE2_WORLD_MAX_MAX_TOKENS,
    )


def _diagnostics(
    window: SceneWindowPlan,
    retry_results: list[DeepImportRetryResult],
    max_tokens: int,
) -> dict[str, Any]:
    final = retry_results[-1] if retry_results else None
    return {
        "source_batch_id": window.window_id,
        "chapter_indices": window.chapter_indices,
        "owned_chapter_indices": window.owned_chapter_indices,
        "input_chars": window.input_chars,
        "max_tokens": max_tokens,
        "attempts": sum(result.attempts for result in retry_results),
        "final_status": final.final_status if final else "failed",
        "final_error_type": final.final_error_type if final else "unknown",
        "token_attempts": [
            result.model_dump(mode="json", exclude={"value"})
            for result in retry_results
        ],
        "target_input_chars": PHASE0_TARGET_INPUT_CHARS,
    }
