"""Unified Scene draft review payloads for workbench AI-assisted edits."""

from __future__ import annotations

import json
from typing import Any, Literal

from modules.outline.models import Scene
from modules.outline.schemas import (
    SceneDraftConflict,
    SceneDraftReviewResponse,
    SceneFieldReference,
    SceneFusionDraft,
    SceneSourceSummary,
)

REVIEW_FIELDS = (
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
)

SEMANTIC_FIELDS = (
    "title",
    "goal",
    "core_conflict",
    "emotional_beat",
    "must_happen",
    "must_not_happen",
    "narrative_tag",
    "pov_character_id",
)


class SceneDraftReviewService:
    """Build review-ready Scene drafts without mutating formal Scene rows."""

    def build_fusion_review(
        self,
        *,
        sources: list[Scene],
        primary_scene_id: str,
        draft_scene: dict[str, Any],
        mode: Literal["fusion", "fusion_suggestion"] = "fusion",
        confidence: float | None = None,
        reason: str | None = None,
        warnings: list[str] | None = None,
    ) -> SceneDraftReviewResponse:
        if not sources:
            raise ValueError("source_scene_ids cannot be empty")
        source_ids = [str(scene.id) for scene in sources]
        if primary_scene_id not in source_ids:
            raise ValueError("primary_scene_id must be one of source_scene_ids")

        primary = next(scene for scene in sources if str(scene.id) == primary_scene_id)
        normalized_draft = self._review_fusion_draft(
            draft_scene,
            sources=sources,
            primary=primary,
            mode=mode,
        )
        conflicts = self._detect_conflicts(sources)
        field_references = self._field_references(sources, primary_scene_id)
        field_sources = self._field_sources(normalized_draft, field_references)
        review_warnings = list(warnings or [])
        review_warnings.append(
            "当前草稿由确定性融合规则生成；AI 草稿接口已统一，真实 LLM 可在后续接入。"
        )
        return SceneDraftReviewResponse(
            mode=mode,
            source_scene_ids=source_ids,
            primary_scene_id=primary_scene_id,
            draft_scene=SceneFusionDraft(**normalized_draft),
            draft_scenes=[],
            field_references=field_references,
            field_sources=field_sources,
            source_scene_summaries=[self._source_summary(scene) for scene in sources],
            conflicts=conflicts,
            warnings=review_warnings,
            confidence=confidence,
            reason=reason or "以主 Scene 为骨架，合并其他 Scene 的非空字段作为审稿草稿。",
        )

    def build_split_review(
        self,
        *,
        source: Scene,
        keep_scene: dict[str, Any],
        new_scene: dict[str, Any],
        confidence: float | None = None,
        reason: str | None = None,
        warnings: list[str] | None = None,
    ) -> SceneDraftReviewResponse:
        source_id = str(source.id)
        field_references = self._field_references([source], source_id)
        draft_scenes = [
            SceneFusionDraft(**self._split_draft(keep_scene, source=source)),
            SceneFusionDraft(**self._split_draft(new_scene, source=source)),
        ]
        return SceneDraftReviewResponse(
            mode="split",
            source_scene_ids=[source_id],
            primary_scene_id=source_id,
            draft_scene=None,
            draft_scenes=draft_scenes,
            field_references=field_references,
            field_sources={
                field: [source_id] for field in REVIEW_FIELDS if field in field_references
            },
            source_scene_summaries=[self._source_summary(source)],
            conflicts=[],
            warnings=[
                *(warnings or []),
                "拆分草稿保留系统计算的章节映射，语义字段请保存前复核。",
            ],
            confidence=confidence,
            reason=reason or "以原 Scene 为主，按拆分边界生成两个可编辑草稿。",
        )

    def _review_fusion_draft(
        self,
        draft: dict[str, Any],
        *,
        sources: list[Scene],
        primary: Scene,
        mode: str,
    ) -> dict[str, Any]:
        source_ids = [str(scene.id) for scene in sources]
        result = dict(draft)
        result["title"] = result.get("title") or self._fusion_title(sources)
        result["goal"] = (
            result.get("goal")
            or primary.goal
            or self._join_unique(getattr(scene, "goal", None) for scene in sources)
        )
        result["core_conflict"] = (
            result.get("core_conflict")
            or primary.core_conflict
            or self._join_unique(
                getattr(scene, "core_conflict", None) for scene in sources
            )
        )
        result["emotional_beat"] = (
            result.get("emotional_beat")
            or primary.emotional_beat
            or self._join_unique(
                getattr(scene, "emotional_beat", None) for scene in sources
            )
        )
        result["must_happen"] = self._join_unique(
            [primary.must_happen, result.get("must_happen")]
            + [scene.must_happen for scene in sources if scene.id != primary.id]
        )
        result["must_not_happen"] = self._join_unique(
            [primary.must_not_happen, result.get("must_not_happen")]
            + [scene.must_not_happen for scene in sources if scene.id != primary.id]
        )
        result["narrative_tag"] = result.get("narrative_tag") or primary.narrative_tag
        result["pov_character_id"] = (
            result.get("pov_character_id") or primary.pov_character_id
        )
        result["chapter_ids"] = self._merge_chapter_ids(sources)
        result["scene_chunks"] = self._merge_chunks(sources)
        result["source"] = result.get("source") or "manual_fusion"
        result["status"] = "draft"
        result["structure_meta"] = {
            **dict(result.get("structure_meta") or {}),
            "draft_review_mode": mode,
            "primary_scene_id": str(primary.id),
            "fused_from_scene_ids": source_ids,
            "needs_review": True,
        }
        return result

    def _split_draft(self, draft: dict[str, Any], *, source: Scene) -> dict[str, Any]:
        result = dict(draft)
        result["title"] = result.get("title") or f"{source.title or 'Scene'}（拆分）"
        for field in (
            "goal",
            "core_conflict",
            "emotional_beat",
            "must_happen",
            "must_not_happen",
            "narrative_tag",
            "pov_character_id",
        ):
            if result.get(field) is None:
                result[field] = getattr(source, field)
        result["source"] = result.get("source") or "manual"
        result["status"] = result.get("status") or "draft"
        result["structure_meta"] = {
            **dict(result.get("structure_meta") or {}),
            "draft_review_mode": "split",
            "primary_scene_id": str(source.id),
            "needs_review": True,
        }
        return result

    def _field_references(
        self,
        scenes: list[Scene],
        primary_scene_id: str,
    ) -> dict[str, list[SceneFieldReference]]:
        references: dict[str, list[SceneFieldReference]] = {}
        for field in REVIEW_FIELDS:
            field_refs: list[SceneFieldReference] = []
            for scene in scenes:
                value = self._scene_value(scene, field)
                if value in (None, "", [], {}):
                    continue
                field_refs.append(
                    SceneFieldReference(
                        scene_id=str(scene.id),
                        title=scene.title,
                        value=value,
                        role=(
                            "primary" if str(scene.id) == primary_scene_id else "source"
                        ),
                    )
                )
            if field_refs:
                references[field] = field_refs
        return references

    def _field_sources(
        self,
        draft: dict[str, Any],
        references: dict[str, list[SceneFieldReference]],
    ) -> dict[str, list[str]]:
        field_sources: dict[str, list[str]] = {}
        for field, refs in references.items():
            if draft.get(field) in (None, "", [], {}):
                continue
            field_sources[field] = [ref.scene_id for ref in refs]
        return field_sources

    def _source_summary(self, scene: Scene) -> SceneSourceSummary:
        meta = scene.structure_meta or {}
        flags: list[str] = []
        if meta.get("needs_review"):
            flags.append("needs_review")
        if meta.get("phase1a_fallback"):
            flags.append("phase1a_fallback")
        if meta.get("boundary_status"):
            flags.append(str(meta["boundary_status"]))
        if meta.get("confidence") is not None:
            flags.append(f"confidence:{meta['confidence']}")
        return SceneSourceSummary(
            id=str(scene.id),
            title=scene.title,
            chapter_range=self._chapter_range(scene.chapter_ids or []),
            source=scene.source,
            status=scene.status,
            quality_flags=flags,
        )

    def _detect_conflicts(self, scenes: list[Scene]) -> list[SceneDraftConflict]:
        conflicts: list[SceneDraftConflict] = []
        for field in SEMANTIC_FIELDS:
            values = {
                str(self._scene_value(scene, field)).strip()
                for scene in scenes
                if self._scene_value(scene, field) not in (None, "", [], {})
            }
            if len(values) > 1 and field in {"pov_character_id", "narrative_tag"}:
                conflicts.append(
                    SceneDraftConflict(
                        field=field,
                        message=(
                            f"{field} 在来源 Scene 中不一致，草稿默认以主 Scene 为准。"
                        ),
                        source_scene_ids=[str(scene.id) for scene in scenes],
                    )
                )
        return conflicts

    def _scene_value(self, scene: Scene, field: str) -> Any:
        if field == "chapter_ids":
            return scene.chapter_ids or []
        if field == "scene_chunks":
            return scene.scene_chunks or []
        return getattr(scene, field, None)

    def _fusion_title(self, sources: list[Scene]) -> str:
        titles = [scene.title for scene in sources if scene.title]
        if not titles:
            return "融合 Scene"
        return f"融合：{' / '.join(titles)}"[:255]

    def _merge_chapter_ids(self, scenes: list[Scene]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for scene in scenes:
            for chapter_id in scene.chapter_ids or []:
                cid = str(chapter_id)
                if cid not in seen:
                    seen.add(cid)
                    result.append(cid)
        return sorted(result, key=self._chapter_sort_key)

    def _merge_chunks(self, scenes: list[Scene]) -> list[dict[str, Any]]:
        chunks: list[dict[str, Any]] = []
        seen: set[str] = set()
        for scene in scenes:
            for chunk in scene.scene_chunks or []:
                copied = dict(chunk)
                key = json.dumps(copied, sort_keys=True, ensure_ascii=False)
                if key not in seen:
                    seen.add(key)
                    chunks.append(copied)
        return sorted(
            chunks,
            key=lambda chunk: self._chapter_sort_key(
                str(chunk.get("chapter_index") or chunk.get("chapter_id") or "0")
            ),
        )

    def _chapter_range(self, chapter_ids: list[str]) -> str:
        nums = sorted(int(cid) for cid in chapter_ids if str(cid).isdigit())
        if not nums:
            return "未关联章节"
        if len(nums) == 1:
            return f"第 {nums[0]} 章"
        return f"第 {nums[0]}-{nums[-1]} 章"

    def _chapter_sort_key(self, value: str) -> tuple[int, str]:
        return (int(value), value) if str(value).isdigit() else (0, str(value))

    def _join_unique(self, values: Any) -> str | None:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            text = str(value or "").strip()
            if text and text not in seen:
                seen.add(text)
                result.append(text)
        return "\n\n".join(result) if result else None
