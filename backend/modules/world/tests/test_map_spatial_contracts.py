from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from modules.world.map_atlas_schemas import MapAtlasNodeUpdate
from modules.world.map_structure_geometry import (
    affine_transform,
    calculable_features,
    diagnose,
    layout,
    route_key,
)
from modules.world.map_structure_schemas import (
    MapDocument,
    MapImagePlacement,
    MapNodeCreate,
)
from modules.world.project_vocabulary_schemas import VocabularyTraits

_PROJECT_TYPE = "00000000-0000-0000-0000-000000000011"
_TYPE_REVISION = "00000000-0000-0000-0000-000000000012"


def feature(feature_id: str, *, space_id="main"):
    return {
        "id": feature_id,
        "kind": "location",
        "label": feature_id,
        "space_id": space_id,
    }


def test_v1_read_adds_implicit_main_space_without_rewriting_version():
    document = MapDocument.model_validate(
        {"schema_version": 1, "features": [feature("a")]}
    )

    assert document.schema_version == 1
    assert document.spaces == []
    assert document.features[0].space_id == "main"


def test_v2_spaces_are_unique_and_feature_membership_is_checked():
    document = MapDocument.model_validate(
        {
            "schema_version": 2,
            "spaces": [
                {"id": "main", "label": "主世界"},
                {"id": "dream", "label": "梦境"},
            ],
            "features": [feature("a", space_id="dream")],
        }
    )
    assert [space.id for space in document.spaces] == ["main", "dream"]

    with pytest.raises(ValidationError, match="missing space"):
        MapDocument.model_validate(
            {
                "schema_version": 2,
                "spaces": [{"id": "main", "label": "主世界"}],
                "features": [feature("a", space_id="dream")],
            }
        )
    with pytest.raises(ValidationError, match="unique"):
        MapDocument.model_validate(
            {
                "schema_version": 2,
                "spaces": [
                    {"id": "main", "label": "主世界"},
                    {"id": "main", "label": "重复"},
                ],
            }
        )


def test_layout_uses_independent_space_frames_and_skips_cross_space_routes():
    document = MapDocument.model_validate(
        {
            "schema_version": 2,
            "spaces": [
                {"id": "main", "label": "主世界"},
                {"id": "dream", "label": "梦境"},
            ],
            "features": [
                feature("main-place"),
                feature("dream-entry", space_id="dream"),
                feature("dream-west", space_id="dream"),
            ],
            "constraints": [
                {
                    "id": "portal",
                    "subject": "main-place",
                    "relation": "connects",
                    "target": "dream-entry",
                    "type_ref": _PROJECT_TYPE,
                    "type_revision_id": _TYPE_REVISION,
                },
                {
                    "id": "east-link",
                    "subject": "dream-entry",
                    "relation": "east",
                    "target": "dream-west",
                },
            ],
        }
    )

    result = layout(document).document
    by_id = {item.id: item for item in result.features}
    without_portal = MapDocument.model_validate(
        document.model_dump(mode="json")
        | {
            "constraints": [
                item.model_dump(mode="json") for item in document.constraints[1:]
            ]
        }
    )
    without_portal_result = layout(without_portal).document
    without_portal_by_id = {item.id: item for item in without_portal_result.features}
    assert {key: item.points for key, item in by_id.items()} == {
        key: item.points for key, item in without_portal_by_id.items()
    }
    assert len(result.features) == 3
    assert by_id["dream-west"].points != by_id["dream-entry"].points


@pytest.mark.parametrize("feature_count", [4, 199, 200])
def test_multispace_layout_retains_local_routes_with_one_global_feature_limit(
    feature_count,
):
    features = [feature("a"), feature("b")]
    features += [feature("c", space_id="dream"), feature("d", space_id="dream")]
    features += [feature(f"extra-{index}") for index in range(feature_count - 4)]
    document = MapDocument(
        spaces=[{"id": "dream", "label": "梦境"}],
        features=features,
        constraints=[
            {"id": "main-road", "subject": "a", "target": "b", "relation": "connects"},
            {"id": "dream-road", "subject": "c", "target": "d", "relation": "connects"},
        ],
    )
    result = layout(document).document
    routes = [item for item in result.features if item.id.startswith("route:")]
    assert len(routes) == min(2, 200 - feature_count)
    assert len(result.features) <= 200
    by_id = {item.id: item for item in result.features}
    for route in routes:
        assert route.points
        assert {by_id[key].space_id for key in route.depends_on} == {route.space_id}
    assert layout(result).document == result


def test_old_route_is_not_objective_after_its_relation_becomes_a_belief():
    document = layout(
        MapDocument(
            features=[feature("a"), feature("b")],
            constraints=[
                {"id": "road", "subject": "a", "target": "b", "relation": "connects"}
            ],
        )
    ).document
    document.constraints[0].modality = "belief"
    assert route_key("road") not in calculable_features(document)
    assert route_key("road") in {item.id for item in layout(document).document.features}


def test_calibration_cannot_mix_independent_space_coordinates():
    document = MapDocument(
        spaces=[{"id": "dream", "label": "梦境"}],
        features=[
            feature("a") | {"points": [{"x": 0, "y": 0}]},
            feature("b") | {"points": [{"x": 100, "y": 0}]},
            feature("c", space_id="dream") | {"points": [{"x": 0, "y": 100}]},
        ],
    )
    placement = MapImagePlacement(
        page_id="00000000-0000-0000-0000-000000000099",
        role="background",
        anchors=[
            {"feature_id": "a", "image_x": 0, "image_y": 0},
            {"feature_id": "b", "image_x": 1, "image_y": 0},
            {"feature_id": "c", "image_x": 0, "image_y": 1},
        ],
    )
    with pytest.raises(ValueError, match="同一空间"):
        affine_transform(placement, document)


def test_cross_space_relations_need_a_pinned_relation_type_and_no_via():
    base = {
        "schema_version": 2,
        "spaces": [
            {"id": "main", "label": "主世界"},
            {"id": "dream", "label": "梦境"},
        ],
        "features": [feature("a"), feature("b", space_id="dream")],
    }
    with pytest.raises(ValidationError, match="cross-space"):
        MapDocument.model_validate(
            {
                **base,
                "constraints": [
                    {
                        "id": "portal",
                        "subject": "a",
                        "relation": "connects",
                        "target": "b",
                    }
                ],
            }
        )

    typed = MapDocument.model_validate(
        {
            **base,
            "constraints": [
                {
                    "id": "portal",
                    "subject": "a",
                    "relation": "connects",
                    "target": "b",
                    "type_ref": _PROJECT_TYPE,
                    "type_revision_id": _TYPE_REVISION,
                }
            ],
        }
    )
    assert typed.constraints[0].type_revision_id is not None

    with pytest.raises(ValidationError, match="cross-space"):
        MapDocument.model_validate(
            {
                **base,
                "features": [
                    feature("a"),
                    feature("b", space_id="dream"),
                    feature("via"),
                ],
                "constraints": [
                    {
                        "id": "portal",
                        "subject": "a",
                        "relation": "connects",
                        "target": "b",
                        "via": ["via"],
                        "type_ref": _PROJECT_TYPE,
                        "type_revision_id": _TYPE_REVISION,
                    }
                ],
            }
        )


def test_custom_relation_needs_a_revision_pinned_type():
    base = {
        "schema_version": 2,
        "features": [feature("a"), feature("b")],
        "constraints": [
            {
                "id": "portal",
                "subject": "a",
                "relation": "doorway_to",
                "target": "b",
            }
        ],
    }
    with pytest.raises(ValidationError, match="custom relation"):
        MapDocument.model_validate(base)
    typed = MapDocument.model_validate(
        {
            **base,
            "constraints": [
                {
                    **base["constraints"][0],
                    "type_ref": _PROJECT_TYPE,
                    "type_revision_id": _TYPE_REVISION,
                }
            ],
        }
    )
    assert typed.constraints[0].relation == "doorway_to"


def test_journey_requires_ordered_units_and_a_quoted_source():
    source = {
        "kind": "entity",
        "id": "00000000-0000-0000-0000-000000000021",
        "source_hash": "a" * 64,
        "quote": "乘船一日可到对岸",
    }
    document = MapDocument.model_validate(
        {
            "schema_version": 2,
            "features": [feature("a"), feature("b")],
            "journeys": [
                {
                    "id": "trip",
                    "origin": "a",
                    "destination": "b",
                    "transport_label": "渡船",
                    "duration": {"minimum": 1, "maximum": 2, "unit": "day"},
                    "distance": {"minimum": 5, "maximum": 8, "unit": "里"},
                    "modality": "event_observed",
                    "sources": [source],
                }
            ],
        }
    )
    assert document.journeys[0].duration.unit == "day"
    assert document.journeys[0].distance.unit == "里"

    with pytest.raises(ValidationError, match="minimum"):
        MapDocument.model_validate(
            {
                "schema_version": 2,
                "features": [feature("a"), feature("b")],
                "journeys": [
                    {
                        "id": "trip",
                        "origin": "a",
                        "destination": "b",
                        "transport_label": "渡船",
                        "duration": {"minimum": 3, "maximum": 1, "unit": "day"},
                        "sources": [source],
                    }
                ],
            }
        )
    with pytest.raises(ValidationError, match="quoted evidence or an author decision"):
        MapDocument.model_validate(
            {
                "schema_version": 2,
                "features": [feature("a"), feature("b")],
                "journeys": [
                    {
                        "id": "trip",
                        "origin": "a",
                        "destination": "b",
                        "transport_label": "渡船",
                        "sources": [source | {"quote": ""}],
                    }
                ],
            }
        )


def test_v2_type_reference_requires_pinned_revision_and_known_modality():
    with pytest.raises(ValidationError, match="pin both"):
        MapDocument.model_validate(
            {
                "schema_version": 2,
                "features": [feature("a") | {"type_ref": _PROJECT_TYPE}],
            }
        )


def test_custom_atlas_level_must_pin_and_clear_its_type_revision_as_a_pair():
    with pytest.raises(ValidationError, match="identity and revision"):
        MapNodeCreate(title="街区", level_type_ref=_PROJECT_TYPE)

    with pytest.raises(ValidationError, match="pinned revision"):
        MapAtlasNodeUpdate(
            level_type_ref=_PROJECT_TYPE,
            expected_updated_at="2026-10-15T00:00:00Z",
        )

    update = MapAtlasNodeUpdate(
        level_type_ref=_PROJECT_TYPE,
        level_type_revision_id=_TYPE_REVISION,
        expected_updated_at="2026-10-15T00:00:00Z",
    )
    assert update.level_type_revision_id is not None
    with pytest.raises(ValidationError):
        MapDocument.model_validate(
            {
                "schema_version": 2,
                "features": [feature("a") | {"modality": "rumor"}],
            }
        )


def test_only_pinned_computational_traits_enable_typed_geometry_and_relations():
    feature_ref = UUID(_PROJECT_TYPE)
    feature_revision = UUID(_TYPE_REVISION)
    relation_ref = UUID("00000000-0000-0000-0000-000000000013")
    relation_revision = UUID("00000000-0000-0000-0000-000000000014")
    document = MapDocument.model_validate(
        {
            "schema_version": 2,
            "features": [
                feature("a")
                | {
                    "type_ref": str(feature_ref),
                    "type_revision_id": str(feature_revision),
                },
                feature("b")
                | {
                    "type_ref": str(feature_ref),
                    "type_revision_id": str(feature_revision),
                },
            ],
            "constraints": [
                {
                    "id": "north",
                    "subject": "a",
                    "relation": "north",
                    "target": "b",
                    "type_ref": str(relation_ref),
                    "type_revision_id": str(relation_revision),
                }
            ],
        }
    )

    without_traits = layout(document).document
    assert all(not item.points for item in without_traits.features)

    type_traits = {
        (feature_ref, feature_revision): VocabularyTraits(geometry=["point"]),
        (relation_ref, relation_revision): VocabularyTraits(orientation=["compass"]),
    }
    with_traits = layout(document, type_traits=type_traits)
    positions = {item.id: item.points[0] for item in with_traits.document.features}
    assert positions["a"].y < positions["b"].y
    assert not any(problem.code == "unplaced" for problem in with_traits.problems)


def test_non_event_and_time_scoped_relations_do_not_create_static_conflicts():
    for qualifiers in (
        {"modality": "belief"},
        {
            "effective": {
                "start": {
                    "kind": "scene",
                    "id": "00000000-0000-0000-0000-000000000099",
                }
            }
        },
    ):
        document = MapDocument.model_validate(
            {
                "schema_version": 2,
                "features": [
                    feature("south", space_id="main") | {"points": [{"x": 0, "y": 100}]},
                    feature("north", space_id="main") | {"points": [{"x": 0, "y": 0}]},
                ],
                "constraints": [
                    {
                        "id": "assertion",
                        "subject": "south",
                        "relation": "north",
                        "target": "north",
                        **qualifiers,
                    }
                ],
            }
        )
        assert "direction_conflict" not in {
            problem.code for problem in diagnose(document)
        }


def test_containment_traits_gate_relation_cycles():
    relation_ref = UUID("00000000-0000-0000-0000-000000000041")
    relation_revision = UUID("00000000-0000-0000-0000-000000000042")
    document = MapDocument.model_validate(
        {
            "schema_version": 2,
            "features": [feature("a"), feature("b")],
            "constraints": [
                {
                    "id": "a-in-b",
                    "subject": "a",
                    "relation": "inside",
                    "target": "b",
                    "type_ref": str(relation_ref),
                    "type_revision_id": str(relation_revision),
                },
                {
                    "id": "b-in-a",
                    "subject": "b",
                    "relation": "inside",
                    "target": "a",
                    "type_ref": str(relation_ref),
                    "type_revision_id": str(relation_revision),
                },
            ],
        }
    )

    without_trait = diagnose(document)
    with_trait = diagnose(
        document,
        type_traits={
            (relation_ref, relation_revision): VocabularyTraits(
                containment=["can_contain"]
            )
        },
    )

    assert "containment_cycle" not in {problem.code for problem in without_trait}
    assert "containment_cycle" in {problem.code for problem in with_trait}
