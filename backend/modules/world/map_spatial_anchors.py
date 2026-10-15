"""Resolve spatial validity anchors against the current Story scene order."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from modules.world.map_structure_schemas import SpatialAnchor, SpatialValidity

_ACTIVE_SCENE_STATUSES = {"candidate", "draft", "canonical"}
SPATIAL_ANCHOR_PROBLEM_CODES = frozenset(
    {
        "scene_anchor_unavailable",
        "chapter_identity_unavailable",
        "spatial_anchor_order_reversed",
    }
)


@dataclass(frozen=True)
class SpatialValidityResolution:
    start_scene_index: int | None
    end_scene_index: int | None
    valid: bool
    reason: str | None = None


def _active_index(scene: dict[str, Any]) -> int | None:
    index = scene.get("scene_index")
    if scene.get("status") not in _ACTIVE_SCENE_STATUSES or not isinstance(index, int):
        return None
    return index


def _scene_anchor_index(
    scene_id: str, scenes: list[dict[str, Any]], *, endpoint: str
) -> int | None:
    by_id = {str(item.get("scene_id")): item for item in scenes}

    def descendants(
        current_id: str, path: frozenset[str] = frozenset()
    ) -> list[int] | None:
        if current_id in path:
            return None
        path = path | {current_id}
        scene = by_id.get(current_id)
        if scene is None:
            return None
        index = _active_index(scene)
        if index is not None:
            return [index]
        replacement_ids = scene.get("replaced_by_scene_ids") or []
        if not isinstance(replacement_ids, list) or not replacement_ids:
            return None
        candidates = []
        for replacement_id in replacement_ids:
            resolved = descendants(str(replacement_id), path)
            if resolved is None:
                return None
            candidates.extend(resolved)
        return candidates

    candidates = descendants(scene_id)
    if not candidates:
        return None
    return min(candidates) if endpoint == "start" else max(candidates)


def resolve_anchor(
    anchor: SpatialAnchor,
    scenes: list[dict[str, Any]],
    *,
    endpoint: str,
) -> tuple[int | None, str | None]:
    if endpoint not in {"start", "end"}:
        raise ValueError("endpoint must be start or end")
    anchor_id = str(anchor.id)
    if anchor.kind == "scene":
        index = _scene_anchor_index(anchor_id, scenes, endpoint=endpoint)
        return (index, None) if index is not None else (None, "scene_anchor_unavailable")

    matching = [
        index
        for scene in scenes
        if _active_index(scene) is not None
        and anchor_id in {str(value) for value in scene.get("chapter_ids") or []}
        and (index := _active_index(scene)) is not None
    ]
    if not matching:
        return None, "chapter_identity_unavailable"
    return (min(matching) if endpoint == "start" else max(matching)), None


def resolve_validity(
    validity: SpatialValidity, scenes: list[dict[str, Any]]
) -> SpatialValidityResolution:
    start_index = None
    end_index = None
    if validity.start is not None:
        start_index, reason = resolve_anchor(validity.start, scenes, endpoint="start")
        if reason is not None:
            return SpatialValidityResolution(None, None, False, reason)
    if validity.end is not None:
        end_index, reason = resolve_anchor(validity.end, scenes, endpoint="end")
        if reason is not None:
            return SpatialValidityResolution(start_index, None, False, reason)
    if start_index is not None and end_index is not None and start_index > end_index:
        return SpatialValidityResolution(
            start_index, end_index, False, "spatial_anchor_order_reversed"
        )
    return SpatialValidityResolution(start_index, end_index, True)


def validity_problems(document, scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    problems = []
    for feature in document.features:
        if feature.effective is None:
            continue
        result = resolve_validity(feature.effective, scenes)
        if not result.valid:
            problems.append(
                {
                    "code": result.reason or "spatial_anchor_unavailable",
                    "message": "生效范围锚点失效或顺序变化，请核对后再用于空间检查",
                    "feature_ids": [feature.id],
                }
            )
    for constraint in document.constraints:
        if constraint.effective is None:
            continue
        result = resolve_validity(constraint.effective, scenes)
        if not result.valid:
            problems.append(
                {
                    "code": result.reason or "spatial_anchor_unavailable",
                    "message": "生效范围锚点失效或顺序变化，请核对后再用于空间检查",
                    "feature_ids": [constraint.subject, constraint.target],
                }
            )
    for journey in document.journeys:
        if journey.effective is None:
            continue
        result = resolve_validity(journey.effective, scenes)
        if not result.valid:
            problems.append(
                {
                    "code": result.reason or "spatial_anchor_unavailable",
                    "message": "生效范围锚点失效或顺序变化，请核对后再用于空间检查",
                    "feature_ids": [journey.origin, journey.destination],
                }
            )
    return problems
