"""Phase 1a Scene slicing for deep import."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from modules.imports.deep_import_retry import (
    DeepImportRetryResult,
    run_deep_import_llm_with_retry,
)
from modules.imports.env_helpers import positive_int_env
from modules.imports.llm_schemas import (
    SceneAnchorRepairOutput,
    SceneChunk,
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
        _infer_chunks_from_neighbor_anchors(candidates, chapter_by_index)
        anchor_repair_stats = await self._repair_unresolved_anchors(
            candidates,
            chapter_by_index,
        )
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
        )
        candidates.extend(recovered_candidates)
        candidates.extend(remaining_fallbacks)
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
        if remaining_fallbacks:
            diagnostics.append(
                {
                    "final_status": "fallback",
                    "final_error_type": "missing_chapter_coverage",
                    "fallback_count": len(remaining_fallbacks),
                    "chapter_indices": [
                        candidate.start_chapter for candidate in remaining_fallbacks
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
            fallback_count=len(remaining_fallbacks),
            candidates=candidates,
        )
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

        async def repair_one(candidate: SceneSliceCandidate) -> bool:
            chapters = [
                chapter_by_index[index]
                for index in candidate.source_chapter_indices
                if index in chapter_by_index
            ]
            payload = {
                "candidate": candidate.model_dump(mode="json"),
                "chapters": chapters,
            }
            try:
                async with semaphore:
                    raw = await repair(payload)
                output = (
                    raw
                    if isinstance(raw, SceneAnchorRepairOutput)
                    else SceneAnchorRepairOutput.model_validate(raw)
                )
                scene = SceneSliceItem(
                    title=candidate.title,
                    goal=candidate.goal,
                    core_conflict=candidate.core_conflict,
                    start_chapter=candidate.start_chapter,
                    end_chapter=candidate.end_chapter,
                    start_anchor=output.start_anchor,
                    end_anchor=output.end_anchor,
                    boundary_status=candidate.boundary_status,
                )
                chunks, unresolved = _materialize_scene_chunks(
                    scene,
                    start_chapter=candidate.start_chapter,
                    end_chapter=candidate.end_chapter,
                    chapter_by_index=chapter_by_index,
                )
                candidate.scene_chunks = chunks
                candidate.diagnostics["anchor_repair"] = {
                    "status": "succeeded" if not unresolved else "unresolved",
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
                    return True
                return False
            except Exception as exc:
                candidate.diagnostics["anchor_repair"] = {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                }
                return False

        outcomes = await asyncio.gather(*(repair_one(candidate) for candidate in targets))
        succeeded = sum(outcomes)
        return {
            "anchor_repair_attempted_count": len(targets),
            "anchor_repair_succeeded_count": succeeded,
            "anchor_repair_failed_count": len(targets) - succeeded,
        }

    async def _recover_missing_chapters(
        self,
        fallback_candidates: list[SceneSliceCandidate],
        chapter_by_index: dict[int, dict[str, Any]],
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
                },
            )
        semaphore = asyncio.Semaphore(min(3, self.concurrency))

        async def recover_one(
            fallback: SceneSliceCandidate,
        ) -> list[SceneSliceCandidate]:
            chapter_index = fallback.start_chapter
            chapter = chapter_by_index.get(chapter_index)
            if chapter is None:
                return []
            try:
                async with semaphore:
                    raw = await recover({"chapter": chapter})
                output = (
                    raw
                    if isinstance(raw, SceneSlicingOutput)
                    else SceneSlicingOutput.model_validate(raw)
                )
                window = SceneWindowPlan(
                    window_index=fallback.source_window_index,
                    window_id=f"recovery-{chapter_index:04d}",
                    covered_start=chapter_index,
                    covered_end=chapter_index,
                    owned_start=chapter_index,
                    owned_end=chapter_index,
                    chapter_indices=[chapter_index],
                    owned_chapter_indices=[chapter_index],
                    input_chars=len(str(chapter.get("content") or "")),
                    max_tokens=8192,
                    batch_size=1,
                    overlap=0,
                )
                recovered = _normalize_output(window, output, chapter_by_index)
                if not 1 <= len(recovered) <= 3 or any(
                    any(
                        chunk.start_offset is None or chunk.end_offset is None
                        for chunk in candidate.scene_chunks
                    )
                    for candidate in recovered
                ):
                    return []
                for candidate in recovered:
                    candidate.needs_review = True
                    candidate.review_reason = " ".join(
                        part
                        for part in (
                            candidate.review_reason,
                            "Recovered from a Phase1a missing-chapter retry.",
                        )
                        if part
                    )
                    candidate.diagnostics["chapter_recovery"] = True
                return recovered
            except Exception:
                return []

        recovered_groups = await asyncio.gather(
            *(recover_one(candidate) for candidate in fallback_candidates)
        )
        recovered: list[SceneSliceCandidate] = []
        remaining: list[SceneSliceCandidate] = []
        for fallback, group in zip(
            fallback_candidates,
            recovered_groups,
            strict=True,
        ):
            if group:
                recovered.extend(group)
            else:
                remaining.append(fallback)
        succeeded = len(fallback_candidates) - len(remaining)
        return (
            recovered,
            remaining,
            {
                "chapter_recovery_attempted_count": len(fallback_candidates),
                "chapter_recovery_succeeded_count": succeeded,
                "chapter_recovery_failed_count": len(remaining),
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
                is_empty_result=lambda output: not output.scenes,
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
                if normalized:
                    last_output = output
                    return _WindowSliceResult(
                        window=window,
                        candidates=normalized,
                        diagnostics=_diagnostics(
                            window,
                            retry_results,
                            max_tokens,
                            structured_diagnostics=structured_diagnostics,
                        ),
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
        needs_review = (
            start != declared_start
            or end != declared_end
            or not scene.title.strip()
            or not scene.goal.strip()
            or not scene.core_conflict.strip()
            or bool(unresolved_chapters)
        )
        review_reasons: list[str] = []
        if (
            start != declared_start
            or end != declared_end
            or not scene.title.strip()
            or not scene.goal.strip()
            or not scene.core_conflict.strip()
        ):
            review_reasons.append(
                "Phase1a normalized LLM range or filled empty locked fields."
            )
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
            core_conflict=scene.core_conflict.strip(),
            start_chapter=start,
            end_chapter=end,
            boundary_status=scene.boundary_status.strip() or "uncertain",
            source_chapter_indices=list(range(start, end + 1)),
            scene_chunks=scene_chunks,
            needs_review=needs_review,
            review_reason=" ".join(review_reasons),
            diagnostics={
                "declared_chapter_range": [declared_start, declared_end],
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
                core_conflict="LLM 窗口切分未覆盖该章节。",
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
