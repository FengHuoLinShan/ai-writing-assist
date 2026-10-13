"""Shared deterministic contracts and helpers for SceneWorkbenchService."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


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
