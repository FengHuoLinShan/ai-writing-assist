"""Phase 1b per-Scene enrichment for deep import."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from pydantic import BaseModel, Field

from modules.imports.deep_import_retry import run_deep_import_llm_with_retry
from modules.imports.env_helpers import positive_int_env
from modules.imports.llm_schemas import SceneChunk, SceneEnrichmentOutput
from modules.imports.scene_fusion import FinalSceneCandidate
from modules.imports.scene_slicing import SceneSliceCandidate

PHASE1B_ENRICH_CONCURRENCY = 200
PHASE1B_ENRICH_MAX_TOKENS = 4096
PHASE1B_ENRICH_MAX_RETRIES = 1

SceneEnrichmentLLMCallable = Callable[[dict[str, Any]], Awaitable[Any]]


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
        max_tokens: int = PHASE1B_ENRICH_MAX_TOKENS,
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
        self.max_tokens = positive_int_env("PHASE1B_ENRICH_MAX_TOKENS", max_tokens)

    async def run(
        self,
        *,
        scenes: Sequence[SceneSliceCandidate],
        chapters: Sequence[dict[str, Any]],
        on_batch_progress: Callable[[int, int, str], Awaitable[None]] | None = None,
    ) -> Phase1bEnrichmentResult:
        chapter_by_index = {
            int(chapter["chapter_index"]): chapter for chapter in chapters
        }
        semaphore = asyncio.Semaphore(self.concurrency)
        total_scenes = len(scenes)
        completed = 0
        progress_lock = asyncio.Lock()

        async def process(index: int, scene: SceneSliceCandidate) -> _EnrichOneResult:
            nonlocal completed
            async with semaphore:
                result = await self._process_scene(index, scene, chapter_by_index)
            async with progress_lock:
                completed += 1
                if on_batch_progress is not None:
                    await on_batch_progress(
                        completed, total_scenes, scene.candidate_id
                    )
            return result

        results = await asyncio.gather(
            *(process(index, scene) for index, scene in enumerate(scenes, start=1))
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
    ) -> _EnrichOneResult:
        payload = _scene_payload(
            scene,
            chapter_by_index,
            sequence_index=sequence_index,
            max_tokens=self.max_tokens,
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

        if retry_result.final_status != "success":
            enrichment = _fallback_enrichment(scene, retry_result.final_error_type)
            candidate = _final_candidate(
                scene,
                enrichment,
                sequence_index=sequence_index,
                fallback_required=True,
                extra_review_reason=retry_result.final_error_type or "phase1b_failed",
            )
            return _EnrichOneResult(
                candidate=candidate,
                diagnostics=diagnostics,
                fallback=True,
            )

        output = retry_result.value
        if not isinstance(output, SceneEnrichmentOutput):
            output = SceneEnrichmentOutput.model_validate(output)
        field_fallback = _fill_missing_enrichment(output, scene)
        candidate = _final_candidate(
            scene,
            field_fallback,
            sequence_index=sequence_index,
            fallback_required=False,
            extra_review_reason=(
                "Phase1b output had missing enrichment fields."
                if field_fallback.needs_review and not output.needs_review
                else ""
            ),
        )
        diagnostics["field_fallback"] = field_fallback != output
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
    chapter_by_index: dict[int, dict[str, Any]],
    *,
    sequence_index: int,
    max_tokens: int,
) -> dict[str, Any]:
    chapters = [
        chapter_by_index[index]
        for index in range(scene.start_chapter, scene.end_chapter + 1)
        if index in chapter_by_index
    ]
    return {
        "phase": "phase1b_enrichment",
        "sequence_index": sequence_index,
        "locked_scene": scene.model_dump(mode="json", exclude={"diagnostics"}),
        "chapters": [
            {
                "chapter_index": int(chapter["chapter_index"]),
                "title": str(chapter.get("title") or f"第{chapter['chapter_index']}章"),
                "content": str(chapter.get("content") or ""),
            }
            for chapter in chapters
        ],
        "max_tokens": max_tokens,
    }


def _empty_enrichment(output: SceneEnrichmentOutput) -> bool:
    return not (
        output.emotional_beat.strip()
        or output.must_happen.strip()
        or output.must_not_happen.strip()
        or output.narrative_tag.strip()
    )


def _fill_missing_enrichment(
    output: SceneEnrichmentOutput,
    scene: SceneSliceCandidate,
) -> SceneEnrichmentOutput:
    missing = []
    emotional_beat = output.emotional_beat.strip()
    if not emotional_beat:
        emotional_beat = "待人工确认情绪节拍。"
        missing.append("emotional_beat")
    must_happen = output.must_happen.strip()
    if not must_happen:
        must_happen = scene.goal or "保留该 Scene 的核心推进。"
        missing.append("must_happen")
    must_not_happen = output.must_not_happen.strip()
    if not must_not_happen:
        must_not_happen = scene.core_conflict or "不得偏离原章节事实。"
        missing.append("must_not_happen")
    narrative_tag = output.narrative_tag.strip() or "imported"
    if not output.narrative_tag.strip():
        missing.append("narrative_tag")
    review_reason = output.review_reason.strip()
    if missing:
        review_reason = (
            (review_reason + " " if review_reason else "")
            + "Missing enrichment fields: "
            + ", ".join(missing)
        )
    return SceneEnrichmentOutput(
        emotional_beat=emotional_beat,
        must_happen=must_happen,
        must_not_happen=must_not_happen,
        narrative_tag=narrative_tag,
        confidence=output.confidence,
        needs_review=output.needs_review or bool(missing),
        review_reason=review_reason,
    )


def _fallback_enrichment(
    scene: SceneSliceCandidate,
    error_kind: str | None,
) -> SceneEnrichmentOutput:
    return SceneEnrichmentOutput(
        emotional_beat="待人工确认情绪节拍。",
        must_happen=scene.goal or "保留该 Scene 的核心推进。",
        must_not_happen=scene.core_conflict or "不得偏离原章节事实。",
        narrative_tag="imported",
        confidence=0.45,
        needs_review=True,
        review_reason=f"Phase1b enrichment fallback: {error_kind or 'unknown'}",
    )


def _final_candidate(
    scene: SceneSliceCandidate,
    enrichment: SceneEnrichmentOutput,
    *,
    sequence_index: int,
    fallback_required: bool,
    extra_review_reason: str = "",
) -> FinalSceneCandidate:
    chapter_indices = list(range(scene.start_chapter, scene.end_chapter + 1))
    review_reasons = [
        reason
        for reason in (
            scene.review_reason if scene.needs_review else "",
            enrichment.review_reason if enrichment.needs_review else "",
            extra_review_reason,
        )
        if reason
    ]
    return FinalSceneCandidate(
        candidate_id=f"phase1b-enriched-{sequence_index:04d}-{scene.candidate_id}",
        phase="phase1b_enrichment",
        title=scene.title,
        goal=scene.goal,
        core_conflict=scene.core_conflict,
        emotional_beat=enrichment.emotional_beat,
        must_happen=enrichment.must_happen,
        must_not_happen=enrichment.must_not_happen,
        narrative_tag=enrichment.narrative_tag or "imported",
        scene_chunks=[
            SceneChunk(chapter_index=chapter_index)
            for chapter_index in chapter_indices
        ],
        source_candidate_ids=[scene.candidate_id],
        source_rounds=["A"],
        source_chapter_indices=chapter_indices,
        operation="kept",
        confidence=enrichment.confidence,
        fallback_required=fallback_required,
        boundary_status=scene.boundary_status,
        boundary_reason="Phase1b enriched Phase1a locked Scene fields.",
        needs_review=scene.needs_review or enrichment.needs_review or fallback_required,
        review_reason=" ".join(review_reasons),
    )


def _quality_stats(results: Sequence[_EnrichOneResult]) -> dict[str, Any]:
    stats: dict[str, Any] = {
        "total_windows": len(results),
        "completed_windows": 0,
        "total_scenes": len(results),
        "completed": 0,
        "failed": 0,
        "fallback_count": 0,
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
