from __future__ import annotations

import uuid

from modules.world.map_spatial_anchors import resolve_validity
from modules.world.map_structure_schemas import SpatialAnchor, SpatialValidity


def sid(value: int) -> str:
    return str(uuid.UUID(int=value))


def scene(scene_id: int, scene_index: int, *, status="canonical", **extra):
    return {
        "scene_id": sid(scene_id),
        "scene_index": scene_index,
        "status": status,
        "chapter_ids": [],
        "replaced_by_scene_ids": [],
        **extra,
    }


def test_scene_anchor_resolves_against_current_order_after_reorder():
    start_id, end_id = sid(1), sid(2)
    validity = SpatialValidity(
        start=SpatialAnchor(kind="scene", id=start_id),
        end=SpatialAnchor(kind="scene", id=end_id),
    )
    first_order = [scene(1, 2), scene(2, 5)]
    reordered = [scene(1, 8), scene(2, 3)]

    assert resolve_validity(validity, first_order).valid
    result = resolve_validity(validity, reordered)
    assert not result.valid
    assert result.reason == "spatial_anchor_order_reversed"


def test_replaced_scene_start_uses_earliest_and_end_uses_latest_replacement():
    replaced_id = sid(1)
    validity = SpatialValidity(
        start=SpatialAnchor(kind="scene", id=replaced_id),
        end=SpatialAnchor(kind="scene", id=replaced_id),
    )
    scenes = [
        scene(1, 0, status="deprecated", replaced_by_scene_ids=[sid(2), sid(3)]),
        scene(2, 4),
        scene(3, 9),
    ]

    result = resolve_validity(validity, scenes)
    assert result.valid
    assert (result.start_scene_index, result.end_scene_index) == (4, 9)


def test_missing_scene_anchor_without_replacement_is_pending():
    validity = SpatialValidity(start=SpatialAnchor(kind="scene", id=sid(9)))
    result = resolve_validity(validity, [scene(1, 0)])
    assert not result.valid
    assert result.reason == "scene_anchor_unavailable"


def test_chapter_anchor_requires_stable_chapter_identity():
    chapter_id = sid(10)
    validity = SpatialValidity(
        start=SpatialAnchor(kind="chapter", id=chapter_id),
        end=SpatialAnchor(kind="chapter", id=chapter_id),
    )
    resolved = resolve_validity(
        validity,
        [scene(1, 4, chapter_ids=[chapter_id]), scene(2, 6, chapter_ids=[chapter_id])],
    )
    assert resolved.valid
    assert (resolved.start_scene_index, resolved.end_scene_index) == (4, 6)

    numeric_chapter_id = uuid.UUID(int=11)
    unresolved = resolve_validity(
        SpatialValidity(start=SpatialAnchor(kind="chapter", id=numeric_chapter_id)),
        [scene(3, 7, chapter_ids=["7"])],
    )
    assert not unresolved.valid
    assert unresolved.reason == "chapter_identity_unavailable"
