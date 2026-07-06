"""Phase 1a Scene slicing for deep import."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from modules.imports.deep_import_retry import (
    DeepImportRetryResult,
    run_deep_import_llm_with_retry,
)
from modules.imports.env_helpers import positive_int_env
from modules.imports.llm_schemas import SceneSlicingOutput
from modules.imports.scene_planning import ScenePlanResult, SceneWindowPlan

PHASE1A_SCENE_SLICING_CONCURRENCY = 50
PHASE1A_RETRY_MAX_TOKENS = (24_576, 32_768)

SceneSlicingLLMCallable = Callable[[dict[str, Any]], Awaitable[Any]]


class SceneSliceCandidate(BaseModel):
    """Locked Scene fields produced by Phase 1a and enriched by Phase 1b."""

    candidate_id: str
    source_window_id: str
    source_window_index: int = Field(..., ge=1)
    title: str = ""
    goal: str = ""
    core_conflict: str = ""
    start_chapter: int = Field(..., ge=1)
    end_chapter: int = Field(..., ge=1)
    boundary_status: str = "uncertain"
    source_chapter_indices: list[int] = Field(default_factory=list)
    needs_review: bool = False
    review_reason: str = ""
    diagnostics: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "title",
        "goal",
        "core_conflict",
        "boundary_status",
        "review_reason",
        mode="before",
    )
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return "" if value is None else str(value).strip()

    @model_validator(mode="after")
    def _normalize_range(self) -> SceneSliceCandidate:
        if self.end_chapter < self.start_chapter:
            self.end_chapter = self.start_chapter
        if not self.source_chapter_indices:
            self.source_chapter_indices = list(
                range(self.start_chapter, self.end_chapter + 1)
            )
        self.source_chapter_indices = sorted(
            {
                int(chapter)
                for chapter in self.source_chapter_indices
                if int(chapter) >= 1
            }
        )
        return self


class SceneSlicingResult(BaseModel):
    """Phase 1a result kept in task state only."""

    candidates: list[SceneSliceCandidate] = Field(default_factory=list)
    quality_stats: dict[str, Any] = Field(default_factory=dict)
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)
    blocked: bool = False
    block_reason: str | None = None


class Phase1aSceneSlicer:
    """Slice full text windows into locked Scene boundaries."""

    def __init__(
        self,
        llm: SceneSlicingLLMCallable | Any,
        *,
        concurrency: int | None = None,
    ) -> None:
        self.llm = llm
        self.concurrency = max(
            1,
            concurrency
            if concurrency is not None
            else positive_int_env(
                "PHASE1A_SCENE_SLICING_CONCURRENCY",
                PHASE1A_SCENE_SLICING_CONCURRENCY,
            ),
        )

    async def run(self, plan: ScenePlanResult) -> SceneSlicingResult:
        if plan.blocked or not plan.windows:
            return SceneSlicingResult(
                quality_stats={
                    "total_batches": 0,
                    "completed_batches": 0,
                    "success": 0,
                    "failed": 0,
                    "fallback_count": 0,
                },
                diagnostics=list(plan.diagnostics),
                blocked=True,
                block_reason=plan.block_reason or "phase1a_no_windows",
            )

        chapter_by_index = {
            int(chapter["chapter_index"]): chapter for chapter in plan.chapters
        }
        semaphore = asyncio.Semaphore(self.concurrency)

        async def process(window: SceneWindowPlan) -> _WindowSliceResult:
            async with semaphore:
                return await self._process_window(window, chapter_by_index)

        window_results = await asyncio.gather(
            *(process(window) for window in plan.windows)
        )
        candidates = [
            candidate
            for result in window_results
            for candidate in result.candidates
        ]
        fallback_candidates = _fallback_missing_chapters(
            candidates,
            plan,
            chapter_by_index,
        )
        candidates.extend(fallback_candidates)
        candidates = sorted(
            candidates,
            key=lambda candidate: (
                candidate.start_chapter,
                candidate.end_chapter,
                candidate.source_window_index,
                candidate.candidate_id,
            ),
        )
        diagnostics = [result.diagnostics for result in window_results]
        if fallback_candidates:
            diagnostics.append(
                {
                    "final_status": "fallback",
                    "final_error_type": "missing_chapter_coverage",
                    "fallback_count": len(fallback_candidates),
                    "chapter_indices": [
                        candidate.start_chapter for candidate in fallback_candidates
                    ],
                }
            )
        quality_stats = _quality_stats(
            window_results,
            fallback_count=len(fallback_candidates),
            scene_count=len(candidates),
        )
        return SceneSlicingResult(
            candidates=candidates,
            quality_stats=quality_stats,
            diagnostics=diagnostics,
            blocked=False,
        )

    async def _process_window(
        self,
        window: SceneWindowPlan,
        chapter_by_index: dict[int, dict[str, Any]],
    ) -> _WindowSliceResult:
        chapters = [
            chapter_by_index[index]
            for index in window.chapter_indices
            if index in chapter_by_index
        ]
        token_attempts = _token_attempts(window.max_tokens)
        retry_results: list[DeepImportRetryResult] = []
        last_output: SceneSlicingOutput | None = None
        for max_tokens in token_attempts:
            payload = _window_payload(window, chapters, max_tokens=max_tokens)
            retry_result = await run_deep_import_llm_with_retry(
                lambda payload=payload: self._call_and_validate(payload),
                is_empty_result=lambda output: not output.scenes,
                max_retries=1,
                retryable_error_types={"network", "rate_limit", "timeout"},
            )
            retry_results.append(retry_result)
            if retry_result.final_status == "success":
                output = retry_result.value
                if not isinstance(output, SceneSlicingOutput):
                    output = SceneSlicingOutput.model_validate(output)
                normalized = _normalize_output(window, output)
                if normalized:
                    last_output = output
                    return _WindowSliceResult(
                        window=window,
                        candidates=normalized,
                        diagnostics=_diagnostics(window, retry_results, max_tokens),
                    )
                retry_results[-1] = DeepImportRetryResult(
                    attempts=retry_result.attempts,
                    final_status="failed",
                    final_error_type="empty_result",
                    diagnostics=retry_result.diagnostics,
                    value=output,
                )
            latest_result = retry_results[-1]
            if (
                latest_result.final_status != "success"
                and latest_result.final_error_type
                not in {"schema_error", "empty_result"}
            ):
                break
        return _WindowSliceResult(
            window=window,
            candidates=[],
            diagnostics=_diagnostics(
                window,
                retry_results,
                token_attempts[-1],
                empty_output=last_output is not None and not last_output.scenes,
            ),
        )

    async def _call_and_validate(self, payload: dict[str, Any]) -> SceneSlicingOutput:
        output = await self.llm(payload)
        if isinstance(output, SceneSlicingOutput):
            return output
        return SceneSlicingOutput.model_validate(output)


class _WindowSliceResult(BaseModel):
    window: SceneWindowPlan
    candidates: list[SceneSliceCandidate] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)


def _window_payload(
    window: SceneWindowPlan,
    chapters: Sequence[dict[str, Any]],
    *,
    max_tokens: int,
) -> dict[str, Any]:
    return {
        "phase": "phase1a_scene_slicing",
        "window": window.model_dump(mode="json"),
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


def _normalize_output(
    window: SceneWindowPlan,
    output: SceneSlicingOutput,
) -> list[SceneSliceCandidate]:
    candidates: list[SceneSliceCandidate] = []
    for index, scene in enumerate(output.scenes, start=1):
        original_start = int(scene.start_chapter)
        original_end = int(scene.end_chapter)
        if original_end < window.covered_start or original_start > window.covered_end:
            continue
        start = max(window.covered_start, original_start)
        end = min(window.covered_end, max(original_end, original_start))
        if not (window.owned_start <= start <= window.owned_end):
            continue
        needs_review = (
            start != original_start
            or end != original_end
            or not scene.title.strip()
            or not scene.goal.strip()
            or not scene.core_conflict.strip()
        )
        review_reason = "Phase1a normalized LLM range or filled empty locked fields."
        candidate = SceneSliceCandidate(
            candidate_id=f"phase1a-{window.window_id}-S{index:03d}",
            source_window_id=window.window_id,
            source_window_index=window.window_index,
            title=scene.title.strip() or f"第{start}章 Scene",
            goal=scene.goal.strip(),
            core_conflict=scene.core_conflict.strip(),
            start_chapter=start,
            end_chapter=end,
            boundary_status=scene.boundary_status.strip() or "uncertain",
            source_chapter_indices=list(range(start, end + 1)),
            needs_review=needs_review,
            review_reason=review_reason if needs_review else "",
        )
        candidates.append(candidate)
    return candidates


def _fallback_missing_chapters(
    candidates: Sequence[SceneSliceCandidate],
    plan: ScenePlanResult,
    chapter_by_index: dict[int, dict[str, Any]],
) -> list[SceneSliceCandidate]:
    requested = {
        int(chapter["chapter_index"])
        for chapter in plan.chapters
    }
    covered = {
        chapter
        for candidate in candidates
        for chapter in candidate.source_chapter_indices
    }
    fallback: list[SceneSliceCandidate] = []
    for chapter_index in sorted(requested - covered):
        chapter = chapter_by_index.get(chapter_index) or {}
        title = str(chapter.get("title") or f"第{chapter_index}章")
        fallback.append(
            SceneSliceCandidate(
                candidate_id=f"phase1a-fallback-{chapter_index:04d}",
                source_window_id=f"fallback-{chapter_index:04d}",
                source_window_index=chapter_index,
                title=title,
                goal="章节级 fallback Scene，需要人工复核。",
                core_conflict="LLM 窗口切分未覆盖该章节。",
                start_chapter=chapter_index,
                end_chapter=chapter_index,
                boundary_status="fallback",
                source_chapter_indices=[chapter_index],
                needs_review=True,
                review_reason="Phase1a failed to cover this chapter.",
                diagnostics={"fallback": True, "chapter_index": chapter_index},
            )
        )
    return fallback


def _token_attempts(initial_max_tokens: int) -> list[int]:
    tokens = [max(1, int(initial_max_tokens))]
    for value in PHASE1A_RETRY_MAX_TOKENS:
        if value > tokens[-1]:
            tokens.append(value)
    return tokens


def _diagnostics(
    window: SceneWindowPlan,
    retry_results: list[DeepImportRetryResult],
    max_tokens: int,
    *,
    empty_output: bool = False,
) -> dict[str, Any]:
    final = retry_results[-1] if retry_results else None
    return {
        "source_batch_id": window.window_id,
        "chapter_indices": window.chapter_indices,
        "owned_chapter_indices": window.owned_chapter_indices,
        "max_tokens": max_tokens,
        "token_attempts": [
            result.model_dump(mode="json", exclude={"value"})
            for result in retry_results
        ],
        "attempts": sum(result.attempts for result in retry_results),
        "final_status": final.final_status if final else "failed",
        "final_error_type": final.final_error_type if final else "unknown",
        "empty_output": empty_output,
    }


def _quality_stats(
    window_results: list[_WindowSliceResult],
    *,
    fallback_count: int,
    scene_count: int,
) -> dict[str, Any]:
    stats: dict[str, Any] = {
        "total_batches": len(window_results),
        "completed_batches": 0,
        "success": 0,
        "failed": 0,
        "schema_error": 0,
        "empty_result": 0,
        "timeout": 0,
        "network": 0,
        "rate_limit": 0,
        "http_error": 0,
        "unknown": 0,
        "final_422": 0,
        "fallback_count": fallback_count,
        "scene_count": scene_count,
    }
    for result in window_results:
        final_status = result.diagnostics.get("final_status")
        final_error_type = result.diagnostics.get("final_error_type")
        if final_status == "success":
            stats["success"] += 1
            stats["completed_batches"] += 1
        else:
            stats["failed"] += 1
        if final_error_type in stats:
            stats[final_error_type] += 1
        if final_error_type == "422":
            stats["final_422"] += 1
    total = int(stats["total_batches"])
    stats["final_422_rate"] = stats["final_422"] / total if total else 0.0
    return stats
