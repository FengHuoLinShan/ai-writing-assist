"""ADR-0039 type-scoped continuity fields and directed attitude contracts."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from infrastructure.stable_hash import stable_hash
from modules.story.continuity.field_provenance import (
    STATE_FIELD_REGISTRY,
    FieldProvenance,
    is_registered_state_field,
)
from modules.story.continuity.scene_projection import SceneMemoryProjectionService
from modules.story.continuity.scene_state_view import SceneStateViewService
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


def test_relation_structure_source_reaches_author_fact_and_ended_observation() -> None:
    relation = {
        "id": "relation-1",
        "source_id": "character-a",
        "target_id": "faction-b",
        "relation_type": "alliance",
        "relation_status": "active",
    }
    ended = {**relation, "relation_status": "ended"}
    state = {
        "relations": [relation],
        "changes": [ended],
        "_field_provenance": [
            FieldProvenance(
                field_key="relation_status",
                dimension="relations",
                object_type="relation",
                event_id="event-ended",
                subject_ref="relation-1",
                version=0,
                recorded_at_sequence=5,
            ).model_dump(mode="json")
        ],
    }
    checkpoint = SimpleNamespace(
        state_json=state,
        id="checkpoint-1",
        confirmed=True,
        source="manual",
    )

    facts = SceneStateViewService._entries_for("relations", checkpoint)

    active = next(item for item in facts if item.field == "relation")
    ended_fact = next(item for item in facts if item.field == "relation_status")
    assert (
        active.source["field_provenance"]["relation_status"]["event_id"] == "event-ended"
    )
    assert ended_fact.layer == "observation"
    assert ended_fact.source["provenance"]["event_id"] == "event-ended"


def test_relation_events_assign_registered_status_without_changing_attitude_model() -> (
    None
):
    from modules.story.continuity.reducer import StoryStateReducer

    state = {}
    relation = {
        "id": "relation-1",
        "source_id": "character-a",
        "target_id": "faction-b",
        "relation_type": "alliance",
        "attitude": {
            "source_entity_id": "character-a",
            "target_entity_id": "faction-b",
            "label": "戒备",
            "degree": "moderate",
        },
    }
    established = SimpleNamespace(
        event_type="relation_established",
        snapshot_after=relation,
        entity_id=None,
        entity_type=None,
        scene_index=3,
        scene_sequence=1,
        sequence=1,
    )
    StoryStateReducer.apply_scene_dimension_event(state, "relations", established)
    assert state["relations"][0]["relation_status"] == "active"
    assert SceneMemoryProjectionService._assigned_motif_fields(
        state, "relations", established
    ) == (
        ("attitude", "relation-1", "relation"),
        ("relation_status", "relation-1", "relation"),
    )

    ended = SimpleNamespace(
        event_type="relation_ended",
        snapshot_after={"relation_id": "relation-1"},
        entity_id=None,
        entity_type=None,
        scene_index=4,
        scene_sequence=2,
        sequence=2,
    )
    StoryStateReducer.apply_scene_dimension_event(state, "relations", ended)
    assert state["relations"] == []
    assert state["changes"][-1]["relation_status"] == "ended"
    assert SceneMemoryProjectionService._assigned_motif_fields(
        state, "relations", ended
    ) == (("relation_status", "relation-1", "relation"),)


def test_custom_text_state_keeps_three_view_gates_and_unconfirmed_model_output() -> None:
    entity_id = "airship-1"
    state = {
        "entities": {
            entity_id: {
                "name": "灰隼号",
                "hull_condition": "breached",
                "free_note": "未注册但保留",
            }
        },
        "_field_provenance": [
            FieldProvenance(
                field_key="hull_condition",
                dimension="entities",
                object_type="airship",
                event_id="author-event-1",
                subject_ref=entity_id,
                version=0,
                recorded_at_sequence=5001,
                author_confirmed=True,
            ).model_dump(mode="json")
        ],
    }
    checkpoint = SimpleNamespace(
        state_json=state,
        id="checkpoint-1",
        confirmed=False,
        source="system_generated",
    )
    entries = SceneStateViewService._entries_for("entities", checkpoint)
    field_fact = next(item for item in entries if item.field == "hull_condition")
    free_fact = next(item for item in entries if item.field == "free_note")
    assert field_fact.confidence == "confirmed"
    assert field_fact.source["provenance"]["author_confirmed"] is True
    assert free_fact.value == "未注册但保留"
    assert "provenance" not in free_fact.source

    view_service = SceneStateViewService()
    author, _, _ = view_service._filter_entries(
        "entities",
        entries,
        kind="author",
        target_id=None,
        knowledge_grants={},
        reveal_cache={},
    )
    character_hidden, _, _ = view_service._filter_entries(
        "entities",
        entries,
        kind="character",
        target_id="character-1",
        knowledge_grants={},
        reveal_cache={},
    )
    reader_hidden, _, _ = view_service._filter_entries(
        "entities",
        entries,
        kind="reader",
        target_id=None,
        knowledge_grants={},
        reveal_cache={},
    )
    character, _, _ = view_service._filter_entries(
        "entities",
        [field_fact],
        kind="character",
        target_id="character-1",
        knowledge_grants={
            entity_id: {"hull_condition": frozenset({stable_hash("breached")})}
        },
        reveal_cache={},
    )
    reader, _, _ = view_service._filter_entries(
        "entities",
        [field_fact],
        kind="reader",
        target_id=None,
        knowledge_grants={},
        reveal_cache={(entity_id, "hull_condition"): True},
    )
    assert field_fact in author
    assert field_fact not in character_hidden
    assert field_fact not in reader_hidden
    assert character == [field_fact]
    assert reader == [field_fact]

    model_event = SimpleNamespace(
        event_type="entity_created",
        snapshot_after={
            "hull_condition": "intact",
            "meta": {"custom_state_field": True, "author_confirmed": True},
        },
        entity_id=entity_id,
        entity_type="airship",
        source="ai_extraction",
    )
    assert (
        SceneMemoryProjectionService._assigned_motif_fields(
            {"entities": {entity_id: {"hull_condition": "intact"}}},
            "entities",
            model_event,
        )
        == ()
    )
