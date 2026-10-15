from __future__ import annotations

from modules.world.map_structure_review import apply_revision_changes, changed_items
from modules.world.map_structure_schemas import MapDocument

_TYPE_REF = "00000000-0000-0000-0000-000000000031"
_TYPE_REVISION = "00000000-0000-0000-0000-000000000032"


def _feature(feature_id: str, *, space_id: str = "main") -> dict:
    return {
        "id": feature_id,
        "kind": "location",
        "label": feature_id,
        "space_id": space_id,
    }


def test_v2_review_tracks_spaces_and_journeys_and_closes_dependencies():
    baseline = MapDocument.model_validate(
        {
            "schema_version": 1,
            "features": [_feature("origin"), _feature("destination")],
        }
    )
    candidate = MapDocument.model_validate(
        {
            "schema_version": 2,
            "spaces": [
                {"id": "main", "label": "主空间"},
                {"id": "dream", "label": "梦境"},
            ],
            "features": [
                _feature("origin"),
                _feature("destination", space_id="dream"),
            ],
            "journeys": [
                {
                    "id": "portal-trip",
                    "origin": "origin",
                    "destination": "destination",
                    "transport_label": "传送门",
                    "connection_type_ref": _TYPE_REF,
                    "connection_type_revision_id": _TYPE_REVISION,
                    "sources": [
                        {
                            "kind": "entity",
                            "id": "00000000-0000-0000-0000-000000000033",
                            "source_hash": "a" * 64,
                            "quote": "穿过门即可抵达",
                        }
                    ],
                }
            ],
        }
    )

    changes = changed_items(baseline, candidate)
    assert {"space:dream", "journey:portal-trip", "feature:destination"} <= changes

    adopted, applied, expanded = apply_revision_changes(
        baseline, candidate, ["journey:portal-trip"]
    )
    assert adopted.schema_version == 2
    assert {space.id for space in adopted.spaces} == {"main", "dream"}
    assert adopted.journeys[0].id == "portal-trip"
    assert set(applied) == {
        "journey:portal-trip",
        "feature:destination",
        "space:main",
        "space:dream",
    }
    assert set(expanded) == set(applied) - {"journey:portal-trip"}


def test_v2_review_promotes_schema_and_implicitly_restores_default_space():
    baseline = MapDocument.model_validate(
        {"schema_version": 1, "features": [_feature("a")]}
    )
    candidate = MapDocument.model_validate(
        {
            "schema_version": 2,
            "spaces": [{"id": "dream", "label": "梦境"}],
            "features": [_feature("a", space_id="dream")],
        }
    )

    adopted, applied, _ = apply_revision_changes(
        baseline, candidate, ["feature:a"]
    )

    assert adopted.schema_version == 2
    assert {space.id for space in adopted.spaces} == {"main", "dream"}
    assert {feature.space_id for feature in adopted.features} == {"dream"}
    assert "space:dream" in applied
