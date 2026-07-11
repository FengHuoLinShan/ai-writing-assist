from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.models import Scene, SceneCrossChapterSuggestion, SceneSpan
from modules.outline.repositories import (
    SceneCrossChapterSuggestionRepository,
    SceneRepository,
)
from modules.outline.scene_draft_review import SceneDraftReviewService
from modules.outline.schemas import (
    SceneCreate,
    SceneCrossChapterSuggestionDismissRequest,
    SceneCrossChapterSuggestionDismissResponse,
    SceneCrossChapterSuggestionListResponse,
    SceneCrossChapterSuggestionResponse,
    SceneCrossChapterSuggestionSummary,
    SceneFusionDraft,
    SceneFusionPreviewRequest,
    SceneFusionPreviewResponse,
    SceneFusionSaveRequest,
    SceneFusionSaveResponse,
    SceneHealthReason,
    SceneHealthSummary,
    SceneImpactPreview,
    SceneMappingUpdate,
    SceneMergeRequest,
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
from modules.outline.services import SceneService
from modules.writing.facade import list_chapter_indices
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
    "overlapping_chapter": "多个 Scene 关联同一章节",
    "chunk_chapter_mismatch": "章节与正文分段不一致",
    "source_mapping_chapter_only": "正文定位仅精确到章节",
    "source_mapping_unresolved": "正文定位需重新确认",
    "pending_cross_chapter_suggestion": "有跨章融合建议待处理",
}

HEALTH_REASON_GROUPS = {
    "manual_organize": "scene_structure",
    "duplicate_chapter": "scene_structure",
    "overlapping_chapter": "scene_structure",
    "chunk_chapter_mismatch": "scene_structure",
    "source_mapping_chapter_only": "source_mapping",
    "source_mapping_unresolved": "source_mapping",
    "pending_cross_chapter_suggestion": "cross_chapter_suggestion",
}

CONFIDENCE_BANDS = {"low", "medium", "high"}


class SceneWorkbenchService:
    def __init__(self) -> None:
        self.repo = SceneRepository()
        self._suggestion_repo = SceneCrossChapterSuggestionRepository()
        self._scene_service = SceneService()
        self._draft_review_service = SceneDraftReviewService()

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
        skip: int = 0,
        limit: int | None = None,
    ) -> SceneWorkbenchResponse:
        self._validate_filters(
            health=health,
            chapter_from=chapter_from,
            chapter_to=chapter_to,
            confidence_band=confidence_band,
        )
        nid = parse_uuid(novel_id, "novel_id")
        all_matching_scenes = await self.repo.get_by_novel_ordered(
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
            skip=0,
            limit=None,
        )
        all_active_scenes = await self.repo.get_by_novel_ordered(
            db,
            nid,
            skip=0,
            limit=None,
        )
        chapter_indices = await list_chapter_indices(db, novel_id)
        unassigned_chapters = self._unassigned_chapters(
            chapter_indices,
            all_active_scenes,
        )
        duplicate_chapter_ids = self._duplicate_scene_chapter_ids(all_active_scenes)
        span_review_by_scene: dict[uuid.UUID, list[SceneSpan]] = defaultdict(list)
        for span in await self.repo.get_scene_spans_needing_review(db, nid):
            span_review_by_scene[span.scene_id].append(span)
        pending_suggestions = await self._active_pending_suggestions(db, nid)
        suggestions_by_scene: dict[
            uuid.UUID, list[SceneCrossChapterSuggestion]
        ] = defaultdict(list)
        for suggestion in pending_suggestions:
            for raw_scene_id in suggestion.source_scene_ids or []:
                try:
                    suggestions_by_scene[uuid.UUID(str(raw_scene_id))].append(suggestion)
                except (TypeError, ValueError):
                    continue

        details_by_scene = {
            scene.id: self._scene_health_details(
                scene,
                duplicate_chapter_ids,
                span_review_by_scene.get(scene.id, []),
                suggestions_by_scene.get(scene.id, []),
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

        effective_skip = skip
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

        if limit is not None:
            visible_scenes = filtered_scenes[
                effective_skip : effective_skip + limit
            ]
        else:
            visible_scenes = filtered_scenes[effective_skip:]

        items = [
            SceneWorkbenchItem(
                scene=SceneResponse.model_validate(scene),
                health=health_by_scene[scene.id],
                health_details=details_by_scene[scene.id],
                chapter_range=self._chapter_range(scene.chapter_ids or []),
                summary=scene.goal or scene.core_conflict or scene.emotional_beat,
            )
            for scene in visible_scenes
        ]

        counts = {key: 0 for key in HEALTH_DEFS}
        breakdown = {
            "scene_structure": 0,
            "source_mapping": 0,
            "cross_chapter_suggestion": 0,
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
        total = len(all_matching_scenes)
        if health:
            total = counts[health]

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
                unassigned_chapters if health in {None, "unassigned"} else []
            ),
            selected_scene_id=normalized_selected_scene_id,
            cross_chapter_suggestions=SceneCrossChapterSuggestionSummary(
                pending_count=len(pending_suggestions)
            ),
        )

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
        duplicate_chapter_ids: set[str] = set()
        structure_reasons: dict[uuid.UUID, list[str]] = {}
        if data.decision == "review":
            active_scenes = await self.repo.get_by_novel_ordered(
                db,
                parse_uuid(novel_id, "novel_id"),
                skip=0,
                limit=None,
            )
            duplicate_chapter_ids = self._duplicate_scene_chapter_ids(active_scenes)
            for scene in scenes:
                details = self._scene_health_details(
                    scene,
                    duplicate_chapter_ids,
                    [],
                    [],
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

    async def persist_cross_chapter_suggestions(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        source_task_id: str,
        suggestions: list[dict[str, Any]],
    ) -> list[str]:
        nid = parse_uuid(novel_id, "novel_id")
        task_id = parse_uuid(source_task_id, "source_task_id")
        stored_ids: list[str] = []
        for suggestion in suggestions:
            source_ids = [
                str(value)
                for value in suggestion.get("source_scene_ids") or []
            ]
            if len(source_ids) < 2 or len(set(source_ids)) != len(source_ids):
                continue
            scenes = await self._get_scenes_in_novel(db, novel_id, source_ids)
            source_fingerprint = self._suggestion_source_fingerprint(scenes)
            suggestion_key = hashlib.sha256(
                f"{','.join(source_ids)}:{source_fingerprint}".encode()
            ).hexdigest()
            stored = await self._suggestion_repo.upsert_pending(
                db,
                novel_id=nid,
                source_task_id=task_id,
                suggestion_key=suggestion_key,
                source_fingerprint=source_fingerprint,
                payload=suggestion,
            )
            stored_ids.append(str(stored.id))
        return stored_ids

    async def list_cross_chapter_suggestions(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        skip: int = 0,
        limit: int = 50,
    ) -> SceneCrossChapterSuggestionListResponse:
        pending = await self._active_pending_suggestions(
            db,
            parse_uuid(novel_id, "novel_id"),
        )
        visible = pending[skip : skip + limit]
        return SceneCrossChapterSuggestionListResponse(
            items=[
                SceneCrossChapterSuggestionResponse.model_validate(item)
                for item in visible
            ],
            total=len(pending),
        )

    async def dismiss_cross_chapter_suggestions(
        self,
        db: AsyncSession,
        novel_id: str,
        data: SceneCrossChapterSuggestionDismissRequest,
    ) -> SceneCrossChapterSuggestionDismissResponse:
        if not data.confirmed:
            raise PermissionError("dismiss suggestions requires confirmed=true")
        if len(set(data.suggestion_ids)) != len(data.suggestion_ids):
            raise ValueError("suggestion_ids cannot contain duplicates")
        nid = parse_uuid(novel_id, "novel_id")
        items: list[SceneCrossChapterSuggestion] = []
        for raw_id in data.suggestion_ids:
            item = await self._suggestion_repo.get_for_novel(
                db,
                nid,
                parse_uuid(raw_id, "suggestion_id"),
            )
            if item is None:
                raise LookupError("Cross-chapter suggestion not found")
            if item.status != "pending":
                raise ValueError("Cross-chapter suggestion is already processed")
            if not await self._suggestion_is_current(db, item):
                raise ValueError("Cross-chapter suggestion is stale")
            items.append(item)
        for item in items:
            await self._suggestion_repo.mark_status(db, item, status="dismissed")
        return SceneCrossChapterSuggestionDismissResponse(dismissed=len(items))

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
            warnings=["关联资产仅提示，不会自动阻断合并。"],
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
        target_meta["merged_from_scene_ids"] = [str(source.id) for source in sources]
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
        fused_scene = await self._fusion_scene_payload(
            db,
            novel_id,
            sources,
            primary_scene_id=data.primary_scene_id,
        )
        review = self._draft_review_service.build_fusion_review(
            sources=sources,
            primary_scene_id=data.primary_scene_id,
            draft_scene=fused_scene,
            mode="fusion",
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
    ) -> SceneCrossChapterSuggestion | None:
        if suggestion_id is None:
            return None
        item = await self._suggestion_repo.get_for_novel(
            db,
            parse_uuid(novel_id, "novel_id"),
            parse_uuid(suggestion_id, "suggestion_id"),
        )
        if item is None:
            raise LookupError("Cross-chapter suggestion not found")
        if item.status != "pending":
            raise ValueError("Cross-chapter suggestion is already processed")
        if list(item.source_scene_ids or []) != source_scene_ids:
            raise ValueError("Cross-chapter suggestion sources do not match")
        if not await self._suggestion_is_current(db, item):
            raise ValueError("Cross-chapter suggestion is stale")
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
                "fusion_strategy": "local_deterministic_preview",
                "needs_review": True,
            },
            "status": "draft",
        }
        if overrides is not None:
            override_values = overrides.model_dump(exclude_unset=True)
            override_meta = override_values.pop("structure_meta", None)
            for field, value in override_values.items():
                if value is not None:
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
        details = self._scene_health_details(
            scene,
            duplicate_chapter_ids or set(),
            [],
            [],
        )
        return self._health_keys(scene, details)

    def _health_keys(
        self,
        scene: Scene,
        details: dict[str, list[SceneHealthReason]],
    ) -> list[str]:
        health: list[str] = []
        meta = scene.structure_meta or {}
        if (
            meta.get("needs_review")
            or (
                scene.source in {"deep_import", "ai_generated"}
                and scene.status in {"draft", "candidate"}
                and not meta.get("reviewed_at")
            )
        ):
            health.append("unreviewed")
        chapter_ids = scene.chapter_ids or []
        if not chapter_ids:
            health.append("unassigned")
        if any(
            not getattr(scene, field)
            for field in ("goal", "core_conflict", "must_happen", "must_not_happen")
        ):
            health.append("missing_setup")
        if details.get("needs_organize"):
            health.append("needs_organize")
        return health

    def _scene_health_details(
        self,
        scene: Scene,
        duplicate_chapter_ids: set[str],
        spans: list[SceneSpan],
        suggestions: list[SceneCrossChapterSuggestion],
    ) -> dict[str, list[SceneHealthReason]]:
        reasons: list[SceneHealthReason] = []
        meta = scene.structure_meta or {}
        chapter_ids = scene.chapter_ids or []
        if meta.get("needs_organize"):
            reasons.append(self._health_reason("manual_organize"))
        if len(chapter_ids) != len(set(chapter_ids)):
            reasons.append(self._health_reason("duplicate_chapter"))
        overlapping = sorted(
            {
                int(chapter_id)
                for chapter_id in chapter_ids
                if str(chapter_id) in duplicate_chapter_ids
                and str(chapter_id).isdigit()
            }
        )
        if overlapping:
            reasons.append(
                self._health_reason(
                    "overlapping_chapter",
                    chapter_indices=overlapping,
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
                    "pending_cross_chapter_suggestion",
                    chapter_indices=[
                        int(value)
                        for value in suggestion.chapter_span or []
                        if str(value).isdigit()
                    ],
                    suggestion_id=str(suggestion.id),
                )
            )
        return {"needs_organize": reasons} if reasons else {}

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
    ) -> list[SceneCrossChapterSuggestion]:
        pending = await self._suggestion_repo.list_by_status(
            db,
            novel_id,
            status="pending",
            skip=0,
            limit=None,
        )
        active: list[SceneCrossChapterSuggestion] = []
        for item in pending:
            if await self._suggestion_is_current(db, item):
                active.append(item)
        return active

    async def _suggestion_is_current(
        self,
        db: AsyncSession,
        item: SceneCrossChapterSuggestion,
    ) -> bool:
        parsed_ids: list[uuid.UUID] = []
        try:
            parsed_ids = [uuid.UUID(str(value)) for value in item.source_scene_ids or []]
        except (TypeError, ValueError):
            return False
        if len(parsed_ids) < 2 or len(set(parsed_ids)) != len(parsed_ids):
            return False
        scenes = await self.repo.get_many_for_novel(db, item.novel_id, parsed_ids)
        scene_by_id = {scene.id: scene for scene in scenes}
        if len(scene_by_id) != len(parsed_ids):
            return False
        ordered = [scene_by_id[scene_id] for scene_id in parsed_ids]
        if any(scene.status == "deprecated" for scene in ordered):
            return False
        return self._suggestion_source_fingerprint(ordered) == item.source_fingerprint

    def _suggestion_source_fingerprint(self, scenes: list[Scene]) -> str:
        payload = [
            {
                "id": str(scene.id),
                "title": scene.title,
                "goal": scene.goal,
                "core_conflict": scene.core_conflict,
                "emotional_beat": scene.emotional_beat,
                "must_happen": scene.must_happen,
                "must_not_happen": scene.must_not_happen,
                "chapter_ids": scene.chapter_ids or [],
                "scene_chunks": scene.scene_chunks or [],
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

    def _unassigned_chapters(
        self,
        chapter_indices: list[int],
        scenes: list[Scene],
    ) -> list[int]:
        assigned = {
            int(chapter_id)
            for scene in scenes
            for chapter_id in scene.chapter_ids or []
            if str(chapter_id).isdigit()
        }
        return [idx for idx in chapter_indices if idx not in assigned]

    def _chapter_range(self, chapter_ids: list[str]) -> str:
        nums = sorted(int(cid) for cid in chapter_ids if str(cid).isdigit())
        if not nums:
            return "未关联章节"
        if len(nums) == 1:
            return f"第 {nums[0]} 章"
        return f"第 {nums[0]}-{nums[-1]} 章"

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
        return sorted(
            chunks,
            key=lambda chunk: self._chapter_sort_key(
                str(chunk.get("chapter_index") or chunk.get("chapter_id") or "0")
            ),
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
