"""Phase 1a Scene slicing for deep import."""

from __future__ import annotations

import asyncio
import hashlib
import unicodedata
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from modules.imports.deep_import_retry import (
    DeepImportRetryResult,
    run_deep_import_llm_with_retry,
)
from modules.imports.env_helpers import positive_int_env
from modules.imports.llm_schemas import (
    SceneAnchorRepairOutput,
    SceneChunk,
    SceneRecoveryOutput,
    SceneRecoverySegment,
    SceneSliceItem,
    SceneSlicingOutput,
)
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
    core_conflict_status: Literal["present", "not_applicable", "uncertain"] = "uncertain"
    phase1a_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    boundary_basis: str = ""
    start_chapter: int = Field(..., ge=1)
    end_chapter: int = Field(..., ge=1)
    boundary_status: str = "uncertain"
    source_chapter_indices: list[int] = Field(default_factory=list)
    scene_chunks: list[SceneChunk] = Field(default_factory=list)
    needs_review: bool = False
    review_reason: str = ""
    diagnostics: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "title",
        "goal",
        "core_conflict",
        "boundary_basis",
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
            {int(chapter) for chapter in self.source_chapter_indices if int(chapter) >= 1}
        )
        if not self.scene_chunks:
            self.scene_chunks = [
                SceneChunk(chapter_index=chapter)
                for chapter in self.source_chapter_indices
            ]
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

    async def run(
        self,
        plan: ScenePlanResult,
        *,
        on_batch_progress: Callable[[int, int, str], Awaitable[None]] | None = None,
    ) -> SceneSlicingResult:
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
        total_windows = len(plan.windows)
        completed = 0
        progress_lock = asyncio.Lock()

        async def process(window: SceneWindowPlan) -> _WindowSliceResult:
            nonlocal completed
            async with semaphore:
                result = await self._process_window(window, chapter_by_index)
            async with progress_lock:
                completed += 1
                if on_batch_progress is not None:
                    await on_batch_progress(completed, total_windows, window.window_id)
            return result

        window_results = await asyncio.gather(
            *(process(window) for window in plan.windows)
        )
        candidates = [
            candidate for result in window_results for candidate in result.candidates
        ]
        edge_coordination = _coordinate_window_edges(window_results, candidates)
        _infer_chunks_from_neighbor_anchors(candidates, chapter_by_index)
        anchor_repair_stats = await self._repair_unresolved_anchors(
            candidates,
            chapter_by_index,
        )
        _infer_chunks_from_neighbor_anchors(candidates, chapter_by_index)
        candidates, overlap_quarantine = _quarantine_exact_overlap_ranges(candidates)
        fallback_candidates = _fallback_missing_chapters(
            candidates,
            plan,
            chapter_by_index,
        )
        (
            recovered_candidates,
            remaining_fallbacks,
            chapter_recovery_stats,
        ) = await self._recover_missing_chapters(
            fallback_candidates,
            chapter_by_index,
            candidates,
            windows=plan.windows,
        )
        candidates.extend(recovered_candidates)
        candidates.extend(remaining_fallbacks)
        _infer_chunks_from_neighbor_anchors(candidates, chapter_by_index)
        candidates, final_overlap_quarantine = _quarantine_exact_overlap_ranges(
            candidates,
        )
        final_overlap_fallbacks: list[SceneSliceCandidate] = []
        if final_overlap_quarantine["overlap_count"]:
            final_overlap_fallbacks = _fallback_missing_chapters(
                candidates,
                plan,
                chapter_by_index,
            )
            candidates.extend(final_overlap_fallbacks)
        trivial_gap_stats = _absorb_trivial_exact_gaps(
            candidates,
            chapter_by_index,
            requested_chapter_indices=sorted(chapter_by_index),
        )
        coverage_gaps = _exact_source_coverage_gaps(
            candidates,
            chapter_by_index,
            requested_chapter_indices=sorted(chapter_by_index),
        )
        partial_gap_fallbacks = _fallback_required_exact_gaps(
            coverage_gaps,
            chapter_by_index,
            leading_edge=_leading_window_relation(window_results),
            trailing_edge=_trailing_window_relation(window_results),
            requested_chapter_indices=sorted(chapter_by_index),
        )
        candidates.extend(partial_gap_fallbacks)
        remaining_coverage_gaps = _exact_source_coverage_gaps(
            candidates,
            chapter_by_index,
            requested_chapter_indices=sorted(chapter_by_index),
        )
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
        diagnostics.append(edge_coordination)
        diagnostics.append(overlap_quarantine)
        diagnostics.append(final_overlap_quarantine)
        diagnostics.append(trivial_gap_stats)
        diagnostics.append(
            {
                "kind": "exact_source_coverage",
                "detected_gap_count": len(coverage_gaps),
                "partial_gap_fallback_count": len(partial_gap_fallbacks),
                "remaining_gap_count": len(remaining_coverage_gaps),
                "remaining_gaps": remaining_coverage_gaps,
                "status": ("complete" if not remaining_coverage_gaps else "needs_review"),
            }
        )
        if remaining_fallbacks or final_overlap_fallbacks or partial_gap_fallbacks:
            diagnostics.append(
                {
                    "final_status": "fallback",
                    "final_error_type": "missing_chapter_coverage",
                    "fallback_count": len(remaining_fallbacks)
                    + len(final_overlap_fallbacks)
                    + len(partial_gap_fallbacks),
                    "chapter_indices": [
                        candidate.start_chapter
                        for candidate in [
                            *remaining_fallbacks,
                            *final_overlap_fallbacks,
                            *partial_gap_fallbacks,
                        ]
                    ],
                }
            )
        if recovered_candidates:
            diagnostics.append(
                {
                    "final_status": "recovered",
                    "final_error_type": None,
                    "recovered_chapter_count": chapter_recovery_stats[
                        "chapter_recovery_succeeded_count"
                    ],
                    "chapter_indices": sorted(
                        {candidate.start_chapter for candidate in recovered_candidates}
                    ),
                }
            )
        quality_stats = _quality_stats(
            window_results,
            fallback_count=(
                len(remaining_fallbacks)
                + len(final_overlap_fallbacks)
                + len(partial_gap_fallbacks)
            ),
            candidates=candidates,
        )
        quality_stats["overlap_quarantined_candidate_count"] = (
            overlap_quarantine["quarantined_candidate_count"]
            + final_overlap_quarantine["quarantined_candidate_count"]
        )
        quality_stats["remaining_exact_overlap_count"] = len(
            _exact_candidate_overlaps(candidates)
        )
        quality_stats["trivial_gap_absorbed_count"] = trivial_gap_stats[
            "absorbed_gap_count"
        ]
        quality_stats["coverage_gap_detected_count"] = len(coverage_gaps)
        quality_stats["coverage_gap_fallback_count"] = len(partial_gap_fallbacks)
        quality_stats["remaining_exact_gap_count"] = len(remaining_coverage_gaps)
        quality_stats["exact_source_coverage_complete"] = not remaining_coverage_gaps
        quality_stats.update(anchor_repair_stats)
        quality_stats.update(chapter_recovery_stats)
        return SceneSlicingResult(
            candidates=candidates,
            quality_stats=quality_stats,
            diagnostics=diagnostics,
            blocked=False,
        )

    async def _repair_unresolved_anchors(
        self,
        candidates: list[SceneSliceCandidate],
        chapter_by_index: dict[int, dict[str, Any]],
    ) -> dict[str, int]:
        repair = getattr(self.llm, "repair_anchors", None)
        targets = [
            candidate
            for candidate in candidates
            if any(
                chunk.start_offset is None or chunk.end_offset is None
                for chunk in candidate.scene_chunks
            )
        ]
        if not callable(repair) or not targets:
            return {
                "anchor_repair_attempted_count": 0,
                "anchor_repair_succeeded_count": 0,
                "anchor_repair_failed_count": 0,
            }

        semaphore = asyncio.Semaphore(min(5, self.concurrency))

        ordered = sorted(candidates, key=_candidate_sort_key)
        neighbor_by_id: dict[
            str, tuple[SceneSliceCandidate | None, SceneSliceCandidate | None]
        ] = {}
        for index, candidate in enumerate(ordered):
            neighbor_by_id[candidate.candidate_id] = (
                ordered[index - 1] if index > 0 else None,
                ordered[index + 1] if index + 1 < len(ordered) else None,
            )

        async def repair_one(candidate: SceneSliceCandidate) -> None:
            boundary_chapter_indices = list(
                dict.fromkeys((candidate.start_chapter, candidate.end_chapter))
            )
            chapters = [
                chapter_by_index[index]
                for index in boundary_chapter_indices
                if index in chapter_by_index
            ]
            previous, following = neighbor_by_id[candidate.candidate_id]
            neighbor_boundaries = {
                "previous": _verified_neighbor_boundary(previous, side="end"),
                "next": _verified_neighbor_boundary(following, side="start"),
            }
            payload = {
                "candidate": candidate.model_dump(mode="json"),
                "chapters": chapters,
                "neighbor_boundaries": neighbor_boundaries,
            }
            try:
                async with semaphore:
                    raw = await repair(payload)
                output = (
                    raw
                    if isinstance(raw, SceneAnchorRepairOutput)
                    else SceneAnchorRepairOutput.model_validate(raw)
                )
                if output.status == "unresolved":
                    candidate.diagnostics["anchor_repair"] = {
                        "status": "unresolved",
                        "reason": output.reason,
                        "unresolved_chapters": list(
                            candidate.diagnostics.get("unresolved_chapters") or []
                        ),
                    }
                    return
                if output.start_anchor:
                    candidate.diagnostics["start_anchor"] = output.start_anchor
                    candidate.diagnostics["start_anchor_matches"] = [
                        list(match)
                        for match in _anchor_matches_in_chapters(
                            chapter_by_index,
                            output.start_anchor,
                        )
                    ]
                if output.end_anchor:
                    candidate.diagnostics["end_anchor"] = output.end_anchor
                    candidate.diagnostics["end_anchor_matches"] = [
                        list(match)
                        for match in _anchor_matches_in_chapters(
                            chapter_by_index,
                            output.end_anchor,
                        )
                    ]
                scene = SceneSliceItem(
                    title=candidate.title,
                    goal=candidate.goal,
                    core_conflict=candidate.core_conflict,
                    core_conflict_status=candidate.core_conflict_status,
                    start_chapter=candidate.start_chapter,
                    end_chapter=candidate.end_chapter,
                    start_anchor=str(candidate.diagnostics.get("start_anchor") or ""),
                    end_anchor=str(candidate.diagnostics.get("end_anchor") or ""),
                    boundary_status=(
                        candidate.boundary_status
                        if candidate.boundary_status
                        in {"complete", "continues_right", "uncertain"}
                        else "uncertain"
                    ),
                    boundary_basis=candidate.boundary_basis,
                    confidence=candidate.phase1a_confidence,
                )
                chunks, unresolved = _materialize_scene_chunks(
                    scene,
                    start_chapter=candidate.start_chapter,
                    end_chapter=candidate.end_chapter,
                    chapter_by_index=chapter_by_index,
                )
                candidate.scene_chunks = chunks
                candidate.diagnostics["anchor_repair"] = {
                    "status": output.status,
                    "reason": output.reason,
                    "unresolved_chapters": unresolved,
                }
                candidate.diagnostics["unresolved_chapters"] = unresolved
                if not unresolved:
                    candidate.diagnostics["source_mapping"] = "exact"
                    candidate.review_reason = " ".join(
                        part
                        for part in (
                            candidate.review_reason,
                            "Source anchors were resolved by the small-context "
                            "repair step.",
                        )
                        if part
                    )
                    return
            except Exception as exc:
                candidate.diagnostics["anchor_repair"] = {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                }
                return

        await asyncio.gather(*(repair_one(candidate) for candidate in targets))
        _infer_chunks_from_neighbor_anchors(candidates, chapter_by_index)
        for candidate in targets:
            repair_diagnostics = candidate.diagnostics.get("anchor_repair")
            if isinstance(repair_diagnostics, dict):
                repair_diagnostics["final_status"] = (
                    "resolved_after_neighbor_inference"
                    if _candidate_has_exact_chunks(candidate)
                    else "unresolved"
                )
                repair_diagnostics["unresolved_chapters"] = list(
                    candidate.diagnostics.get("unresolved_chapters") or []
                )
        succeeded = sum(_candidate_has_exact_chunks(candidate) for candidate in targets)
        return {
            "anchor_repair_attempted_count": len(targets),
            "anchor_repair_succeeded_count": succeeded,
            "anchor_repair_failed_count": len(targets) - succeeded,
        }

    async def _recover_missing_chapters(
        self,
        fallback_candidates: list[SceneSliceCandidate],
        chapter_by_index: dict[int, dict[str, Any]],
        existing_candidates: list[SceneSliceCandidate],
        windows: Sequence[SceneWindowPlan] = (),
    ) -> tuple[
        list[SceneSliceCandidate],
        list[SceneSliceCandidate],
        dict[str, int],
    ]:
        recover = getattr(self.llm, "recover_chapter", None)
        if not callable(recover) or not fallback_candidates:
            return (
                [],
                fallback_candidates,
                {
                    "chapter_recovery_attempted_count": 0,
                    "chapter_recovery_succeeded_count": 0,
                    "chapter_recovery_failed_count": 0,
                    "recovery_gap_attempted_count": 0,
                    "recovery_gap_succeeded_count": 0,
                    "recovery_gap_failed_count": 0,
                },
            )
        gaps = _continuous_fallback_gaps(fallback_candidates)

        async def recover_one(
            gap: list[SceneSliceCandidate],
        ) -> tuple[bool, list[SceneSliceCandidate]]:
            gap_start = gap[0].start_chapter
            gap_end = gap[-1].end_chapter
            chapters = [
                chapter_by_index[index]
                for index in range(gap_start, gap_end + 1)
                if index in chapter_by_index
            ]
            if len(chapters) != gap_end - gap_start + 1:
                return False, []
            left, right = _gap_neighbors(
                existing_candidates,
                gap_start=gap_start,
                gap_end=gap_end,
            )
            try:
                raw = await recover(
                    {
                        "gap": {
                            "start_chapter": gap_start,
                            "end_chapter": gap_end,
                        },
                        "chapters": chapters,
                        # Compatibility alias for existing test/provider doubles.
                        "chapter": chapters[0] if len(chapters) == 1 else None,
                        "left_scene": _recovery_neighbor_payload(left),
                        "right_scene": _recovery_neighbor_payload(right),
                        "left_boundary_text": _recovery_boundary_text(
                            left,
                            chapter_by_index,
                            side="left",
                        ),
                        "right_boundary_text": _recovery_boundary_text(
                            right,
                            chapter_by_index,
                            side="right",
                        ),
                        "reference_context": _reference_context_for_gap(
                            windows,
                            gap_start=gap_start,
                            gap_end=gap_end,
                        ),
                    }
                )
                output = (
                    raw
                    if isinstance(raw, SceneRecoveryOutput)
                    else SceneRecoveryOutput.model_validate(raw)
                )
                if output.status != "resolved":
                    return False, []
                materialized = _materialize_recovery_output(
                    output,
                    gap_start=gap_start,
                    gap_end=gap_end,
                    chapter_by_index=chapter_by_index,
                    left=left,
                    right=right,
                )
                if materialized is None:
                    return False, []
                recovered, replacements = materialized
                _apply_candidate_replacements(existing_candidates, replacements)
                return True, recovered
            except Exception:
                return False, []

        recovered: list[SceneSliceCandidate] = []
        remaining: list[SceneSliceCandidate] = []
        succeeded_chapters = 0
        succeeded_gaps = 0
        for gap in gaps:
            succeeded, group = await recover_one(gap)
            if succeeded:
                recovered.extend(group)
                succeeded_chapters += len(gap)
                succeeded_gaps += 1
            else:
                remaining.extend(gap)
        return (
            recovered,
            remaining,
            {
                "chapter_recovery_attempted_count": len(fallback_candidates),
                "chapter_recovery_succeeded_count": succeeded_chapters,
                "chapter_recovery_failed_count": len(remaining),
                "recovery_gap_attempted_count": len(gaps),
                "recovery_gap_succeeded_count": succeeded_gaps,
                "recovery_gap_failed_count": len(gaps) - succeeded_gaps,
            },
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
        structured_diagnostics: list[dict[str, Any]] = []
        last_output: SceneSlicingOutput | None = None
        for max_tokens in token_attempts:
            payload = _window_payload(window, chapters, max_tokens=max_tokens)
            retry_result = await run_deep_import_llm_with_retry(
                lambda payload=payload: self._call_and_validate(payload),
                is_empty_result=_empty_slicing_output,
                max_retries=1,
                retryable_error_types={"network", "rate_limit", "timeout"},
            )
            retry_results.append(retry_result)
            structured_diagnostics.extend(
                _pop_llm_diagnostics(self.llm, window.window_id)
            )
            if retry_result.final_status == "success":
                output = retry_result.value
                if not isinstance(output, SceneSlicingOutput):
                    output = SceneSlicingOutput.model_validate(output)
                normalized = _normalize_output(window, output, chapter_by_index)
                exact_overlaps = _exact_candidate_overlaps(normalized)
                exact_gaps = _exact_internal_candidate_gaps(
                    normalized,
                    chapter_by_index,
                    start_chapter=window.owned_start,
                    end_chapter=window.owned_end,
                )
                semantic_retry_failure: dict[str, Any] | None = None
                overlap_retry_attempted = bool(exact_overlaps)
                coverage_retry_attempted = bool(exact_gaps)
                if normalized and (exact_overlaps or exact_gaps):
                    correction_payload = _window_payload(
                        window,
                        chapters,
                        max_tokens=max_tokens,
                    )
                    correction_payload["validation_feedback"] = {
                        "kind": (
                            "scene_span_integrity"
                            if exact_overlaps and exact_gaps
                            else "overlapping_scene_spans"
                            if exact_overlaps
                            else "uncovered_scene_spans"
                        ),
                        "overlaps": exact_overlaps,
                        "uncovered_spans": exact_gaps,
                        "previous_output": output.model_dump(mode="json"),
                    }
                    correction_result = await run_deep_import_llm_with_retry(
                        lambda: self._call_and_validate(correction_payload),
                        is_empty_result=_empty_slicing_output,
                        max_retries=1,
                        retryable_error_types={"network", "rate_limit", "timeout"},
                    )
                    structured_diagnostics.extend(
                        _pop_llm_diagnostics(self.llm, window.window_id)
                    )
                    if correction_result.final_status == "success":
                        retry_results.append(correction_result)
                        corrected_output = correction_result.value
                        if not isinstance(corrected_output, SceneSlicingOutput):
                            corrected_output = SceneSlicingOutput.model_validate(
                                corrected_output
                            )
                        corrected = _normalize_output(
                            window,
                            corrected_output,
                            chapter_by_index,
                        )
                        if corrected:
                            output = corrected_output
                            normalized = corrected
                            exact_overlaps = _exact_candidate_overlaps(normalized)
                            exact_gaps = _exact_internal_candidate_gaps(
                                normalized,
                                chapter_by_index,
                                start_chapter=window.owned_start,
                                end_chapter=window.owned_end,
                            )
                    else:
                        semantic_retry_failure = correction_result.model_dump(
                            mode="json",
                            exclude={"value"},
                        )
                if exact_overlaps:
                    _mark_exact_overlaps_for_review(normalized, exact_overlaps)
                if exact_gaps:
                    _mark_exact_gaps_for_review(normalized, exact_gaps)
                if normalized or (
                    not output.scenes
                    and output.window_edges.leading_relation == "continues_from_left"
                ):
                    last_output = output
                    diagnostics = _diagnostics(
                        window,
                        retry_results,
                        max_tokens,
                        structured_diagnostics=structured_diagnostics,
                    )
                    diagnostics["window_edges"] = output.window_edges.model_dump(
                        mode="json"
                    )
                    diagnostics["semantic_overlap_retry"] = {
                        "attempted": overlap_retry_attempted,
                        "failure": semantic_retry_failure,
                        "remaining_overlap_count": len(exact_overlaps),
                        "remaining_overlaps": exact_overlaps,
                    }
                    diagnostics["semantic_coverage_retry"] = {
                        "attempted": coverage_retry_attempted,
                        "failure": semantic_retry_failure,
                        "remaining_gap_count": len(exact_gaps),
                        "remaining_gaps": exact_gaps,
                    }
                    return _WindowSliceResult(
                        window=window,
                        candidates=normalized,
                        diagnostics=diagnostics,
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
                and latest_result.final_error_type not in {"schema_error", "empty_result"}
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
                structured_diagnostics=structured_diagnostics,
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
    payload = {
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
    payload["left_boundary_context"] = getattr(
        window,
        "left_boundary_context",
        None,
    )
    payload["reference_context"] = getattr(window, "reference_context", None)
    return payload


def _empty_slicing_output(output: SceneSlicingOutput) -> bool:
    return not output.scenes and (
        output.window_edges.leading_relation != "continues_from_left"
    )


def _exact_candidate_overlaps(
    candidates: Sequence[SceneSliceCandidate],
) -> list[dict[str, Any]]:
    """Return only overlaps proven by exact offsets within one LLM window."""

    overlaps: list[dict[str, Any]] = []
    for left_index, left in enumerate(candidates):
        for right in candidates[left_index + 1 :]:
            for left_chunk in left.scene_chunks:
                if left_chunk.start_offset is None or left_chunk.end_offset is None:
                    continue
                for right_chunk in right.scene_chunks:
                    if (
                        right_chunk.chapter_index != left_chunk.chapter_index
                        or right_chunk.start_offset is None
                        or right_chunk.end_offset is None
                    ):
                        continue
                    start = max(left_chunk.start_offset, right_chunk.start_offset)
                    end = min(left_chunk.end_offset, right_chunk.end_offset)
                    if start >= end:
                        continue
                    overlaps.append(
                        {
                            "left_candidate_id": left.candidate_id,
                            "right_candidate_id": right.candidate_id,
                            "chapter_index": left_chunk.chapter_index,
                            "start_offset": start,
                            "end_offset": end,
                            "overlap_chars": end - start,
                        }
                    )
    return overlaps


def _exact_internal_candidate_gaps(
    candidates: Sequence[SceneSliceCandidate],
    chapter_by_index: dict[int, dict[str, Any]],
    *,
    start_chapter: int,
    end_chapter: int,
) -> list[dict[str, Any]]:
    """Return meaningful holes bounded by two exact Scene owners.

    Leading and trailing window text is governed by ``window_edges``. This helper
    deliberately reports only holes between two candidates so a continuation
    from an adjacent window is not mistaken for missing prose.
    """

    exact_chunks: list[tuple[int, int, int, SceneSliceCandidate]] = []
    for candidate in candidates:
        for chunk in candidate.scene_chunks:
            if (
                chunk.start_offset is None
                or chunk.end_offset is None
                or not start_chapter <= chunk.chapter_index <= end_chapter
            ):
                continue
            exact_chunks.append(
                (
                    chunk.chapter_index,
                    int(chunk.start_offset),
                    int(chunk.end_offset),
                    candidate,
                )
            )
    exact_chunks.sort(key=lambda item: (item[0], item[1], item[2], item[3].candidate_id))

    gaps: list[dict[str, Any]] = []
    for left, right in zip(exact_chunks, exact_chunks[1:], strict=False):
        left_chapter, _left_start, left_end, left_candidate = left
        right_chapter, right_start, _right_end, right_candidate = right
        if left_candidate.candidate_id == right_candidate.candidate_id:
            continue
        if (right_chapter, right_start) <= (left_chapter, left_end):
            continue
        spans = _gap_spans_between_positions(
            chapter_by_index,
            start=(left_chapter, left_end),
            end=(right_chapter, right_start),
        )
        if not spans or not any(
            _gap_requires_semantic_recovery(str(span.get("text") or "")) for span in spans
        ):
            continue
        gaps.append(
            {
                "left_candidate_id": left_candidate.candidate_id,
                "right_candidate_id": right_candidate.candidate_id,
                "spans": spans,
                "gap_chars": sum(
                    int(span["end_offset"]) - int(span["start_offset"]) for span in spans
                ),
                "meaningful_chars": sum(
                    _meaningful_character_count(str(span.get("text") or ""))
                    for span in spans
                ),
            }
        )
    return gaps


def _gap_spans_between_positions(
    chapter_by_index: dict[int, dict[str, Any]],
    *,
    start: tuple[int, int],
    end: tuple[int, int],
) -> list[dict[str, Any]]:
    start_chapter, start_offset = start
    end_chapter, end_offset = end
    spans: list[dict[str, Any]] = []
    for chapter_index in range(start_chapter, end_chapter + 1):
        content = str((chapter_by_index.get(chapter_index) or {}).get("content") or "")
        if not content:
            continue
        span_start = start_offset if chapter_index == start_chapter else 0
        span_end = end_offset if chapter_index == end_chapter else len(content)
        if span_start >= span_end:
            continue
        spans.append(
            {
                "chapter_index": chapter_index,
                "start_offset": span_start,
                "end_offset": span_end,
                "text": content[span_start:span_end],
            }
        )
    return spans


def _meaningful_character_count(text: str) -> int:
    return sum(
        1 for character in text if unicodedata.category(character)[:1] in {"L", "M", "N"}
    )


def _gap_requires_semantic_recovery(text: str) -> bool:
    return _meaningful_character_count(text) > 0


def _mark_exact_gaps_for_review(
    candidates: Sequence[SceneSliceCandidate],
    gaps: Sequence[dict[str, Any]],
) -> None:
    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    affected_ids = {
        str(item.get(key) or "")
        for item in gaps
        for key in ("left_candidate_id", "right_candidate_id")
    }
    for candidate_id in affected_ids:
        candidate = by_id.get(candidate_id)
        if candidate is None:
            continue
        candidate.needs_review = True
        candidate.review_reason = " ".join(
            part
            for part in (
                candidate.review_reason,
                "Phase1a left meaningful source text unassigned after semantic "
                "correction.",
            )
            if part
        )
        candidate.diagnostics["exact_span_gaps"] = [
            dict(item)
            for item in gaps
            if candidate_id
            in {
                str(item.get("left_candidate_id") or ""),
                str(item.get("right_candidate_id") or ""),
            }
        ]


def _exact_source_coverage_gaps(
    candidates: Sequence[SceneSliceCandidate],
    chapter_by_index: dict[int, dict[str, Any]],
    *,
    requested_chapter_indices: Sequence[int],
) -> list[dict[str, Any]]:
    """Find every exact offset hole without treating chapter presence as coverage."""

    by_chapter: dict[
        int,
        list[tuple[int, int, str]],
    ] = {}
    for candidate in candidates:
        for chunk in candidate.scene_chunks:
            if chunk.start_offset is None or chunk.end_offset is None:
                continue
            by_chapter.setdefault(chunk.chapter_index, []).append(
                (
                    int(chunk.start_offset),
                    int(chunk.end_offset),
                    candidate.candidate_id,
                )
            )

    gaps: list[dict[str, Any]] = []
    for chapter_index in requested_chapter_indices:
        content = str((chapter_by_index.get(chapter_index) or {}).get("content") or "")
        if not content:
            continue
        intervals = sorted(by_chapter.get(chapter_index, []))
        cursor = 0
        left_candidate_id: str | None = None
        for start, end, candidate_id in intervals:
            if start > cursor:
                text = content[cursor:start]
                gaps.append(
                    _coverage_gap_payload(
                        chapter_index=chapter_index,
                        start_offset=cursor,
                        end_offset=start,
                        text=text,
                        left_candidate_id=left_candidate_id,
                        right_candidate_id=candidate_id,
                        edge_kind="leading" if cursor == 0 else "internal",
                    )
                )
            if end > cursor:
                cursor = end
                left_candidate_id = candidate_id
        if cursor < len(content):
            text = content[cursor:]
            gaps.append(
                _coverage_gap_payload(
                    chapter_index=chapter_index,
                    start_offset=cursor,
                    end_offset=len(content),
                    text=text,
                    left_candidate_id=left_candidate_id,
                    right_candidate_id=None,
                    edge_kind="full" if not intervals else "trailing",
                )
            )
    global_intervals = sorted(
        (
            chapter_index,
            start,
            end,
            candidate_id,
        )
        for chapter_index, intervals in by_chapter.items()
        for start, end, candidate_id in intervals
    )
    for gap in gaps:
        chapter_index = int(gap["chapter_index"])
        start_offset = int(gap["start_offset"])
        end_offset = int(gap["end_offset"])
        if not gap.get("left_candidate_id"):
            previous = [
                interval
                for interval in global_intervals
                if (interval[0], interval[2]) <= (chapter_index, start_offset)
            ]
            if previous:
                gap["left_candidate_id"] = max(
                    previous,
                    key=lambda item: (item[0], item[2], item[1], item[3]),
                )[3]
        if not gap.get("right_candidate_id"):
            following = [
                interval
                for interval in global_intervals
                if (interval[0], interval[1]) >= (chapter_index, end_offset)
            ]
            if following:
                gap["right_candidate_id"] = min(
                    following,
                    key=lambda item: (item[0], item[1], item[2], item[3]),
                )[3]
    return gaps


def _coverage_gap_payload(
    *,
    chapter_index: int,
    start_offset: int,
    end_offset: int,
    text: str,
    left_candidate_id: str | None,
    right_candidate_id: str | None,
    edge_kind: str,
) -> dict[str, Any]:
    return {
        "chapter_index": chapter_index,
        "start_offset": start_offset,
        "end_offset": end_offset,
        "gap_chars": end_offset - start_offset,
        "meaningful_chars": _meaningful_character_count(text),
        "text": text,
        "left_candidate_id": left_candidate_id,
        "right_candidate_id": right_candidate_id,
        "edge_kind": edge_kind,
    }


def _absorb_trivial_exact_gaps(
    candidates: list[SceneSliceCandidate],
    chapter_by_index: dict[int, dict[str, Any]],
    *,
    requested_chapter_indices: Sequence[int],
) -> dict[str, Any]:
    """Assign whitespace/punctuation separators without asking the model."""

    gaps = _exact_source_coverage_gaps(
        candidates,
        chapter_by_index,
        requested_chapter_indices=requested_chapter_indices,
    )
    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    absorbed: list[dict[str, Any]] = []
    for gap in gaps:
        if int(gap["meaningful_chars"]) > 0:
            continue
        chapter_index = int(gap["chapter_index"])
        candidate: SceneSliceCandidate | None = None
        candidate_id = ""
        chunk_index: int | None = None
        for raw_candidate_id in (
            gap.get("left_candidate_id"),
            gap.get("right_candidate_id"),
        ):
            possible_id = str(raw_candidate_id or "")
            possible = by_id.get(possible_id)
            if possible is None:
                continue
            possible_chunk_index = _chunk_index(possible, chapter_index)
            if possible_chunk_index is None:
                continue
            candidate = possible
            candidate_id = possible_id
            chunk_index = possible_chunk_index
            break
        if candidate is None or chunk_index is None:
            continue
        chunk = candidate.scene_chunks[chunk_index]
        if chunk.start_offset is None or chunk.end_offset is None:
            continue
        start_offset = int(chunk.start_offset)
        end_offset = int(chunk.end_offset)
        if gap.get("left_candidate_id") == candidate_id:
            end_offset = int(gap["end_offset"])
        else:
            start_offset = int(gap["start_offset"])
        _replace_exact_chunk(
            candidate,
            chunk_index=chunk_index,
            chapter_index=chapter_index,
            start_offset=start_offset,
            end_offset=end_offset,
            chapter_by_index=chapter_by_index,
        )
        absorbed.append({key: value for key, value in gap.items() if key != "text"})
    return {
        "kind": "trivial_exact_gap_absorption",
        "absorbed_gap_count": len(absorbed),
        "absorbed_gaps": absorbed,
    }


def _replace_exact_chunk(
    candidate: SceneSliceCandidate,
    *,
    chunk_index: int,
    chapter_index: int,
    start_offset: int,
    end_offset: int,
    chapter_by_index: dict[int, dict[str, Any]],
) -> None:
    chapter = chapter_by_index.get(chapter_index) or {}
    content = str(chapter.get("content") or "")
    selected = content[start_offset:end_offset]
    candidate.scene_chunks[chunk_index] = SceneChunk(
        chapter_index=chapter_index,
        start_offset=start_offset,
        end_offset=end_offset,
        source_draft_id=_source_draft_id(chapter),
        source_content_hash=_source_content_hash(chapter),
        anchor_hash=hashlib.sha256(selected.encode("utf-8")).hexdigest(),
        anchor_excerpt=selected[:256],
    )
    candidate.diagnostics.setdefault("trivial_gap_absorbed_chapters", []).append(
        chapter_index
    )


def _fallback_required_exact_gaps(
    gaps: Sequence[dict[str, Any]],
    chapter_by_index: dict[int, dict[str, Any]],
    *,
    leading_edge: str,
    trailing_edge: str,
    requested_chapter_indices: Sequence[int],
) -> list[SceneSliceCandidate]:
    if not requested_chapter_indices:
        return []
    first_chapter = min(requested_chapter_indices)
    last_chapter = max(requested_chapter_indices)
    fallbacks: list[SceneSliceCandidate] = []
    for gap in gaps:
        meaningful_chars = int(gap.get("meaningful_chars") or 0)
        if meaningful_chars <= 0:
            continue
        left_id = str(gap.get("left_candidate_id") or "")
        right_id = str(gap.get("right_candidate_id") or "")
        chapter_index = int(gap["chapter_index"])
        required = bool(left_id and right_id)
        if not left_id and chapter_index == first_chapter and leading_edge == "new_scene":
            required = True
        if (
            not right_id
            and chapter_index == last_chapter
            and trailing_edge == "ends_in_input"
        ):
            required = True
        if gap.get("edge_kind") == "full":
            required = True
        if not required:
            continue
        chapter = chapter_by_index.get(chapter_index) or {}
        content = str(chapter.get("content") or "")
        start_offset = int(gap["start_offset"])
        end_offset = int(gap["end_offset"])
        selected = content[start_offset:end_offset]
        fallbacks.append(
            SceneSliceCandidate(
                candidate_id=(
                    f"phase1a-gap-fallback-{chapter_index:04d}-"
                    f"{start_offset:08d}-{end_offset:08d}"
                ),
                source_window_id=f"gap-fallback-{chapter_index:04d}",
                source_window_index=chapter_index,
                title=f"第{chapter_index}章未归属正文",
                goal="保留未能可靠归属的正文片段，等待人工复核。",
                core_conflict="",
                core_conflict_status="uncertain",
                phase1a_confidence=0.0,
                boundary_basis=(
                    "Phase1a semantic correction still left meaningful source text "
                    "without an exact Scene owner."
                ),
                start_chapter=chapter_index,
                end_chapter=chapter_index,
                boundary_status="fallback",
                source_chapter_indices=[chapter_index],
                scene_chunks=[
                    SceneChunk(
                        chapter_index=chapter_index,
                        start_offset=start_offset,
                        end_offset=end_offset,
                        source_draft_id=_source_draft_id(chapter),
                        source_content_hash=_source_content_hash(chapter),
                        anchor_hash=hashlib.sha256(selected.encode("utf-8")).hexdigest(),
                        anchor_excerpt=selected[:256],
                    )
                ],
                needs_review=True,
                review_reason=(
                    "Phase1a left meaningful prose unassigned after semantic "
                    "correction; an exact fallback span was preserved."
                ),
                diagnostics={
                    "fallback": True,
                    "partial_gap_fallback": True,
                    "source_mapping": "exact",
                    "unresolved_chapters": [],
                    "coverage_gap": {
                        key: value for key, value in gap.items() if key != "text"
                    },
                },
            )
        )
    return fallbacks


def _leading_window_relation(window_results: Sequence[_WindowSliceResult]) -> str:
    if not window_results:
        return "uncertain"
    first = min(window_results, key=lambda result: result.window.window_index)
    edges = first.diagnostics.get("window_edges")
    return (
        str(edges.get("leading_relation") or "uncertain")
        if isinstance(edges, dict)
        else "uncertain"
    )


def _trailing_window_relation(window_results: Sequence[_WindowSliceResult]) -> str:
    if not window_results:
        return "uncertain"
    last = max(window_results, key=lambda result: result.window.window_index)
    edges = last.diagnostics.get("window_edges")
    return (
        str(edges.get("trailing_relation") or "uncertain")
        if isinstance(edges, dict)
        else "uncertain"
    )


def _mark_exact_overlaps_for_review(
    candidates: Sequence[SceneSliceCandidate],
    overlaps: Sequence[dict[str, Any]],
) -> None:
    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    affected_ids = {
        str(item.get(key) or "")
        for item in overlaps
        for key in ("left_candidate_id", "right_candidate_id")
    }
    for candidate_id in affected_ids:
        candidate = by_id.get(candidate_id)
        if candidate is None:
            continue
        candidate.needs_review = True
        candidate.review_reason = " ".join(
            part
            for part in (
                candidate.review_reason,
                "Phase1a exact source spans still overlap after semantic correction.",
            )
            if part
        )
        candidate.diagnostics["exact_span_overlaps"] = [
            dict(item)
            for item in overlaps
            if candidate_id
            in {
                str(item.get("left_candidate_id") or ""),
                str(item.get("right_candidate_id") or ""),
            }
        ]


def _quarantine_exact_overlap_ranges(
    candidates: Sequence[SceneSliceCandidate],
) -> tuple[list[SceneSliceCandidate], dict[str, Any]]:
    """Remove ambiguous ranges so recovery/fallback can restore safe coverage."""

    overlaps = _exact_candidate_overlaps(candidates)
    if not overlaps:
        return list(candidates), {
            "kind": "exact_span_overlap_quarantine",
            "status": "not_needed",
            "overlap_count": 0,
            "quarantined_candidate_count": 0,
            "quarantined_candidate_ids": [],
            "chapter_ranges": [],
        }

    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    directly_affected = {
        str(item.get(key) or "")
        for item in overlaps
        for key in ("left_candidate_id", "right_candidate_id")
    }
    raw_ranges = sorted(
        (
            candidate.start_chapter,
            candidate.end_chapter,
        )
        for candidate_id in directly_affected
        if (candidate := by_id.get(candidate_id)) is not None
    )
    merged_ranges: list[list[int]] = []
    for start, end in raw_ranges:
        if not merged_ranges or start > merged_ranges[-1][1] + 1:
            merged_ranges.append([start, end])
            continue
        merged_ranges[-1][1] = max(merged_ranges[-1][1], end)

    def touches_quarantined_range(candidate: SceneSliceCandidate) -> bool:
        return any(
            candidate.start_chapter <= end and candidate.end_chapter >= start
            for start, end in merged_ranges
        )

    quarantined = [
        candidate for candidate in candidates if touches_quarantined_range(candidate)
    ]
    kept = [
        candidate for candidate in candidates if not touches_quarantined_range(candidate)
    ]
    return kept, {
        "kind": "exact_span_overlap_quarantine",
        "status": "quarantined_for_recovery",
        "overlap_count": len(overlaps),
        "overlaps": overlaps,
        "quarantined_candidate_count": len(quarantined),
        "quarantined_candidate_ids": [
            candidate.candidate_id for candidate in quarantined
        ],
        "chapter_ranges": merged_ranges,
    }


def _coordinate_window_edges(
    window_results: Sequence[_WindowSliceResult],
    candidates: Sequence[SceneSliceCandidate],
) -> dict[str, Any]:
    ordered = sorted(window_results, key=lambda result: result.window.window_index)
    observations: list[dict[str, Any]] = []
    unresolved_continuations: list[str] = []
    mismatches: list[dict[str, Any]] = []
    previous_observation: dict[str, Any] | None = None
    for result in ordered:
        edges = result.diagnostics.get("window_edges")
        if not isinstance(edges, dict):
            edges = {
                "leading_relation": "uncertain",
                "trailing_relation": "uncertain",
                "reason": "No validated edge decision was returned.",
            }
        window_candidates = [
            candidate
            for candidate in candidates
            if candidate.source_window_id == result.window.window_id
        ]
        leading_relation = str(edges.get("leading_relation") or "uncertain")
        has_left_owner = any(
            candidate.source_window_index < result.window.window_index
            and candidate.start_chapter < result.window.owned_start
            and candidate.end_chapter >= result.window.owned_start
            for candidate in candidates
        )
        if leading_relation == "continues_from_left" and not has_left_owner:
            unresolved_continuations.append(result.window.window_id)
        observation = {
            "window_id": result.window.window_id,
            "owned_range": [
                result.window.owned_start,
                result.window.owned_end,
            ],
            "candidate_count": len(window_candidates),
            "leading_relation": leading_relation,
            "trailing_relation": str(edges.get("trailing_relation") or "uncertain"),
            "reason": str(edges.get("reason") or ""),
        }
        observations.append(observation)
        if previous_observation is not None:
            previous_trailing = previous_observation["trailing_relation"]
            mismatch_reason = ""
            if previous_trailing == "continues_right" and leading_relation == "new_scene":
                mismatch_reason = "previous_continuation_without_left_continuation"
            if mismatch_reason:
                mismatch = {
                    "left_window_id": previous_observation["window_id"],
                    "right_window_id": result.window.window_id,
                    "reason": mismatch_reason,
                }
                mismatches.append(mismatch)
                for candidate in candidates:
                    if candidate.source_window_id in {
                        previous_observation["window_id"],
                        result.window.window_id,
                    }:
                        candidate.needs_review = True
                        candidate.review_reason = " ".join(
                            part
                            for part in (
                                candidate.review_reason,
                                "Adjacent Phase1a window edge decisions conflict.",
                            )
                            if part
                        )
                        candidate.diagnostics.setdefault(
                            "window_edge_mismatches",
                            [],
                        ).append(mismatch)
        previous_observation = observation
    return {
        "kind": "window_edge_coordination",
        "window_count": len(ordered),
        "observations": observations,
        "unresolved_continuation_window_ids": unresolved_continuations,
        "mismatches": mismatches,
        "status": (
            "needs_recovery"
            if unresolved_continuations
            else "needs_review"
            if mismatches
            else "coordinated"
        ),
    }


def _normalize_output(
    window: SceneWindowPlan,
    output: SceneSlicingOutput,
    chapter_by_index: dict[int, dict[str, Any]],
) -> list[SceneSliceCandidate]:
    candidates: list[SceneSliceCandidate] = []
    for index, scene in enumerate(output.scenes, start=1):
        declared_start = int(scene.start_chapter)
        declared_end = int(scene.end_chapter)
        start_anchor_matches = _anchor_matches_in_chapters(
            chapter_by_index,
            scene.start_anchor,
        )
        end_anchor_matches = _anchor_matches_in_chapters(
            chapter_by_index,
            scene.end_anchor,
        )
        anchored_range = _anchored_scene_range(
            start_anchor_matches,
            end_anchor_matches,
        )
        original_start, original_end = anchored_range or (
            declared_start,
            declared_end,
        )
        if original_end < window.covered_start or original_start > window.covered_end:
            continue
        start = max(window.covered_start, original_start)
        end = min(window.covered_end, max(original_end, original_start))
        if not (window.owned_start <= start <= window.owned_end):
            continue
        scene_chunks, unresolved_chapters = _materialize_scene_chunks(
            scene,
            start_chapter=start,
            end_chapter=end,
            chapter_by_index=chapter_by_index,
        )
        conflict = (scene.core_conflict or "").strip()
        conflict_needs_review = scene.core_conflict_status == "uncertain"
        needs_review = (
            start != declared_start
            or end != declared_end
            or not scene.title.strip()
            or not scene.goal.strip()
            or conflict_needs_review
            or scene.boundary_status == "uncertain"
            or bool(unresolved_chapters)
        )
        review_reasons: list[str] = []
        if (
            start != declared_start
            or end != declared_end
            or not scene.title.strip()
            or not scene.goal.strip()
        ):
            review_reasons.append(
                "Phase1a normalized LLM range or filled empty locked fields."
            )
        if conflict_needs_review:
            review_reasons.append("Phase1a could not determine whether conflict applies.")
        if scene.boundary_status == "uncertain":
            review_reasons.append("Phase1a boundary remains uncertain.")
        if unresolved_chapters:
            review_reasons.append(
                "Source anchors were missing, ambiguous, or out of order for chapters: "
                + ", ".join(str(chapter) for chapter in unresolved_chapters)
                + "."
            )
        candidate = SceneSliceCandidate(
            candidate_id=f"phase1a-{window.window_id}-S{index:03d}",
            source_window_id=window.window_id,
            source_window_index=window.window_index,
            title=scene.title.strip() or f"第{start}章 Scene",
            goal=scene.goal.strip(),
            core_conflict=conflict,
            core_conflict_status=scene.core_conflict_status,
            phase1a_confidence=scene.confidence,
            boundary_basis=scene.boundary_basis,
            start_chapter=start,
            end_chapter=end,
            boundary_status=scene.boundary_status.strip() or "uncertain",
            source_chapter_indices=list(range(start, end + 1)),
            scene_chunks=scene_chunks,
            needs_review=needs_review,
            review_reason=" ".join(review_reasons),
            diagnostics={
                "declared_chapter_range": [declared_start, declared_end],
                "start_anchor": scene.start_anchor,
                "end_anchor": scene.end_anchor,
                "window_edges": output.window_edges.model_dump(mode="json"),
                "anchored_chapter_range": (
                    list(anchored_range) if anchored_range is not None else None
                ),
                "start_anchor_matches": [list(match) for match in start_anchor_matches],
                "end_anchor_matches": [list(match) for match in end_anchor_matches],
                "source_mapping": (
                    "exact" if not unresolved_chapters else "partial_or_unresolved"
                ),
                "unresolved_chapters": unresolved_chapters,
            },
        )
        candidates.append(candidate)
    return candidates


def _anchored_scene_range(
    start_matches: list[tuple[int, int, int]],
    end_matches: list[tuple[int, int, int]],
) -> tuple[int, int] | None:
    if len(start_matches) != 1 or len(end_matches) != 1:
        return None
    start_chapter = start_matches[0][0]
    end_chapter = end_matches[0][0]
    if start_chapter > end_chapter:
        return None
    if start_chapter == end_chapter and start_matches[0][1] >= end_matches[0][2]:
        return None
    return start_chapter, end_chapter


def _anchor_matches_in_chapters(
    chapter_by_index: dict[int, dict[str, Any]],
    anchor: str,
) -> list[tuple[int, int, int]]:
    return [
        (chapter_index, start_offset, end_offset)
        for chapter_index, chapter in sorted(chapter_by_index.items())
        for start_offset, end_offset in _anchor_ranges(
            str(chapter.get("content") or ""),
            anchor,
        )
    ]


def _materialize_scene_chunks(
    scene: SceneSliceItem,
    *,
    start_chapter: int,
    end_chapter: int,
    chapter_by_index: dict[int, dict[str, Any]],
) -> tuple[list[SceneChunk], list[int]]:
    """Resolve copied boundary anchors against frozen local chapter text."""
    chunks: list[SceneChunk] = []
    unresolved: list[int] = []
    for chapter_index in range(start_chapter, end_chapter + 1):
        chapter = chapter_by_index.get(chapter_index) or {}
        content = str(chapter.get("content") or "")
        offsets = _scene_offsets_for_chapter(
            content,
            chapter_index=chapter_index,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            start_anchor=scene.start_anchor,
            end_anchor=scene.end_anchor,
        )
        if offsets is None:
            chunks.append(SceneChunk(chapter_index=chapter_index))
            unresolved.append(chapter_index)
            continue
        start_offset, end_offset = offsets
        excerpt = content[start_offset : min(end_offset, start_offset + 256)]
        selected = content[start_offset:end_offset]
        chunks.append(
            SceneChunk(
                chapter_index=chapter_index,
                start_offset=start_offset,
                end_offset=end_offset,
                source_draft_id=_source_draft_id(chapter),
                source_content_hash=_source_content_hash(chapter),
                anchor_hash=hashlib.sha256(selected.encode("utf-8")).hexdigest(),
                anchor_excerpt=excerpt,
            )
        )
    return chunks, unresolved


def _scene_offsets_for_chapter(
    content: str,
    *,
    chapter_index: int,
    start_chapter: int,
    end_chapter: int,
    start_anchor: str,
    end_anchor: str,
) -> tuple[int, int] | None:
    if not content:
        return None
    if chapter_index == start_chapter == end_chapter:
        return _unique_ordered_anchor_pair(content, start_anchor, end_anchor)
    if chapter_index == start_chapter:
        starts = _anchor_ranges(content, start_anchor)
        return (starts[0][0], len(content)) if len(starts) == 1 else None
    if chapter_index == end_chapter:
        ends = _anchor_ranges(content, end_anchor)
        if len(ends) != 1:
            return None
        return 0, ends[0][1]
    return 0, len(content)


def _unique_ordered_anchor_pair(
    content: str,
    start_anchor: str,
    end_anchor: str,
) -> tuple[int, int] | None:
    pairs = [
        (start, end)
        for start, _start_end in _anchor_ranges(content, start_anchor)
        for _end_start, end in _anchor_ranges(content, end_anchor)
        if start < end
    ]
    return pairs[0] if len(pairs) == 1 else None


def _anchor_ranges(content: str, anchor: str) -> list[tuple[int, int]]:
    normalized_content, original_positions = _normalize_anchor_text(content)
    normalized_anchor, _ = _normalize_anchor_text(anchor)
    if not normalized_content or not normalized_anchor:
        return []
    ranges: list[tuple[int, int]] = []
    start = 0
    while True:
        position = normalized_content.find(normalized_anchor, start)
        if position < 0:
            return ranges
        end_position = position + len(normalized_anchor) - 1
        ranges.append(
            (
                original_positions[position],
                original_positions[end_position] + 1,
            )
        )
        start = position + 1


def _normalize_anchor_text(text: str) -> tuple[str, list[int]]:
    characters: list[str] = []
    original_positions: list[int] = []
    for position, character in enumerate(str(text or "")):
        if character.isspace():
            continue
        characters.append(character)
        original_positions.append(position)
    return "".join(characters), original_positions


def _infer_chunks_from_neighbor_anchors(
    candidates: list[SceneSliceCandidate],
    chapter_by_index: dict[int, dict[str, Any]],
) -> None:
    """Close one-sided boundaries from coverage and adjacent proven offsets."""
    by_chapter: dict[int, list[SceneSliceCandidate]] = {}
    for candidate in candidates:
        for chapter_index in candidate.source_chapter_indices:
            by_chapter.setdefault(chapter_index, []).append(candidate)

    for chapter_index, chapter_candidates in by_chapter.items():
        content = str((chapter_by_index.get(chapter_index) or {}).get("content") or "")
        if not content:
            continue
        ordered = sorted(
            chapter_candidates,
            key=lambda candidate: (
                candidate.start_chapter,
                candidate.source_window_index,
                candidate.candidate_id,
            ),
        )
        for position, candidate in enumerate(ordered):
            chunk_index = _chunk_index(candidate, chapter_index)
            if chunk_index is None:
                continue
            chunk = candidate.scene_chunks[chunk_index]
            if chunk.start_offset is not None and chunk.end_offset is not None:
                continue
            start_offset = _candidate_anchor_boundary(
                candidate,
                "start_anchor_matches",
                chapter_index,
                boundary_index=1,
            )
            end_offset = _candidate_anchor_boundary(
                candidate,
                "end_anchor_matches",
                chapter_index,
                boundary_index=2,
            )
            if chapter_index > candidate.start_chapter:
                start_offset = 0
            if chapter_index < candidate.end_chapter:
                end_offset = len(content)
            if len(ordered) == 1 and candidate.start_chapter != candidate.end_chapter:
                inferred_from_single_owner = False
                if start_offset is None:
                    start_offset = 0
                    inferred_from_single_owner = True
                if end_offset is None:
                    end_offset = len(content)
                    inferred_from_single_owner = True
                if inferred_from_single_owner:
                    candidate.diagnostics.setdefault(
                        "single_owner_inferred_chapters", []
                    ).append(chapter_index)
            if start_offset is None and position > 0:
                previous = ordered[position - 1]
                previous_chunk = _chunk_for_chapter(previous, chapter_index)
                if previous_chunk is not None and previous_chunk.end_offset is not None:
                    start_offset = previous_chunk.end_offset
            if end_offset is None and position + 1 < len(ordered):
                following = ordered[position + 1]
                following_chunk = _chunk_for_chapter(following, chapter_index)
                if (
                    following_chunk is not None
                    and following_chunk.start_offset is not None
                ):
                    end_offset = following_chunk.start_offset
            if (
                start_offset is None
                or end_offset is None
                or not 0 <= start_offset < end_offset <= len(content)
            ):
                continue
            selected = content[start_offset:end_offset]
            candidate.scene_chunks[chunk_index] = SceneChunk(
                chapter_index=chapter_index,
                start_offset=start_offset,
                end_offset=end_offset,
                source_draft_id=_source_draft_id(
                    chapter_by_index.get(chapter_index) or {}
                ),
                source_content_hash=_source_content_hash(
                    chapter_by_index.get(chapter_index) or {}
                ),
                anchor_hash=hashlib.sha256(selected.encode("utf-8")).hexdigest(),
                anchor_excerpt=selected[:256],
            )
            candidate.diagnostics.setdefault("neighbor_inferred_chapters", []).append(
                chapter_index
            )
            unresolved = candidate.diagnostics.get("unresolved_chapters")
            if isinstance(unresolved, list) and chapter_index in unresolved:
                unresolved.remove(chapter_index)
        for candidate in ordered:
            unresolved = candidate.diagnostics.get("unresolved_chapters")
            if isinstance(unresolved, list) and not unresolved:
                candidate.diagnostics["source_mapping"] = "exact"


def _source_draft_id(chapter: dict[str, Any]) -> str | None:
    value = chapter.get("source_draft_id")
    return str(value) if value else None


def _source_content_hash(chapter: dict[str, Any]) -> str | None:
    value = str(chapter.get("source_content_hash") or "")
    return value if len(value) == 64 else None


def _candidate_anchor_boundary(
    candidate: SceneSliceCandidate,
    key: str,
    chapter_index: int,
    *,
    boundary_index: int,
) -> int | None:
    raw_matches = candidate.diagnostics.get(key)
    if not isinstance(raw_matches, list):
        return None
    matches = [
        match
        for match in raw_matches
        if isinstance(match, list) and len(match) == 3 and int(match[0]) == chapter_index
    ]
    if len(matches) != 1:
        return None
    return int(matches[0][boundary_index])


def _chunk_index(
    candidate: SceneSliceCandidate,
    chapter_index: int,
) -> int | None:
    return next(
        (
            index
            for index, chunk in enumerate(candidate.scene_chunks)
            if chunk.chapter_index == chapter_index
        ),
        None,
    )


def _chunk_for_chapter(
    candidate: SceneSliceCandidate,
    chapter_index: int,
) -> SceneChunk | None:
    index = _chunk_index(candidate, chapter_index)
    return candidate.scene_chunks[index] if index is not None else None


def _candidate_sort_key(candidate: SceneSliceCandidate) -> tuple[int, int, str]:
    return (
        candidate.start_chapter,
        candidate.end_chapter,
        candidate.candidate_id,
    )


def _candidate_has_exact_chunks(candidate: SceneSliceCandidate) -> bool:
    return bool(candidate.scene_chunks) and all(
        chunk.start_offset is not None and chunk.end_offset is not None
        for chunk in candidate.scene_chunks
    )


def _verified_neighbor_boundary(
    candidate: SceneSliceCandidate | None,
    *,
    side: Literal["start", "end"],
) -> dict[str, Any] | None:
    if candidate is None or not _candidate_has_exact_chunks(candidate):
        return None
    ordered = sorted(
        candidate.scene_chunks,
        key=lambda chunk: (
            chunk.chapter_index,
            chunk.start_offset if chunk.start_offset is not None else -1,
        ),
    )
    chunk = ordered[0] if side == "start" else ordered[-1]
    return {
        "candidate_id": candidate.candidate_id,
        "chapter_index": chunk.chapter_index,
        "offset": chunk.start_offset if side == "start" else chunk.end_offset,
        "anchor_excerpt": chunk.anchor_excerpt,
    }


def _continuous_fallback_gaps(
    fallbacks: Sequence[SceneSliceCandidate],
) -> list[list[SceneSliceCandidate]]:
    gaps: list[list[SceneSliceCandidate]] = []
    for fallback in sorted(fallbacks, key=_candidate_sort_key):
        if not gaps or fallback.start_chapter > gaps[-1][-1].end_chapter + 1:
            gaps.append([fallback])
        else:
            gaps[-1].append(fallback)
    return gaps


def _gap_neighbors(
    candidates: Sequence[SceneSliceCandidate],
    *,
    gap_start: int,
    gap_end: int,
) -> tuple[SceneSliceCandidate | None, SceneSliceCandidate | None]:
    left_candidates = [
        candidate for candidate in candidates if candidate.end_chapter < gap_start
    ]
    right_candidates = [
        candidate for candidate in candidates if candidate.start_chapter > gap_end
    ]
    left = max(left_candidates, key=_candidate_sort_key) if left_candidates else None
    right = min(right_candidates, key=_candidate_sort_key) if right_candidates else None
    return left, right


def _recovery_neighbor_payload(
    candidate: SceneSliceCandidate | None,
) -> dict[str, Any] | None:
    if candidate is None:
        return None
    return {
        "candidate_id": candidate.candidate_id,
        "title": candidate.title,
        "goal": candidate.goal,
        "core_conflict": candidate.core_conflict or None,
        "core_conflict_status": candidate.core_conflict_status,
        "start_chapter": candidate.start_chapter,
        "end_chapter": candidate.end_chapter,
        "boundary_status": candidate.boundary_status,
        "boundary_basis": candidate.boundary_basis,
        "scene_chunks": [
            chunk.model_dump(mode="json") for chunk in candidate.scene_chunks
        ],
    }


def _reference_context_for_gap(
    windows: Sequence[SceneWindowPlan],
    *,
    gap_start: int,
    gap_end: int,
) -> dict[str, Any]:
    selected = [
        window
        for window in windows
        if window.covered_start <= gap_end and window.covered_end >= gap_start
    ]
    if not selected:
        return {}
    if len(selected) == 1:
        return dict(selected[0].reference_context)
    return {
        "windows": [
            {
                "window_id": window.window_id,
                "owned_range": [window.owned_start, window.owned_end],
                "context": dict(window.reference_context),
            }
            for window in selected
        ]
    }


def _recovery_boundary_text(
    candidate: SceneSliceCandidate | None,
    chapter_by_index: dict[int, dict[str, Any]],
    *,
    side: Literal["left", "right"],
    max_chars: int = 2000,
) -> str:
    if candidate is None or not candidate.scene_chunks:
        return ""
    ordered = sorted(
        candidate.scene_chunks,
        key=lambda chunk: (
            chunk.chapter_index,
            int(chunk.start_offset or 0),
        ),
    )
    chunk = ordered[-1] if side == "left" else ordered[0]
    content = str((chapter_by_index.get(chunk.chapter_index) or {}).get("content") or "")
    if side == "left":
        end = chunk.end_offset if chunk.end_offset is not None else len(content)
        return content[max(0, end - max_chars) : end]
    start = chunk.start_offset or 0
    return content[start : start + max_chars]


def _materialize_recovery_output(
    output: SceneRecoveryOutput,
    *,
    gap_start: int,
    gap_end: int,
    chapter_by_index: dict[int, dict[str, Any]],
    left: SceneSliceCandidate | None,
    right: SceneSliceCandidate | None,
) -> (
    tuple[
        list[SceneSliceCandidate],
        dict[str, SceneSliceCandidate],
    ]
    | None
):
    disposition_order = {"extend_left": 0, "new_scene": 1, "extend_right": 2}
    previous_disposition = -1
    materialized: list[tuple[SceneRecoverySegment, list[SceneChunk]]] = []
    for segment in output.segments:
        disposition = disposition_order[segment.disposition]
        if disposition < previous_disposition:
            return None
        previous_disposition = disposition
        if not (gap_start <= segment.start_chapter <= segment.end_chapter <= gap_end):
            return None
        if segment.disposition == "extend_left" and left is None:
            return None
        if segment.disposition == "extend_right" and right is None:
            return None
        gap_chapters = {
            chapter_index: chapter_by_index[chapter_index]
            for chapter_index in range(gap_start, gap_end + 1)
            if chapter_index in chapter_by_index
        }
        start_matches = _anchor_matches_in_chapters(
            gap_chapters,
            segment.start_anchor,
        )
        end_matches = _anchor_matches_in_chapters(
            gap_chapters,
            segment.end_anchor,
        )
        if (
            len(start_matches) != 1
            or start_matches[0][0] != segment.start_chapter
            or len(end_matches) != 1
            or end_matches[0][0] != segment.end_chapter
        ):
            return None
        scene = SceneSliceItem(
            title=segment.title,
            goal=segment.goal,
            core_conflict=segment.core_conflict,
            core_conflict_status=segment.core_conflict_status,
            start_chapter=segment.start_chapter,
            end_chapter=segment.end_chapter,
            start_anchor=segment.start_anchor,
            end_anchor=segment.end_anchor,
            boundary_status=segment.boundary_status,
            boundary_basis=segment.boundary_basis,
            confidence=segment.confidence,
        )
        chunks, unresolved = _materialize_scene_chunks(
            scene,
            start_chapter=segment.start_chapter,
            end_chapter=segment.end_chapter,
            chapter_by_index=chapter_by_index,
        )
        if unresolved or not _chunks_have_frozen_sources(chunks, chapter_by_index):
            return None
        materialized.append((segment, chunks))
    if not _segments_exactly_cover_gap(
        materialized,
        gap_start=gap_start,
        gap_end=gap_end,
        chapter_by_index=chapter_by_index,
    ):
        return None

    replacements: dict[str, SceneSliceCandidate] = {}
    recovered: list[SceneSliceCandidate] = []
    for index, (segment, chunks) in enumerate(materialized, start=1):
        if segment.disposition == "new_scene":
            recovered.append(
                SceneSliceCandidate(
                    candidate_id=(
                        f"phase1a-recovery-{gap_start:04d}-{gap_end:04d}-S{index:03d}"
                    ),
                    source_window_id=f"recovery-{gap_start:04d}-{gap_end:04d}",
                    source_window_index=gap_start,
                    title=segment.title or f"第{segment.start_chapter}章 Scene",
                    goal=segment.goal,
                    core_conflict=segment.core_conflict or "",
                    core_conflict_status=segment.core_conflict_status,
                    phase1a_confidence=segment.confidence,
                    boundary_basis=segment.boundary_basis,
                    start_chapter=segment.start_chapter,
                    end_chapter=segment.end_chapter,
                    boundary_status=segment.boundary_status,
                    source_chapter_indices=list(
                        range(segment.start_chapter, segment.end_chapter + 1)
                    ),
                    scene_chunks=chunks,
                    needs_review=True,
                    review_reason="Recovered from a continuous Phase1a coverage gap.",
                    diagnostics={
                        "chapter_recovery": True,
                        "recovery_disposition": segment.disposition,
                        "left_right_relation": output.left_right_relation,
                        "recovery_reason": output.reason,
                        "source_mapping": "exact",
                        "unresolved_chapters": [],
                    },
                )
            )
            continue
        original = left if segment.disposition == "extend_left" else right
        if original is None:
            return None
        candidate = replacements.get(
            original.candidate_id,
            original.model_copy(deep=True),
        )
        _extend_candidate_with_recovery(
            candidate,
            chunks,
            segment=segment,
            output=output,
            chapter_by_index=chapter_by_index,
        )
        replacements[original.candidate_id] = candidate

    if output.left_right_relation == "same_scene":
        if left is None or right is None:
            return None
        for original in (left, right):
            candidate = replacements.get(
                original.candidate_id,
                original.model_copy(deep=True),
            )
            _mark_recovery_review(candidate, output)
            replacements[original.candidate_id] = candidate
    return recovered, replacements


def _chunks_have_frozen_sources(
    chunks: Sequence[SceneChunk],
    chapter_by_index: dict[int, dict[str, Any]],
) -> bool:
    for chunk in chunks:
        chapter = chapter_by_index.get(chunk.chapter_index)
        if chapter is None or chunk.start_offset is None or chunk.end_offset is None:
            return False
        if chunk.source_draft_id != _source_draft_id(chapter):
            return False
        if chunk.source_content_hash != _source_content_hash(chapter):
            return False
    return True


def _segments_exactly_cover_gap(
    materialized: Sequence[tuple[SceneRecoverySegment, list[SceneChunk]]],
    *,
    gap_start: int,
    gap_end: int,
    chapter_by_index: dict[int, dict[str, Any]],
) -> bool:
    if not materialized:
        return False
    previous_end: tuple[int, int] | None = None
    by_chapter: dict[int, list[tuple[int, int]]] = {}
    for _segment, chunks in materialized:
        ordered = sorted(
            chunks,
            key=lambda chunk: (chunk.chapter_index, int(chunk.start_offset or 0)),
        )
        first = ordered[0]
        last = ordered[-1]
        start_key = (first.chapter_index, int(first.start_offset or 0))
        end_key = (last.chapter_index, int(last.end_offset or 0))
        if previous_end is not None and start_key < previous_end:
            return False
        previous_end = end_key
        for chunk in ordered:
            if chunk.start_offset is None or chunk.end_offset is None:
                return False
            by_chapter.setdefault(chunk.chapter_index, []).append(
                (chunk.start_offset, chunk.end_offset)
            )
    for chapter_index in range(gap_start, gap_end + 1):
        content = str((chapter_by_index.get(chapter_index) or {}).get("content") or "")
        intervals = sorted(by_chapter.get(chapter_index, []))
        if not content or not intervals:
            return False
        cursor = 0
        for start, end in intervals:
            if start < cursor or not 0 <= start < end <= len(content):
                return False
            if content[cursor:start].strip():
                return False
            cursor = end
        if content[cursor:].strip():
            return False
    return True


def _extend_candidate_with_recovery(
    candidate: SceneSliceCandidate,
    chunks: Sequence[SceneChunk],
    *,
    segment: SceneRecoverySegment,
    output: SceneRecoveryOutput,
    chapter_by_index: dict[int, dict[str, Any]],
) -> None:
    candidate.scene_chunks = _union_exact_scene_chunks(
        [*candidate.scene_chunks, *chunks],
        chapter_by_index,
    )
    candidate.source_chapter_indices = sorted(
        {chunk.chapter_index for chunk in candidate.scene_chunks}
    )
    candidate.start_chapter = min(candidate.source_chapter_indices)
    candidate.end_chapter = max(candidate.source_chapter_indices)
    candidate.boundary_status = "uncertain"
    candidate.boundary_basis = " ".join(
        part for part in (candidate.boundary_basis, segment.boundary_basis) if part
    )
    candidate.phase1a_confidence = min(
        candidate.phase1a_confidence,
        segment.confidence,
    )
    _mark_recovery_review(candidate, output)


def _union_exact_scene_chunks(
    chunks: Sequence[SceneChunk],
    chapter_by_index: dict[int, dict[str, Any]],
) -> list[SceneChunk]:
    by_chapter: dict[int, list[SceneChunk]] = {}
    for chunk in chunks:
        by_chapter.setdefault(chunk.chapter_index, []).append(chunk)
    result: list[SceneChunk] = []
    for chapter_index, chapter_chunks in sorted(by_chapter.items()):
        ordered = sorted(
            chapter_chunks,
            key=lambda chunk: int(chunk.start_offset or 0),
        )
        if len(ordered) == 1:
            result.append(ordered[0])
            continue
        if any(
            chunk.start_offset is None or chunk.end_offset is None for chunk in ordered
        ):
            result.extend(ordered)
            continue
        start = min(int(chunk.start_offset) for chunk in ordered)
        end = max(int(chunk.end_offset) for chunk in ordered)
        content = str((chapter_by_index.get(chapter_index) or {}).get("content") or "")
        selected = content[start:end]
        chapter = chapter_by_index.get(chapter_index) or {}
        result.append(
            SceneChunk(
                chapter_index=chapter_index,
                start_offset=start,
                end_offset=end,
                source_draft_id=_source_draft_id(chapter),
                source_content_hash=_source_content_hash(chapter),
                anchor_hash=hashlib.sha256(selected.encode("utf-8")).hexdigest(),
                anchor_excerpt=selected[:256],
            )
        )
    return result


def _mark_recovery_review(
    candidate: SceneSliceCandidate,
    output: SceneRecoveryOutput,
) -> None:
    candidate.needs_review = True
    candidate.review_reason = " ".join(
        part
        for part in (
            candidate.review_reason,
            "Extended or linked by a Phase1a continuous-gap recovery.",
        )
        if part
    )
    candidate.diagnostics["chapter_recovery"] = True
    candidate.diagnostics["left_right_relation"] = output.left_right_relation
    candidate.diagnostics["recovery_reason"] = output.reason
    candidate.diagnostics["source_mapping"] = "exact"
    candidate.diagnostics["unresolved_chapters"] = []


def _apply_candidate_replacements(
    candidates: list[SceneSliceCandidate],
    replacements: dict[str, SceneSliceCandidate],
) -> None:
    for index, candidate in enumerate(candidates):
        replacement = replacements.get(candidate.candidate_id)
        if replacement is not None:
            candidates[index] = replacement


def _fallback_missing_chapters(
    candidates: Sequence[SceneSliceCandidate],
    plan: ScenePlanResult,
    chapter_by_index: dict[int, dict[str, Any]],
) -> list[SceneSliceCandidate]:
    requested = {int(chapter["chapter_index"]) for chapter in plan.chapters}
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
                core_conflict="",
                core_conflict_status="uncertain",
                phase1a_confidence=0.0,
                boundary_basis="Phase1a did not return usable coverage for this chapter.",
                start_chapter=chapter_index,
                end_chapter=chapter_index,
                boundary_status="fallback",
                source_chapter_indices=[chapter_index],
                scene_chunks=[_full_chapter_chunk(chapter_index, chapter)],
                needs_review=True,
                review_reason="Phase1a failed to cover this chapter.",
                diagnostics={
                    "fallback": True,
                    "chapter_index": chapter_index,
                    "source_mapping": "exact",
                    "unresolved_chapters": [],
                },
            )
        )
    return fallback


def _full_chapter_chunk(
    chapter_index: int,
    chapter: dict[str, Any],
) -> SceneChunk:
    content = str(chapter.get("content") or "")
    return SceneChunk(
        chapter_index=chapter_index,
        start_offset=0,
        end_offset=len(content),
        source_draft_id=_source_draft_id(chapter),
        source_content_hash=_source_content_hash(chapter),
        anchor_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        anchor_excerpt=content[:256],
    )


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
    structured_diagnostics: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    final = retry_results[-1] if retry_results else None
    return {
        "source_batch_id": window.window_id,
        "chapter_indices": window.chapter_indices,
        "owned_chapter_indices": window.owned_chapter_indices,
        "max_tokens": max_tokens,
        "token_attempts": [
            result.model_dump(mode="json", exclude={"value"}) for result in retry_results
        ],
        "attempts": sum(result.attempts for result in retry_results),
        "final_status": final.final_status if final else "failed",
        "final_error_type": final.final_error_type if final else "unknown",
        "empty_output": empty_output,
        "structured_diagnostics": list(structured_diagnostics or []),
    }


def _pop_llm_diagnostics(llm: Any, window_id: str) -> list[dict[str, Any]]:
    pop = getattr(llm, "pop_diagnostics", None)
    if not callable(pop):
        return []
    diagnostics = pop(window_id)
    return list(diagnostics) if isinstance(diagnostics, list) else []


def _quality_stats(
    window_results: list[_WindowSliceResult],
    *,
    fallback_count: int,
    candidates: list[SceneSliceCandidate],
) -> dict[str, Any]:
    exact_scene_count = sum(
        bool(candidate.scene_chunks)
        and all(
            chunk.start_offset is not None and chunk.end_offset is not None
            for chunk in candidate.scene_chunks
        )
        for candidate in candidates
    )
    exact_span_count = sum(
        chunk.start_offset is not None and chunk.end_offset is not None
        for candidate in candidates
        for chunk in candidate.scene_chunks
    )
    fallback_chapter_indices = sorted(
        {
            candidate.start_chapter
            for candidate in candidates
            if candidate.diagnostics.get("fallback") is True
        }
    )
    span_count = sum(len(candidate.scene_chunks) for candidate in candidates)
    structured_attempts = [
        {"source_batch_id": result.window.window_id, **diagnostic}
        for result in window_results
        for diagnostic in result.diagnostics.get("structured_diagnostics", [])
        if diagnostic.get("kind") == "structured_usage"
    ]
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
        "fallback_chapter_indices": fallback_chapter_indices,
        "scene_count": len(candidates),
        "exact_scene_count": exact_scene_count,
        "unresolved_scene_count": len(candidates) - exact_scene_count,
        "span_count": span_count,
        "exact_span_count": exact_span_count,
        "unresolved_span_count": span_count - exact_span_count,
        "exact_scene_rate": (exact_scene_count / len(candidates) if candidates else 0.0),
        "structured_attempts": structured_attempts,
        "length_retry_count": sum(
            attempt.get("error_kind") == "truncated_json"
            for attempt in structured_attempts
        ),
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
