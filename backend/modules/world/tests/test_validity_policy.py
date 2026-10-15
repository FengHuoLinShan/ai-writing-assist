from __future__ import annotations

from uuid import uuid4

from modules.world.map_declaration_state import map_declaration_subject_id
from modules.world.validity_policy import (
    exact_story_field_observation,
    exact_story_map_declaration_observation,
    exact_story_relation_observation,
    resolve_map_declaration_validity,
)


def _view(
    dimension: str,
    facts: list[dict],
    *,
    novel_id: str | None = None,
    scene_id: str | None = None,
    scene_index: int | None = None,
    dimension_status: str = "ok",
) -> dict:
    result = {
        "dimensions": [
            {"dimension": dimension, "status": dimension_status, "facts": facts}
        ]
    }
    if novel_id is not None:
        result["novel_id"] = novel_id
    if scene_id is not None:
        result["scene_id"] = scene_id
    if scene_index is not None:
        result["scene_index"] = scene_index
    return result


def _map_fact(
    *,
    novel_id: str,
    node_id: str,
    revision_id: str,
    declaration_kind: str = "feature",
    declaration_id: str = "feature:harbor",
    status: str = "active",
    scene_index: int = 2,
    author_confirmed: bool = True,
) -> dict:
    subject_id = map_declaration_subject_id(
        novel_id, node_id, declaration_kind, declaration_id
    )
    identity_ref = {
        "contract_version": 1,
        "novel_id": novel_id,
        "node_id": node_id,
        "revision_id": revision_id,
        "subject_id": subject_id,
        "declaration_kind": declaration_kind,
        "declaration_id": declaration_id,
        "field_key": "effective_status",
    }
    return {
        "subject_id": subject_id,
        "field": "effective_status",
        "value": status,
        "layer": "fact",
        "confidence": "confirmed",
        "occurred_at": {"scene_index": scene_index, "scene_sequence": 1},
        "source": {
            "provenance": {
                "field": "effective_status",
                "object_type": "map_declaration",
                "status": "unverified",
                "event_id": "map-event-1",
                "source_refs": [],
                "author_confirmed": author_confirmed,
                "identity_ref": identity_ref,
            }
        },
    }


def test_custom_field_observation_requires_exact_entity_type_key_and_confirmation() -> (
    None
):
    provenance = {
        "field": "hull_condition",
        "object_type": "airship",
        "status": "unverified",
        "event_id": "event-1",
        "source_refs": [],
        "author_confirmed": True,
    }
    fact = {
        "subject_id": "airship-1",
        "field": "hull_condition",
        "value": "breached",
        "layer": "fact",
        "confidence": "confirmed",
        "occurred_at": {"scene_index": 2},
        "source": {"provenance": provenance},
    }

    observation = exact_story_field_observation(
        _view("entities", [fact]),
        entity_id="airship-1",
        entity_type="airship",
        field_key="hull_condition",
        cutoff_scene_index=3,
    )
    assert observation.value == "breached"
    assert observation.author_confirmed is True
    assert observation.scene_index == 2

    wrong_entity = exact_story_field_observation(
        _view("entities", [fact]),
        entity_id="airship-2",
        entity_type="airship",
        field_key="hull_condition",
        cutoff_scene_index=3,
    )
    wrong_field = exact_story_field_observation(
        _view("entities", [fact]),
        entity_id="airship-1",
        entity_type="airship",
        field_key="drive_condition",
        cutoff_scene_index=3,
    )
    wrong_type = exact_story_field_observation(
        _view("entities", [fact]),
        entity_id="airship-1",
        entity_type="vehicle",
        field_key="hull_condition",
        cutoff_scene_index=3,
    )
    assert wrong_entity.gap == "story_observation_missing"
    assert wrong_field.gap == "story_observation_missing"
    assert wrong_type.gap == "story_alignment_unverified"


def test_custom_field_observation_rejects_derived_and_cutoff_or_future_proof() -> None:
    fact = {
        "subject_id": "airship-1",
        "field": "hull_condition",
        "value": "breached",
        "layer": "fact",
        "confidence": "derived",
        "occurred_at": {"scene_index": 3},
        "source": {
            "provenance": {
                "field": "hull_condition",
                "object_type": "airship",
                "status": "exact",
                "event_id": "event-1",
                "source_refs": [{"source_hash": "a" * 64}],
            }
        },
    }
    observation = exact_story_field_observation(
        _view("entities", [fact]),
        entity_id="airship-1",
        entity_type="airship",
        field_key="hull_condition",
        cutoff_scene_index=3,
    )
    assert observation.gap == "story_observation_unconfirmed"

    fact["confidence"] = "confirmed"
    observation = exact_story_field_observation(
        _view("entities", [fact]),
        entity_id="airship-1",
        entity_type="airship",
        field_key="hull_condition",
        cutoff_scene_index=3,
    )
    assert observation.gap == "story_observation_not_before_cutoff"


def test_relation_observation_requires_same_stable_relation_id() -> None:
    provenance = {
        "field": "relation_status",
        "object_type": "relation",
        "status": "exact",
        "event_id": "event-1",
        "source_refs": [{"source_hash": "b" * 64}],
    }
    fact = {
        "subject_id": "relation-1",
        "field": "relation",
        "value": {
            "id": "relation-1",
            "source_id": "character-a",
            "target_id": "faction-b",
            "relation_type": "alliance",
            "relation_status": "active",
        },
        "confidence": "confirmed",
        "occurred_at": {"scene_index": 4},
        "source": {"field_provenance": {"relation_status": provenance}},
    }

    observation = exact_story_relation_observation(
        _view("relations", [fact]), relation_id="relation-1", cutoff_scene_index=5
    )
    assert observation.status == "active"
    assert observation.event_id == "event-1"

    # Equal endpoints/type do not align a different World relation row.
    mismatched_id = exact_story_relation_observation(
        _view("relations", [fact]), relation_id="another-relation", cutoff_scene_index=5
    )
    assert mismatched_id.gap == "story_observation_missing"


def test_relation_end_observation_is_exact_and_cutoff_bounded() -> None:
    fact = {
        "subject_id": "relation-1",
        "field": "relation_status",
        "value": {
            "id": "relation-1",
            "relation_status": "ended",
        },
        "confidence": "confirmed",
        "occurred_at": {"scene_index": 4},
        "source": {
            "provenance": {
                "field": "relation_status",
                "object_type": "relation",
                "status": "exact",
                "event_id": "event-end",
                "source_refs": [{"source_hash": "c" * 64}],
            }
        },
    }

    observation = exact_story_relation_observation(
        _view("relations", [fact]), relation_id="relation-1", cutoff_scene_index=5
    )
    assert observation.status == "ended"
    assert observation.event_id == "event-end"
    assert (
        exact_story_relation_observation(
            _view("relations", [fact]), relation_id="relation-1", cutoff_scene_index=4
        ).gap
        == "story_observation_not_before_cutoff"
    )


def test_map_observation_requires_exact_project_node_kind_id_and_revision() -> None:
    novel_id, other_novel_id = str(uuid4()), str(uuid4())
    cutoff_scene_id, other_scene_id = str(uuid4()), str(uuid4())
    node_id, other_node_id = str(uuid4()), str(uuid4())
    revision_id, other_revision_id = str(uuid4()), str(uuid4())
    fact = _map_fact(
        novel_id=novel_id,
        node_id=node_id,
        revision_id=revision_id,
    )

    observation = exact_story_map_declaration_observation(
        _view(
            "entities", [fact], novel_id=novel_id, scene_id=cutoff_scene_id, scene_index=3
        ),
        novel_id=novel_id,
        cutoff_scene_id=cutoff_scene_id,
        node_id=node_id,
        revision_id=revision_id,
        declaration_kind="feature",
        declaration_id="feature:harbor",
        cutoff_scene_index=3,
    )
    assert observation.status == "active"
    assert observation.author_confirmed is True
    assert observation.event_id == "map-event-1"
    assert (
        exact_story_map_declaration_observation(
            _view(
                "entities",
                [fact],
                novel_id=novel_id,
                scene_id=cutoff_scene_id,
                scene_index=3,
            ),
            novel_id=novel_id,
            cutoff_scene_id=other_scene_id,
            node_id=node_id,
            revision_id=revision_id,
            declaration_kind="feature",
            declaration_id="feature:harbor",
            cutoff_scene_index=3,
        ).gap
        == "story_view_scene_mismatch"
    )
    assert (
        exact_story_map_declaration_observation(
            _view(
                "entities",
                [fact],
                novel_id=novel_id,
                scene_id=cutoff_scene_id,
                scene_index=4,
            ),
            novel_id=novel_id,
            cutoff_scene_id=cutoff_scene_id,
            node_id=node_id,
            revision_id=revision_id,
            declaration_kind="feature",
            declaration_id="feature:harbor",
            cutoff_scene_index=3,
        ).gap
        == "story_view_cutoff_mismatch"
    )
    assert (
        exact_story_map_declaration_observation(
            _view(
                "entities",
                [fact],
                novel_id=novel_id,
                scene_id=cutoff_scene_id,
                scene_index=3,
                dimension_status="degraded",
            ),
            novel_id=novel_id,
            cutoff_scene_id=cutoff_scene_id,
            node_id=node_id,
            revision_id=revision_id,
            declaration_kind="feature",
            declaration_id="feature:harbor",
            cutoff_scene_index=3,
        ).gap
        == "story_state_degraded"
    )

    assert (
        exact_story_map_declaration_observation(
            _view(
                "entities",
                [fact],
                novel_id=novel_id,
                scene_id=cutoff_scene_id,
                scene_index=3,
            ),
            novel_id=other_novel_id,
            cutoff_scene_id=cutoff_scene_id,
            node_id=node_id,
            revision_id=revision_id,
            declaration_kind="feature",
            declaration_id="feature:harbor",
            cutoff_scene_index=3,
        ).gap
        == "story_view_project_mismatch"
    )
    assert (
        exact_story_map_declaration_observation(
            _view(
                "entities",
                [fact],
                novel_id=novel_id,
                scene_id=cutoff_scene_id,
                scene_index=3,
            ),
            novel_id=novel_id,
            cutoff_scene_id=cutoff_scene_id,
            node_id=other_node_id,
            revision_id=revision_id,
            declaration_kind="feature",
            declaration_id="feature:harbor",
            cutoff_scene_index=3,
        ).gap
        == "story_observation_missing"
    )
    assert (
        exact_story_map_declaration_observation(
            _view(
                "entities",
                [fact],
                novel_id=novel_id,
                scene_id=cutoff_scene_id,
                scene_index=3,
            ),
            novel_id=novel_id,
            cutoff_scene_id=cutoff_scene_id,
            node_id=node_id,
            revision_id=revision_id,
            declaration_kind="feature",
            declaration_id="feature:other-harbor",
            cutoff_scene_index=3,
        ).gap
        == "story_observation_missing"
    )
    assert (
        exact_story_map_declaration_observation(
            _view(
                "entities",
                [fact],
                novel_id=novel_id,
                scene_id=cutoff_scene_id,
                scene_index=3,
            ),
            novel_id=novel_id,
            cutoff_scene_id=cutoff_scene_id,
            node_id=node_id,
            revision_id=revision_id,
            declaration_kind="constraint",
            declaration_id="feature:harbor",
            cutoff_scene_index=3,
        ).gap
        == "story_observation_missing"
    )
    assert (
        exact_story_map_declaration_observation(
            _view(
                "entities",
                [fact],
                novel_id=novel_id,
                scene_id=cutoff_scene_id,
                scene_index=3,
            ),
            novel_id=novel_id,
            cutoff_scene_id=cutoff_scene_id,
            node_id=node_id,
            revision_id=other_revision_id,
            declaration_kind="feature",
            declaration_id="feature:harbor",
            cutoff_scene_index=3,
        ).gap
        == "story_map_declaration_revision_changed"
    )

    future = _map_fact(
        novel_id=novel_id,
        node_id=node_id,
        revision_id=revision_id,
        scene_index=3,
    )
    assert (
        exact_story_map_declaration_observation(
            _view(
                "entities",
                [future],
                novel_id=novel_id,
                scene_id=cutoff_scene_id,
                scene_index=3,
            ),
            novel_id=novel_id,
            cutoff_scene_id=cutoff_scene_id,
            node_id=node_id,
            revision_id=revision_id,
            declaration_kind="feature",
            declaration_id="feature:harbor",
            cutoff_scene_index=3,
        ).gap
        == "story_observation_not_before_cutoff"
    )

    unconfirmed = _map_fact(
        novel_id=novel_id,
        node_id=node_id,
        revision_id=revision_id,
        author_confirmed=False,
    )
    assert (
        exact_story_map_declaration_observation(
            _view(
                "entities",
                [unconfirmed],
                novel_id=novel_id,
                scene_id=cutoff_scene_id,
                scene_index=3,
            ),
            novel_id=novel_id,
            cutoff_scene_id=cutoff_scene_id,
            node_id=node_id,
            revision_id=revision_id,
            declaration_kind="feature",
            declaration_id="feature:harbor",
            cutoff_scene_index=3,
        ).gap
        == "story_source_unverified"
    )
    legacy = _map_fact(
        novel_id=novel_id,
        node_id=node_id,
        revision_id=revision_id,
    )
    del legacy["source"]["provenance"]["identity_ref"]
    assert (
        exact_story_map_declaration_observation(
            _view(
                "entities",
                [legacy],
                novel_id=novel_id,
                scene_id=cutoff_scene_id,
                scene_index=3,
            ),
            novel_id=novel_id,
            cutoff_scene_id=cutoff_scene_id,
            node_id=node_id,
            revision_id=revision_id,
            declaration_kind="feature",
            declaration_id="feature:harbor",
            cutoff_scene_index=3,
        ).gap
        == "story_alignment_unverified"
    )


def test_map_validity_defaults_to_author_and_overrides_only_with_exact_story_state() -> (
    None
):
    novel_id, node_id, revision_id = str(uuid4()), str(uuid4()), str(uuid4())
    fact = _map_fact(
        novel_id=novel_id,
        node_id=node_id,
        revision_id=revision_id,
        status="active",
    )
    cutoff_scene_id = str(uuid4())
    view = _view(
        "entities", [fact], novel_id=novel_id, scene_id=cutoff_scene_id, scene_index=3
    )
    args = {
        "author_active": False,
        "anchor_gap": None,
        "story_view": view,
        "novel_id": novel_id,
        "cutoff_scene_id": cutoff_scene_id,
        "node_id": node_id,
        "revision_id": revision_id,
        "declaration_kind": "feature",
        "declaration_id": "feature:harbor",
        "cutoff_scene_index": 3,
    }

    author_priority = resolve_map_declaration_validity(**args, allow_story_override=False)
    assert author_priority.status == "author_priority"
    assert author_priority.effective is False

    story_override = resolve_map_declaration_validity(**args, allow_story_override=True)
    assert story_override.status == "story_override"
    assert story_override.effective is True

    missing_policy = resolve_map_declaration_validity(
        **args,
        allow_story_override=True,
        policy_gap="project_override_setting_unavailable",
    )
    assert missing_policy.status == "gap"
    assert missing_policy.gap == "project_override_setting_unavailable"
    assert missing_policy.effective is False

    future = _view(
        "entities",
        [
            _map_fact(
                novel_id=novel_id,
                node_id=node_id,
                revision_id=revision_id,
                status="active",
                scene_index=3,
            )
        ],
        novel_id=novel_id,
        scene_id=cutoff_scene_id,
        scene_index=3,
    )
    unavailable = resolve_map_declaration_validity(
        **{**args, "story_view": future}, allow_story_override=True
    )
    assert unavailable.status == "gap"
    assert unavailable.gap == "story_observation_not_before_cutoff"
    assert unavailable.effective is False


def test_map_projection_key_is_scoped_by_project_node_and_declaration_kind() -> None:
    novel_id, other_novel_id = str(uuid4()), str(uuid4())
    node_id, other_node_id = str(uuid4()), str(uuid4())
    feature_key = map_declaration_subject_id(novel_id, node_id, "feature", "same-key")
    assert feature_key != map_declaration_subject_id(
        other_novel_id, node_id, "feature", "same-key"
    )
    assert feature_key != map_declaration_subject_id(
        novel_id, other_node_id, "feature", "same-key"
    )
    assert feature_key != map_declaration_subject_id(
        novel_id, node_id, "constraint", "same-key"
    )
    assert map_declaration_subject_id(
        novel_id, node_id, "feature", "constraint:same-key"
    ) != map_declaration_subject_id(novel_id, node_id, "constraint", "same-key")
