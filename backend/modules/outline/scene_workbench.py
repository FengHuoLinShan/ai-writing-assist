from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from itertools import combinations
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.tasks.enqueuer import enqueue_task
from modules.outline.contracts import (
    SCENE_SEMANTIC_FIELDS,
    scene_semantic_field_status,
)
from modules.outline.models import Scene, SceneFusionSuggestion, SceneSpan
from modules.outline.repositories import (
    SceneFusionSuggestionRepository,
    SceneIdentityProjection,
    SceneRepository,
    SceneSuggestionSourceProjection,
    SceneWorkbenchHealthProjection,
)
from modules.outline.scene_draft_review import (
    SceneDraftReviewService,
    mapping_scope_warnings,
)
from modules.outline.scene_fusion_draft import SceneFusionDraftGenerator
from modules.outline.schemas import (
    SceneCreate,
    SceneFusionDraft,
    SceneFusionPreviewRequest,
    SceneFusionPreviewResponse,
    SceneFusionSaveRequest,
    SceneFusionSaveResponse,
    SceneFusionSuggestionDismissRequest,
    SceneFusionSuggestionDismissResponse,
    SceneFusionSuggestionListResponse,
    SceneFusionSuggestionResponse,
    SceneFusionSuggestionSummary,
    SceneHealthReason,
    SceneHealthSummary,
    SceneImpactPreview,
    SceneMappingUpdate,
    SceneMergeRequest,
    SceneProgressSummary,
    SceneReplacementApplyRequest,
    SceneReplacementApplyResponse,
    SceneResponse,
    SceneReviewRequest,
    SceneReviewResponse,
    SceneSourceMappingReviewRequest,
    SceneSourceMappingReviewResponse,
    SceneSpanOverlapDetail,
    SceneSpanSummary,
    SceneSplitRequest,
    SceneUpdate,
    SceneWorkbenchItem,
    SceneWorkbenchResponse,
)
from modules.outline.services import SceneService, scene_has_missing_setup
from modules.writing.facade import (
    get_draft,
    list_chapter_indices,
    list_effective_chapter_indices,
)
from shared.utils import parse_uuid

HEALTH_DEFS = {
    "unreviewed": "未复核",
    "unassigned": "未关联章节",
    "missing_setup": "缺设定",
    "needs_organize": "待整理",
}

HEALTH_REASON_LABELS = {
    "manual_organize": "Scene 结构待确认",
    "duplicate_chapter": "Scene 内章节重复",
    "overlapping_span": "Scene 正文片段与其他 Scene 重叠",
    "chunk_chapter_mismatch": "章节与正文分段不一致",
    "source_mapping_chapter_only": "正文定位仅精确到章节",
    "source_mapping_unresolved": "正文定位需重新确认",
    "pending_scene_fusion_suggestion": "有 Scene 融合建议待处理",
}

HEALTH_REASON_GROUPS = {
    "manual_organize": "scene_structure",
    "duplicate_chapter": "scene_structure",
    "overlapping_span": "scene_structure",
    "chunk_chapter_mismatch": "scene_structure",
    "source_mapping_chapter_only": "source_mapping",
    "source_mapping_unresolved": "source_mapping",
    "pending_scene_fusion_suggestion": "scene_fusion_suggestion",
}

CONFIDENCE_BANDS = {"low", "medium", "high"}
_FUSION_DECISION_STATUSES = ("pending", "dismissed", "adopted")
MAPPING_STATUS_LABELS = {
    "exact": "精确定位",
    "reanchored": "已重新定位",
    "chapter_only": "仅关联章节",
    "unresolved": "需重新定位",
}
_ANCHOR_SUMMARY_LIMIT = 120


class SceneSuggestionConflictError(RuntimeError):
    """A durable suggestion changed or was already processed."""

    def __init__(self, message: str, *, persist_stale: bool = False) -> None:
        super().__init__(message)
        self.persist_stale = persist_stale


class SceneWorkbenchService:
    def __init__(
        self,
        *,
        fusion_draft_generator: SceneFusionDraftGenerator | None = None,
    ) -> None:
        self.repo = SceneRepository()
        self._suggestion_repo = SceneFusionSuggestionRepository()
        self._scene_service = SceneService()
        self._draft_review_service = SceneDraftReviewService()
        self._fusion_draft_generator = (
            fusion_draft_generator or SceneFusionDraftGenerator()
        )

    async def create_scene(
        self,
        db: AsyncSession,
        novel_id: str,
        data: SceneCreate,
    ) -> SceneResponse:
        return await self._scene_service.create(db, novel_id, data)

    async def validate_mapping_chapters(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_ids: list[str] | None,
        scene_chunks: list[dict] | None,
    ) -> None:
        """Validate author-supplied Scene mappings against this novel's chapters."""
        await self._validate_mapping_chapters(
            db,
            novel_id,
            chapter_ids,
            scene_chunks,
        )

    async def update_scene(
        self,
        db: AsyncSession,
        novel_id: str,
        scene_id: str,
        data: SceneUpdate,
    ) -> SceneResponse:
        return await self._scene_service.update(
            db,
            scene_id,
            data,
            novel_id=novel_id,
        )

    async def delete_scene(
        self,
        db: AsyncSession,
        novel_id: str,
        scene_id: str,
    ) -> None:
        await self._scene_service.delete(db, scene_id, novel_id=novel_id)

    async def reorder_scenes(
        self,
        db: AsyncSession,
        novel_id: str,
        scene_ids: list[str],
    ) -> dict:
        return await self._scene_service.reorder(db, novel_id, scene_ids)

    async def split_chapters_from_api(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int,
        target_scene_id: str | None = None,
    ) -> list[SceneResponse]:
        contracts = await self._scene_service.split_chapters(
            db,
            novel_id,
            chapter_index,
            target_scene_id,
        )
        return [SceneResponse.model_validate(c.__dict__) for c in contracts]

    async def get_workbench(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        selected_scene_id: str | None = None,
        status: str | None = None,
        source: str | None = None,
        workflow_id: str | None = None,
        needs_review: bool | None = None,
        boundary_status: str | None = None,
        phase: str | None = None,
        phase1a_fallback: bool | None = None,
        health: str | None = None,
        q: str | None = None,
        chapter_from: int | None = None,
        chapter_to: int | None = None,
        confidence_band: str | None = None,
        view_mode: str = "normal",
        segment: str | None = None,
        anchor: str | None = None,
        skip: int = 0,
        limit: int | None = None,
    ) -> SceneWorkbenchResponse:
        self._validate_filters(
            health=health,
            chapter_from=chapter_from,
            chapter_to=chapter_to,
            confidence_band=confidence_band,
        )
        if view_mode not in {"normal", "hot"}:
            raise ValueError("Invalid view_mode")
        if segment not in {None, "current", "upcoming", "past", "unassigned"}:
            raise ValueError("Invalid segment")
        if anchor not in {None, "latest"}:
            raise ValueError("Invalid anchor")
        if view_mode != "hot" and (segment is not None or anchor is not None):
            raise ValueError("segment and anchor require hot view_mode")
        nid = parse_uuid(novel_id, "novel_id")
        all_matching_scenes = await self.repo.get_workbench_health_projections(
            db,
            nid,
            status=status,
            source=source,
            workflow_id=workflow_id,
            needs_review=needs_review,
            boundary_status=boundary_status,
            phase=phase,
            phase1a_fallback=phase1a_fallback,
            q=q,
            chapter_from=chapter_from,
            chapter_to=chapter_to,
            confidence_band=confidence_band,
        )
        if health:
            # Health buckets are actionable work queues. Historical Scenes remain
            # available through the explicit status=deprecated management filter,
            # but must not re-enter those queues when both filters are combined.
            all_matching_scenes = [
                scene for scene in all_matching_scenes if scene.status != "deprecated"
            ]
        chapter_indices = await list_effective_chapter_indices(db, novel_id)
        as_of_chapter = max(chapter_indices) if chapter_indices else None
        progress_segment_by_scene = {
            scene.id: self._progress_segment(scene, as_of_chapter)
            for scene in all_matching_scenes
        }
        assigned_chapter_indices = await self.repo.get_active_assigned_chapter_indices(
            db,
            nid,
        )
        unassigned_chapters = [
            chapter_index
            for chapter_index in chapter_indices
            if chapter_index not in assigned_chapter_indices
        ]
        span_review_by_scene: dict[uuid.UUID, list[SceneSpan]] = defaultdict(list)
        for span in await self.repo.get_scene_spans_needing_review(db, nid):
            span_review_by_scene[span.scene_id].append(span)
        coverage_spans = await self.repo.get_scene_spans_for_coverage(
            db,
            nid,
            content_mode="canonical",
            statuses=("draft", "canonical"),
        )
        overlap_pairs = self._overlapping_span_pairs(coverage_spans)
        overlap_chapters_by_scene = self._overlap_chapters(overlap_pairs)
        overlap_scene_ids = {span.scene_id for pair in overlap_pairs for span in pair[:2]}
        overlap_identities = await self.repo.get_scene_identity_projections(
            db,
            nid,
            overlap_scene_ids,
        )
        overlap_details_by_scene = self._overlap_details(
            overlap_pairs,
            overlap_identities,
        )
        pending_suggestions = await self._active_pending_suggestions(
            db,
            nid,
            use_source_projections=True,
        )
        suggestions_by_scene: dict[uuid.UUID, list[SceneFusionSuggestion]] = defaultdict(
            list
        )
        for suggestion in pending_suggestions:
            for raw_scene_id in suggestion.source_scene_ids or []:
                try:
                    suggestions_by_scene[uuid.UUID(str(raw_scene_id))].append(suggestion)
                except (TypeError, ValueError):
                    continue

        details_by_scene = {
            scene.id: self._scene_health_details(
                scene,
                span_review_by_scene.get(scene.id, []),
                suggestions_by_scene.get(scene.id, []),
                overlap_chapters_by_scene.get(scene.id, set()),
            )
            for scene in all_matching_scenes
        }
        health_by_scene = {
            scene_id: self._health_keys(scene, details_by_scene[scene_id])
            for scene_id, scene in ((scene.id, scene) for scene in all_matching_scenes)
        }

        filtered_scenes = all_matching_scenes
        if health:
            filtered_scenes = [
                scene
                for scene in all_matching_scenes
                if health in health_by_scene[scene.id]
            ]
        progress_counts = {
            key: sum(
                1
                for scene in filtered_scenes
                if progress_segment_by_scene[scene.id] == key
            )
            for key in ("current", "upcoming", "past", "unassigned")
        }
        if segment:
            filtered_scenes = [
                scene
                for scene in filtered_scenes
                if progress_segment_by_scene[scene.id] == segment
            ]

        effective_skip = skip
        has_explicit_navigation = (
            skip > 0
            or segment is not None
            or any(
                value is not None
                for value in (
                    status,
                    source,
                    workflow_id,
                    needs_review,
                    boundary_status,
                    phase,
                    phase1a_fallback,
                    health,
                    q,
                    chapter_from,
                    chapter_to,
                    confidence_band,
                )
            )
        )
        normalized_selected_scene_id: str | None = None
        if selected_scene_id:
            selected_id = parse_uuid(selected_scene_id, "selected_scene_id")
            selected_index = next(
                (
                    index
                    for index, scene in enumerate(filtered_scenes)
                    if scene.id == selected_id
                ),
                None,
            )
            if selected_index is None:
                raise LookupError("Scene not found")
            normalized_selected_scene_id = str(selected_id)
            if limit is not None and not (
                effective_skip <= selected_index < effective_skip + limit
            ):
                effective_skip = (selected_index // limit) * limit
        elif (
            anchor == "latest"
            and not has_explicit_navigation
            and limit is not None
            and as_of_chapter is not None
        ):
            anchor_index = self._latest_anchor_index(
                filtered_scenes,
                as_of_chapter,
            )
            if anchor_index is not None:
                effective_skip = (anchor_index // limit) * limit

        if limit is not None:
            visible_scenes = filtered_scenes[effective_skip : effective_skip + limit]
        else:
            visible_scenes = filtered_scenes[effective_skip:]

        visible_models = await self.repo.get_many_for_novel(
            db,
            nid,
            [scene.id for scene in visible_scenes],
        )
        visible_by_id = {scene.id: scene for scene in visible_models}
        visible_spans_by_scene: dict[uuid.UUID, list[SceneSpan]] = defaultdict(list)
        for span in await self.repo.get_scene_spans_for_scenes(
            db,
            nid,
            [scene.id for scene in visible_scenes],
        ):
            visible_spans_by_scene[span.scene_id].append(span)
        items = []
        for projection in visible_scenes:
            scene = visible_by_id.get(projection.id)
            if scene is None:
                raise LookupError("Scene not found")
            items.append(
                SceneWorkbenchItem(
                    scene=SceneResponse.model_validate(scene),
                    health=health_by_scene[scene.id],
                    health_details=details_by_scene[scene.id],
                    chapter_range=self._display_chapter_range(scene),
                    summary=scene.goal or scene.core_conflict or scene.emotional_beat,
                    span_summaries=self._span_summaries(
                        visible_spans_by_scene.get(scene.id, [])
                    ),
                    overlap_details=overlap_details_by_scene.get(scene.id, []),
                    segment=(
                        progress_segment_by_scene[scene.id]
                        if view_mode == "hot"
                        else None
                    ),
                )
            )

        counts = {key: 0 for key in HEALTH_DEFS}
        breakdown = {
            "scene_structure": 0,
            "source_mapping": 0,
            "scene_fusion_suggestion": 0,
        }
        for scene in all_matching_scenes:
            for key in health_by_scene[scene.id]:
                counts[key] += 1
            reason_groups = {
                HEALTH_REASON_GROUPS[reason.code]
                for reason in details_by_scene[scene.id].get("needs_organize", [])
            }
            for group in reason_groups:
                breakdown[group] += 1
        counts["unassigned"] += len(unassigned_chapters)
        total = len(filtered_scenes)

        return SceneWorkbenchResponse(
            health={
                key: SceneHealthSummary(
                    key=key,
                    label=label,
                    count=counts[key],
                    breakdown=breakdown if key == "needs_organize" else {},
                )
                for key, label in HEALTH_DEFS.items()
            },
            items=items,
            total=total,
            skip=effective_skip,
            unassigned_chapters=(
                unassigned_chapters
                if health in {None, "unassigned"} and segment in {None, "unassigned"}
                else []
            ),
            selected_scene_id=normalized_selected_scene_id,
            fusion_suggestions=SceneFusionSuggestionSummary(
                pending_count=len(pending_suggestions)
            ),
            progress=(
                SceneProgressSummary(
                    as_of_chapter=as_of_chapter,
                    **progress_counts,
                )
                if view_mode == "hot"
                else None
            ),
        )

    @staticmethod
    def _progress_chapters(scene) -> list[int]:
        result: list[int] = []
        for raw in scene.chapter_ids or []:
            try:
                chapter = int(raw)
            except (TypeError, ValueError):
                continue
            if chapter >= 1:
                result.append(chapter)
        if result:
            return sorted(set(result))
        meta = dict(scene.structure_meta or {})
        if meta.get("planning_state") != "planned":
            return []
        planned = meta.get("planned_chapter_range") or {}
        for value in (planned.get("start"), planned.get("end")):
            if isinstance(value, int) and value >= 1:
                result.append(value)
        return sorted(set(result))

    @classmethod
    def _progress_segment(cls, scene, as_of_chapter: int | None) -> str:
        chapters = cls._progress_chapters(scene)
        if not chapters:
            return "unassigned"
        if as_of_chapter is None:
            return "upcoming"
        if chapters[0] <= as_of_chapter <= chapters[-1]:
            return "current"
        if chapters[0] > as_of_chapter:
            return "upcoming"
        return "past"

    @classmethod
    def _latest_anchor_index(cls, scenes, as_of_chapter: int) -> int | None:
        if not scenes:
            return None
        current = [
            index
            for index, scene in enumerate(scenes)
            if cls._progress_segment(scene, as_of_chapter) == "current"
        ]
        if current:
            return current[0]

        best: tuple[int, int] | None = None
        for index, scene in enumerate(scenes):
            chapters = cls._progress_chapters(scene)
            if not chapters:
                continue
            distance = min(abs(chapter - as_of_chapter) for chapter in chapters)
            candidate = (distance, index)
            if best is None or candidate < best:
                best = candidate
        return best[1] if best is not None else None

    async def review_scenes(
        self,
        db: AsyncSession,
        novel_id: str,
        data: SceneReviewRequest,
    ) -> SceneReviewResponse:
        if len(set(data.scene_ids)) != len(data.scene_ids):
            raise ValueError("scene_ids cannot contain duplicates")
        scenes = await self._get_scenes_in_novel(db, novel_id, data.scene_ids)
        if any(scene.status == "deprecated" for scene in scenes):
            raise ValueError("Deprecated Scene cannot be reviewed")
        structure_reasons: dict[uuid.UUID, list[str]] = {}
        if data.decision == "review":
            for scene in scenes:
                details = self._scene_health_details(
                    scene,
                    [],
                    [],
                    set(),
                )
                structure_reasons[scene.id] = [
                    reason.code
                    for reason in details.get("needs_organize", [])
                    if HEALTH_REASON_GROUPS[reason.code] == "scene_structure"
                ]

        reviewed_at = datetime.now(UTC).isoformat()
        updated_items: list[SceneResponse] = []
        for scene in scenes:
            meta = dict(scene.structure_meta or {})
            if data.decision == "review":
                meta.update(
                    {
                        "needs_review": False,
                        "needs_organize": False,
                        "reviewed_at": reviewed_at,
                        "reviewed_by": "manual",
                        "reviewed_from": (
                            "scene_workbench_bulk"
                            if len(scenes) > 1
                            else "scene_workbench"
                        ),
                        "reviewed_attention_reasons": structure_reasons.get(
                            scene.id,
                            [],
                        ),
                    }
                )
                meta = self._manually_reviewed_semantic_meta(
                    scene,
                    meta,
                    reviewed_at=reviewed_at,
                )
                update_data = SceneUpdate(status="canonical", structure_meta=meta)
            else:
                meta["needs_review"] = True
                for key in (
                    "reviewed_at",
                    "reviewed_by",
                    "reviewed_from",
                    "reviewed_attention_reasons",
                ):
                    meta.pop(key, None)
                update_data = SceneUpdate(structure_meta=meta)
            updated = await self.repo.update(db, scene.id, update_data)
            if updated is None:
                raise LookupError("Scene not found")
            updated_items.append(SceneResponse.model_validate(updated))
        return SceneReviewResponse(items=updated_items)

    @staticmethod
    def _manually_reviewed_semantic_meta(
        scene: Scene,
        meta: dict[str, Any],
        *,
        reviewed_at: str,
    ) -> dict[str, Any]:
        has_trusted_semantics = scene.source in {"deep_import", "manual_fusion"} or any(
            scene_semantic_field_status(scene, field) is not None
            for field in SCENE_SEMANTIC_FIELDS
        )
        if not has_trusted_semantics:
            return meta

        statuses: dict[str, str] = {}
        for field in SCENE_SEMANTIC_FIELDS:
            if field == "narrative_function":
                value = meta.get(field)
            else:
                value = getattr(scene, field, None)
            if field == "narrative_tag" and value == "draft":
                value = None
            statuses[field] = "present" if value not in (None, "") else "not_applicable"
        meta.update(
            {
                "semantic_field_statuses": statuses,
                "semantic_uncertain_fields": [],
                "core_conflict_status": statuses["core_conflict"],
                "semantic_reviewed_at": reviewed_at,
                "semantic_reviewed_by": "manual",
            }
        )
        return meta

    async def review_source_mappings(
        self,
        db: AsyncSession,
        novel_id: str,
        data: SceneSourceMappingReviewRequest,
    ) -> SceneSourceMappingReviewResponse:
        if not data.confirmed:
            raise PermissionError("source mapping review requires confirmed=true")
        scene_ids = [item.scene_id for item in data.items]
        if len(set(scene_ids)) != len(scene_ids):
            raise ValueError("scene_ids cannot contain duplicates")
        scenes = await self._get_scenes_in_novel(db, novel_id, scene_ids)
        nid = parse_uuid(novel_id, "novel_id")
        spans_by_scene: dict[uuid.UUID, list[SceneSpan]] = defaultdict(list)
        for span in await self.repo.get_scene_spans_needing_review(db, nid):
            spans_by_scene[span.scene_id].append(span)

        validated_reviews: list[tuple[Scene, str]] = []
        for request_item, scene in zip(data.items, scenes, strict=True):
            spans = spans_by_scene.get(scene.id, [])
            if not spans:
                raise ValueError("Scene has no source mapping requiring review")
            fingerprint = self._source_mapping_fingerprint(spans)
            if fingerprint != request_item.expected_fingerprint:
                raise ValueError("Source mapping changed; reload before confirming")
            validated_reviews.append((scene, fingerprint))

        reviewed_at = datetime.now(UTC).isoformat()
        updated_items: list[SceneResponse] = []
        for scene, fingerprint in validated_reviews:
            meta = dict(scene.structure_meta or {})
            meta["source_mapping_review"] = {
                "decision": data.decision,
                "fingerprint": fingerprint,
                "reviewed_at": reviewed_at,
                "reviewed_by": "manual",
            }
            updated = await self.repo.update(
                db,
                scene.id,
                SceneUpdate(structure_meta=meta),
            )
            if updated is None:
                raise LookupError("Scene not found")
            updated_items.append(SceneResponse.model_validate(updated))
        return SceneSourceMappingReviewResponse(items=updated_items)

    async def persist_fusion_suggestions(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        source_workflow_id: str,
        suggestions: list[dict[str, Any]],
    ) -> list[str]:
        nid = parse_uuid(novel_id, "novel_id")
        stored_ids: list[str] = []
        for suggestion in suggestions:
            suggestion_payload = dict(suggestion)
            source_ids = [
                str(value) for value in suggestion_payload.get("source_scene_ids") or []
            ]
            if len(source_ids) < 2 or len(set(source_ids)) != len(source_ids):
                continue
            scenes = await self._get_scenes_in_novel(db, novel_id, source_ids)
            source_fingerprint = self._suggestion_source_fingerprint(scenes)
            suggestion_kind = str(
                suggestion_payload.get("suggestion_kind") or "cross_chapter"
            )
            decision_origin = suggestion_payload.get("decision_origin")
            if decision_origin:
                scan_trace = list(suggestion_payload.get("scan_trace") or [])
                scan_trace.append(
                    {
                        "decision_origin": str(decision_origin),
                        "contract_version": "phase1c-v2",
                    }
                )
                suggestion_payload["scan_trace"] = scan_trace
            suggestion_key = hashlib.sha256(
                (
                    f"{suggestion_kind}:{','.join(source_ids)}:{source_fingerprint}"
                ).encode()
            ).hexdigest()
            stored = await self._suggestion_repo.upsert_pending(
                db,
                novel_id=nid,
                source_workflow_id=source_workflow_id,
                suggestion_key=suggestion_key,
                source_fingerprint=source_fingerprint,
                payload=suggestion_payload,
            )
            stored_ids.append(str(stored.id))
        return stored_ids

    async def get_current_fusion_decision_pairs(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> set[frozenset[str]]:
        """Return current Scene pairs already decided through Phase 1c review.

        This is an outline-internal read model for global structure dedup. A
        current pending or dismissed decision owns its source pair. An adopted
        decision also owns every source-to-result pair so keep-originals does
        not reappear as a global duplicate suggestion.
        """
        decisions = await self._current_fusion_suggestions(
            db,
            parse_uuid(novel_id, "novel_id"),
            statuses=_FUSION_DECISION_STATUSES,
        )
        protected_pairs: set[frozenset[str]] = set()
        for item in decisions:
            source_ids = [str(value) for value in item.source_scene_ids or []]
            protected_pairs.update(
                frozenset(pair) for pair in combinations(source_ids, 2)
            )
            if item.status == "adopted" and item.result_scene_id is not None:
                result_id = str(item.result_scene_id)
                protected_pairs.update(
                    frozenset((source_id, result_id)) for source_id in source_ids
                )
        return protected_pairs

    async def list_fusion_suggestions(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        skip: int = 0,
        limit: int = 50,
    ) -> SceneFusionSuggestionListResponse:
        pending = await self._active_pending_suggestions(
            db,
            parse_uuid(novel_id, "novel_id"),
        )
        visible = pending[skip : skip + limit]
        return SceneFusionSuggestionListResponse(
            items=[
                SceneFusionSuggestionResponse.model_validate(item) for item in visible
            ],
            total=len(pending),
        )

    async def dismiss_fusion_suggestions(
        self,
        db: AsyncSession,
        novel_id: str,
        data: SceneFusionSuggestionDismissRequest,
    ) -> SceneFusionSuggestionDismissResponse:
        if not data.confirmed:
            raise PermissionError("dismiss suggestions requires confirmed=true")
        if len(set(data.suggestion_ids)) != len(data.suggestion_ids):
            raise ValueError("suggestion_ids cannot contain duplicates")
        nid = parse_uuid(novel_id, "novel_id")
        items: list[SceneFusionSuggestion] = []
        for raw_id in data.suggestion_ids:
            item = await self._suggestion_repo.get_for_novel(
                db,
                nid,
                parse_uuid(raw_id, "suggestion_id"),
            )
            if item is None:
                raise LookupError("Scene fusion suggestion not found")
            if item.status != "pending":
                raise ValueError("Scene fusion suggestion is already processed")
            if not await self._suggestion_is_current(db, item):
                raise ValueError("Scene fusion suggestion is stale")
            items.append(item)
        for item in items:
            await self._suggestion_repo.mark_status(db, item, status="dismissed")
        return SceneFusionSuggestionDismissResponse(dismissed=len(items))

    async def apply_replacement_suggestion(
        self,
        db: AsyncSession,
        novel_id: str,
        data: SceneReplacementApplyRequest,
    ) -> SceneReplacementApplyResponse:
        if not data.confirmed:
            raise PermissionError("replacement apply requires confirmed=true")
        nid = parse_uuid(novel_id, "novel_id")
        item = await self._suggestion_repo.get_for_novel_for_update(
            db,
            nid,
            parse_uuid(data.suggestion_id, "suggestion_id"),
        )
        if item is None:
            raise LookupError("Scene replacement suggestion not found")
        if item.suggestion_kind != "replacement":
            raise ValueError("suggestion is not a Scene replacement")
        if item.status != "pending":
            raise SceneSuggestionConflictError("Scene replacement is already processed")

        source_ids = self._parse_suggestion_source_ids(item)
        if source_ids is None:
            raise SceneSuggestionConflictError("Scene replacement sources are invalid")
        source_scenes = await self._lock_replacement_sources(db, nid, source_ids)
        if not self._replacement_suggestion_is_current(item, source_scenes):
            await self._suggestion_repo.mark_status(db, item, status="stale")
            raise SceneSuggestionConflictError(
                "Scene replacement suggestion is stale",
                persist_stale=True,
            )

        proposed = dict(item.proposed_scene or {})
        stored_drafts = list(proposed.get("draft_scenes") or [])
        drafts = self._replacement_drafts(data, stored_drafts)
        try:
            await self._validate_replacement_source_hashes(db, novel_id, drafts)
        except SceneSuggestionConflictError as exc:
            await self._suggestion_repo.mark_status(db, item, status="stale")
            raise SceneSuggestionConflictError(
                str(exc),
                persist_stale=True,
            ) from exc

        active = list(
            (
                await db.execute(
                    select(Scene)
                    .where(
                        Scene.novel_id == nid,
                        Scene.status.in_(("candidate", "draft", "canonical")),
                    )
                    .order_by(Scene.scene_index, Scene.id)
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        next_index = max((scene.scene_index for scene in active), default=-1) + 1
        now = datetime.now(UTC).isoformat()
        created: list[Scene] = []
        for replacement_order, draft in enumerate(drafts):
            meta = {
                **dict(draft.get("structure_meta") or {}),
                "needs_review": False,
                "needs_organize": False,
                "reviewed_at": now,
                "reviewed_by": "manual",
                "reviewed_from": "scene_replacement",
                "adopted_at": now,
                "replaces_scene_ids": [str(scene.id) for scene in source_scenes],
                "source_workflow_id": item.source_workflow_id,
                "replacement_suggestion_id": str(item.id),
                "replacement_order": replacement_order,
            }
            payload = SceneCreate(
                scene_index=next_index,
                title=draft.get("title"),
                goal=draft.get("goal"),
                core_conflict=draft.get("core_conflict"),
                emotional_beat=draft.get("emotional_beat"),
                must_happen=draft.get("must_happen"),
                must_not_happen=draft.get("must_not_happen"),
                narrative_tag=draft.get("narrative_tag") or "imported",
                source="deep_import",
                scene_chunks=list(draft.get("scene_chunks") or []),
                chapter_ids=list(draft.get("chapter_ids") or []),
                structure_meta=meta,
                status="canonical",
            )
            created.append(await self.repo.create(db, nid, payload))
            next_index += 1

        created_ids = [scene.id for scene in created]
        for scene in source_scenes:
            meta = {
                **dict(scene.structure_meta or {}),
                "previous_status": scene.status,
                "deprecated_reason": "scene_replacement",
                "deprecated_at": now,
                "replaced_by_scene_ids": [str(scene_id) for scene_id in created_ids],
            }
            await self.repo.update(
                db,
                scene.id,
                SceneUpdate(status="deprecated", structure_meta=meta),
            )

        remaining = [scene for scene in active if scene.id not in set(source_ids)]
        ordered = sorted([*remaining, *created], key=self._replacement_sort_key)
        await self.repo.reorder(db, nid, [scene.id for scene in ordered])
        await self._suggestion_repo.mark_status(
            db,
            item,
            status="adopted",
            result_scene_id=created_ids[0] if created_ids else None,
            result_scene_ids=created_ids,
        )
        chapter_indices = sorted(
            {
                int(chapter)
                for draft in drafts
                for chapter in draft.get("chapter_ids") or []
            }
        )
        rag_task_id = enqueue_task(
            db,
            "rag_reindex_novel",
            meta={
                "novel_id": novel_id,
                "start_chapter": chapter_indices[0] if chapter_indices else None,
                "end_chapter": chapter_indices[-1] if chapter_indices else None,
                "source": "scene_replacement_apply",
            },
            novel_id=novel_id,
        )
        return SceneReplacementApplyResponse(
            deprecated_scene_ids=[str(scene.id) for scene in source_scenes],
            result_scene_ids=[str(scene_id) for scene_id in created_ids],
            rag_reindex_task_id=str(rag_task_id),
        )

    async def _lock_replacement_sources(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        source_ids: list[uuid.UUID],
    ) -> list[Scene]:
        result = await db.execute(
            select(Scene)
            .where(Scene.novel_id == novel_id, Scene.id.in_(source_ids))
            .with_for_update()
        )
        by_id = {scene.id: scene for scene in result.scalars().all()}
        if any(scene_id not in by_id for scene_id in source_ids):
            raise SceneSuggestionConflictError("Scene replacement source is missing")
        return [by_id[scene_id] for scene_id in source_ids]

    def _replacement_drafts(
        self,
        data: SceneReplacementApplyRequest,
        stored: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not stored:
            raise SceneSuggestionConflictError("Scene replacement has no candidates")
        if data.decision == "replace":
            if data.draft_scenes is not None:
                raise ValueError("draft_scenes is only valid for edit_then_replace")
            return [dict(item) for item in stored]
        if data.draft_scenes is None or len(data.draft_scenes) != len(stored):
            raise ValueError("edited draft_scenes must preserve candidate count")
        allowed = {
            "title",
            "goal",
            "core_conflict",
            "emotional_beat",
            "must_happen",
            "must_not_happen",
            "narrative_tag",
        }
        merged: list[dict[str, Any]] = []
        for original, edited in zip(stored, data.draft_scenes, strict=True):
            unexpected = set(edited) - allowed
            if unexpected:
                raise ValueError(
                    f"edited replacement contains protected fields: {sorted(unexpected)}"
                )
            merged.append({**dict(original), **{key: edited[key] for key in edited}})
        return merged

    async def _validate_replacement_source_hashes(
        self,
        db: AsyncSession,
        novel_id: str,
        drafts: list[dict[str, Any]],
    ) -> None:
        for draft in drafts:
            for chunk in draft.get("scene_chunks") or []:
                draft_id = chunk.get("source_draft_id")
                expected_hash = chunk.get("source_content_hash")
                if not draft_id or not expected_hash:
                    continue
                current = await get_draft(db, novel_id, str(draft_id))
                if current is None or current.content_hash != expected_hash:
                    raise SceneSuggestionConflictError(
                        "Scene replacement source content has changed"
                    )

    @staticmethod
    def _replacement_sort_key(scene: Scene) -> tuple[Any, ...]:
        chapters = SceneRepository().chapter_indices_for_scene(scene)
        offsets = [
            int(chunk["start_offset"])
            for chunk in scene.scene_chunks or []
            if isinstance(chunk, dict) and chunk.get("start_offset") is not None
        ]
        meta = dict(scene.structure_meta or {})
        return (
            chapters[0] if chapters else 10**12,
            min(offsets) if offsets else 10**12,
            scene.scene_index,
            int(meta.get("replacement_order", 10**12)),
            str(scene.id),
        )

    def _validate_filters(
        self,
        *,
        health: str | None,
        chapter_from: int | None,
        chapter_to: int | None,
        confidence_band: str | None,
    ) -> None:
        if health and health not in HEALTH_DEFS:
            raise ValueError("Unsupported scene health filter")
        if confidence_band and confidence_band not in CONFIDENCE_BANDS:
            raise ValueError("Unsupported confidence band")
        if (
            chapter_from is not None
            and chapter_to is not None
            and chapter_from > chapter_to
        ):
            raise ValueError("chapter_from must be less than or equal to chapter_to")

    async def update_mapping(
        self,
        db: AsyncSession,
        novel_id: str,
        scene_id: str,
        data: SceneMappingUpdate,
    ) -> SceneResponse:
        scene = await self._get_scene_in_novel(db, novel_id, scene_id)
        await self._validate_mapping_chapters(
            db,
            novel_id,
            data.chapter_ids,
            data.scene_chunks,
        )
        meta = dict(scene.structure_meta or {})
        if data.structure_meta is not None:
            meta.update(data.structure_meta)
        resulting_chapter_ids = (
            data.chapter_ids
            if data.chapter_ids is not None
            else scene.chapter_ids or []
        )
        resulting_chunks = (
            data.scene_chunks
            if data.scene_chunks is not None
            else scene.scene_chunks or []
        )
        if resulting_chapter_ids or resulting_chunks:
            meta["planning_state"] = "materialized"
        update_payload: dict[str, Any] = {"structure_meta": meta}
        if data.chapter_ids is not None:
            update_payload["chapter_ids"] = data.chapter_ids
        if data.scene_chunks is not None:
            update_payload["scene_chunks"] = data.scene_chunks
        if data.status is not None:
            update_payload["status"] = data.status
        updated = await self.repo.update(
            db,
            scene.id,
            SceneUpdate(**update_payload),
        )
        if updated is None:
            raise LookupError("Scene not found")
        return SceneResponse.model_validate(updated)

    async def preview_merge(
        self,
        db: AsyncSession,
        novel_id: str,
        data: SceneMergeRequest,
    ) -> SceneImpactPreview:
        target, sources = await self._load_merge_scenes(db, novel_id, data)
        merged_chapters = self._merge_chapter_ids(
            target.chapter_ids or [],
            *[source.chapter_ids or [] for source in sources],
        )
        field_changes = self._merge_field_changes(target, sources)
        before = {
            str(target.id): target.chapter_ids or [],
            **{str(source.id): source.chapter_ids or [] for source in sources},
        }
        after = {
            str(target.id): merged_chapters,
            **{str(source.id): [] for source in sources},
        }
        start, end = self._range_from_chapters(merged_chapters)
        return SceneImpactPreview(
            operation="merge",
            chapter_mapping_change={"before": before, "after": after},
            field_changes=field_changes,
            related_threads=await self._related_thread_summary(db, novel_id, start, end),
            related_foreshadowing=await self._related_foreshadowing_summary(
                db, novel_id, start, end
            ),
            related_reveals=await self._related_reveal_summary(db, novel_id, start, end),
            map_summary_impact={
                "message": (
                    "目标 Scene 将承接来源 Scene 的章节映射；地图摘要将在写作页重新读取。"
                )
            },
            warnings=[
                *mapping_scope_warnings([target, *sources]),
                *self._merge_chunk_precision_warnings(
                    target.scene_chunks or [],
                    *[source.scene_chunks or [] for source in sources],
                ),
                "关联资产仅提示，不会自动阻断合并。",
            ],
            scene=SceneResponse.model_validate(target),
        )

    async def merge(
        self,
        db: AsyncSession,
        novel_id: str,
        data: SceneMergeRequest,
    ) -> SceneWorkbenchItem:
        if not data.confirmed:
            raise PermissionError("merge requires confirmed=true")
        target, sources = await self._load_merge_scenes(db, novel_id, data)
        merged_chapters = self._merge_chapter_ids(
            target.chapter_ids or [],
            *[source.chapter_ids or [] for source in sources],
        )
        merged_chunks = self._merge_chunks(
            target.scene_chunks or [],
            *[source.scene_chunks or [] for source in sources],
        )
        field_payload = {
            field: getattr(target, field) or self._first_non_empty(sources, field)
            for field in (
                "goal",
                "core_conflict",
                "emotional_beat",
                "must_happen",
                "must_not_happen",
                "pov_character_id",
            )
        }
        target_meta = dict(target.structure_meta or {})
        if not target_meta.get("narrative_function"):
            inherited_function = next(
                (
                    str(
                        (scene.structure_meta or {}).get("narrative_function") or ""
                    ).strip()
                    for scene in sources
                    if (scene.structure_meta or {}).get("narrative_function")
                ),
                None,
            )
            if inherited_function:
                target_meta["narrative_function"] = inherited_function
        target_meta["merged_from_scene_ids"] = [str(source.id) for source in sources]
        target_meta.update(
            self._mechanical_fusion_semantic_meta(
                [target, *sources],
                resulting_values=field_payload,
            )
        )
        updated_target = await self.repo.update(
            db,
            target.id,
            SceneUpdate(
                chapter_ids=merged_chapters,
                scene_chunks=merged_chunks,
                structure_meta=target_meta,
                **field_payload,
            ),
        )
        if updated_target is None:
            raise LookupError("Target Scene not found")

        await self.repo.deprecate_with_reference(
            db,
            sources,
            reference_field="merged_into_scene_id",
            reference_scene_id=target.id,
            clear_mapping=True,
        )

        return SceneWorkbenchItem(
            scene=SceneResponse.model_validate(updated_target),
            health=self._scene_health(updated_target),
            chapter_range=self._chapter_range(updated_target.chapter_ids or []),
            summary=updated_target.goal
            or updated_target.core_conflict
            or updated_target.emotional_beat,
        )

    async def preview_split(
        self,
        db: AsyncSession,
        novel_id: str,
        data: SceneSplitRequest,
    ) -> SceneImpactPreview:
        source = await self._get_scene_in_novel(db, novel_id, data.source_scene_id)
        keep, move = self._split_chapter_ids(
            source.chapter_ids or [],
            data.split_chapter_index,
            data.split_pos,
        )
        keep_chunks, move_chunks = self._split_chunks(
            source.scene_chunks or [],
            data.split_chapter_index,
            data.split_pos,
        )
        new_scene = self._new_split_scene_payload(source, data, move, move_chunks)
        review = self._draft_review_service.build_split_review(
            source=source,
            keep_scene={
                "scene_index": source.scene_index,
                "title": source.title,
                "goal": source.goal,
                "core_conflict": source.core_conflict,
                "emotional_beat": source.emotional_beat,
                "must_happen": source.must_happen,
                "must_not_happen": source.must_not_happen,
                "narrative_tag": source.narrative_tag,
                "source": source.source,
                "chapter_ids": keep,
                "scene_chunks": keep_chunks,
                "pov_character_id": source.pov_character_id,
                "status": source.status,
                "structure_meta": {
                    **dict(source.structure_meta or {}),
                    "draft_review_mode": "split",
                    "primary_scene_id": str(source.id),
                },
            },
            new_scene=new_scene,
        )
        start, end = self._range_from_chapters(source.chapter_ids or [])
        return SceneImpactPreview(
            operation="split",
            chapter_mapping_change={
                "before": {str(source.id): source.chapter_ids or []},
                "after": {str(source.id): keep},
            },
            field_changes={
                "source_scene": {
                    "chapter_ids": {
                        "before": source.chapter_ids or [],
                        "after": keep,
                    }
                },
                "new_scene": {"chapter_ids": move, "status": new_scene["status"]},
            },
            related_threads=await self._related_thread_summary(db, novel_id, start, end),
            related_foreshadowing=await self._related_foreshadowing_summary(
                db, novel_id, start, end
            ),
            related_reveals=await self._related_reveal_summary(db, novel_id, start, end),
            map_summary_impact={
                "message": "拆分后两个 Scene 的地图摘要将在写作页按新映射重新读取。"
            },
            warnings=["拆分不会修改正文内容。"],
            scene=SceneResponse.model_validate(source),
            new_scene=new_scene,
            draft_scenes=[
                draft.model_dump(mode="json", exclude_none=True)
                for draft in review.draft_scenes
            ],
            primary_scene_id=review.primary_scene_id,
            field_references={
                field: [ref.model_dump(mode="json", exclude_none=True) for ref in refs]
                for field, refs in review.field_references.items()
            },
            field_sources=review.field_sources,
            source_scene_summaries=[
                summary.model_dump(mode="json", exclude_none=True)
                for summary in review.source_scene_summaries
            ],
            conflicts=[
                conflict.model_dump(mode="json", exclude_none=True)
                for conflict in review.conflicts
            ],
            confidence=review.confidence,
            reason=review.reason,
        )

    async def split(
        self,
        db: AsyncSession,
        novel_id: str,
        data: SceneSplitRequest,
    ) -> SceneWorkbenchItem:
        if not data.confirmed:
            raise PermissionError("split requires confirmed=true")
        source = await self._get_scene_in_novel(db, novel_id, data.source_scene_id)
        keep, move = self._split_chapter_ids(
            source.chapter_ids or [],
            data.split_chapter_index,
            data.split_pos,
        )
        keep_chunks, move_chunks = self._split_chunks(
            source.scene_chunks or [],
            data.split_chapter_index,
            data.split_pos,
        )
        source_meta = dict(source.structure_meta or {})
        source_meta["split_at_chapter_index"] = data.split_chapter_index
        if data.draft_scenes:
            source_meta = self._adopted_structure_meta(
                source_meta,
                source="scene_split_preview",
            )
        source_update_payload: dict[str, Any] = {
            "chapter_ids": keep,
            "scene_chunks": keep_chunks,
            "structure_meta": source_meta,
        }
        if data.draft_scenes and len(data.draft_scenes) >= 1:
            source_update_payload.update(
                self._semantic_scene_overrides(data.draft_scenes[0])
            )
        updated_source = await self.repo.update(
            db,
            source.id,
            SceneUpdate(**source_update_payload),
        )
        if updated_source is None:
            raise LookupError("Source Scene not found")

        new_payload = self._new_split_scene_payload(source, data, move, move_chunks)
        if data.draft_scenes and len(data.draft_scenes) >= 2:
            new_payload.update(self._semantic_scene_overrides(data.draft_scenes[1]))
        new_scene = await self.repo.create(
            db,
            parse_uuid(novel_id, "novel_id"),
            SceneCreate(**new_payload),
        )
        await self._shift_later_scenes(db, new_scene)
        await db.flush()

        response = SceneResponse.model_validate(updated_source)
        item = SceneWorkbenchItem(
            scene=response,
            new_scene=SceneResponse.model_validate(new_scene),
            health=self._scene_health(updated_source),
            chapter_range=self._chapter_range(updated_source.chapter_ids or []),
            summary=updated_source.goal
            or updated_source.core_conflict
            or updated_source.emotional_beat,
        )
        return item

    def _semantic_scene_overrides(self, draft: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "title",
            "goal",
            "core_conflict",
            "emotional_beat",
            "must_happen",
            "must_not_happen",
            "narrative_tag",
            "pov_character_id",
        }
        return {key: value for key, value in draft.items() if key in allowed}

    async def preview_llm_fusion(
        self,
        db: AsyncSession,
        novel_id: str,
        data: SceneFusionPreviewRequest,
    ) -> SceneFusionPreviewResponse:
        if not data.primary_scene_id:
            raise ValueError("primary_scene_id is required for AI Scene fusion preview")
        sources = await self._load_fusion_scenes(db, novel_id, data.source_scene_ids)
        review_sources = [
            SimpleNamespace(
                **{
                    field: getattr(scene, field)
                    for field in (
                        "id",
                        "title",
                        "goal",
                        "core_conflict",
                        "emotional_beat",
                        "must_happen",
                        "must_not_happen",
                        "narrative_tag",
                        "pov_character_id",
                        "chapter_ids",
                        "scene_chunks",
                        "source",
                        "status",
                        "structure_meta",
                    )
                }
            )
            for scene in sources
        ]
        deterministic_draft = await self._fusion_scene_payload(
            db,
            novel_id,
            sources,
            primary_scene_id=data.primary_scene_id,
        )
        generated = await self._fusion_draft_generator.generate(
            db,
            novel_id=novel_id,
            sources=sources,
            primary_scene_id=data.primary_scene_id,
            deterministic_draft=deterministic_draft,
        )
        fused_scene = {
            **deterministic_draft,
            **generated.semantic_fields,
        }
        fused_scene["narrative_function"] = generated.semantic_meta.get(
            "narrative_function"
        )
        fused_scene["structure_meta"] = {
            **dict(deterministic_draft.get("structure_meta") or {}),
            **generated.semantic_meta,
            "fusion_strategy": (
                "local_deterministic_fallback"
                if generated.degraded
                else "project_llm_structured"
            ),
            "semantic_preview_values": {
                **{
                    field: fused_scene.get(field)
                    for field in SCENE_SEMANTIC_FIELDS
                    if field != "narrative_function"
                },
                "narrative_function": generated.semantic_meta.get(
                    "narrative_function"
                ),
            },
        }
        review = self._draft_review_service.build_fusion_review(
            sources=review_sources,  # type: ignore[arg-type]
            primary_scene_id=data.primary_scene_id,
            draft_scene=fused_scene,
            mode="fusion",
            confidence=generated.confidence,
            reason=generated.reason,
            warnings=generated.warnings,
        )
        draft = (
            review.draft_scene.model_dump(mode="json", exclude_none=True)
            if review.draft_scene
            else fused_scene
        )
        return SceneFusionPreviewResponse(
            mode=review.mode,
            source_scene_ids=[str(scene.id) for scene in sources],
            primary_scene_id=review.primary_scene_id,
            draft_scene=review.draft_scene,
            draft_scenes=review.draft_scenes,
            field_references=review.field_references,
            field_sources=review.field_sources,
            source_scene_summaries=review.source_scene_summaries,
            conflicts=review.conflicts,
            warnings=review.warnings,
            confidence=review.confidence,
            reason=review.reason,
            fused_scene=draft,
            preview_scene=draft,
        )

    async def save_llm_fusion(
        self,
        db: AsyncSession,
        novel_id: str,
        data: SceneFusionSaveRequest,
    ) -> SceneFusionSaveResponse:
        sources = await self._load_fusion_scenes(db, novel_id, data.source_scene_ids)
        source_ids = [str(scene.id) for scene in sources]
        suggestion = await self._load_current_suggestion(
            db,
            novel_id,
            data.suggestion_id,
            source_ids,
        )
        if data.mode == "discard":
            if suggestion is not None:
                await self._suggestion_repo.mark_status(
                    db,
                    suggestion,
                    status="dismissed",
                )
            return SceneFusionSaveResponse(
                status="discarded",
                source_scene_ids=source_ids,
                fused_scene=None,
                warnings=["融合结果已放弃，原 Scene 未修改。"],
            )

        overrides = data.fused_scene if data.mode != "discard" else None
        payload = await self._fusion_scene_payload(
            db,
            novel_id,
            sources,
            overrides,
            primary_scene_id=data.primary_scene_id,
        )
        payload["structure_meta"] = self._adopted_structure_meta(
            payload.get("structure_meta"),
            source=str(payload.get("source") or "manual_fusion"),
        )
        payload["structure_meta"] = self._author_reviewed_fusion_semantic_meta(
            payload,
            payload["structure_meta"],
        )
        await self._validate_fusion_override_chapters(db, novel_id, overrides)
        created = await self.repo.create(
            db,
            parse_uuid(novel_id, "novel_id"),
            SceneCreate(**payload),
        )

        if data.mode == "deprecate_originals":
            await self.repo.deprecate_with_reference(
                db,
                sources,
                reference_field="fused_into_scene_id",
                reference_scene_id=created.id,
            )

        if suggestion is not None:
            await self._suggestion_repo.mark_status(
                db,
                suggestion,
                status="adopted",
                result_scene_id=created.id,
            )

        return SceneFusionSaveResponse(
            status="saved",
            source_scene_ids=source_ids,
            fused_scene=SceneResponse.model_validate(created),
        )

    async def _get_scene_in_novel(
        self,
        db: AsyncSession,
        novel_id: str,
        scene_id: str,
    ) -> Scene:
        sid = parse_uuid(scene_id, "scene_id")
        nid = parse_uuid(novel_id, "novel_id")
        scene = await self.repo.get(db, sid)
        if scene is None or scene.novel_id != nid:
            raise LookupError("Scene not found")
        return scene

    async def _get_scenes_in_novel(
        self,
        db: AsyncSession,
        novel_id: str,
        scene_ids: list[str],
    ) -> list[Scene]:
        nid = parse_uuid(novel_id, "novel_id")
        parsed_ids = [parse_uuid(scene_id, "scene_id") for scene_id in scene_ids]
        scenes = await self.repo.get_many_for_novel(db, nid, parsed_ids)
        scene_by_id: dict[uuid.UUID, Scene] = {scene.id: scene for scene in scenes}
        if len(scene_by_id) != len(set(parsed_ids)):
            raise LookupError("Scene not found")
        return [scene_by_id[scene_id] for scene_id in parsed_ids]

    async def _load_current_suggestion(
        self,
        db: AsyncSession,
        novel_id: str,
        suggestion_id: str | None,
        source_scene_ids: list[str],
    ) -> SceneFusionSuggestion | None:
        if suggestion_id is None:
            return None
        item = await self._suggestion_repo.get_for_novel(
            db,
            parse_uuid(novel_id, "novel_id"),
            parse_uuid(suggestion_id, "suggestion_id"),
        )
        if item is None:
            raise LookupError("Scene fusion suggestion not found")
        if item.status != "pending":
            raise ValueError("Scene fusion suggestion is already processed")
        if list(item.source_scene_ids or []) != source_scene_ids:
            raise ValueError("Scene fusion suggestion sources do not match")
        if not await self._suggestion_is_current(db, item):
            raise ValueError("Scene fusion suggestion is stale")
        return item

    async def _load_merge_scenes(
        self,
        db: AsyncSession,
        novel_id: str,
        data: SceneMergeRequest,
    ) -> tuple[Scene, list[Scene]]:
        scenes = await self._get_scenes_in_novel(
            db,
            novel_id,
            [data.target_scene_id, *data.source_scene_ids],
        )
        target, sources = scenes[0], scenes[1:]
        if any(source.id == target.id for source in sources):
            raise ValueError("source_scene_ids cannot include target_scene_id")
        return target, sources

    async def _load_fusion_scenes(
        self,
        db: AsyncSession,
        novel_id: str,
        source_scene_ids: list[str],
    ) -> list[Scene]:
        if len(set(source_scene_ids)) != len(source_scene_ids):
            raise ValueError("source_scene_ids cannot contain duplicates")
        return await self._get_scenes_in_novel(db, novel_id, source_scene_ids)

    async def _fusion_scene_payload(
        self,
        db: AsyncSession,
        novel_id: str,
        sources: list[Scene],
        overrides: SceneFusionDraft | None = None,
        primary_scene_id: str | None = None,
    ) -> dict[str, Any]:
        if not sources:
            raise ValueError("source_scene_ids cannot be empty")
        source_ids = [str(scene.id) for scene in sources]
        ordered_sources = self._primary_first_sources(sources, primary_scene_id)
        payload: dict[str, Any] = {
            "scene_index": await self._next_scene_index(db, novel_id),
            "title": self._fusion_title(ordered_sources),
            "goal": self._join_unique_scene_text(ordered_sources, "goal"),
            "core_conflict": self._join_unique_scene_text(
                ordered_sources,
                "core_conflict",
            ),
            "emotional_beat": self._join_unique_scene_text(
                ordered_sources,
                "emotional_beat",
            ),
            "must_happen": self._join_unique_scene_text(ordered_sources, "must_happen"),
            "must_not_happen": self._join_unique_scene_text(
                ordered_sources,
                "must_not_happen",
            ),
            "narrative_tag": ordered_sources[0].narrative_tag or "draft",
            "source": "manual_fusion",
            "scene_chunks": self._merge_chunks(
                *[source.scene_chunks or [] for source in ordered_sources]
            ),
            "chapter_ids": self._merge_chapter_ids(
                *[source.chapter_ids or [] for source in ordered_sources]
            ),
            "pov_character_id": self._first_non_empty(
                ordered_sources,
                "pov_character_id",
            ),
            "structure_meta": {
                "fused_from_scene_ids": source_ids,
                "fusion_kind": "llm_scene_workbench",
                "fusion_strategy": "author_reviewed_preview",
                "needs_review": True,
            },
            "status": "draft",
        }
        if overrides is not None:
            override_values = overrides.model_dump(exclude_unset=True)
            override_meta = override_values.pop("structure_meta", None)
            has_narrative_function = "narrative_function" in override_values
            narrative_function = override_values.pop("narrative_function", None)
            if has_narrative_function:
                override_meta = {
                    **dict(override_meta or {}),
                    "narrative_function": narrative_function,
                }
            for field, value in override_values.items():
                if field in {
                    "title",
                    "goal",
                    "core_conflict",
                    "emotional_beat",
                    "must_happen",
                    "must_not_happen",
                    "narrative_tag",
                } or value is not None:
                    payload[field] = value
            if override_meta is not None:
                meta = dict(payload["structure_meta"])
                meta.update(override_meta)
                payload["structure_meta"] = meta
        payload["status"] = "draft"
        payload["source"] = payload.get("source") or "manual_fusion"
        payload["structure_meta"] = {
            **dict(payload.get("structure_meta") or {}),
            "fused_from_scene_ids": source_ids,
            **({"primary_scene_id": primary_scene_id} if primary_scene_id else {}),
        }
        return payload

    def _primary_first_sources(
        self,
        sources: list[Scene],
        primary_scene_id: str | None,
    ) -> list[Scene]:
        if primary_scene_id is None:
            return sources
        for scene in sources:
            if str(scene.id) == primary_scene_id:
                return [scene, *[source for source in sources if source.id != scene.id]]
        raise ValueError("primary_scene_id must be one of source_scene_ids")

    async def _validate_fusion_override_chapters(
        self,
        db: AsyncSession,
        novel_id: str,
        overrides: SceneFusionDraft | None,
    ) -> None:
        if overrides is None:
            return
        override_values = overrides.model_dump(exclude_unset=True)
        if "chapter_ids" not in override_values and "scene_chunks" not in override_values:
            return
        if not await list_chapter_indices(db, novel_id):
            return
        await self._validate_mapping_chapters(
            db,
            novel_id,
            override_values.get("chapter_ids"),
            override_values.get("scene_chunks"),
        )

    async def _next_scene_index(self, db: AsyncSession, novel_id: str) -> int:
        nid = parse_uuid(novel_id, "novel_id")
        scenes = await self.repo.get_by_novel_ordered(
            db,
            nid,
        )
        deprecated_scenes = await self.repo.get_by_novel_ordered(
            db,
            nid,
            status="deprecated",
        )
        all_scenes = [*scenes, *deprecated_scenes]
        if not all_scenes:
            return 0
        return max(scene.scene_index for scene in all_scenes) + 1

    def _fusion_title(self, sources: list[Scene]) -> str:
        titles = [scene.title for scene in sources if scene.title]
        if not titles:
            return "融合 Scene"
        joined = " / ".join(titles)
        return f"融合：{joined}"[:255]

    def _join_unique_scene_text(self, scenes: list[Scene], field: str) -> str | None:
        values: list[str] = []
        seen: set[str] = set()
        for scene in scenes:
            value = getattr(scene, field)
            if value and value not in seen:
                seen.add(value)
                values.append(value)
        if not values:
            return None
        return "\n\n".join(values)

    async def _validate_mapping_chapters(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_ids: list[str] | None,
        scene_chunks: list[dict] | None,
    ) -> None:
        if chapter_ids is None and scene_chunks is None:
            return
        known_chapters = set(await list_chapter_indices(db, novel_id))
        if chapter_ids is not None:
            for chapter_id in chapter_ids:
                chapter_index = self._coerce_chapter_index(chapter_id, "chapter_ids")
                if chapter_index not in known_chapters:
                    raise ValueError(f"Chapter {chapter_index} is not in this novel")
        if scene_chunks is not None:
            for chunk in scene_chunks:
                chapter_ref = chunk.get("chapter_index")
                if chapter_ref is None:
                    chapter_ref = chunk.get("chapter_id")
                chapter_index = self._coerce_chapter_index(
                    chapter_ref,
                    "scene_chunks",
                )
                if chapter_index not in known_chapters:
                    raise ValueError(
                        f"Chunk chapter {chapter_index} is not in this novel"
                    )
                if chunk.get("chapter_id") is not None:
                    chunk_id = self._coerce_chapter_index(
                        chunk.get("chapter_id"),
                        "scene_chunks.chapter_id",
                    )
                    if chunk_id != chapter_index:
                        raise ValueError(
                            "scene_chunks chapter_id and chapter_index mismatch"
                        )

    def _coerce_chapter_index(self, value: Any, field: str) -> int:
        if value is None or not str(value).isdigit():
            raise ValueError(f"{field} must use numeric chapter indexes")
        return int(value)

    def _duplicate_scene_chapter_ids(self, scenes: list[Scene]) -> set[str]:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for scene in scenes:
            for chapter_id in {str(cid) for cid in scene.chapter_ids or []}:
                if chapter_id in seen:
                    duplicates.add(chapter_id)
                else:
                    seen.add(chapter_id)
        return duplicates

    def _scene_health(
        self,
        scene: Scene,
        duplicate_chapter_ids: set[str] | None = None,
    ) -> list[str]:
        del duplicate_chapter_ids
        details = self._scene_health_details(
            scene,
            [],
            [],
            set(),
        )
        return self._health_keys(scene, details)

    def _health_keys(
        self,
        scene: Scene | SceneWorkbenchHealthProjection,
        details: dict[str, list[SceneHealthReason]],
    ) -> list[str]:
        health: list[str] = []
        meta = scene.structure_meta or {}
        if meta.get("needs_review") or (
            scene.source in {"deep_import", "ai_generated"}
            and scene.status in {"draft", "candidate"}
            and not meta.get("reviewed_at")
        ):
            health.append("unreviewed")
        chapter_ids = scene.chapter_ids or []
        if not chapter_ids and meta.get("planning_state") != "planned":
            health.append("unassigned")
        if scene_has_missing_setup(scene):
            health.append("missing_setup")
        if details.get("needs_organize"):
            health.append("needs_organize")
        return health

    def _scene_health_details(
        self,
        scene: Scene | SceneWorkbenchHealthProjection,
        spans: list[SceneSpan],
        suggestions: list[SceneFusionSuggestion],
        overlapping_span_chapters: set[int],
    ) -> dict[str, list[SceneHealthReason]]:
        reasons: list[SceneHealthReason] = []
        meta = scene.structure_meta or {}
        chapter_ids = scene.chapter_ids or []
        if meta.get("needs_organize"):
            reasons.append(self._health_reason("manual_organize"))
        if len(chapter_ids) != len(set(chapter_ids)):
            reasons.append(self._health_reason("duplicate_chapter"))
        if overlapping_span_chapters:
            reasons.append(
                self._health_reason(
                    "overlapping_span",
                    chapter_indices=sorted(overlapping_span_chapters),
                )
            )
        chunk_chapters = {
            str(chunk.get("chapter_id") or chunk.get("chapter_index"))
            for chunk in scene.scene_chunks or []
            if chunk.get("chapter_id") is not None
            or chunk.get("chapter_index") is not None
        }
        if chunk_chapters and set(chapter_ids) != chunk_chapters:
            reasons.append(self._health_reason("chunk_chapter_mismatch"))

        if spans:
            fingerprint = self._source_mapping_fingerprint(spans)
            review = meta.get("source_mapping_review") or {}
            if review.get("fingerprint") != fingerprint:
                for status in ("chapter_only", "unresolved"):
                    matching = [span for span in spans if span.mapping_status == status]
                    if not matching:
                        continue
                    reasons.append(
                        self._health_reason(
                            f"source_mapping_{status}",
                            count=len(matching),
                            chapter_indices=sorted(
                                {span.chapter_index for span in matching}
                            ),
                            fingerprint=fingerprint,
                        )
                    )

        for suggestion in suggestions:
            reasons.append(
                self._health_reason(
                    "pending_scene_fusion_suggestion",
                    chapter_indices=[
                        int(value)
                        for value in suggestion.chapter_span or []
                        if str(value).isdigit()
                    ],
                    suggestion_id=str(suggestion.id),
                )
            )
        return {"needs_organize": reasons} if reasons else {}

    @staticmethod
    def _overlapping_span_chapters(
        spans: list[SceneSpan],
    ) -> dict[uuid.UUID, set[int]]:
        return SceneWorkbenchService._overlap_chapters(
            SceneWorkbenchService._overlapping_span_pairs(spans)
        )

    @staticmethod
    def _overlapping_span_pairs(
        spans: list[SceneSpan],
    ) -> list[tuple[SceneSpan, SceneSpan, int, int]]:
        by_source: dict[tuple[int, str], list[SceneSpan]] = defaultdict(list)
        for span in spans:
            if (
                span.start_offset is None
                or span.end_offset is None
                or span.mapping_status not in {"exact", "reanchored"}
            ):
                continue
            source_key = (
                f"hash:{span.source_content_hash}"
                if span.source_content_hash
                else (f"draft:{span.source_draft_id}" if span.source_draft_id else None)
            )
            if source_key is None:
                continue
            by_source[(span.chapter_index, source_key)].append(span)
        overlaps: list[tuple[SceneSpan, SceneSpan, int, int]] = []
        for (chapter_index, _source_key), chapter_spans in by_source.items():
            ordered = sorted(
                chapter_spans,
                key=lambda item: (item.start_offset or 0, item.end_offset or 0),
            )
            for index, left in enumerate(ordered):
                for right in ordered[index + 1 :]:
                    if (right.start_offset or 0) >= (left.end_offset or 0):
                        break
                    if left.scene_id == right.scene_id:
                        continue
                    overlaps.append(
                        (
                            left,
                            right,
                            max(left.start_offset or 0, right.start_offset or 0),
                            min(left.end_offset or 0, right.end_offset or 0),
                        )
                    )
        return overlaps

    @staticmethod
    def _overlap_chapters(
        pairs: list[tuple[SceneSpan, SceneSpan, int, int]],
    ) -> dict[uuid.UUID, set[int]]:
        chapters: dict[uuid.UUID, set[int]] = defaultdict(set)
        for left, right, _overlap_start, _overlap_end in pairs:
            chapters[left.scene_id].add(left.chapter_index)
            chapters[right.scene_id].add(right.chapter_index)
        return chapters

    def _overlap_details(
        self,
        pairs: list[tuple[SceneSpan, SceneSpan, int, int]],
        identities: dict[uuid.UUID, SceneIdentityProjection],
    ) -> dict[uuid.UUID, list[SceneSpanOverlapDetail]]:
        details: dict[uuid.UUID, list[SceneSpanOverlapDetail]] = defaultdict(list)
        for left, right, overlap_start, overlap_end in pairs:
            details[left.scene_id].append(
                self._overlap_detail(left, right, overlap_start, overlap_end, identities)
            )
            details[right.scene_id].append(
                self._overlap_detail(right, left, overlap_start, overlap_end, identities)
            )
        for scene_details in details.values():
            scene_details.sort(
                key=lambda item: (
                    item.chapter_index,
                    item.overlap_start_offset,
                    item.overlap_end_offset,
                    item.counterpart_scene_label,
                    item.counterpart_scene_id,
                )
            )
        return details

    def _overlap_detail(
        self,
        scene_span: SceneSpan,
        counterpart_span: SceneSpan,
        overlap_start: int,
        overlap_end: int,
        identities: dict[uuid.UUID, SceneIdentityProjection],
    ) -> SceneSpanOverlapDetail:
        identity = identities.get(counterpart_span.scene_id)
        normalized_title = identity.title.strip() if identity and identity.title else ""
        title = normalized_title or None
        label = title or (
            f"Scene {identity.scene_index + 1}" if identity else "未命名 Scene"
        )
        return SceneSpanOverlapDetail(
            counterpart_scene_id=str(counterpart_span.scene_id),
            counterpart_scene_title=title,
            counterpart_scene_label=label,
            chapter_index=scene_span.chapter_index,
            scene_start_offset=int(scene_span.start_offset or 0),
            scene_end_offset=int(scene_span.end_offset or 0),
            counterpart_start_offset=int(counterpart_span.start_offset or 0),
            counterpart_end_offset=int(counterpart_span.end_offset or 0),
            overlap_start_offset=overlap_start,
            overlap_end_offset=overlap_end,
            range_label=(
                f"第 {scene_span.chapter_index} 章 · "
                f"字符 {overlap_start}–{overlap_end} 与「{label}」重叠"
            ),
        )

    def _span_summaries(self, spans: list[SceneSpan]) -> list[SceneSpanSummary]:
        ordered = sorted(
            spans,
            key=lambda span: (
                span.chapter_index,
                span.start_offset if span.start_offset is not None else 10**12,
                span.start_paragraph if span.start_paragraph is not None else 10**12,
                span.part_no,
            ),
        )
        return [self._span_summary(span) for span in ordered]

    def _span_summary(self, span: SceneSpan) -> SceneSpanSummary:
        status_label = MAPPING_STATUS_LABELS.get(span.mapping_status, "待确认")
        range_parts = [f"第 {span.chapter_index} 章"]
        if span.start_offset is not None and span.end_offset is not None:
            range_parts.append(f"字符 {span.start_offset}–{span.end_offset}")
        elif span.start_paragraph is not None:
            paragraph_start = span.start_paragraph + 1
            if span.end_paragraph is None:
                range_parts.append(f"第 {paragraph_start} 段起")
            else:
                range_parts.append(f"第 {paragraph_start}–{span.end_paragraph + 1} 段")
        else:
            range_parts.append("整章范围待确认")
        range_parts.append(status_label)
        anchor = " ".join((span.anchor_excerpt or "").split()) or None
        if anchor and len(anchor) > _ANCHOR_SUMMARY_LIMIT:
            anchor = f"{anchor[:_ANCHOR_SUMMARY_LIMIT].rstrip()}…"
        return SceneSpanSummary(
            chapter_index=span.chapter_index,
            content_mode=span.content_mode,
            part_no=span.part_no,
            mapping_status=span.mapping_status,
            mapping_status_label=status_label,
            start_offset=span.start_offset,
            end_offset=span.end_offset,
            start_paragraph=span.start_paragraph,
            end_paragraph=span.end_paragraph,
            anchor_excerpt=anchor,
            range_label=" · ".join(range_parts),
        )

    def _health_reason(
        self,
        code: str,
        *,
        count: int = 1,
        chapter_indices: list[int] | None = None,
        fingerprint: str | None = None,
        suggestion_id: str | None = None,
    ) -> SceneHealthReason:
        return SceneHealthReason(
            code=code,
            label=HEALTH_REASON_LABELS[code],
            count=count,
            chapter_indices=chapter_indices or [],
            fingerprint=fingerprint,
            suggestion_id=suggestion_id,
        )

    def _source_mapping_fingerprint(self, spans: list[SceneSpan]) -> str:
        payload = [
            {
                "content_mode": span.content_mode,
                "part_no": span.part_no,
                "chapter_index": span.chapter_index,
                "mapping_status": span.mapping_status,
                "source_draft_id": (
                    str(span.source_draft_id) if span.source_draft_id else None
                ),
                "source_content_hash": span.source_content_hash,
                "start_offset": span.start_offset,
                "end_offset": span.end_offset,
                "anchor_hash": span.anchor_hash,
            }
            for span in sorted(
                spans,
                key=lambda item: (item.content_mode, item.part_no, item.chapter_index),
            )
        ]
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    async def _active_pending_suggestions(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        use_source_projections: bool = False,
    ) -> list[SceneFusionSuggestion]:
        return await self._current_fusion_suggestions(
            db,
            novel_id,
            statuses=("pending",),
            use_source_projections=use_source_projections,
        )

    async def _current_fusion_suggestions(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        statuses: tuple[str, ...],
        use_source_projections: bool = False,
    ) -> list[SceneFusionSuggestion]:
        candidates = await self._suggestion_repo.list_by_statuses(
            db,
            novel_id,
            statuses=statuses,
            skip=0,
            limit=None,
        )
        parsed_candidates: list[tuple[SceneFusionSuggestion, list[uuid.UUID]]] = []
        source_ids: set[uuid.UUID] = set()
        for item in candidates:
            parsed_ids = self._parse_suggestion_source_ids(item)
            if parsed_ids is None:
                continue
            parsed_candidates.append((item, parsed_ids))
            source_ids.update(parsed_ids)
        if not parsed_candidates:
            return []

        if use_source_projections:
            scenes = await self.repo.get_suggestion_source_projections(
                db,
                novel_id,
                list(source_ids),
            )
        else:
            scenes = await self.repo.get_many_for_novel(
                db,
                novel_id,
                list(source_ids),
            )
        scene_by_id = {scene.id: scene for scene in scenes}
        return [
            item
            for item, parsed_ids in parsed_candidates
            if self._suggestion_sources_are_current(item, parsed_ids, scene_by_id)
        ]

    async def _suggestion_is_current(
        self,
        db: AsyncSession,
        item: SceneFusionSuggestion,
    ) -> bool:
        parsed_ids = self._parse_suggestion_source_ids(item)
        if parsed_ids is None:
            return False
        scenes = await self.repo.get_many_for_novel(db, item.novel_id, parsed_ids)
        scene_by_id = {scene.id: scene for scene in scenes}
        return self._suggestion_sources_are_current(item, parsed_ids, scene_by_id)

    @staticmethod
    def _parse_suggestion_source_ids(
        item: SceneFusionSuggestion,
    ) -> list[uuid.UUID] | None:
        try:
            parsed_ids = [uuid.UUID(str(value)) for value in item.source_scene_ids or []]
        except (TypeError, ValueError):
            return None
        minimum = 1 if item.suggestion_kind == "replacement" else 2
        if len(parsed_ids) < minimum or len(set(parsed_ids)) != len(parsed_ids):
            return None
        return parsed_ids

    def _suggestion_sources_are_current(
        self,
        item: SceneFusionSuggestion,
        source_ids: list[uuid.UUID],
        scene_by_id: dict[uuid.UUID, Scene | SceneSuggestionSourceProjection],
    ) -> bool:
        if any(scene_id not in scene_by_id for scene_id in source_ids):
            return False
        ordered = [scene_by_id[scene_id] for scene_id in source_ids]
        if any(scene.status == "deprecated" for scene in ordered):
            return False
        if item.suggestion_kind == "replacement":
            return self._replacement_suggestion_is_current(item, ordered)
        return self._suggestion_source_fingerprint(ordered) == item.source_fingerprint

    @staticmethod
    def _replacement_suggestion_is_current(
        item: SceneFusionSuggestion,
        scenes: list[Scene | SceneSuggestionSourceProjection],
    ) -> bool:
        from modules.outline.scene_replacement import (
            replacement_source_fingerprint,
            replacement_source_scene_fingerprint,
        )

        if any(scene.status == "deprecated" for scene in scenes):
            return False
        proposed = dict(item.proposed_scene or {})
        expected_scene_fingerprint = proposed.get("source_scene_fingerprint")
        if expected_scene_fingerprint != replacement_source_scene_fingerprint(scenes):
            return False
        return item.source_fingerprint == replacement_source_fingerprint(
            scenes,
            proposed,
        )

    def _suggestion_source_fingerprint(
        self,
        scenes: list[Scene | SceneSuggestionSourceProjection],
    ) -> str:
        payload = [
            {
                "id": str(scene.id),
                "title": scene.title,
                "goal": scene.goal,
                "core_conflict": scene.core_conflict,
                "emotional_beat": scene.emotional_beat,
                "must_happen": scene.must_happen,
                "must_not_happen": scene.must_not_happen,
                "narrative_tag": scene.narrative_tag,
                "pov_character_id": scene.pov_character_id,
                "chapter_ids": scene.chapter_ids or [],
                "scene_chunks": scene.scene_chunks or [],
                "semantic_meta": {
                    key: value
                    for key, value in (scene.structure_meta or {}).items()
                    if key
                    in {
                        "semantic_contract_version",
                        "semantic_origin",
                        "semantic_field_statuses",
                        "semantic_uncertain_fields",
                        "narrative_function",
                        "core_conflict_status",
                    }
                },
            }
            for scene in scenes
        ]
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _chapter_range(self, chapter_ids: list[str]) -> str:
        nums = sorted(int(cid) for cid in chapter_ids if str(cid).isdigit())
        if not nums:
            return "未关联章节"
        if len(nums) == 1:
            return f"第 {nums[0]} 章"
        return f"第 {nums[0]}-{nums[-1]} 章"

    def _display_chapter_range(self, scene: Scene) -> str:
        mapped = self._chapter_range(scene.chapter_ids or [])
        if mapped != "未关联章节":
            return mapped
        meta = dict(scene.structure_meta or {})
        if meta.get("planning_state") != "planned":
            return mapped
        planned = meta.get("planned_chapter_range") or {}
        start = planned.get("start")
        end = planned.get("end")
        if isinstance(start, int) and isinstance(end, int):
            return f"计划中 · 第 {start}-{end} 章"
        if isinstance(start, int):
            return f"计划中 · 第 {start} 章起"
        if isinstance(end, int):
            return f"计划中 · 截至第 {end} 章"
        return "计划中"

    def _merge_chapter_ids(self, *chapter_groups: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for group in chapter_groups:
            for chapter_id in group:
                cid = str(chapter_id)
                if cid not in seen:
                    seen.add(cid)
                    result.append(cid)
        return sorted(result, key=self._chapter_sort_key)

    def _merge_chunks(self, *chunk_groups: list[dict]) -> list[dict]:
        chunks = [dict(chunk) for group in chunk_groups for chunk in group]
        precise_chapters = {
            self._chunk_chapter_key(chunk)
            for chunk in chunks
            if self._chunk_has_precise_range(chunk)
        }
        normalized: list[dict] = []
        seen: set[str] = set()
        for chunk in chunks:
            chapter_key = self._chunk_chapter_key(chunk)
            if (
                chapter_key in precise_chapters
                and self._chunk_is_chapter_placeholder(chunk)
            ):
                continue
            fingerprint = json.dumps(
                chunk,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            normalized.append(chunk)
        return sorted(
            normalized,
            key=self._chunk_sort_key,
        )

    def _merge_chunk_precision_warnings(
        self,
        *chunk_groups: list[dict],
    ) -> list[str]:
        chunks = [dict(chunk) for group in chunk_groups for chunk in group]
        precise_chapters = {
            self._chunk_chapter_key(chunk)
            for chunk in chunks
            if self._chunk_has_precise_range(chunk)
        }
        replaced = sorted(
            {
                chapter
                for chunk in chunks
                if (chapter := self._chunk_chapter_key(chunk)) in precise_chapters
                and self._chunk_is_chapter_placeholder(chunk)
            },
            key=self._chapter_sort_key,
        )
        if not replaced:
            return []
        labels = "、".join(f"第 {chapter} 章" for chapter in replaced)
        return [
            f"{labels}同时存在精确正文定位和章节级占位；确认合并后将保留精确定位，移除同章占位。"
        ]

    @staticmethod
    def _chunk_chapter_key(chunk: dict) -> str:
        return str(chunk.get("chapter_index") or chunk.get("chapter_id") or "0")

    @staticmethod
    def _chunk_has_precise_range(chunk: dict) -> bool:
        for start_field, end_field in (
            ("start_offset", "end_offset"),
            ("start_pos", "end_pos"),
        ):
            start = chunk.get(start_field)
            end = chunk.get(end_field)
            if (
                isinstance(start, int)
                and not isinstance(start, bool)
                and isinstance(end, int)
                and not isinstance(end, bool)
                and end > start
            ):
                return True
        return False

    def _chunk_sort_key(self, chunk: dict) -> tuple[int, str, int, int]:
        chapter_key = self._chapter_sort_key(self._chunk_chapter_key(chunk))
        for start_field, end_field in (
            ("start_offset", "end_offset"),
            ("start_pos", "end_pos"),
        ):
            start = chunk.get(start_field)
            end = chunk.get(end_field)
            if (
                isinstance(start, int)
                and not isinstance(start, bool)
                and isinstance(end, int)
                and not isinstance(end, bool)
            ):
                return (*chapter_key, start, end)
        return (*chapter_key, -1, -1)

    @classmethod
    def _chunk_is_chapter_placeholder(cls, chunk: dict) -> bool:
        if cls._chunk_has_precise_range(chunk):
            return False
        if chunk.get("end_paragraph") is not None:
            return False
        if chunk.get("start_paragraph") not in (None, 0):
            return False
        return not any(
            chunk.get(field)
            for field in (
                "source_draft_id",
                "source_content_hash",
                "anchor_hash",
                "anchor_excerpt",
            )
        )

    def _chapter_sort_key(self, value: str) -> tuple[int, str]:
        return (int(value), value) if str(value).isdigit() else (0, str(value))

    def _merge_field_changes(
        self,
        target: Scene,
        sources: list[Scene],
    ) -> dict[str, dict[str, Any]]:
        changes: dict[str, dict[str, Any]] = {}
        for field in (
            "goal",
            "core_conflict",
            "emotional_beat",
            "must_happen",
            "must_not_happen",
            "pov_character_id",
        ):
            before = getattr(target, field)
            inherited = before or self._first_non_empty(sources, field)
            if inherited != before:
                changes[field] = {"before": before, "after": inherited}
        return changes

    def _first_non_empty(self, scenes: list[Scene], field: str) -> Any:
        for scene in scenes:
            value = getattr(scene, field)
            if value:
                return value
        return None

    def _mechanical_fusion_semantic_meta(
        self,
        scenes: list[Scene],
        *,
        resulting_values: dict[str, Any],
    ) -> dict[str, Any]:
        statuses: dict[str, str] = {}
        uncertain_fields: list[str] = []
        conflicts: dict[str, list[str]] = {}
        for field in sorted(SCENE_SEMANTIC_FIELDS):
            if field == "narrative_function":
                values = [
                    str((scene.structure_meta or {}).get(field) or "").strip()
                    for scene in scenes
                ]
                final_value = next((value for value in values if value), None)
            else:
                values = [
                    str(getattr(scene, field, None) or "").strip()
                    for scene in scenes
                ]
                final_value = resulting_values.get(field)
                if field == "narrative_tag":
                    final_value = scenes[0].narrative_tag
            distinct = list(dict.fromkeys(value for value in values if value))
            source_statuses = [
                status
                for scene in scenes
                if (status := scene_semantic_field_status(scene, field)) is not None
            ]
            if len(distinct) > 1:
                status = "uncertain"
                conflicts[field] = distinct
            elif "uncertain" in source_statuses:
                status = "uncertain"
            elif final_value:
                status = "present"
            elif source_statuses and all(
                value == "not_applicable" for value in source_statuses
            ) and len(source_statuses) == len(scenes):
                status = "not_applicable"
            else:
                status = "uncertain"
            statuses[field] = status
            if status == "uncertain":
                uncertain_fields.append(field)
        return {
            "semantic_contract_version": "scene-semantic-state-v2",
            "semantic_origin": "mechanical_fusion",
            "semantic_field_statuses": statuses,
            "semantic_uncertain_fields": uncertain_fields,
            "semantic_basis": "机械融合仅合并映射并按既定优先级选取字段，未做语义综合。",
            "mechanical_fusion_conflicts": conflicts,
            "needs_review": bool(uncertain_fields),
            "core_conflict_status": statuses["core_conflict"],
        }

    @staticmethod
    def _author_reviewed_fusion_semantic_meta(
        payload: dict[str, Any],
        structure_meta: dict[str, Any],
    ) -> dict[str, Any]:
        meta = dict(structure_meta)
        previous_statuses = meta.get("semantic_field_statuses")
        if not isinstance(previous_statuses, dict):
            previous_statuses = {}
        preview_values = meta.get("semantic_preview_values")
        if not isinstance(preview_values, dict):
            preview_values = {}
        statuses: dict[str, str] = {}
        for field in sorted(SCENE_SEMANTIC_FIELDS):
            value = (
                meta.get("narrative_function")
                if field == "narrative_function"
                else payload.get(field)
            )
            changed = field in preview_values and value != preview_values.get(field)
            previous = str(previous_statuses.get(field) or "")
            if changed:
                status = "present" if value not in (None, "") else "not_applicable"
            elif previous in {"present", "not_applicable", "uncertain"}:
                status = previous
            else:
                status = "present" if value not in (None, "") else "uncertain"
            statuses[field] = status
        uncertain_fields = [
            field for field, status in statuses.items() if status == "uncertain"
        ]
        meta.update(
            {
                "semantic_contract_version": "scene-fusion-synthesis-v2",
                "semantic_origin": "author_reviewed_fusion",
                "semantic_field_statuses": statuses,
                "semantic_uncertain_fields": uncertain_fields,
                "core_conflict_status": statuses["core_conflict"],
                "needs_review": bool(uncertain_fields),
            }
        )
        return meta

    def _split_chapter_ids(
        self,
        chapter_ids: list[str],
        split_chapter_index: int,
        split_pos: int | None = None,
    ) -> tuple[list[str], list[str]]:
        keep: list[str] = []
        move: list[str] = []
        found_boundary = False
        for chapter_id in chapter_ids:
            if str(chapter_id).isdigit() and int(chapter_id) == split_chapter_index:
                found_boundary = True
                if split_pos is not None:
                    keep.append(str(chapter_id))
                move.append(str(chapter_id))
            elif str(chapter_id).isdigit() and int(chapter_id) > split_chapter_index:
                move.append(str(chapter_id))
            else:
                keep.append(str(chapter_id))
        if split_pos is not None and not found_boundary:
            raise ValueError(
                "split_chapter_index must exist in chapter_ids for split_pos"
            )
        if not keep or not move:
            raise ValueError("split_chapter_index must split existing chapter_ids")
        return keep, move

    def _split_chunks(
        self,
        chunks: list[dict],
        split_chapter_index: int,
        split_pos: int | None,
    ) -> tuple[list[dict], list[dict]]:
        if not chunks:
            return [], []
        keep: list[dict] = []
        move: list[dict] = []
        boundary_split = False
        for chunk in chunks:
            copied = dict(chunk)
            chapter_index = self._chunk_chapter_index(copied)
            if chapter_index == split_chapter_index and split_pos is not None:
                start_pos = self._coerce_position(copied.get("start_pos", 0), "start_pos")
                end_pos = self._coerce_position(copied.get("end_pos"), "end_pos")
                if start_pos < split_pos < end_pos:
                    keep_part = dict(copied)
                    move_part = dict(copied)
                    keep_part["end_pos"] = split_pos
                    move_part["start_pos"] = split_pos
                    keep.append(keep_part)
                    move.append(move_part)
                    boundary_split = True
                elif end_pos <= split_pos:
                    keep.append(copied)
                elif start_pos >= split_pos:
                    move.append(copied)
                else:
                    raise ValueError("split_pos must be inside boundary chunk range")
            elif chapter_index is not None and chapter_index >= split_chapter_index:
                move.append(copied)
            else:
                keep.append(copied)
        if split_pos is not None and not boundary_split:
            raise ValueError("split_pos must be inside boundary chunk range")
        return keep, move

    def _chunk_chapter_index(self, chunk: dict) -> int | None:
        chapter_ref = chunk.get("chapter_index")
        if chapter_ref is None:
            chapter_ref = chunk.get("chapter_id")
        if chapter_ref is None or not str(chapter_ref).isdigit():
            return None
        return int(chapter_ref)

    def _coerce_position(self, value: Any, field: str) -> int:
        if value is None or not str(value).isdigit():
            raise ValueError(f"{field} must be numeric for split_pos")
        return int(value)

    def _new_split_scene_payload(
        self,
        source: Scene,
        data: SceneSplitRequest,
        chapter_ids: list[str],
        chunks: list[dict],
    ) -> dict[str, Any]:
        return {
            "scene_index": source.scene_index + 1,
            "title": data.new_scene_title or f"{source.title or 'Scene'}（拆分）",
            "narrative_tag": source.narrative_tag or "draft",
            "source": "manual",
            "chapter_ids": chapter_ids,
            "scene_chunks": chunks,
            "pov_character_id": source.pov_character_id,
            "status": data.new_scene_status or "draft",
            "structure_meta": {
                "split_from_scene_id": str(source.id),
                "split_at_chapter_index": data.split_chapter_index,
                "needs_organize": True,
                "needs_review": False,
                "adopted_at": datetime.now(UTC).isoformat(),
                "source": "manual",
            },
        }

    @staticmethod
    def _adopted_structure_meta(
        structure_meta: dict[str, Any] | None,
        *,
        source: str,
    ) -> dict[str, Any]:
        return {
            **dict(structure_meta or {}),
            "needs_review": False,
            "adopted_at": datetime.now(UTC).isoformat(),
            "source": source,
        }

    async def _shift_later_scenes(self, db: AsyncSession, new_scene: Scene) -> None:
        scenes = await self.repo.get_by_novel_ordered(db, new_scene.novel_id)
        for scene in scenes:
            if scene.id != new_scene.id and scene.scene_index >= new_scene.scene_index:
                scene.scene_index += 1
                db.add(scene)

    def _range_from_chapters(self, chapter_ids: list[str]) -> tuple[int, int]:
        nums = sorted(int(cid) for cid in chapter_ids if str(cid).isdigit())
        if not nums:
            return (0, 0)
        return nums[0], nums[-1]

    async def _related_thread_summary(
        self,
        db: AsyncSession,
        novel_id: str,
        start: int,
        end: int,
    ) -> dict[str, Any]:
        if start <= 0 or end <= 0:
            return {"count": 0}
        from modules.outline.services import PlotThreadService

        count = await PlotThreadService().count_by_novel_and_range(
            db, parse_uuid(novel_id, "novel_id"), start, end
        )
        return {"count": count}

    async def _related_foreshadowing_summary(
        self,
        db: AsyncSession,
        novel_id: str,
        start: int,
        end: int,
    ) -> dict[str, Any]:
        if start <= 0 or end <= 0:
            return {"count": 0}
        from modules.outline.foreshadowing_repository import ForeshadowingPlanRepository

        count = await ForeshadowingPlanRepository().count_by_novel_and_range(
            db, parse_uuid(novel_id, "novel_id"), start, end
        )
        return {"count": count}

    async def _related_reveal_summary(
        self,
        db: AsyncSession,
        novel_id: str,
        start: int,
        end: int,
    ) -> dict[str, Any]:
        if start <= 0 or end <= 0:
            return {"count": 0}
        from sqlalchemy import select

        from modules.outline.models import RevealPlan

        nid = parse_uuid(novel_id, "novel_id")
        result = await db.execute(select(RevealPlan).where(RevealPlan.novel_id == nid))
        count = 0
        for plan in result.scalars().all():
            stages = plan.reveal_stages or []
            if any(
                start <= int(stage.get("chapter_index", 0)) <= end for stage in stages
            ):
                count += 1
        return {"count": count}
