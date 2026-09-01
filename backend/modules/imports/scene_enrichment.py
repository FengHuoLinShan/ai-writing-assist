"""Phase 1b per-Scene enrichment for deep import."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

from modules.imports.deep_import_retry import run_deep_import_llm_with_retry
from modules.imports.env_helpers import positive_int_env
from modules.imports.llm_schemas import SceneChunk, SceneEnrichmentOutput
from modules.imports.scene_fusion import FinalSceneCandidate
from modules.imports.scene_slicing import SceneSliceCandidate

PHASE1B_ENRICH_CONCURRENCY = 200
PHASE1B_ENRICH_MAX_TOKENS = 32_768
PHASE1B_ENRICH_MAX_RETRIES = 1
PHASE1B_CONTEXT_CONTRACT_VERSION = "phase1b-context-v3"
PHASE1B_CHARACTER_TOP_K = 6
PHASE1B_WORLD_OBJECT_TOP_K = 16

SceneEnrichmentLLMCallable = Callable[[dict[str, Any]], Awaitable[Any]]
Phase1bFieldStatus = Literal["present", "not_applicable", "uncertain"]


class Phase1bEnrichmentResult(BaseModel):
    """Phase 1b enrichment result kept in task state only."""

    candidates: list[FinalSceneCandidate] = Field(default_factory=list)
    quality_stats: dict[str, Any] = Field(default_factory=dict)
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)
    degraded: bool = False
    blocked: bool = False
    block_reason: str | None = None


class Phase1bSceneEnricher:
    """Enrich Phase 1a locked Scene slices without changing boundaries."""

    def __init__(
        self,
        llm: SceneEnrichmentLLMCallable | Any,
        *,
        concurrency: int | None = None,
        max_retries: int = PHASE1B_ENRICH_MAX_RETRIES,
        max_tokens: int | None = None,
    ) -> None:
        self.llm = llm
        self.concurrency = max(
            1,
            concurrency
            if concurrency is not None
            else positive_int_env(
                "PHASE1B_ENRICH_CONCURRENCY",
                PHASE1B_ENRICH_CONCURRENCY,
            ),
        )
        self.max_retries = max(0, min(max_retries, 1))
        self.max_tokens = (
            positive_int_env(
                "PHASE1B_ENRICH_MAX_TOKENS",
                PHASE1B_ENRICH_MAX_TOKENS,
            )
            if max_tokens is None
            else max(1, int(max_tokens))
        )

    async def run(
        self,
        *,
        scenes: Sequence[SceneSliceCandidate],
        chapters: Sequence[dict[str, Any]],
        phase1a_context: dict[str, Any] | None = None,
        on_batch_progress: Callable[[int, int, str], Awaitable[None]] | None = None,
    ) -> Phase1bEnrichmentResult:
        chapter_by_index = {
            int(chapter["chapter_index"]): chapter for chapter in chapters
        }
        ordered_scenes = list(scenes)
        semaphore = asyncio.Semaphore(self.concurrency)
        total_scenes = len(ordered_scenes)
        completed = 0
        progress_lock = asyncio.Lock()

        async def process(index: int, scene: SceneSliceCandidate) -> _EnrichOneResult:
            nonlocal completed
            previous_scene = ordered_scenes[index - 1] if index > 0 else None
            async with semaphore:
                result = await self._process_scene(
                    index + 1,
                    scene,
                    chapter_by_index,
                    previous_scene=previous_scene,
                    phase1a_context=phase1a_context or {},
                )
            async with progress_lock:
                completed += 1
                if on_batch_progress is not None:
                    await on_batch_progress(completed, total_scenes, scene.candidate_id)
            return result

        results = await asyncio.gather(
            *(process(index, scene) for index, scene in enumerate(ordered_scenes))
        )
        candidates = [result.candidate for result in results]
        diagnostics = [result.diagnostics for result in results]
        quality_stats = _quality_stats(results)
        return Phase1bEnrichmentResult(
            candidates=candidates,
            quality_stats=quality_stats,
            diagnostics=diagnostics,
            degraded=quality_stats["fallback_count"] > 0,
            blocked=False,
            block_reason=(
                "phase1b_enrichment_fallback"
                if quality_stats["fallback_count"] > 0
                else None
            ),
        )

    async def _process_scene(
        self,
        sequence_index: int,
        scene: SceneSliceCandidate,
        chapter_by_index: dict[int, dict[str, Any]],
        *,
        previous_scene: SceneSliceCandidate | None,
        phase1a_context: dict[str, Any],
    ) -> _EnrichOneResult:
        scene_source, source_integrity = _materialize_scene_source(
            scene,
            chapter_by_index,
        )
        related_context, context_fingerprint = _related_context_for_scene(
            scene,
            previous_scene=previous_scene,
            scene_source=scene_source,
            phase1a_context=phase1a_context,
        )
        payload = _scene_payload(
            scene,
            scene_source=scene_source,
            source_integrity=source_integrity,
            related_context=related_context,
            context_fingerprint=context_fingerprint,
            sequence_index=sequence_index,
            max_tokens=self.max_tokens,
        )

        if not source_integrity["complete"]:
            error_kind = "source_integrity"
            diagnostics = {
                "attempts": 0,
                "final_status": "failed",
                "final_error_type": error_kind,
                "candidate_id": scene.candidate_id,
                "start_chapter": scene.start_chapter,
                "end_chapter": scene.end_chapter,
                "max_tokens": self.max_tokens,
                "source_integrity": _compact_source_integrity(source_integrity),
                "context_fingerprint": context_fingerprint,
            }
            candidate = _final_candidate(
                scene,
                _fallback_enrichment(),
                sequence_index=sequence_index,
                fallback_required=True,
                source_integrity=source_integrity,
                context_fingerprint=context_fingerprint,
                extra_review_reason="Phase1b source integrity validation failed.",
            )
            return _EnrichOneResult(
                candidate=candidate,
                diagnostics=diagnostics,
                fallback=True,
            )

        retry_result = await run_deep_import_llm_with_retry(
            lambda: self._call_and_validate(payload),
            is_empty_result=_empty_enrichment,
            max_retries=self.max_retries,
            retryable_error_types={
                "network",
                "rate_limit",
                "timeout",
                "empty_result",
            },
        )
        diagnostics = retry_result.model_dump(mode="json", exclude={"value"})
        diagnostics["candidate_id"] = scene.candidate_id
        diagnostics["start_chapter"] = scene.start_chapter
        diagnostics["end_chapter"] = scene.end_chapter
        diagnostics["max_tokens"] = self.max_tokens
        diagnostics["source_integrity"] = _compact_source_integrity(source_integrity)
        diagnostics["context_fingerprint"] = context_fingerprint

        if retry_result.final_status != "success":
            error_kind = retry_result.final_error_type or "phase1b_failed"
            candidate = _final_candidate(
                scene,
                _fallback_enrichment(),
                sequence_index=sequence_index,
                fallback_required=True,
                source_integrity=source_integrity,
                context_fingerprint=context_fingerprint,
                extra_review_reason=f"Phase1b enrichment fallback: {error_kind}.",
            )
            return _EnrichOneResult(
                candidate=candidate,
                diagnostics=diagnostics,
                fallback=True,
            )

        output = retry_result.value
        if not isinstance(output, SceneEnrichmentOutput):
            output = SceneEnrichmentOutput.model_validate(output)
        output = _validate_enrichment_evidence(output, scene_source)
        candidate = _final_candidate(
            scene,
            output,
            sequence_index=sequence_index,
            fallback_required=False,
            source_integrity=source_integrity,
            context_fingerprint=context_fingerprint,
        )
        return _EnrichOneResult(
            candidate=candidate,
            diagnostics=diagnostics,
            fallback=False,
        )

    async def _call_and_validate(
        self,
        payload: dict[str, Any],
    ) -> SceneEnrichmentOutput:
        output = await self.llm(payload)
        if isinstance(output, SceneEnrichmentOutput):
            return output
        return SceneEnrichmentOutput.model_validate(output)


class _EnrichOneResult(BaseModel):
    candidate: FinalSceneCandidate
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    fallback: bool = False


def _scene_payload(
    scene: SceneSliceCandidate,
    *,
    scene_source: list[dict[str, Any]],
    source_integrity: dict[str, Any],
    related_context: dict[str, Any],
    context_fingerprint: str,
    sequence_index: int,
    max_tokens: int,
) -> dict[str, Any]:
    return {
        "phase": "phase1b_enrichment",
        "sequence_index": sequence_index,
        "locked_scene": scene.model_dump(mode="json", exclude={"diagnostics"}),
        "scene_source": scene_source,
        "source_integrity": source_integrity,
        "related_context": related_context,
        "context_fingerprint": context_fingerprint,
        "max_tokens": max_tokens,
    }


def _materialize_scene_source(
    scene: SceneSliceCandidate,
    chapter_by_index: dict[int, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    issues: list[str] = []
    materialized: list[dict[str, Any]] = []
    ordered_chunks = sorted(scene.scene_chunks, key=_chunk_sort_key)
    materialized_chapters: set[int] = set()
    last_end_by_chapter: dict[int, int] = {}
    total_chars = 0

    if not ordered_chunks:
        issues.append("missing_scene_chunks")

    for chunk_index, chunk in enumerate(ordered_chunks, start=1):
        chapter = chapter_by_index.get(chunk.chapter_index)
        if chapter is None:
            issues.append(f"missing_chapter:{chunk.chapter_index}")
            continue
        content = str(chapter.get("content") or "")
        chapter_hash = str(chapter.get("source_content_hash") or "")
        computed_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        chapter_draft_id = str(chapter.get("source_draft_id") or "")
        chunk_draft_id = str(chunk.source_draft_id or "")
        chunk_hash = str(chunk.source_content_hash or "")
        start = chunk.start_offset
        end = chunk.end_offset

        chunk_issues: list[str] = []
        if start is None or end is None:
            chunk_issues.append("missing_offsets")
        elif start < 0 or end <= start or end > len(content):
            chunk_issues.append("invalid_offsets")
        if not chapter_draft_id or not chunk_draft_id:
            chunk_issues.append("missing_source_draft_id")
        elif chapter_draft_id != chunk_draft_id:
            chunk_issues.append("source_draft_id_mismatch")
        if not chapter_hash or chapter_hash != computed_hash:
            chunk_issues.append("chapter_content_hash_mismatch")
        if not chunk_hash or chunk_hash != chapter_hash:
            chunk_issues.append("source_content_hash_mismatch")
        if (
            start is not None
            and end is not None
            and chunk.chapter_index in last_end_by_chapter
            and start < last_end_by_chapter[chunk.chapter_index]
        ):
            chunk_issues.append("overlapping_chunks")

        if chunk_issues:
            issues.extend(
                f"chunk_{chunk_index}:{issue}" for issue in dict.fromkeys(chunk_issues)
            )
            continue

        assert start is not None and end is not None
        text = content[start:end]
        if len(text) != end - start:
            issues.append(f"chunk_{chunk_index}:incomplete_span")
            continue
        materialized.append(
            {
                "chunk_index": chunk_index,
                "chapter_index": chunk.chapter_index,
                "chapter_title": str(
                    chapter.get("title") or f"第{chunk.chapter_index}章"
                ),
                "start_offset": start,
                "end_offset": end,
                "source_draft_id": chunk_draft_id,
                "source_content_hash": chunk_hash,
                "text": text,
            }
        )
        materialized_chapters.add(chunk.chapter_index)
        last_end_by_chapter[chunk.chapter_index] = end
        total_chars += len(text)

    expected_chapters = sorted(set(scene.source_chapter_indices))
    actual_chapters = sorted(materialized_chapters)
    if actual_chapters != expected_chapters:
        issues.append("source_chapter_coverage_mismatch")
    if len(materialized) != len(ordered_chunks):
        issues.append("chunk_materialization_incomplete")

    issues = list(dict.fromkeys(issues))
    source_fingerprint = _stable_hash(
        {
            "candidate_id": scene.candidate_id,
            "chunks": materialized,
        }
    )
    integrity = {
        "complete": not issues,
        "status": "exact" if not issues else "invalid",
        "issues": issues,
        "chunk_count": len(ordered_chunks),
        "materialized_chunk_count": len(materialized),
        "expected_chapter_indices": expected_chapters,
        "materialized_chapter_indices": actual_chapters,
        "total_chars": total_chars,
        "source_fingerprint": source_fingerprint,
    }
    return materialized, integrity


def _chunk_sort_key(chunk: SceneChunk) -> tuple[int, int, int]:
    return (
        chunk.chapter_index,
        chunk.start_offset if chunk.start_offset is not None else -1,
        chunk.end_offset if chunk.end_offset is not None else -1,
    )


def _related_context_for_scene(
    scene: SceneSliceCandidate,
    *,
    previous_scene: SceneSliceCandidate | None,
    scene_source: Sequence[dict[str, Any]],
    phase1a_context: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    selected_windows = _select_context_windows(scene, phase1a_context)
    outline_scenes: list[dict[str, Any]] = []
    outline_arcs: list[dict[str, Any]] = []
    plot_threads: list[dict[str, Any]] = []
    warnings: list[Any] = []
    source_windows: list[dict[str, Any]] = []

    for window in selected_windows:
        reference = window.get("reference_context") or {}
        outline = reference.get("outline") or {}
        outline_scenes.extend(
            item
            for item in _dict_items(outline.get("scenes"))
            if _item_visible_by_scene_end(item, scene.end_chapter, "chapter_indices")
        )
        outline_arcs.extend(
            item
            for item in _dict_items(outline.get("arcs"))
            if _item_visible_by_scene_end(item, scene.end_chapter, "end_chapter")
        )
        plot_threads.extend(
            item
            for item in _dict_items(outline.get("plot_threads"))
            if _item_visible_by_scene_end(
                item,
                scene.end_chapter,
                "planned_payoff_chapter",
            )
        )
        source_windows.append(
            {
                "window_id": str(window.get("window_id") or ""),
                "range": reference.get("range") or {},
                "content_hash": str(reference.get("content_hash") or ""),
            }
        )

    visible_text = "\n".join(str(item.get("text") or "") for item in scene_source)
    related_context = {
        "contract_version": PHASE1B_CONTEXT_CONTRACT_VERSION,
        "phase1a_context_contract_version": str(
            phase1a_context.get("contract_version") or ""
        ),
        "phase1a_context_fingerprint": str(phase1a_context.get("fingerprint") or ""),
        "source_windows": source_windows,
        "current_scene": _compact_locked_scene(scene),
        "adjacent_scenes": {
            "previous": (
                _compact_locked_scene(previous_scene)
                if previous_scene is not None
                else None
            ),
        },
        "context_role": "director_only",
        "outline": {
            "scenes": _dedupe_context_items(outline_scenes),
            "arcs": _dedupe_context_items(outline_arcs),
            "plot_threads": _dedupe_context_items(plot_threads),
            "warnings": _dedupe_values(warnings),
        },
        "characters": _ranked_context_items(
            selected_windows,
            key="characters",
            limit=PHASE1B_CHARACTER_TOP_K,
            visible_text=visible_text,
        ),
        "world_objects": _ranked_context_items(
            selected_windows,
            key="world_objects",
            limit=PHASE1B_WORLD_OBJECT_TOP_K,
            visible_text=visible_text,
        ),
    }
    return related_context, _stable_hash(related_context)


def _item_visible_by_scene_end(item: dict[str, Any], cutoff: int, field: str) -> bool:
    value = item.get(field)
    if field == "chapter_indices":
        values = value if isinstance(value, list) else []
        try:
            return bool(values) and max(int(item) for item in values) < cutoff
        except (TypeError, ValueError):
            return False
    try:
        return int(value) < cutoff
    except (TypeError, ValueError):
        return False


def _select_context_windows(
    scene: SceneSliceCandidate,
    phase1a_context: dict[str, Any],
) -> list[dict[str, Any]]:
    windows = _dict_items(phase1a_context.get("windows"))
    exact = [
        window
        for window in windows
        if str(window.get("window_id") or "") == scene.source_window_id
    ]
    overlaps = [
        window
        for window in windows
        if window not in exact and _window_overlaps_scene(window, scene)
    ]
    return [*exact, *overlaps]


def _window_overlaps_scene(
    window: dict[str, Any],
    scene: SceneSliceCandidate,
) -> bool:
    reference = window.get("reference_context") or {}
    ranges = reference.get("range") or {}
    raw_range = ranges.get("covered") or ranges.get("owned") or []
    if not isinstance(raw_range, list | tuple) or len(raw_range) != 2:
        return False
    try:
        start, end = int(raw_range[0]), int(raw_range[1])
    except (TypeError, ValueError):
        return False
    return start <= scene.end_chapter and end >= scene.start_chapter


def _compact_locked_scene(scene: SceneSliceCandidate) -> dict[str, Any]:
    return scene.model_dump(mode="json", exclude={"diagnostics"})


def _dict_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _dedupe_context_items(items: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        identity = str(item.get("id") or "") or _stable_hash(item)
        if identity in seen:
            continue
        seen.add(identity)
        result.append(item)
    return result


def _ranked_context_items(
    windows: Sequence[dict[str, Any]],
    *,
    key: Literal["characters", "world_objects"],
    limit: int,
    visible_text: str,
) -> list[dict[str, Any]]:
    """Merge overlapping Phase 1a Top-K sets without losing their rank signal."""
    reason_rank = {
        "text_mention": 0,
        "scene_relation": 1,
        "outline_relation": 2,
    }
    best_by_id: dict[str, tuple[tuple[int, int, int, str, int], dict[str, Any]]] = {}
    for window_position, window in enumerate(windows):
        reference = window.get("reference_context") or {}
        trace = reference.get("selection_trace") or {}
        included = trace.get("included") or {}
        trace_items = _dict_items(included.get(key))
        trace_by_id = {
            str(item.get("id") or ""): item for item in trace_items if item.get("id")
        }
        ranges = reference.get("range") or {}
        raw_range = ranges.get("covered") or ranges.get("owned") or []
        try:
            window_start = int(raw_range[0])
        except (IndexError, TypeError, ValueError):
            window_start = 1_000_000_000 + window_position
        for item_position, item in enumerate(_dict_items(reference.get(key))):
            identity = str(item.get("id") or "") or _stable_hash(item)
            item_trace = trace_by_id.get(identity) or {}
            reason = str(item_trace.get("reason") or "")
            try:
                first_order = int(item_trace.get("first_order"))
            except (TypeError, ValueError):
                first_order = item_position
            rank = (
                reason_rank.get(reason, 3),
                window_start,
                first_order,
                identity,
                window_position,
            )
            current = best_by_id.get(identity)
            if current is None or rank < current[0]:
                best_by_id[identity] = (rank, item)
    visible = [
        compact
        for _rank, item in sorted(best_by_id.values(), key=lambda value: value[0])
        for compact in [_identity_only_context(item)]
        if any(
            term and term in visible_text
            for term in [compact.get("name"), *(compact.get("aliases") or [])]
        )
    ]
    return visible[:limit]


def _identity_only_context(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item[key]
        for key in (
            "id",
            "entity_id",
            "character_id",
            "entity_type",
            "name",
            "aliases",
            "status",
        )
        if item.get(key) not in (None, "", [])
    }


def _dedupe_values(values: Sequence[Any]) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for value in values:
        identity = _stable_json(value)
        if identity in seen:
            continue
        seen.add(identity)
        result.append(value)
    return result


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _stable_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _compact_source_integrity(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value[key]
        for key in (
            "complete",
            "status",
            "issues",
            "chunk_count",
            "materialized_chunk_count",
            "expected_chapter_indices",
            "materialized_chapter_indices",
            "total_chars",
            "source_fingerprint",
        )
    }


def _empty_enrichment(_output: SceneEnrichmentOutput) -> bool:
    # Every optional field may be genuinely not applicable. A schema-valid empty
    # enrichment is therefore a meaningful result, not an automatic retry signal.
    return False


def _fallback_enrichment() -> SceneEnrichmentOutput:
    return SceneEnrichmentOutput(
        emotional_beat=None,
        must_happen=None,
        must_not_happen=None,
        narrative_tag="draft",
        narrative_function="",
        basis="",
        field_evidence={},
        uncertain_fields=[
            "emotional_beat",
            "must_happen",
            "must_not_happen",
            "narrative_tag",
            "narrative_function",
        ],
        confidence=0.0,
    )


def _validate_enrichment_evidence(
    enrichment: SceneEnrichmentOutput,
    scene_source: Sequence[dict[str, Any]],
) -> SceneEnrichmentOutput:
    source_texts = [str(item.get("text") or "") for item in scene_source]
    valid_evidence: dict[str, list[str]] = {}
    uncertain = list(enrichment.uncertain_fields)
    updates: dict[str, Any] = {}
    for field in ("emotional_beat", "must_happen", "must_not_happen"):
        quotes = [
            quote.strip()
            for quote in enrichment.field_evidence.get(field, [])
            if quote.strip() and any(quote.strip() in text for text in source_texts)
        ]
        quotes = list(dict.fromkeys(quotes))
        if quotes:
            valid_evidence[field] = quotes
        elif getattr(enrichment, field):
            updates[field] = None
            uncertain.append(field)
    return enrichment.model_copy(
        update={
            **updates,
            "field_evidence": valid_evidence,
            "uncertain_fields": list(dict.fromkeys(uncertain)),
        }
    )


def _phase1b_field_statuses(
    enrichment: SceneEnrichmentOutput,
) -> dict[str, Phase1bFieldStatus]:
    uncertain = set(enrichment.uncertain_fields)
    values: dict[str, Any] = {
        "emotional_beat": enrichment.emotional_beat,
        "must_happen": enrichment.must_happen,
        "must_not_happen": enrichment.must_not_happen,
        "narrative_tag": enrichment.narrative_tag,
        "narrative_function": enrichment.narrative_function,
    }
    return {
        field: (
            "uncertain"
            if field in uncertain
            else "not_applicable"
            if value in (None, "") or (field == "narrative_tag" and value == "draft")
            else "present"
        )
        for field, value in values.items()
    }


def _is_phase1a_fallback(scene: SceneSliceCandidate) -> bool:
    return bool(
        scene.diagnostics.get("fallback")
        or scene.candidate_id.startswith("phase1a-fallback-")
        or scene.source_window_id.startswith("fallback-")
    )


def _final_candidate(
    scene: SceneSliceCandidate,
    enrichment: SceneEnrichmentOutput,
    *,
    sequence_index: int,
    fallback_required: bool,
    source_integrity: dict[str, Any],
    context_fingerprint: str,
    extra_review_reason: str = "",
) -> FinalSceneCandidate:
    phase1a_fallback = _is_phase1a_fallback(scene)
    uncertain_fields = list(enrichment.uncertain_fields)
    review_reasons = [
        reason
        for reason in (
            scene.review_reason if scene.needs_review else "",
            "Phase1a fallback Scene requires review." if phase1a_fallback else "",
            (
                "Phase1b source integrity is incomplete."
                if not source_integrity.get("complete")
                else ""
            ),
            (
                "Phase1b uncertain fields: " + ", ".join(uncertain_fields) + "."
                if uncertain_fields
                else ""
            ),
            extra_review_reason,
        )
        if reason
    ]
    needs_review = bool(
        scene.needs_review
        or phase1a_fallback
        or not source_integrity.get("complete")
        or uncertain_fields
        or fallback_required
    )
    return FinalSceneCandidate(
        candidate_id=f"phase1b-enriched-{sequence_index:04d}-{scene.candidate_id}",
        phase="phase1b_enrichment",
        title=scene.title,
        goal=scene.goal,
        core_conflict=scene.core_conflict,
        core_conflict_status=scene.core_conflict_status,
        phase1a_confidence=scene.phase1a_confidence,
        boundary_basis=scene.boundary_basis,
        emotional_beat=enrichment.emotional_beat,
        must_happen=enrichment.must_happen,
        must_not_happen=enrichment.must_not_happen,
        narrative_tag=enrichment.narrative_tag or "draft",
        narrative_function=enrichment.narrative_function,
        phase1b_basis=enrichment.basis,
        phase1b_field_evidence=enrichment.field_evidence,
        phase1b_field_statuses=_phase1b_field_statuses(enrichment),
        phase1b_uncertain_fields=uncertain_fields,
        phase1b_confidence=enrichment.confidence,
        phase1b_context_fingerprint=context_fingerprint,
        phase1b_source_fingerprint=str(source_integrity.get("source_fingerprint") or ""),
        scene_chunks=list(scene.scene_chunks),
        source_candidate_ids=[scene.candidate_id],
        source_rounds=["A"],
        source_chapter_indices=list(scene.source_chapter_indices),
        operation="kept",
        confidence=enrichment.confidence,
        fallback_required=fallback_required or phase1a_fallback,
        boundary_status=scene.boundary_status,
        boundary_reason=(
            scene.boundary_basis or "Phase1b enriched Phase1a locked Scene fields."
        ),
        needs_review=needs_review,
        review_reason=" ".join(dict.fromkeys(review_reasons)),
    )


def _quality_stats(results: Sequence[_EnrichOneResult]) -> dict[str, Any]:
    stats: dict[str, Any] = {
        "total_windows": len(results),
        "completed_windows": 0,
        "total_scenes": len(results),
        "completed": 0,
        "failed": 0,
        "fallback_count": 0,
        "source_integrity": 0,
        "schema_error": 0,
        "empty_result": 0,
        "timeout": 0,
        "network": 0,
        "rate_limit": 0,
        "http_error": 0,
        "unknown": 0,
        "final_422": 0,
        "concurrency": positive_int_env(
            "PHASE1B_ENRICH_CONCURRENCY",
            PHASE1B_ENRICH_CONCURRENCY,
        ),
        "max_tokens": positive_int_env(
            "PHASE1B_ENRICH_MAX_TOKENS",
            PHASE1B_ENRICH_MAX_TOKENS,
        ),
        "max_retries": PHASE1B_ENRICH_MAX_RETRIES,
    }
    for result in results:
        if result.fallback:
            stats["failed"] += 1
            stats["fallback_count"] += 1
        else:
            stats["completed"] += 1
            stats["completed_windows"] += 1
        final_error_type = result.diagnostics.get("final_error_type")
        if final_error_type in stats:
            stats[final_error_type] += 1
        if final_error_type == "422":
            stats["final_422"] += 1
    total = int(stats["total_scenes"])
    stats["fallback_rate"] = stats["fallback_count"] / total if total else 0.0
    return stats
