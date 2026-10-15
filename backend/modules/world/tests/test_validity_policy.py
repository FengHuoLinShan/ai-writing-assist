from __future__ import annotations

from modules.world.validity_policy import (
    exact_story_field_observation,
    exact_story_relation_observation,
)


def _view(dimension: str, facts: list[dict]) -> dict:
    return {"dimensions": [{"dimension": dimension, "status": "ok", "facts": facts}]}


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
