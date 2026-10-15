from __future__ import annotations

from modules.world.map_structure_geometry import affine_transform, geometry_hash
from modules.world.map_structure_schemas import MapDocument, MapImagePlacement

V1_GEOMETRY_HASH = "67bf3630cccb66380e80e50a8828ac48ae39530414ffbdfe71717ad20a12dca9"


def v1_document() -> MapDocument:
    return MapDocument.model_validate(
        {
            "schema_version": 1,
            "features": [
                {
                    "id": "a",
                    "kind": "location",
                    "label": "甲城",
                    "entity_id": "00000000-0000-0000-0000-000000000001",
                    "points": [{"x": 10, "y": 20}],
                    "reader_from_chapter": 1,
                },
                {
                    "id": "b",
                    "kind": "location",
                    "label": "乙城",
                    "points": [{"x": 100, "y": 20}],
                },
                {
                    "id": "c",
                    "kind": "location",
                    "label": "丙城",
                    "points": [{"x": 10, "y": 100}],
                },
            ],
            "constraints": [
                {
                    "id": "route",
                    "subject": "a",
                    "relation": "connects",
                    "target": "b",
                    "path_kind": "road",
                    "path_label": "驿道",
                    "generated_by_task_id": "00000000-0000-0000-0000-000000000002",
                    "sources": [
                        {
                            "kind": "entity",
                            "id": "00000000-0000-0000-0000-000000000003",
                            "source_hash": "a" * 64,
                            "quote": "甲城以北有乙城",
                        }
                    ],
                }
            ],
        }
    )


def test_v1_geometry_hash_is_frozen_and_old_calibration_still_matches() -> None:
    document = v1_document()
    assert geometry_hash(document) == V1_GEOMETRY_HASH

    placement = MapImagePlacement.model_validate(
        {
            "page_id": "00000000-0000-0000-0000-000000000004",
            "role": "background",
            "anchors": [
                {"feature_id": "a", "image_x": 0, "image_y": 0},
                {"feature_id": "b", "image_x": 1, "image_y": 0},
                {"feature_id": "c", "image_x": 0, "image_y": 1},
            ],
            "geometry_hash": V1_GEOMETRY_HASH,
        }
    )
    assert placement.geometry_hash == geometry_hash(document)
    assert len(affine_transform(placement, document)) == 6


def test_v1_geometry_hash_ignores_source_and_task_metadata() -> None:
    document = v1_document()
    document.constraints[0].generated_by_task_id = (
        "00000000-0000-0000-0000-000000000005"
    )
    document.constraints[0].sources[0].source_hash = "b" * 64
    assert geometry_hash(document) == V1_GEOMETRY_HASH
