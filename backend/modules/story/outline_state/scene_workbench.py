"""SceneWorkbenchService core mutations and stable service entry."""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.stable_hash import stable_hash
from modules.story.outline_state.contracts import (
    SCENE_SEMANTIC_FIELDS,
    OutlineAuthorAttentionItemContract,
    scene_semantic_field_status,
)
from modules.story.outline_state.models import Scene, SceneFusionSuggestion, SceneSpan
from modules.story.outline_state.repositories import (
    SceneFusionSuggestionRepository,
    SceneRepository,
)
from modules.story.outline_state.scene_draft_review import (
    SceneDraftReviewService,
    mapping_scope_warnings,
)
from modules.story.outline_state.scene_fusion_draft import SceneFusionDraftGenerator
from modules.story.outline_state.schemas import (
    SceneChapterQuickCreate,
    SceneCreate,
    SceneFusionSuggestionSummary,
    SceneHealthSummary,
    SceneImpactPreview,
    SceneMappingUpdate,
    SceneMergeRequest,
    SceneProgressSummary,
    SceneResponse,
    SceneReviewRequest,
    SceneReviewResponse,
    SceneSourceMappingReviewRequest,
    SceneSourceMappingReviewResponse,
    SceneSplitRequest,
    SceneUpdate,
    SceneWorkbenchItem,
    SceneWorkbenchResponse,
)
from modules.story.outline_state.services import SceneService
from modules.writing.facade import (
    list_chapter_indices,
    list_effective_chapter_indices,
)
from shared.utils import parse_uuid

if TYPE_CHECKING:
    pass


from modules.story.outline_state.scene_workbench_fusion import SceneWorkbenchFusionMixin
from modules.story.outline_state.scene_workbench_health import SceneWorkbenchHealthMixin
from modules.story.outline_state.scene_workbench_support import (
    _ANCHOR_SUMMARY_LIMIT as _ANCHOR_SUMMARY_LIMIT,
)
from modules.story.outline_state.scene_workbench_support import (
    _FUSION_DECISION_STATUSES as _FUSION_DECISION_STATUSES,
)
from modules.story.outline_state.scene_workbench_support import (
    CONFIDENCE_BANDS as CONFIDENCE_BANDS,
)
from modules.story.outline_state.scene_workbench_support import (
    HEALTH_DEFS as HEALTH_DEFS,
)
from modules.story.outline_state.scene_workbench_support import (
    HEALTH_REASON_GROUPS as HEALTH_REASON_GROUPS,
)
from modules.story.outline_state.scene_workbench_support import (
    HEALTH_REASON_LABELS as HEALTH_REASON_LABELS,
)
from modules.story.outline_state.scene_workbench_support import (
    MAPPING_STATUS_LABELS as MAPPING_STATUS_LABELS,
)
from modules.story.outline_state.scene_workbench_support import (
    SceneSuggestionConflictError as SceneSuggestionConflictError,
)


class SceneWorkbenchService(SceneWorkbenchHealthMixin, SceneWorkbenchFusionMixin):
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

    async def link_scene_to_chapter(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int,
        scene_id: str,
    ) -> SceneResponse:
        await self._validate_mapping_chapters(
            db,
            novel_id,
            [str(chapter_index)],
            None,
        )
        nid = parse_uuid(novel_id, "novel_id")
        sid = parse_uuid(scene_id, "scene_id")
        scenes = await self.repo.get_many_for_novel(
            db,
            nid,
            [sid],
            for_update=True,
        )
        if not scenes or scenes[0].status not in {"draft", "canonical"}:
            raise LookupError("Scene not found")
        scene = scenes[0]
        meta = {**(scene.structure_meta or {}), "planning_state": "materialized"}
        updated = await self.repo.update(
            db,
            scene.id,
            SceneUpdate(
                chapter_ids=self._merge_chapter_ids(
                    scene.chapter_ids or [],
                    [str(chapter_index)],
                ),
                structure_meta=meta,
            ),
        )
        if updated is None:
            raise LookupError("Scene not found")
        return SceneResponse.model_validate(updated)

    async def create_scene_for_chapter(
        self,
        db: AsyncSession,
        novel_id: str,
        chapter_index: int,
        data: SceneChapterQuickCreate,
    ) -> SceneResponse:
        await self._validate_mapping_chapters(
            db,
            novel_id,
            [str(chapter_index)],
            None,
        )
        nid = parse_uuid(novel_id, "novel_id")
        await self.repo.lock_scene_order(db, nid)
        scene_index = await self._scene_service.get_next_scene_index(db, novel_id)
        scene = await self.repo.create(
            db,
            nid,
            SceneCreate(
                scene_index=scene_index,
                title=data.title,
                source="manual",
                status="draft",
                chapter_ids=[str(chapter_index)],
                structure_meta={"planning_state": "materialized"},
            ),
        )
        return SceneResponse.model_validate(scene)

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

    async def get_author_attention_items(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> tuple[OutlineAuthorAttentionItemContract, ...]:
        """Project active Scene health and fusion decisions without raw ORM data."""
        workbench = await self.get_workbench(db, novel_id, limit=None)
        projected: list[OutlineAuthorAttentionItemContract] = []
        fusion_by_id: dict[str, OutlineAuthorAttentionItemContract] = {}

        for item in workbench.items:
            scene = item.scene
            if scene.status == "deprecated":
                continue
            scene_id = str(scene.id)
            chapters = self.repo.chapter_indices_for_scene(scene)
            chapter_index = min(chapters) if chapters else None
            organize_reasons = item.health_details.get("needs_organize", [])
            non_fusion_reasons = [
                reason
                for reason in organize_reasons
                if reason.code != "pending_scene_fusion_suggestion"
            ]

            for reason in organize_reasons:
                if (
                    reason.code != "pending_scene_fusion_suggestion"
                    or not reason.suggestion_id
                ):
                    continue
                suggestion_id = str(reason.suggestion_id)
                existing = fusion_by_id.get(suggestion_id)
                if existing is not None:
                    fusion_by_id[suggestion_id] = replace(
                        existing,
                        scene_ids=tuple(dict.fromkeys((*existing.scene_ids, scene_id))),
                    )
                    continue
                suggestion_chapter = (
                    min(reason.chapter_indices)
                    if reason.chapter_indices
                    else chapter_index
                )
                fusion_by_id[suggestion_id] = OutlineAuthorAttentionItemContract(
                    key=f"outline:fusion:{suggestion_id}",
                    source_kind="outline_fusion",
                    title="确认 Scene 融合建议",
                    summary="查看相关 Scene，并决定是否融合。",
                    author_action="needs_decision",
                    severity="medium",
                    target_kind="outline_fusion",
                    item_id=suggestion_id,
                    chapter_index=suggestion_chapter,
                    scene_id=scene_id,
                    scene_ids=(scene_id,),
                    suggestion_id=suggestion_id,
                    updated_at=scene.updated_at,
                )

            health = [key for key in item.health if key != "needs_organize"]
            if non_fusion_reasons:
                health.append("needs_organize")
            health = list(dict.fromkeys(health))
            if not health:
                continue
            labels = [HEALTH_DEFS[key] for key in health if key in HEALTH_DEFS]
            scene_label = scene.title or f"Scene {scene.scene_index}"
            projected.append(
                OutlineAuthorAttentionItemContract(
                    key=f"outline:scene-health:{scene_id}",
                    source_kind="outline_scene_health",
                    title=f"检查场景：{scene_label}",
                    summary=f"待处理：{'、'.join(labels)}。",
                    author_action=(
                        "needs_decision" if "unreviewed" in health else "can_improve"
                    ),
                    severity="medium" if "unreviewed" in health else "low",
                    target_kind="outline_scene",
                    item_id=scene_id,
                    chapter_index=chapter_index,
                    scene_id=scene_id,
                    updated_at=scene.updated_at,
                )
            )

        return tuple([*projected, *fusion_by_id.values()])

    async def review_scenes(
        self,
        db: AsyncSession,
        novel_id: str,
        data: SceneReviewRequest,
    ) -> SceneReviewResponse:
        if len(set(data.scene_ids)) != len(data.scene_ids):
            raise ValueError("scene_ids cannot contain duplicates")
        # 逐场景 read-modify-write structure_meta，必须持行锁避免并发 PATCH 丢键
        scenes = await self._get_scenes_in_novel(
            db, novel_id, data.scene_ids, for_update=True
        )
        if any(scene.status == "deprecated" for scene in scenes):
            raise ValueError("Deprecated Scene cannot be reviewed")
        if data.decision == "review_boundary" and any(
            scene.source != "evolution"
            or scene.status != "draft"
            or (scene.structure_meta or {}).get("semantic_origin") != "boundary_only"
            for scene in scenes
        ):
            raise ValueError("只能单独确认自动场景草稿的边界")
        if data.decision == "review_boundary":
            from modules.story.outline_state.review_attention import boundary_fingerprint

            if set(data.boundary_fingerprints) != set(data.scene_ids) or any(
                data.boundary_fingerprints[str(scene.id)] != boundary_fingerprint(scene)
                for scene in scenes
            ):
                raise ValueError("场景边界已变化，请重新查看后确认")
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

        action_at = datetime.now(UTC).isoformat()
        updated_items: list[SceneResponse] = []
        for scene in scenes:
            meta = dict(scene.structure_meta or {})
            if data.decision == "review_boundary":
                meta.update(
                    {
                        "needs_review": False,
                        "boundary_review": {
                            "decision": "confirmed",
                            "reviewed_at": action_at,
                            "reviewed_by": "manual",
                            "source_fingerprint": data.boundary_fingerprints[
                                str(scene.id)
                            ],
                        },
                    }
                )
                update_data = SceneUpdate(structure_meta=meta)
            elif data.decision == "review":
                meta.update(
                    {
                        "needs_review": False,
                        "needs_organize": False,
                        "reviewed_at": action_at,
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
                    reviewed_at=action_at,
                )
                update_data = SceneUpdate(status="canonical", structure_meta=meta)
            elif data.decision == "reopen":
                meta["needs_review"] = True
                for key in (
                    "reviewed_at",
                    "reviewed_by",
                    "reviewed_from",
                    "reviewed_attention_reasons",
                    "boundary_review",
                ):
                    meta.pop(key, None)
                update_data = SceneUpdate(structure_meta=meta)
            elif data.decision == "ignore_structure":
                meta.update(
                    {
                        "organize_ignored": True,
                        "organize_ignored_at": action_at,
                        "organize_ignored_by": "manual",
                    }
                )
                update_data = SceneUpdate(structure_meta=meta)
            else:
                for key in (
                    "organize_ignored",
                    "organize_ignored_at",
                    "organize_ignored_by",
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
            data.chapter_ids if data.chapter_ids is not None else scene.chapter_ids or []
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
        *,
        for_update: bool = False,
    ) -> list[Scene]:
        nid = parse_uuid(novel_id, "novel_id")
        parsed_ids = [parse_uuid(scene_id, "scene_id") for scene_id in scene_ids]
        scenes = await self.repo.get_many_for_novel(
            db, nid, parsed_ids, **({"for_update": True} if for_update else {})
        )
        scene_by_id: dict[uuid.UUID, Scene] = {scene.id: scene for scene in scenes}
        if len(scene_by_id) != len(set(parsed_ids)):
            raise LookupError("Scene not found")
        return [scene_by_id[scene_id] for scene_id in parsed_ids]

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
            for_update=True,
        )
        target, sources = scenes[0], scenes[1:]
        if any(source.id == target.id for source in sources):
            raise ValueError("source_scene_ids cannot include target_scene_id")
        return target, sources

    async def _next_scene_index(self, db: AsyncSession, novel_id: str) -> int:
        nid = parse_uuid(novel_id, "novel_id")
        # scene_index 分配必须与其它创建路径在 scene_order advisory lock 下串行，
        # 否则并发保存会分配到相同索引且无唯一约束兜底
        await self.repo.lock_scene_order(db, nid)
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
        return stable_hash(payload, stringify_unknown=False)

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
            if chapter_key in precise_chapters and self._chunk_is_chapter_placeholder(
                chunk
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
                    str(getattr(scene, field, None) or "").strip() for scene in scenes
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
            elif (
                source_statuses
                and all(value == "not_applicable" for value in source_statuses)
                and len(source_statuses) == len(scenes)
            ):
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
