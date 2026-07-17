"""High-quality Phase 1c Scene boundary review and semantic synthesis."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import defaultdict
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

from modules.imports.llm_schemas import SceneChunk
from modules.imports.scene_fusion import FinalSceneCandidate
from modules.outline.contracts import (
    SceneBoundaryAssessmentContract,
    SceneBoundaryReviewOutputContract,
    SceneCandidateConcernContract,
    SceneFusionSynthesisOutputContract,
)

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
    """Legacy pair shape retained only for test/caller compatibility."""

    decision: FusionDecision = "needs_review"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""


class Phase1cSuggestion(BaseModel):
    suggestion_kind: SuggestionKind
    source_candidate_ids: list[str] = Field(..., min_length=2)
    proposed_action: FusionDecision
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""
    chapter_span: list[int] = Field(default_factory=list)
    proposed_scene: dict[str, Any] = Field(default_factory=dict)
    scan_trace: list[dict[str, Any]] = Field(default_factory=list)
    initial_status: Literal["pending", "dismissed"] = "pending"
    decision_origin: str = "phase1c_boundary_review_v2"


class Phase1cFusionResult(BaseModel):
    candidates: list[FinalSceneCandidate] = Field(default_factory=list)
    suggestions: list[Phase1cSuggestion] = Field(default_factory=list)
    quality_stats: dict[str, Any] = Field(default_factory=dict)
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)
    degraded: bool = False
    block_reason: str | None = None


class Phase1cSceneFusionService:
    """Review a Scene sequence, then synthesize only safe connected groups."""

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
        # Kept as a compatibility setting; v2 never truncates Scene evidence.
        self.boundary_context_chars = max(100, int(boundary_context_chars))
        self.concurrency = max(1, int(concurrency))

    async def run(
        self,
        candidates: Sequence[FinalSceneCandidate],
        chapters: Sequence[dict[str, Any]],
        *,
        project_profile: dict[str, Any] | None = None,
        phase1a_context: dict[str, Any] | None = None,
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
                    "input_truncated": False,
                },
            )

        chapter_by_index = {
            int(item["chapter_index"]): item
            for item in chapters
            if item.get("chapter_index") is not None
        }
        review_groups = _boundary_review_groups(
            ordered,
            phase1a_context=phase1a_context or {},
        )
        semaphore = asyncio.Semaphore(self.concurrency)
        completed = 0
        progress_lock = asyncio.Lock()

        async def review_group(group: dict[str, Any]) -> tuple[
            list[SceneBoundaryAssessmentContract],
            list[SceneCandidateConcernContract],
            list[dict[str, Any]],
        ]:
            nonlocal completed
            owned_pairs = list(group["owned_pairs"])
            payload = _boundary_review_payload(
                ordered,
                group=group,
                chapter_by_index=chapter_by_index,
                project_profile=project_profile or {},
            )
            errors: list[dict[str, Any]] = []
            try:
                async with semaphore:
                    raw = await self.llm(payload)
                review = (
                    raw
                    if isinstance(raw, SceneBoundaryReviewOutputContract)
                    else SceneBoundaryReviewOutputContract.model_validate(raw)
                )
                assessments = _validate_boundary_review(
                    review,
                    expected_pairs=[
                        (
                            ordered[index].candidate_id,
                            ordered[index + 1].candidate_id,
                        )
                        for index in owned_pairs
                    ],
                    visible_candidate_ids=set(group["visible_candidate_ids"]),
                )
                concerns = list(review.candidate_concerns)
            except Exception as exc:
                error = type(exc).__name__
                errors.append(
                    {
                        "window_id": group["window_id"],
                        "error": error,
                        "boundary_pairs": [
                            {
                                "left_candidate_id": ordered[index].candidate_id,
                                "right_candidate_id": ordered[index + 1].candidate_id,
                            }
                            for index in owned_pairs
                        ],
                    }
                )
                assessments = [
                    SceneBoundaryAssessmentContract(
                        left_candidate_id=ordered[index].candidate_id,
                        right_candidate_id=ordered[index + 1].candidate_id,
                        relation="uncertain",
                        basis=f"Phase1c boundary review failed: {error}",
                        uncertainties=[error],
                        confidence=0.0,
                    )
                    for index in owned_pairs
                ]
                concerns = []
            async with progress_lock:
                for index in owned_pairs:
                    completed += 1
                    if on_pair_progress is not None:
                        await on_pair_progress(
                            completed,
                            len(pairs),
                            f"{ordered[index].candidate_id}:"
                            f"{ordered[index + 1].candidate_id}",
                        )
            return assessments, concerns, errors

        reviewed = await asyncio.gather(*(review_group(group) for group in review_groups))
        assessments = [item for group, _, _ in reviewed for item in group]
        concerns = [item for _, group, _ in reviewed for item in group]
        review_errors = [item for _, _, group in reviewed for item in group]
        failed_review_pairs = {
            (
                str(pair.get("left_candidate_id") or ""),
                str(pair.get("right_candidate_id") or ""),
            )
            for error in review_errors
            for pair in error.get("boundary_pairs", [])
            if isinstance(pair, dict)
        }
        assessment_by_pair = {
            (item.left_candidate_id, item.right_candidate_id): item
            for item in assessments
        }
        ordered_assessments = [
            assessment_by_pair[(left.candidate_id, right.candidate_id)]
            for left, right in pairs
        ]
        concern_by_candidate: dict[
            str,
            list[SceneCandidateConcernContract],
        ] = defaultdict(list)
        for concern in concerns:
            concern_by_candidate[concern.candidate_id].append(concern)

        exact_by_id = {
            candidate.candidate_id: _has_exact_provenance(candidate, chapter_by_index)
            for candidate in ordered
        }
        components = _auto_fusion_components(
            ordered,
            ordered_assessments,
            exact_by_id=exact_by_id,
            concern_by_candidate=concern_by_candidate,
            threshold=self.auto_merge_confidence,
        )
        synthesis_by_component: dict[
            tuple[int, ...],
            SceneFusionSynthesisOutputContract,
        ] = {}
        synthesis_errors: dict[tuple[int, ...], str] = {}

        async def synthesize(indices: tuple[int, ...]) -> None:
            payload = _synthesis_payload(
                [ordered[index] for index in indices],
                assessments=[ordered_assessments[index] for index in indices[:-1]],
                chapter_by_index=chapter_by_index,
                project_profile=project_profile or {},
                phase1a_context=phase1a_context or {},
            )
            try:
                async with semaphore:
                    raw = await self.llm(payload)
                synthesis_by_component[indices] = (
                    raw
                    if isinstance(raw, SceneFusionSynthesisOutputContract)
                    else SceneFusionSynthesisOutputContract.model_validate(raw)
                )
            except Exception as exc:
                synthesis_errors[indices] = type(exc).__name__

        await asyncio.gather(*(synthesize(component) for component in components))

        output: list[FinalSceneCandidate] = []
        member_sets: list[set[str]] = []
        suggestions: list[Phase1cSuggestion] = []
        consumed_indices: set[int] = set()
        auto_merged = 0
        for component in components:
            synthesis = synthesis_by_component.get(component)
            members = [ordered[index] for index in component]
            can_apply = bool(
                synthesis
                and synthesis.confidence >= self.auto_merge_confidence
                and not synthesis.uncertain_fields
            )
            if can_apply and synthesis is not None:
                fused = _materialize_synthesis(
                    members,
                    synthesis,
                    assessments=[ordered_assessments[index] for index in component[:-1]],
                )
                output.append(fused)
                member_sets.append({member.candidate_id for member in members})
                consumed_indices.update(component)
                auto_merged += len(component) - 1
                continue
            suggestions.append(
                _component_suggestion(
                    members,
                    synthesis=synthesis,
                    error=synthesis_errors.get(component),
                    assessments=[ordered_assessments[index] for index in component[:-1]],
                )
            )

        for index, candidate in enumerate(ordered):
            if index in consumed_indices:
                continue
            candidate_concerns = concern_by_candidate.get(candidate.candidate_id, [])
            if candidate_concerns:
                candidate = _mark_candidate_concerns(candidate, candidate_concerns)
            output.append(candidate)
            member_sets.append({candidate.candidate_id})

        sorted_output_with_members = sorted(
            zip(output, member_sets, strict=True),
            key=lambda item: _candidate_sort_key(item[0]),
        )
        output = [item[0] for item in sorted_output_with_members]
        member_sets = [item[1] for item in sorted_output_with_members]

        component_edges = {
            index for component in components for index in component[:-1]
        }
        auto_component_edges = {
            index
            for component in components
            if component[0] in consumed_indices
            for index in component[:-1]
        }
        for pair_index, (left, right) in enumerate(pairs):
            if pair_index in component_edges:
                continue
            if (left.candidate_id, right.candidate_id) in failed_review_pairs:
                # A technical review failure is task-level diagnostic evidence,
                # not an author decision. Do not turn one failed window into a
                # pending suggestion for every boundary it owned.
                continue
            assessment = ordered_assessments[pair_index]
            suggestions.extend(
                _boundary_suggestions(
                    left,
                    right,
                    assessment,
                    exact=exact_by_id[left.candidate_id]
                    and exact_by_id[right.candidate_id],
                    threshold=self.auto_merge_confidence,
                )
            )

        suggestions = _remap_suggestions_to_final_candidates(
            suggestions,
            output,
            member_sets,
        )
        diagnostics = [
            {
                "left_candidate_id": left.candidate_id,
                "right_candidate_id": right.candidate_id,
                "suggestion_kind": _suggestion_kind(left, right),
                "relation": assessment.relation,
                "fusion_intent": assessment.fusion_intent,
                "confidence": assessment.confidence,
                "uncertainties": assessment.uncertainties,
                "exact_provenance": exact_by_id[left.candidate_id]
                and exact_by_id[right.candidate_id],
                "auto_applied": pair_index in auto_component_edges,
            }
            for pair_index, ((left, right), assessment) in enumerate(
                zip(pairs, ordered_assessments, strict=True)
            )
        ]
        failures = len(review_errors) + len(synthesis_errors)
        return Phase1cFusionResult(
            candidates=output,
            suggestions=suggestions,
            quality_stats={
                "pair_count": len(pairs),
                "completed_pairs": len(pairs),
                "review_call_count": len(review_groups),
                "synthesis_call_count": len(components),
                "auto_merged": auto_merged,
                "suggestion_count": sum(
                    item.initial_status == "pending" for item in suggestions
                ),
                "silent_separate_decision_count": sum(
                    item.initial_status == "dismissed" for item in suggestions
                ),
                "candidate_concern_count": len(concerns),
                "failed_calls": failures,
                "auto_merge_confidence": self.auto_merge_confidence,
                "concurrency": self.concurrency,
                "input_truncated": False,
                "contract_version": "phase1c-v2",
            },
            diagnostics=[*diagnostics, *review_errors],
            degraded=failures > 0,
            block_reason="phase1c_review_or_synthesis_failures" if failures else None,
        )


def _candidate_sort_key(candidate: FinalSceneCandidate) -> tuple[int, int, str]:
    chunks = sorted(candidate.scene_chunks, key=_chunk_sort_key)
    first = chunks[0] if chunks else SceneChunk(chapter_index=1)
    return first.chapter_index, first.start_offset or 0, candidate.candidate_id


def _chunk_sort_key(chunk: SceneChunk) -> tuple[int, int, int]:
    return chunk.chapter_index, chunk.start_offset or 0, chunk.end_offset or 0


def _boundary_review_groups(
    candidates: list[FinalSceneCandidate],
    *,
    phase1a_context: dict[str, Any],
) -> list[dict[str, Any]]:
    windows = [
        item for item in phase1a_context.get("windows", []) if isinstance(item, dict)
    ]
    owners: list[tuple[str, set[int], dict[str, Any]]] = []
    for index, window in enumerate(windows):
        reference = window.get("reference_context") or {}
        range_payload = reference.get("range") or {}
        owned = {
            int(value)
            for value in range_payload.get("owned", [])
            if str(value).isdigit()
        }
        owners.append((str(window.get("window_id") or index), owned, window))
    grouped: dict[str, list[int]] = defaultdict(list)
    window_by_id = {item[0]: item[2] for item in owners}
    for pair_index in range(len(candidates) - 1):
        right = candidates[pair_index + 1]
        right_chapter = _candidate_sort_key(right)[0]
        owner_id = next(
            (window_id for window_id, owned, _ in owners if right_chapter in owned),
            "phase1c-all",
        )
        grouped[owner_id].append(pair_index)
    groups: list[dict[str, Any]] = []
    for window_id, pair_indices in grouped.items():
        visible_indices = {
            candidate_index
            for pair_index in pair_indices
            for candidate_index in (pair_index, pair_index + 1)
        }
        visible_indices.add(max(0, min(visible_indices) - 1))
        visible_indices.add(min(len(candidates) - 1, max(visible_indices) + 1))
        groups.append(
            {
                "window_id": window_id,
                "owned_pairs": sorted(pair_indices),
                "visible_indices": sorted(visible_indices),
                "visible_candidate_ids": [
                    candidates[index].candidate_id for index in sorted(visible_indices)
                ],
                "reference_context": (
                    window_by_id.get(window_id, {}).get("reference_context") or {}
                ),
            }
        )
    return sorted(groups, key=lambda item: min(item["owned_pairs"]))


def _boundary_review_payload(
    candidates: list[FinalSceneCandidate],
    *,
    group: dict[str, Any],
    chapter_by_index: dict[int, dict[str, Any]],
    project_profile: dict[str, Any],
) -> dict[str, Any]:
    return {
        "task": "phase1c_boundary_review_v2",
        "contract_version": "phase1c-boundary-v2",
        "window_id": group["window_id"],
        "project": _project_payload(project_profile),
        "owned_boundaries": [
            {
                "left_candidate_id": candidates[index].candidate_id,
                "right_candidate_id": candidates[index + 1].candidate_id,
            }
            for index in group["owned_pairs"]
        ],
        "candidate_sequence": [
            _candidate_payload(candidates[index], chapter_by_index)
            for index in group["visible_indices"]
        ],
        "related_context": group["reference_context"],
    }


def _validate_boundary_review(
    review: SceneBoundaryReviewOutputContract,
    *,
    expected_pairs: list[tuple[str, str]],
    visible_candidate_ids: set[str],
) -> list[SceneBoundaryAssessmentContract]:
    returned_order = [
        (item.left_candidate_id, item.right_candidate_id)
        for item in review.boundaries
    ]
    if returned_order != expected_pairs:
        raise ValueError("boundary assessment order/coverage mismatch")
    if len(returned_order) != len(set(returned_order)):
        raise ValueError("duplicate boundary assessment")
    if any(
        concern.candidate_id not in visible_candidate_ids
        for concern in review.candidate_concerns
    ):
        raise ValueError("candidate concern references invisible candidate")
    return list(review.boundaries)


def _auto_fusion_components(
    candidates: list[FinalSceneCandidate],
    assessments: list[SceneBoundaryAssessmentContract],
    *,
    exact_by_id: dict[str, bool],
    concern_by_candidate: dict[str, list[SceneCandidateConcernContract]],
    threshold: float,
) -> list[tuple[int, ...]]:
    components: list[tuple[int, ...]] = []
    start: int | None = None
    for index, assessment in enumerate(assessments):
        left = candidates[index]
        right = candidates[index + 1]
        eligible = (
            assessment.relation in {"same_scene", "duplicate"}
            and assessment.confidence >= threshold
            and not assessment.uncertainties
            and exact_by_id[left.candidate_id]
            and exact_by_id[right.candidate_id]
            and not concern_by_candidate.get(left.candidate_id)
            and not concern_by_candidate.get(right.candidate_id)
            and not left.fallback_required
            and not right.fallback_required
        )
        if eligible and start is None:
            start = index
        if not eligible and start is not None:
            components.append(tuple(range(start, index + 1)))
            start = None
    if start is not None:
        components.append(tuple(range(start, len(candidates))))
    return [component for component in components if len(component) > 1]


def _synthesis_payload(
    candidates: list[FinalSceneCandidate],
    *,
    assessments: list[SceneBoundaryAssessmentContract],
    chapter_by_index: dict[int, dict[str, Any]],
    project_profile: dict[str, Any],
    phase1a_context: dict[str, Any],
) -> dict[str, Any]:
    relevant_window_ids = {
        str(source_id).split(":", 1)[0]
        for candidate in candidates
        for source_id in candidate.source_candidate_ids
    }
    related_windows = [
        item
        for item in phase1a_context.get("windows", [])
        if not relevant_window_ids
        or str(item.get("window_id") or "") in relevant_window_ids
    ]
    if not related_windows:
        related_windows = list(phase1a_context.get("windows", []))
    return {
        "task": "phase1c_scene_synthesis_v2",
        "contract_version": "scene-fusion-synthesis-v2",
        "project": _project_payload(project_profile),
        "members": [
            _candidate_payload(candidate, chapter_by_index) for candidate in candidates
        ],
        "boundary_assessments": [
            assessment.model_dump(mode="json") for assessment in assessments
        ],
        "related_context": {
            "contract_version": phase1a_context.get("contract_version"),
            "fingerprint": phase1a_context.get("fingerprint"),
            "windows": related_windows,
        },
    }


def _candidate_payload(
    candidate: FinalSceneCandidate,
    chapter_by_index: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "candidate_id": candidate.candidate_id,
        "title": candidate.title,
        "goal": candidate.goal,
        "core_conflict": candidate.core_conflict or None,
        "core_conflict_status": candidate.core_conflict_status,
        "phase1a_confidence": candidate.phase1a_confidence,
        "boundary_basis": candidate.boundary_basis,
        "boundary_status": candidate.boundary_status,
        "emotional_beat": candidate.emotional_beat,
        "must_happen": candidate.must_happen,
        "must_not_happen": candidate.must_not_happen,
        "narrative_tag": candidate.narrative_tag,
        "narrative_function": candidate.narrative_function or None,
        "phase1b_basis": candidate.phase1b_basis,
        "phase1b_field_statuses": candidate.phase1b_field_statuses,
        "phase1b_uncertain_fields": candidate.phase1b_uncertain_fields,
        "phase1b_confidence": candidate.phase1b_confidence,
        "fallback_required": candidate.fallback_required,
        "needs_review": candidate.needs_review,
        "review_reason": candidate.review_reason,
        "source_chapter_indices": candidate.source_chapter_indices,
        "scene_chunks": [
            chunk.model_dump(mode="json") for chunk in candidate.scene_chunks
        ],
        "scene_source": _materialize_candidate_source(candidate, chapter_by_index),
    }


def _materialize_candidate_source(
    candidate: FinalSceneCandidate,
    chapter_by_index: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    source: list[dict[str, Any]] = []
    for chunk in sorted(candidate.scene_chunks, key=_chunk_sort_key):
        chapter = chapter_by_index.get(chunk.chapter_index) or {}
        content = str(chapter.get("content") or "")
        start = max(0, chunk.start_offset or 0)
        end = min(
            len(content),
            chunk.end_offset if chunk.end_offset is not None else len(content),
        )
        source.append(
            {
                "chapter_index": chunk.chapter_index,
                "source_draft_id": chunk.source_draft_id,
                "source_content_hash": chunk.source_content_hash,
                "start_offset": chunk.start_offset,
                "end_offset": chunk.end_offset,
                "text": content[start:end],
            }
        )
    return source


def _materialize_synthesis(
    members: list[FinalSceneCandidate],
    synthesis: SceneFusionSynthesisOutputContract,
    *,
    assessments: list[SceneBoundaryAssessmentContract],
) -> FinalSceneCandidate:
    first = members[0]
    statuses = synthesis.semantic_field_statuses()
    return first.model_copy(
        update={
            "candidate_id": "phase1c-" + "-".join(item.candidate_id for item in members),
            "phase": "phase1c_fusion",
            "title": synthesis.title,
            "goal": synthesis.goal,
            "core_conflict": synthesis.core_conflict or "",
            "core_conflict_status": synthesis.core_conflict_status,
            "emotional_beat": synthesis.emotional_beat,
            "must_happen": synthesis.must_happen,
            "must_not_happen": synthesis.must_not_happen,
            "narrative_tag": synthesis.narrative_tag,
            "narrative_function": synthesis.narrative_function or "",
            "phase1b_basis": synthesis.basis,
            "phase1b_field_statuses": statuses,
            "phase1b_uncertain_fields": synthesis.uncertain_fields,
            "phase1b_confidence": synthesis.confidence,
            "phase1b_context_fingerprint": _merge_context_fingerprints(
                *(item.phase1b_context_fingerprint for item in members)
            ),
            "phase1b_source_fingerprint": _merge_context_fingerprints(
                *(item.phase1b_source_fingerprint for item in members)
            ),
            "scene_chunks": _union_chunks(
                [chunk for item in members for chunk in item.scene_chunks]
            ),
            "source_candidate_ids": list(
                dict.fromkeys(
                    source_id
                    for item in members
                    for source_id in item.source_candidate_ids
                )
            ),
            "source_rounds": sorted(
                {value for item in members for value in item.source_rounds}
            ),
            "source_chapter_indices": sorted(
                {value for item in members for value in item.source_chapter_indices}
            ),
            "operation": "merged",
            "confidence": synthesis.confidence,
            "fallback_required": False,
            "phase1a_confidence": min(item.phase1a_confidence for item in members),
            "boundary_basis": " ".join(
                dict.fromkeys(
                    value
                    for value in [
                        *(item.boundary_basis for item in members),
                        *(item.basis for item in assessments),
                    ]
                    if value
                )
            ),
            "boundary_status": "complete",
            "boundary_reason": synthesis.basis,
            "needs_review": False,
            "review_reason": "",
        }
    )


def _component_suggestion(
    members: list[FinalSceneCandidate],
    *,
    synthesis: SceneFusionSynthesisOutputContract | None,
    error: str | None,
    assessments: list[SceneBoundaryAssessmentContract],
) -> Phase1cSuggestion:
    reason = (
        synthesis.basis
        if synthesis is not None
        else f"Phase1c synthesis failed: {error or 'unknown'}"
    )
    confidence = synthesis.confidence if synthesis is not None else 0.0
    return Phase1cSuggestion(
        suggestion_kind=_suggestion_kind(members[0], members[-1]),
        source_candidate_ids=[item.candidate_id for item in members],
        proposed_action="merge" if synthesis is not None else "needs_review",
        confidence=confidence,
        reason=reason,
        chapter_span=sorted(
            {chapter for item in members for chapter in item.source_chapter_indices}
        ),
        proposed_scene=(synthesis.model_dump(mode="json") if synthesis else {}),
        scan_trace=[item.model_dump(mode="json") for item in assessments],
    )


def _boundary_suggestions(
    left: FinalSceneCandidate,
    right: FinalSceneCandidate,
    assessment: SceneBoundaryAssessmentContract,
    *,
    exact: bool,
    threshold: float,
) -> list[Phase1cSuggestion]:
    actionable = assessment.relation in {"same_scene", "duplicate"}
    high_confidence_separate = (
        assessment.relation == "separate"
        and assessment.confidence >= threshold
        and not assessment.uncertainties
        and exact
    )
    if assessment.relation == "separate" and not high_confidence_separate:
        action: FusionDecision = "keep_separate"
    elif high_confidence_separate:
        action = "keep_separate"
    elif actionable:
        action = {
            "left_is_fragment": "absorb_left",
            "right_is_fragment": "absorb_right",
        }.get(assessment.fusion_intent or "", "merge")  # type: ignore[assignment]
    elif assessment.relation in {"overlap", "uncertain"}:
        action = "needs_review"
    else:
        return []
    return [
        Phase1cSuggestion(
            suggestion_kind=_suggestion_kind(left, right),
            source_candidate_ids=[left.candidate_id, right.candidate_id],
            proposed_action=action,
            confidence=assessment.confidence,
            reason=assessment.basis,
            chapter_span=sorted(
                set(left.source_chapter_indices + right.source_chapter_indices)
            ),
            scan_trace=[assessment.model_dump(mode="json")],
            initial_status="dismissed" if high_confidence_separate else "pending",
        )
    ]


def _mark_candidate_concerns(
    candidate: FinalSceneCandidate,
    concerns: list[SceneCandidateConcernContract],
) -> FinalSceneCandidate:
    reason = " ".join(dict.fromkeys(item.concern for item in concerns if item.concern))
    return candidate.model_copy(
        update={
            "needs_review": True,
            "review_reason": " ".join(
                value for value in (candidate.review_reason, reason) if value
            ),
        }
    )


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
        if chunk.start_offset < 0 or chunk.end_offset > len(content):
            return False
        if str(chunk.source_draft_id or "") != str(chapter.get("source_draft_id") or ""):
            return False
        if str(chunk.source_content_hash or "") != str(
            chapter.get("source_content_hash") or ""
        ):
            return False
    return True


def _project_payload(project_profile: dict[str, Any]) -> dict[str, Any]:
    return {
        key: project_profile.get(key)
        for key in ("title", "genre", "tone")
        if project_profile.get(key)
    }


def _merge_context_fingerprints(*values: str) -> str:
    fingerprints = list(dict.fromkeys(value for value in values if value))
    if not fingerprints:
        return ""
    if len(fingerprints) == 1:
        return fingerprints[0]
    payload = json.dumps(fingerprints, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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
    final_id_by_member = {
        member_id: candidate.candidate_id
        for candidate, members in zip(candidates, candidate_members, strict=True)
        for member_id in members
    }
    candidate_by_id = {candidate.candidate_id: candidate for candidate in candidates}
    remapped: list[Phase1cSuggestion] = []
    seen: set[tuple[str, ...]] = set()
    for suggestion in suggestions:
        source_ids = list(
            dict.fromkeys(
                final_id_by_member.get(source_id, source_id)
                for source_id in suggestion.source_candidate_ids
            )
        )
        if len(source_ids) < 2:
            continue
        dedupe_key = (*source_ids, suggestion.proposed_action, suggestion.initial_status)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
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
