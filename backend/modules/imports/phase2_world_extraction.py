"""Simplified window-level Phase 2 world extraction for deep import."""

from __future__ import annotations

import asyncio
import math
import re
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.chapter_loader import load_chapter_range
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
    Phase2WorldUncertainItem,
)
from modules.imports.entity_extraction.scene_entity_config import current_phase2_project_settings
from modules.imports.entity_extraction.scene_entity_extraction import SceneEntityExtractionService
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
PHASE2_WORLD_WINDOW_CONCURRENCY = 20
INVALID_SCENE_REF_SAMPLE_LIMIT = 5
WINDOW_DIAGNOSTIC_SAMPLE_LIMIT = 10
UUID_LIKE_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

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
    invalid_scene_ref_diagnostics: dict[str, Any] = Field(default_factory=dict)
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
        on_scene_progress: Callable[..., Awaitable[None]] | None = None,
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
            await on_scene_progress(
                completed=0, total=total_owned_scenes, scene_id=None, chapter=None
            )

        window_results = await self._run_windows(
            plan.windows,
            plan.chapters,
            scenes,
            on_scene_progress=on_scene_progress,
            total_owned_scenes=total_owned_scenes,
        )

        completed_scene_ids: set[str] = set()
        for result in window_results:
            if result.final_status == "success":
                completed_scene_ids.update(result.owned_scene_ids)

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
        invalid_ref_diagnostics = _merge_invalid_ref_diagnostics(window_results)
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
            "phase2_window_diagnostics": _window_diagnostics_for_artifact(
                window_results
            ),
            "phase2_invalid_scene_ref_diagnostics": invalid_ref_diagnostics,
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
            "phase2_world_window_concurrency": self.concurrency,
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
        *,
        on_scene_progress: Callable[..., Awaitable[None]] | None = None,
        total_owned_scenes: int = 0,
    ) -> list[_WindowWorldResult]:
        chapter_by_index = {
            int(chapter["chapter_index"]): chapter for chapter in chapters
        }
        semaphore = asyncio.Semaphore(self.concurrency)
        completed_scene_ids: set[str] = set()
        progress_lock = asyncio.Lock()

        async def process(window: SceneWindowPlan) -> _WindowWorldResult:
            async with semaphore:
                result = await self._process_window(window, chapter_by_index, scenes)
            if on_scene_progress is not None:
                async with progress_lock:
                    if result.final_status == "success":
                        completed_scene_ids.update(result.owned_scene_ids)
                    completed = (
                        min(total_owned_scenes, len(completed_scene_ids))
                        if total_owned_scenes
                        else 0
                    )
                    representative_scene_id = (
                        result.owned_scene_ids[0]
                        if result.owned_scene_ids
                        else None
                    )
                    representative_chapter = (
                        int(window.owned_start)
                        if window.owned_start is not None
                        else None
                    )
                    await on_scene_progress(
                        completed=completed,
                        total=total_owned_scenes,
                        scene_id=representative_scene_id,
                        chapter=representative_chapter,
                    )
            return result

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
        scene_ref_context = _scene_ref_context(
            selected_scenes,
            owned_scene_ids=owned_scene_ids,
        )
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
                (
                    normalized,
                    invalid_refs,
                    overlap_only,
                    invalid_ref_diagnostics,
                ) = _normalize_world_output(
                    output,
                    scenes_by_id=scenes_by_id,
                    owned_scene_ids=owned_scene_ids,
                    diagnostics_context={
                        **scene_ref_context,
                        "window_id": window.window_id,
                        "chapter_indices": window.chapter_indices,
                        "owned_chapter_indices": window.owned_chapter_indices,
                    },
                )
                return _WindowWorldResult(
                    window=window,
                    output=normalized,
                    diagnostics=_diagnostics(window, retry_results, max_tokens),
                    final_status="success",
                    final_error_type=None,
                    invalid_scene_ref_count=invalid_refs,
                    invalid_scene_ref_diagnostics=invalid_ref_diagnostics,
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


def _scene_ref_context(
    scenes: Sequence[dict[str, Any]],
    *,
    owned_scene_ids: set[str],
) -> dict[str, Any]:
    scene_index_values = {
        str(_scene_index(scene)) for scene in scenes if _scene_index(scene) > 0
    }
    chapter_values = {
        str(chapter) for scene in scenes for chapter in _scene_chapters(scene)
    }
    source_counts: dict[str, int] = {}
    for scene in scenes:
        source = _scene_id_source(scene)
        source_counts[source] = source_counts.get(source, 0) + 1
    return {
        "available_scene_ids": [_scene_id(scene) for scene in scenes],
        "owned_scene_ids": sorted(owned_scene_ids),
        "scene_index_values": scene_index_values,
        "chapter_values": chapter_values,
        "available_id_source_counts": source_counts,
    }


def _new_invalid_ref_diagnostic(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "total": 0,
        "category_counts": {},
        "samples": [],
        "sample_limit": INVALID_SCENE_REF_SAMPLE_LIMIT,
        "truncated": False,
        "available_id_source_counts": context.get("available_id_source_counts") or {},
        "available_scene_ids_sample": list(context.get("available_scene_ids") or [])[
            :INVALID_SCENE_REF_SAMPLE_LIMIT
        ],
        "owned_scene_ids_sample": list(context.get("owned_scene_ids") or [])[
            :INVALID_SCENE_REF_SAMPLE_LIMIT
        ],
        "window_id": context.get("window_id"),
        "chapter_indices": list(context.get("chapter_indices") or []),
        "owned_chapter_indices": list(context.get("owned_chapter_indices") or []),
    }


def _record_invalid_ref_sample(
    diagnostic: dict[str, Any],
    *,
    category: str,
    item_type: str,
    item_name: str,
    raw_ids: list[str],
    valid_ids: list[str],
    invalid_ids: list[str],
) -> None:
    counts = diagnostic.setdefault("category_counts", {})
    counts[category] = int(counts.get(category, 0) or 0) + 1
    samples = diagnostic.setdefault("samples", [])
    if len(samples) >= INVALID_SCENE_REF_SAMPLE_LIMIT:
        diagnostic["truncated"] = True
        return
    samples.append(
        {
            "category": category,
            "item_type": item_type,
            "item_name": _short_diag_text(item_name),
            "raw_ids": raw_ids[:INVALID_SCENE_REF_SAMPLE_LIMIT],
            "valid_ids": valid_ids[:INVALID_SCENE_REF_SAMPLE_LIMIT],
            "invalid_ids": invalid_ids[:INVALID_SCENE_REF_SAMPLE_LIMIT],
            "window_id": diagnostic.get("window_id"),
            "available_scene_ids_sample": diagnostic.get(
                "available_scene_ids_sample",
                [],
            ),
            "owned_scene_ids_sample": diagnostic.get("owned_scene_ids_sample", []),
        }
    )


def _invalid_ref_category(scene_id: str, context: dict[str, Any]) -> str:
    text = str(scene_id or "").strip()
    if not text:
        return "empty_after_normalize"
    if text in set(context.get("scene_index_values") or set()):
        return "scene_index_like"
    if text in set(context.get("chapter_values") or set()):
        return "chapter_index_like"
    if UUID_LIKE_RE.match(text):
        return "uuid_like_but_unknown"
    if "-" in text or text.lower().startswith("scene"):
        return "not_in_available_ids"
    return "non_uuid_text"


def _merge_invalid_ref_diagnostics(
    window_results: Sequence[_WindowWorldResult],
) -> dict[str, Any]:
    merged = {
        "total": 0,
        "category_counts": {},
        "samples": [],
        "sample_limit": INVALID_SCENE_REF_SAMPLE_LIMIT,
        "truncated": False,
        "window_count": len(window_results),
        "windows_with_invalid_refs": [],
        "available_id_source_counts": {},
    }
    for result in window_results:
        diagnostic = result.invalid_scene_ref_diagnostics or {}
        total = int(diagnostic.get("total", 0) or 0)
        merged["total"] += total
        if total:
            merged["windows_with_invalid_refs"].append(result.window.window_id)
        for category, count in (diagnostic.get("category_counts") or {}).items():
            counts = merged["category_counts"]
            counts[category] = int(counts.get(category, 0) or 0) + int(count or 0)
        for source, count in (diagnostic.get("available_id_source_counts") or {}).items():
            sources = merged["available_id_source_counts"]
            sources[source] = int(sources.get(source, 0) or 0) + int(count or 0)
        for sample in diagnostic.get("samples") or []:
            if len(merged["samples"]) >= INVALID_SCENE_REF_SAMPLE_LIMIT:
                merged["truncated"] = True
                break
            merged["samples"].append(sample)
        if diagnostic.get("truncated"):
            merged["truncated"] = True
    merged["sampled_count"] = len(merged["samples"])
    return merged


def _window_diagnostics_for_artifact(
    window_results: Sequence[_WindowWorldResult],
) -> dict[str, Any]:
    diagnostics = [_safe_window_diagnostic(result) for result in window_results]
    slowest = sorted(
        diagnostics,
        key=lambda item: int(item.get("elapsed_ms_total", 0) or 0),
        reverse=True,
    )[:WINDOW_DIAGNOSTIC_SAMPLE_LIMIT]
    failed = [
        item
        for item in diagnostics
        if str(item.get("final_status") or "") != "success"
    ][:WINDOW_DIAGNOSTIC_SAMPLE_LIMIT]
    sampled = diagnostics[:WINDOW_DIAGNOSTIC_SAMPLE_LIMIT]
    return {
        "total": len(diagnostics),
        "sampled_count": len(sampled),
        "truncated": len(diagnostics) > len(sampled),
        "samples": sampled,
        "slowest": slowest,
        "failed": failed,
    }


def _safe_window_diagnostic(result: _WindowWorldResult) -> dict[str, Any]:
    diagnostic = result.diagnostics or {}
    token_attempts = [
        _safe_retry_result(item) for item in diagnostic.get("token_attempts") or []
    ]
    return {
        "source_batch_id": diagnostic.get("source_batch_id"),
        "chapter_indices": diagnostic.get("chapter_indices") or [],
        "owned_chapter_indices": diagnostic.get("owned_chapter_indices") or [],
        "input_chars": int(diagnostic.get("input_chars", 0) or 0),
        "max_tokens": int(diagnostic.get("max_tokens", 0) or 0),
        "attempts": int(diagnostic.get("attempts", 0) or 0),
        "final_status": diagnostic.get("final_status"),
        "final_error_type": diagnostic.get("final_error_type"),
        "elapsed_ms_total": sum(
            int(item.get("elapsed_ms", 0) or 0)
            for attempt in token_attempts
            for item in attempt.get("diagnostics", [])
        ),
        "token_attempts": token_attempts,
        "invalid_scene_ref_count": result.invalid_scene_ref_count,
        "overlap_only_count": result.overlap_only_count,
    }


def _safe_retry_result(item: Any) -> dict[str, Any]:
    if hasattr(item, "model_dump"):
        item = item.model_dump(mode="json", exclude={"value"})
    if not isinstance(item, dict):
        return {}
    attempts = [
        _safe_attempt_diagnostic(attempt)
        for attempt in item.get("diagnostics") or []
        if isinstance(attempt, dict)
    ]
    return {
        "attempts": int(item.get("attempts", 0) or 0),
        "final_status": item.get("final_status"),
        "final_error_type": item.get("final_error_type"),
        "elapsed_ms_total": sum(
            int(attempt.get("elapsed_ms", 0) or 0) for attempt in attempts
        ),
        "diagnostics": attempts,
    }


def _safe_attempt_diagnostic(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "attempt": item.get("attempt"),
        "status": item.get("status"),
        "error_type": item.get("error_type"),
        "elapsed_ms": item.get("elapsed_ms"),
        "retry_scheduled": bool(item.get("retry_scheduled")),
    }


def _short_diag_text(value: Any, *, limit: int = 80) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else f"{text[:limit]}..."


async def _load_chapters(
    db: AsyncSession,
    novel_id: str,
    *,
    chapter_start: int,
    chapter_end: int,
) -> list[dict[str, Any]]:
    return await load_chapter_range(
        db,
        novel_id,
        chapter_start,
        chapter_end,
        include_missing=True,
    )


def _normalize_world_output(
    output: Phase2WorldExtractionOutput,
    *,
    scenes_by_id: dict[str, dict[str, Any]],
    owned_scene_ids: set[str],
    diagnostics_context: dict[str, Any] | None = None,
) -> tuple[Phase2WorldExtractionOutput, int, int, dict[str, Any]]:
    invalid_refs = 0
    overlap_only = 0
    objects: list[Phase2WorldObject] = []
    relations: list[Phase2WorldRelation] = []
    deltas: list[Phase2WorldDelta] = []
    uncertain: list[Phase2WorldUncertainItem] = []
    diagnostic = _new_invalid_ref_diagnostic(diagnostics_context or {})

    def normalize_ids(
        raw_ids: Sequence[str],
        *,
        item_type: str,
        item_name: str,
    ) -> tuple[list[str], int]:
        valid: list[str] = []
        invalid = 0
        raw_values = [str(scene_id).strip() for scene_id in raw_ids if scene_id]
        if not raw_values:
            _record_invalid_ref_sample(
                diagnostic,
                category="empty_after_normalize",
                item_type=item_type,
                item_name=item_name,
                raw_ids=[],
                valid_ids=[],
                invalid_ids=[],
            )
            return valid, 1
        for scene_id in raw_values:
            if scene_id in scenes_by_id:
                if scene_id not in valid:
                    valid.append(scene_id)
            else:
                invalid += 1
                category = _invalid_ref_category(
                    scene_id,
                    diagnostics_context or {},
                )
                _record_invalid_ref_sample(
                    diagnostic,
                    category=category,
                    item_type=item_type,
                    item_name=item_name,
                    raw_ids=raw_values,
                    valid_ids=valid,
                    invalid_ids=[scene_id],
                )
        return valid, invalid

    for item in output.objects:
        scene_ids, invalid = normalize_ids(
            item.supporting_scene_ids,
            item_type="object",
            item_name=item.name,
        )
        invalid_refs += invalid
        if not scene_ids:
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
        scene_ids, invalid = normalize_ids(
            item.supporting_scene_ids,
            item_type="relation",
            item_name=f"{item.source_name}->{item.target_name}",
        )
        invalid_refs += invalid
        if not scene_ids:
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
        scene_ids, invalid = normalize_ids(
            item.supporting_scene_ids,
            item_type="delta",
            item_name=item.subject_name,
        )
        invalid_refs += invalid
        if not scene_ids:
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
    for item in output.uncertain_items:
        scene_ids, invalid = normalize_ids(
            item.supporting_scene_ids,
            item_type="uncertain_item",
            item_name="uncertain_item",
        )
        invalid_refs += invalid
        uncertain.append(item.model_copy(update={"supporting_scene_ids": scene_ids}))
    diagnostic["total"] = invalid_refs
    return (
        Phase2WorldExtractionOutput(
            objects=objects,
            relations=relations,
            deltas=deltas,
            uncertain_items=uncertain,
        ),
        invalid_refs,
        overlap_only,
        diagnostic,
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
        "display_index_do_not_use_as_supporting_scene_id": _scene_index(scene),
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


def _scene_id_source(scene: dict[str, Any]) -> str:
    if scene.get("id"):
        return "id"
    if scene.get("scene_id"):
        return "scene_id"
    return "scene_index_fallback"


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
    token_attempts = [_safe_retry_result(result) for result in retry_results]
    return {
        "source_batch_id": window.window_id,
        "chapter_indices": window.chapter_indices,
        "owned_chapter_indices": window.owned_chapter_indices,
        "input_chars": window.input_chars,
        "max_tokens": max_tokens,
        "attempts": sum(result.attempts for result in retry_results),
        "final_status": final.final_status if final else "failed",
        "final_error_type": final.final_error_type if final else "unknown",
        "elapsed_ms_total": sum(
            int(item.get("elapsed_ms", 0) or 0)
            for attempt in token_attempts
            for item in attempt.get("diagnostics", [])
        ),
        "token_attempts": token_attempts,
        "target_input_chars": PHASE0_TARGET_INPUT_CHARS,
        "diagnostic_type": "phase2_world_window",
    }
