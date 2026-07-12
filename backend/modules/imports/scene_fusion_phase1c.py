"""High-quality Phase 1c Scene boundary fusion for deep import."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

from modules.imports.llm_schemas import SceneChunk
from modules.imports.scene_fusion import FinalSceneCandidate

FusionDecision = Literal[
    "merge",
    "absorb_left",
    "absorb_right",
    "keep_separate",
    "needs_review",
]
SuggestionKind = Literal["intra_chapter", "cross_chapter", "duplicate_window"]
Phase1cLLMCallable = Callable[[dict[str, Any]], Awaitable[Any]]


class Phase1cDecision(BaseModel):
    decision: FusionDecision = "needs_review"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""


class Phase1cSuggestion(BaseModel):
    suggestion_kind: SuggestionKind
    source_candidate_ids: list[str] = Field(..., min_length=2, max_length=2)
    proposed_action: FusionDecision
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""
    chapter_span: list[int] = Field(default_factory=list)


class Phase1cFusionResult(BaseModel):
    candidates: list[FinalSceneCandidate] = Field(default_factory=list)
    suggestions: list[Phase1cSuggestion] = Field(default_factory=list)
    quality_stats: dict[str, Any] = Field(default_factory=dict)
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)
    degraded: bool = False
    block_reason: str | None = None


class Phase1cSceneFusionService:
    """Evaluate adjacent exact Scene candidates and apply only safe decisions."""

    def __init__(
        self,
        llm: Phase1cLLMCallable,
        *,
        auto_merge_confidence: float = 0.92,
        boundary_context_chars: int = 2000,
        concurrency: int = 20,
    ) -> None:
        self.llm = llm
        self.auto_merge_confidence = max(0.0, min(float(auto_merge_confidence), 1.0))
        self.boundary_context_chars = max(100, int(boundary_context_chars))
        self.concurrency = max(1, int(concurrency))

    async def run(
        self,
        candidates: Sequence[FinalSceneCandidate],
        chapters: Sequence[dict[str, Any]],
        *,
        project_profile: dict[str, Any] | None = None,
        on_pair_progress: Callable[[int, int, str], Awaitable[None]] | None = None,
    ) -> Phase1cFusionResult:
        ordered = sorted(candidates, key=_candidate_sort_key)
        pairs = list(zip(ordered, ordered[1:], strict=False))
        if not pairs:
            return Phase1cFusionResult(
                candidates=ordered,
                quality_stats={
                    "pair_count": 0,
                    "completed_pairs": 0,
                    "auto_merged": 0,
                    "suggestion_count": 0,
                },
            )

        chapter_by_index = {
            int(item["chapter_index"]): item
            for item in chapters
            if item.get("chapter_index") is not None
        }
        semaphore = asyncio.Semaphore(self.concurrency)
        completed = 0
        progress_lock = asyncio.Lock()

        async def evaluate(
            left: FinalSceneCandidate,
            right: FinalSceneCandidate,
        ) -> tuple[
            FinalSceneCandidate,
            FinalSceneCandidate,
            SuggestionKind,
            Phase1cDecision,
            str | None,
        ]:
            nonlocal completed
            kind = _suggestion_kind(left, right)
            payload = _decision_payload(
                left,
                right,
                kind=kind,
                chapter_by_index=chapter_by_index,
                context_chars=self.boundary_context_chars,
                project_profile=project_profile or {},
            )
            error: str | None = None
            try:
                async with semaphore:
                    raw = await self.llm(payload)
                decision = (
                    raw
                    if isinstance(raw, Phase1cDecision)
                    else Phase1cDecision.model_validate(raw)
                )
            except Exception as exc:  # phase-local degradation must not block import
                error = type(exc).__name__
                decision = Phase1cDecision(
                    decision="needs_review",
                    confidence=0.0,
                    reason=f"Phase1c decision failed: {error}",
                )
            async with progress_lock:
                completed += 1
                if on_pair_progress is not None:
                    await on_pair_progress(
                        completed,
                        len(pairs),
                        f"{left.candidate_id}:{right.candidate_id}",
                    )
            return left, right, kind, decision, error

        evaluated = await asyncio.gather(
            *(evaluate(left, right) for left, right in pairs)
        )
        output: list[FinalSceneCandidate] = []
        suggestions: list[Phase1cSuggestion] = []
        diagnostics: list[dict[str, Any]] = []
        auto_merged = 0
        current = ordered[0]
        current_member_ids = {current.candidate_id}
        output_members: list[set[str]] = []
        for left, right, kind, decision, error in evaluated:
            exact = _has_exact_provenance(
                left,
                chapter_by_index,
            ) and _has_exact_provenance(right, chapter_by_index)
            actionable = decision.decision in {"merge", "absorb_left", "absorb_right"}
            can_apply = (
                actionable
                and decision.confidence >= self.auto_merge_confidence
                and exact
                and not error
                and (
                    current.candidate_id == left.candidate_id
                    or decision.decision == "merge"
                )
            )
            diagnostics.append(
                {
                    "left_candidate_id": left.candidate_id,
                    "right_candidate_id": right.candidate_id,
                    "suggestion_kind": kind,
                    "decision": decision.decision,
                    "confidence": decision.confidence,
                    "exact_provenance": exact,
                    "auto_applied": can_apply,
                    "error": error,
                }
            )
            if can_apply:
                current = _merge_candidates(current, right, decision)
                current_member_ids.add(right.candidate_id)
                auto_merged += 1
                continue
            if (
                actionable
                or decision.decision == "needs_review"
                or decision.confidence < self.auto_merge_confidence
            ):
                suggestions.append(
                    Phase1cSuggestion(
                        suggestion_kind=kind,
                        # Keep the evaluated pair here. A later adjacent merge can
                        # replace either formal candidate, so these ids are remapped
                        # after the full merge chain has settled.
                        source_candidate_ids=[left.candidate_id, right.candidate_id],
                        proposed_action=decision.decision,
                        confidence=decision.confidence,
                        reason=decision.reason,
                        chapter_span=sorted(
                            set(
                                current.source_chapter_indices
                                + right.source_chapter_indices
                            )
                        ),
                    )
                )
            output.append(current)
            output_members.append(current_member_ids)
            current = right
            current_member_ids = {right.candidate_id}
        output.append(current)
        output_members.append(current_member_ids)
        suggestions = _remap_suggestions_to_final_candidates(
            suggestions,
            output,
            output_members,
        )

        failures = sum(1 for item in diagnostics if item["error"])
        return Phase1cFusionResult(
            candidates=output,
            suggestions=suggestions,
            quality_stats={
                "pair_count": len(pairs),
                "completed_pairs": len(pairs),
                "auto_merged": auto_merged,
                "suggestion_count": len(suggestions),
                "failed_pairs": failures,
                "auto_merge_confidence": self.auto_merge_confidence,
                "concurrency": self.concurrency,
            },
            diagnostics=diagnostics,
            degraded=failures > 0,
            block_reason="phase1c_pair_failures" if failures else None,
        )


def _candidate_sort_key(candidate: FinalSceneCandidate) -> tuple[int, int, str]:
    chunks = sorted(candidate.scene_chunks, key=_chunk_sort_key)
    first = chunks[0] if chunks else SceneChunk(chapter_index=1)
    return first.chapter_index, first.start_offset or 0, candidate.candidate_id


def _chunk_sort_key(chunk: SceneChunk) -> tuple[int, int, int]:
    return chunk.chapter_index, chunk.start_offset or 0, chunk.end_offset or 0


def _suggestion_kind(
    left: FinalSceneCandidate,
    right: FinalSceneCandidate,
) -> SuggestionKind:
    for left_chunk in left.scene_chunks:
        for right_chunk in right.scene_chunks:
            if left_chunk.chapter_index != right_chunk.chapter_index:
                continue
            if None in (
                left_chunk.start_offset,
                left_chunk.end_offset,
                right_chunk.start_offset,
                right_chunk.end_offset,
            ):
                continue
            if max(left_chunk.start_offset, right_chunk.start_offset) < min(
                left_chunk.end_offset, right_chunk.end_offset
            ):
                return "duplicate_window"
    if set(left.source_chapter_indices) & set(right.source_chapter_indices):
        return "intra_chapter"
    return "cross_chapter"


def _has_exact_provenance(
    candidate: FinalSceneCandidate,
    chapter_by_index: dict[int, dict[str, Any]],
) -> bool:
    if candidate.fallback_required or not candidate.scene_chunks:
        return False
    for chunk in candidate.scene_chunks:
        chapter = chapter_by_index.get(chunk.chapter_index)
        if chapter is None or chunk.start_offset is None or chunk.end_offset is None:
            return False
        content = str(chapter.get("content") or "")
        if chunk.end_offset > len(content):
            return False
        if str(chunk.source_draft_id or "") != str(
            chapter.get("source_draft_id") or ""
        ):
            return False
        if str(chunk.source_content_hash or "") != str(
            chapter.get("source_content_hash") or ""
        ):
            return False
    return True


def _decision_payload(
    left: FinalSceneCandidate,
    right: FinalSceneCandidate,
    *,
    kind: SuggestionKind,
    chapter_by_index: dict[int, dict[str, Any]],
    context_chars: int,
    project_profile: dict[str, Any],
) -> dict[str, Any]:
    return {
        "suggestion_kind": kind,
        "project": {
            key: project_profile.get(key)
            for key in ("title", "genre", "tone")
            if project_profile.get(key)
        },
        "left": _compact_candidate(left),
        "right": _compact_candidate(right),
        "boundary_text": _boundary_text(
            left,
            right,
            chapter_by_index=chapter_by_index,
            context_chars=context_chars,
        ),
    }


def _compact_candidate(candidate: FinalSceneCandidate) -> dict[str, Any]:
    return {
        "candidate_id": candidate.candidate_id,
        "title": candidate.title,
        "goal": candidate.goal,
        "core_conflict": candidate.core_conflict,
        "must_happen": candidate.must_happen,
        "source_chapter_indices": candidate.source_chapter_indices,
        "scene_chunks": [
            chunk.model_dump(mode="json") for chunk in candidate.scene_chunks
        ],
    }


def _boundary_text(
    left: FinalSceneCandidate,
    right: FinalSceneCandidate,
    *,
    chapter_by_index: dict[int, dict[str, Any]],
    context_chars: int,
) -> dict[str, str]:
    left_chunk = sorted(left.scene_chunks, key=_chunk_sort_key)[-1]
    right_chunk = sorted(right.scene_chunks, key=_chunk_sort_key)[0]
    left_content = str(
        chapter_by_index.get(left_chunk.chapter_index, {}).get("content") or ""
    )
    right_content = str(
        chapter_by_index.get(right_chunk.chapter_index, {}).get("content") or ""
    )
    left_end = (
        left_chunk.end_offset
        if left_chunk.end_offset is not None
        else len(left_content)
    )
    right_start = right_chunk.start_offset or 0
    return {
        "left_tail": left_content[max(0, left_end - context_chars) : left_end],
        "right_head": right_content[right_start : right_start + context_chars],
    }


def _merge_candidates(
    left: FinalSceneCandidate,
    right: FinalSceneCandidate,
    decision: Phase1cDecision,
) -> FinalSceneCandidate:
    primary = right if decision.decision == "absorb_left" else left
    chunks = _union_chunks([*left.scene_chunks, *right.scene_chunks])
    return primary.model_copy(
        update={
            "candidate_id": f"phase1c-{left.candidate_id}-{right.candidate_id}",
            "phase": "phase1c_fusion",
            "scene_chunks": chunks,
            "source_candidate_ids": list(
                dict.fromkeys(
                    [*left.source_candidate_ids, *right.source_candidate_ids]
                )
            ),
            "source_rounds": sorted(set(left.source_rounds + right.source_rounds)),
            "source_chapter_indices": sorted(
                set(left.source_chapter_indices + right.source_chapter_indices)
            ),
            "operation": "merged",
            "confidence": decision.confidence,
            "fallback_required": left.fallback_required or right.fallback_required,
            "boundary_status": "complete",
            "boundary_reason": decision.reason or "Phase1c high-confidence fusion.",
            "needs_review": left.needs_review or right.needs_review,
            "review_reason": " ".join(
                value for value in (left.review_reason, right.review_reason) if value
            ),
        }
    )


def _union_chunks(chunks: list[SceneChunk]) -> list[SceneChunk]:
    ordered = sorted(chunks, key=_chunk_sort_key)
    result: list[SceneChunk] = []
    for chunk in ordered:
        if not result:
            result.append(chunk)
            continue
        previous = result[-1]
        same_source = (
            previous.chapter_index == chunk.chapter_index
            and previous.source_draft_id == chunk.source_draft_id
            and previous.source_content_hash == chunk.source_content_hash
        )
        exact_offsets = (
            previous.start_offset is not None
            and previous.end_offset is not None
            and chunk.start_offset is not None
            and chunk.end_offset is not None
        )
        if same_source and exact_offsets and chunk.start_offset <= previous.end_offset:
            result[-1] = previous.model_copy(
                update={"end_offset": max(previous.end_offset, chunk.end_offset)}
            )
            continue
        result.append(chunk)
    return result


def _remap_suggestions_to_final_candidates(
    suggestions: list[Phase1cSuggestion],
    candidates: list[FinalSceneCandidate],
    candidate_members: list[set[str]],
) -> list[Phase1cSuggestion]:
    """Point pending suggestions at candidates that will actually be committed."""

    final_id_by_member = {
        member_id: candidate.candidate_id
        for candidate, members in zip(candidates, candidate_members, strict=True)
        for member_id in members
    }
    candidate_by_id = {candidate.candidate_id: candidate for candidate in candidates}
    remapped: list[Phase1cSuggestion] = []
    for suggestion in suggestions:
        source_ids = list(
            dict.fromkeys(
                final_id_by_member.get(source_id, source_id)
                for source_id in suggestion.source_candidate_ids
            )
        )
        if len(source_ids) < 2:
            continue
        chapter_span = sorted(
            {
                chapter
                for source_id in source_ids
                for chapter in (
                    candidate_by_id[source_id].source_chapter_indices
                    if source_id in candidate_by_id
                    else suggestion.chapter_span
                )
            }
        )
        remapped.append(
            suggestion.model_copy(
                update={
                    "source_candidate_ids": source_ids,
                    "chapter_span": chapter_span,
                }
            )
        )
    return remapped
