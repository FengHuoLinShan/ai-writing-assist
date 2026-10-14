"""scene workbench health operations for SceneWorkbenchService."""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.story.outline_state.models import Scene, SceneFusionSuggestion, SceneSpan
from modules.story.outline_state.repositories import (
    SceneIdentityProjection,
    SceneWorkbenchHealthProjection,
)
from modules.story.outline_state.schemas import (
    SceneHealthReason,
    SceneSpanOverlapDetail,
    SceneSpanSummary,
)
from modules.story.outline_state.services import scene_has_missing_setup
from shared.utils import parse_uuid

if TYPE_CHECKING:
    pass


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


class SceneWorkbenchHealthMixin:
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
        from modules.story.outline_state.review_attention import needs_scene_decision

        if needs_scene_decision(source=scene.source, status=scene.status, meta=meta):
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
        if meta.get("organize_ignored") is True:
            reasons = [
                reason
                for reason in reasons
                if HEALTH_REASON_GROUPS[reason.code] != "scene_structure"
            ]
        return {"needs_organize": reasons} if reasons else {}

    @staticmethod
    def _overlapping_span_chapters(
        spans: list[SceneSpan],
    ) -> dict[uuid.UUID, set[int]]:
        return SceneWorkbenchHealthMixin._overlap_chapters(
            SceneWorkbenchHealthMixin._overlapping_span_pairs(spans)
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

    async def _related_thread_summary(
        self,
        db: AsyncSession,
        novel_id: str,
        start: int,
        end: int,
    ) -> dict[str, Any]:
        if start <= 0 or end <= 0:
            return {"count": 0}
        from modules.story.outline_state.services import PlotThreadService

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
        from modules.story.outline_state.foreshadowing_repository import (
            ForeshadowingPlanRepository,
        )

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

        from modules.story.outline_state.models import RevealPlan

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
