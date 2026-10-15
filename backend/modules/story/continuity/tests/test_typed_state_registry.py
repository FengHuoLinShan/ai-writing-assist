"""ADR-0039 type-scoped continuity fields and directed attitude contracts."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from modules.story.continuity.field_provenance import (
    STATE_FIELD_REGISTRY,
    FieldProvenance,
    is_registered_state_field,
)
from modules.story.continuity.scene_projection import SceneMemoryProjectionService
from modules.story.continuity.schemas import RelationAttitude, RelationInPanorama
from modules.story.facade import RelationAttitude as FacadeRelationAttitude


def test_typed_state_fields_are_scoped_by_object_type() -> None:
    assert is_registered_state_field("location", "condition", "entities")
    assert is_registered_state_field("item", "condition", "entities")
    assert not is_registered_state_field("character", "condition", "entities")
    assert ("character", "current_goal") in STATE_FIELD_REGISTRY

    valid = FieldProvenance(
        field_key="emotion",
        dimension="entities",
        object_type="character",
        event_id="event-1",
        subject_ref="character-1",
        version=0,
        recorded_at_sequence=1,
    )
    assert valid.object_type == "character"
    with pytest.raises(ValidationError):
        FieldProvenance(
            field_key="emotion",
            dimension="entities",
            object_type="item",
            event_id="event-2",
            subject_ref="item-1",
            version=0,
            recorded_at_sequence=1,
        )


def test_projection_records_registered_typed_fields_only() -> None:
    entity_id = "character-1"
    payload = {"emotion": "戒备", "current_goal": "找到出口", "free_note": "不登记"}
    state = {"entities": {entity_id: payload.copy()}}
    event = SimpleNamespace(
        snapshot_after=payload,
        event_type="entity_updated",
        entity_id=entity_id,
        entity_type="character",
    )
    assigned = SceneMemoryProjectionService._assigned_motif_fields(
        state, "entities", event
    )
    assert set(assigned) == {
        ("emotion", entity_id, "character"),
        ("current_goal", entity_id, "character"),
    }
    untyped_event = SimpleNamespace(
        snapshot_after=payload,
        event_type="entity_updated",
        entity_id=entity_id,
        entity_type=None,
    )
    assert (
        SceneMemoryProjectionService._assigned_motif_fields(
            state, "entities", untyped_event
        )
        == ()
    )


def test_relation_attitude_is_directed_and_graded() -> None:
    assert FacadeRelationAttitude is RelationAttitude
    attitude = RelationAttitude(
        source_entity_id="character-a",
        target_entity_id="faction-b",
        label="戒备",
        degree="strong",
    )
    assert attitude.source_entity_id != attitude.target_entity_id
    with pytest.raises(ValidationError):
        RelationAttitude(
            source_entity_id="character-a",
            target_entity_id="character-a",
            label="信任",
        )
    with pytest.raises(ValidationError):
        RelationInPanorama(
            id="relation-1",
            source_id="character-a",
            target_id="faction-b",
            relation_type="trust",
            attitude=RelationAttitude(
                source_entity_id="faction-b",
                target_entity_id="character-a",
                label="戒备",
            ),
        )


def test_relation_projection_traces_attitude_assignment() -> None:
    source = "character-a"
    target = "faction-b"
    relationship = {
        "id": "relation-1",
        "source_id": source,
        "target_id": target,
        "relation_type": "alliance",
        "attitude": {
            "source_entity_id": source,
            "target_entity_id": target,
            "label": "戒备",
            "degree": "moderate",
        },
    }
    state = {"relations": [relationship.copy()]}
    event = SimpleNamespace(
        snapshot_after=relationship,
        event_type="relation_established",
        entity_id=None,
        entity_type=None,
    )
    assigned = SceneMemoryProjectionService._assigned_motif_fields(
        state, "relations", event
    )
    assert assigned == (("attitude", "relation-1", "relation"),)
