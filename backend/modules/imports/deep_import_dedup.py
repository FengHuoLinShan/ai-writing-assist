"""Internal dedup coordinator for deep import write boundaries."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.llm_schemas import SceneChunk
from modules.imports.scene_fusion import FinalSceneCandidate

DedupScope = Literal["scene", "entity", "relation", "structure"]
DedupAction = Literal[
    "kept",
    "collapsed",
    "auto_merged",
    "review_suggested",
    "skipped",
    "degraded",
]

_PUNCT_RE = re.compile(r"[\s　，。！？、；：,.!?;:《》“”\"'（）()【】\[\]—_-]+")


@dataclass(frozen=True)
class DedupDecision:
    scope: DedupScope
    action: DedupAction
    confidence: float
    source_ids: list[str] = field(default_factory=list)
    target_id: str | None = None
    method: str = ""
    auto_applied: bool = False
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "action": self.action,
            "confidence": round(float(self.confidence), 3),
            "source_ids": list(self.source_ids),
            "target_id": self.target_id,
            "method": self.method,
            "auto_applied": self.auto_applied,
            "reason": self.reason[:240],
        }


@dataclass(frozen=True)
class SceneDedupResult:
    candidates: list[FinalSceneCandidate]
    quality_stats: dict[str, Any]
    decisions: list[DedupDecision]


class SceneDedupAgent:
    """Collapse deterministic duplicate final scene candidates before DB writes."""

    def dedupe(self, candidates: list[FinalSceneCandidate]) -> SceneDedupResult:
        grouped: dict[str, FinalSceneCandidate] = {}
        decisions: list[DedupDecision] = []
        input_count = len(candidates)

        for candidate in candidates:
            key = self._candidate_key(candidate)
            existing = grouped.get(key)
            if existing is None:
                grouped[key] = candidate
                continue
            if not self._can_collapse(existing, candidate):
                grouped[self._fallback_key(candidate, grouped)] = candidate
                continue
            merged = self._merge_candidates(existing, candidate)
            grouped[key] = merged
            decisions.append(
                DedupDecision(
                    scope="scene",
                    action="collapsed",
                    confidence=max(existing.confidence, candidate.confidence),
                    source_ids=_unique_strings(
                        [
                            *existing.source_candidate_ids,
                            *candidate.source_candidate_ids,
                        ]
                    ),
                    target_id=merged.candidate_id,
                    method="scene_candidate_signature",
                    auto_applied=True,
                    reason=(
                        "same workflow scene candidates shared provenance/chunk anchors"
                    ),
                )
            )

        output = sorted(grouped.values(), key=_scene_sort_key)
        collapsed = input_count - len(output)
        stats = {
            "checked": input_count,
            "same_workflow_collapsed": max(0, collapsed),
            "output_count": len(output),
            "decisions": [decision.to_dict() for decision in decisions[:20]],
        }
        return SceneDedupResult(
            candidates=output,
            quality_stats=stats,
            decisions=decisions,
        )

    def _candidate_key(self, candidate: FinalSceneCandidate) -> str:
        source_ids = sorted(set(candidate.source_candidate_ids or []))
        chunk_key = self._chunk_key(candidate.scene_chunks)
        title_goal = "|".join(
            [
                _normalize_text(candidate.title),
                _normalize_text(candidate.goal),
                _normalize_text(candidate.core_conflict),
            ]
        )
        chapter_span = ",".join(str(index) for index in candidate.source_chapter_indices)
        if source_ids:
            return "sources:" + ",".join(source_ids)
        if chunk_key and title_goal.strip("|"):
            return f"chunks:{chunk_key}:{title_goal}"
        return f"text:{chapter_span}:{title_goal}"

    def _fallback_key(
        self,
        candidate: FinalSceneCandidate,
        grouped: dict[str, FinalSceneCandidate],
    ) -> str:
        base = self._candidate_key(candidate)
        index = 1
        key = f"{base}:keep:{candidate.candidate_id or index}"
        while key in grouped:
            index += 1
            key = f"{base}:keep:{candidate.candidate_id or index}:{index}"
        return key

    def _can_collapse(
        self,
        primary: FinalSceneCandidate,
        duplicate: FinalSceneCandidate,
    ) -> bool:
        primary_sources = set(primary.source_candidate_ids or [])
        duplicate_sources = set(duplicate.source_candidate_ids or [])
        if primary_sources and duplicate_sources and primary_sources == duplicate_sources:
            return True

        primary_chunks = set(self._chunk_parts(primary.scene_chunks))
        duplicate_chunks = set(self._chunk_parts(duplicate.scene_chunks))
        if primary_chunks and duplicate_chunks and primary_chunks & duplicate_chunks:
            same_title = _normalize_text(primary.title) == _normalize_text(
                duplicate.title
            )
            same_goal = _normalize_text(primary.goal) == _normalize_text(duplicate.goal)
            return same_title and same_goal

        return False

    def _merge_candidates(
        self,
        primary: FinalSceneCandidate,
        duplicate: FinalSceneCandidate,
    ) -> FinalSceneCandidate:
        winner, other = (
            (primary, duplicate)
            if primary.confidence >= duplicate.confidence
            else (duplicate, primary)
        )
        chunks = _merge_chunks(primary.scene_chunks, duplicate.scene_chunks)
        source_ids = _unique_strings(
            [*primary.source_candidate_ids, *duplicate.source_candidate_ids]
        )
        source_rounds = _unique_strings(
            [*primary.source_rounds, *duplicate.source_rounds]
        )
        chapters = sorted(
            set([*primary.source_chapter_indices, *duplicate.source_chapter_indices])
        )
        discard_reasons = {
            **(primary.discard_reasons or {}),
            **(duplicate.discard_reasons or {}),
        }
        if other.candidate_id:
            discard_reasons[other.candidate_id] = "duplicate_candidate"
        review_reason = "；".join(
            text for text in [primary.review_reason, duplicate.review_reason] if text
        )[:500]
        return winner.model_copy(
            update={
                "candidate_id": winner.candidate_id or primary.candidate_id,
                "title": winner.title or other.title,
                "goal": winner.goal or other.goal,
                "core_conflict": winner.core_conflict or other.core_conflict,
                "emotional_beat": winner.emotional_beat or other.emotional_beat,
                "must_happen": winner.must_happen or other.must_happen,
                "must_not_happen": winner.must_not_happen or other.must_not_happen,
                "scene_chunks": chunks,
                "source_candidate_ids": source_ids,
                "source_rounds": source_rounds,
                "source_chapter_indices": chapters,
                "operation": "merged",
                "confidence": max(primary.confidence, duplicate.confidence),
                "discard_reasons": discard_reasons,
                "needs_review": primary.needs_review or duplicate.needs_review,
                "review_reason": review_reason or winner.review_reason,
            }
        )

    def _chunk_key(self, chunks: list[SceneChunk]) -> str:
        return ",".join(self._chunk_parts(chunks))

    def _chunk_parts(self, chunks: list[SceneChunk]) -> list[str]:
        return [
            f"{chunk.chapter_index}:{chunk.start_paragraph}:{chunk.end_paragraph or 0}"
            for chunk in sorted(
                chunks,
                key=lambda item: (
                    item.chapter_index,
                    item.start_paragraph,
                    item.end_paragraph or 0,
                ),
            )
        ]


class StructureReviewAgent:
    """Run outline structure dedup suggestions after Phase 3 writes."""

    async def review(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        workflow_id: str | None,
    ) -> dict[str, Any]:
        from modules.outline import facade as outline_facade

        try:
            suggestion_result = await outline_facade.suggest_structure_dedup(
                db,
                novel_id,
                asset_types=[
                    "plot_thread",
                    "outline_arc",
                    "foreshadowing_plan",
                    "reveal_plan",
                ],
                max_suggestions=40,
            )
        except Exception as exc:
            return {
                "checked": 0,
                "suggestions_recorded": 0,
                "auto_applied": 0,
                "skipped_external_asset": 0,
                "current_workflow_asset_outcomes": {
                    "review": 0,
                    "not_adopted": 0,
                    "affected": 0,
                    "review_asset_ids": [],
                    "not_adopted_asset_ids": [],
                },
                "degraded": 1,
                "error_kind": "structure_dedup_failed",
                "error_message": str(exc)[:240],
                "suggestions": [],
            }

        suggestions = [
            item
            for item in suggestion_result.get("suggestions", [])
            if isinstance(item, dict)
        ]
        auto_apply = [
            item
            for item in suggestions
            if _same_workflow_suggestion(item, workflow_id)
            and float(item.get("confidence") or 0) >= 0.96
            and item.get("action") in {"merge", "deprecate_duplicate"}
        ]
        skipped_external = len(suggestions) - len(auto_apply)
        apply_result: dict[str, Any] = {"applied": 0, "skipped": 0, "warnings": []}
        if auto_apply:
            apply_result = await outline_facade.apply_structure_dedup(
                db,
                novel_id,
                confirmed=True,
                suggestions=auto_apply,
            )
        workflow_asset_outcomes = _current_workflow_asset_outcomes(
            suggestions,
            auto_apply=auto_apply,
            apply_result=apply_result,
            workflow_id=workflow_id,
        )
        return {
            "checked": int(suggestion_result.get("total_assets_scanned", 0) or 0),
            "suggestions_recorded": len(suggestions),
            "auto_applied": int(apply_result.get("applied", 0) or 0),
            "skipped_external_asset": skipped_external,
            "current_workflow_asset_outcomes": workflow_asset_outcomes,
            "degraded": 0,
            "warnings": apply_result.get("warnings") or [],
            "suggestions": [
                _safe_structure_suggestion(item) for item in suggestions[:20]
            ],
        }


class DeepImportDedupCoordinator:
    """Coordinator facade for the role-like dedup agents."""

    def __init__(self) -> None:
        self.scene_agent = SceneDedupAgent()
        self.structure_agent = StructureReviewAgent()

    def dedupe_scenes(
        self,
        candidates: list[FinalSceneCandidate],
    ) -> SceneDedupResult:
        return self.scene_agent.dedupe(candidates)

    async def review_structure(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        workflow_id: str | None,
    ) -> dict[str, Any]:
        return await self.structure_agent.review(
            db,
            novel_id,
            workflow_id=workflow_id,
        )


def _same_workflow_suggestion(item: dict[str, Any], workflow_id: str | None) -> bool:
    if not workflow_id:
        return False
    return (
        item.get("source_workflow_id") == workflow_id
        and item.get("target_workflow_id") == workflow_id
    )


def _current_workflow_asset_outcomes(
    suggestions: list[dict[str, Any]],
    *,
    auto_apply: list[dict[str, Any]],
    apply_result: dict[str, Any],
    workflow_id: str | None,
) -> dict[str, Any]:
    """Count unique current-workflow assets, never suggestion pairs."""
    if not workflow_id:
        return {
            "review": 0,
            "not_adopted": 0,
            "affected": 0,
            "review_asset_ids": [],
            "not_adopted_asset_ids": [],
        }

    not_adopted = _applied_structure_assets(
        auto_apply,
        apply_result=apply_result,
    )
    review: set[tuple[str, str]] = set()
    for item in suggestions:
        source = _structure_asset_identity(item, side="source")
        if source is not None and source in not_adopted:
            # This suggestion was resolved by deprecating its workflow-owned source.
            continue
        review.update(_current_workflow_assets(item, workflow_id=workflow_id))

    review.difference_update(not_adopted)
    return {
        "review": len(review),
        "not_adopted": len(not_adopted),
        "affected": len(review | not_adopted),
        "review_asset_ids": sorted(
            f"{asset_type}:{asset_id}" for asset_type, asset_id in review
        ),
        "not_adopted_asset_ids": sorted(
            f"{asset_type}:{asset_id}" for asset_type, asset_id in not_adopted
        ),
    }


def _applied_structure_assets(
    auto_apply: list[dict[str, Any]],
    *,
    apply_result: dict[str, Any],
) -> set[tuple[str, str]]:
    applied_count = max(0, int(apply_result.get("applied", 0) or 0))
    applied: set[tuple[str, str]] = set()
    for result in apply_result.get("results") or []:
        if not isinstance(result, dict):
            continue
        identity = _structure_asset_identity(result, side="source")
        if identity is not None:
            applied.add(identity)

    # Compatibility with existing/fake outline facades that only return a count.
    if len(applied) < applied_count:
        for item in auto_apply:
            identity = _structure_asset_identity(item, side="source")
            if identity is not None:
                applied.add(identity)
            if len(applied) >= applied_count:
                break
    return applied


def _current_workflow_assets(
    item: dict[str, Any],
    *,
    workflow_id: str,
) -> set[tuple[str, str]]:
    assets: set[tuple[str, str]] = set()
    for side in ("source", "target"):
        if item.get(f"{side}_workflow_id") != workflow_id:
            continue
        identity = _structure_asset_identity(item, side=side)
        if identity is not None:
            assets.add(identity)
    return assets


def _structure_asset_identity(
    item: dict[str, Any],
    *,
    side: str,
) -> tuple[str, str] | None:
    asset_type = str(item.get("asset_type") or "").strip()
    asset_id = str(item.get(f"{side}_asset_id") or "").strip()
    if not asset_type or not asset_id:
        return None
    return asset_type, asset_id


def _safe_structure_suggestion(item: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "asset_type",
        "action",
        "source_asset_id",
        "source_title",
        "target_asset_id",
        "target_title",
        "recommended_primary_asset_id",
        "confidence",
        "match_method",
        "requires_confirmation",
        "source_workflow_id",
        "target_workflow_id",
    }
    return {key: value for key, value in item.items() if key in allowed}


def _normalize_text(value: Any) -> str:
    return _PUNCT_RE.sub("", str(value or "").strip().lower())


def _unique_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _merge_chunks(
    primary: list[SceneChunk],
    duplicate: list[SceneChunk],
) -> list[SceneChunk]:
    keyed: dict[tuple[int, int, int], SceneChunk] = {}
    for chunk in [*primary, *duplicate]:
        key = (
            int(chunk.chapter_index),
            int(chunk.start_paragraph or 0),
            int(chunk.end_paragraph or 0),
        )
        keyed.setdefault(key, chunk)
    return [
        keyed[key]
        for key in sorted(
            keyed,
            key=lambda item: (item[0], item[1], item[2]),
        )
    ]


def _scene_sort_key(candidate: FinalSceneCandidate) -> tuple[int, int, str]:
    chapters = candidate.source_chapter_indices or [10**9]
    return (chapters[0], chapters[-1], candidate.candidate_id)
