"""StoryStateReducer 单一语义内核纯逻辑测试（V4 E03a / T04）。"""

from __future__ import annotations

from dataclasses import dataclass

from modules.story.continuity.reducer import StoryStateReducer

ENTITY_ID = "11111111-1111-4111-8111-111111111111"


@dataclass
class _Event:
    event_type: str
    snapshot_after: dict
    entity_id: str | None = None


def test_chapter_view_records_observation_changes() -> None:
    state: dict = {}
    StoryStateReducer.apply_chapter_event(
        state,
        _Event(
            "manual_correction",
            {"field_path": "林舟.status", "new_value": "持有铜钥匙"},
        ),
    )
    assert state["entities"] == {}
    assert state["changes"] == [{"field_path": "林舟.status", "new_value": "持有铜钥匙"}]


def test_entity_updated_unknown_entity_is_pending_not_phantom() -> None:
    state: dict = {"entities": {}}
    StoryStateReducer.apply_chapter_event(
        state,
        _Event(
            "entity_updated",
            {"id": ENTITY_ID, "name": "林舟"},
            entity_id=ENTITY_ID,
        ),
    )
    assert state["entities"] == {}
    assert state["changes"][0]["name"] == "林舟"

    # 身份/创建证据补齐后同负载并入核心状态。
    StoryStateReducer.apply_chapter_event(
        state,
        _Event(
            "entity_created",
            {"id": ENTITY_ID, "name": "林舟"},
            entity_id=ENTITY_ID,
        ),
    )
    assert state["entities"][ENTITY_ID]["name"] == "林舟"


def test_entity_created_then_updated_merges_payload() -> None:
    state: dict = {}
    StoryStateReducer.apply_chapter_event(
        state, _Event("entity_created", {"id": ENTITY_ID, "name": "林舟"}, ENTITY_ID)
    )
    StoryStateReducer.apply_chapter_event(
        state, _Event("entity_updated", {"status": "旅人"}, ENTITY_ID)
    )
    assert state["entities"][ENTITY_ID] == {
        "id": ENTITY_ID,
        "name": "林舟",
        "status": "旅人",
    }
    assert state["changes"] == []


def test_knowledge_replay_is_idempotent_on_duplicate_ids() -> None:
    state: dict = {}
    for index in range(3):
        StoryStateReducer.apply_chapter_event(
            state,
            _Event(
                "knowledge_changed",
                {"id": "know-1", "knowledge": f"v{index}"},
                ENTITY_ID,
            ),
        )
    assert len(state["character_knowledge"]) == 1
    assert state["character_knowledge"][0]["knowledge"] == "v2"


def test_knowledge_without_id_appends() -> None:
    state: dict = {}
    StoryStateReducer.apply_chapter_event(
        state, _Event("knowledge_changed", {"knowledge": "a"}, ENTITY_ID)
    )
    StoryStateReducer.apply_chapter_event(
        state, _Event("knowledge_changed", {"knowledge": "b"}, ENTITY_ID)
    )
    assert [k["knowledge"] for k in state["character_knowledge"]] == ["a", "b"]


def test_scene_dimension_projection_matches_chapter_core() -> None:
    events = [
        _Event("entity_created", {"id": ENTITY_ID, "name": "林舟"}, ENTITY_ID),
        _Event(
            "entity_moved", {"location_id": "loc-1", "text_state": "白石城"}, ENTITY_ID
        ),
        _Event(
            "relation_established",
            {"id": "rel-1", "source_id": ENTITY_ID, "target_id": "x"},
        ),
        _Event("knowledge_changed", {"id": "k1", "knowledge": "青竹保管钥匙"}, ENTITY_ID),
        _Event("manual_correction", {"field_path": "x", "new_value": "y"}),
    ]
    chapter: dict = {}
    for event in events:
        StoryStateReducer.apply_chapter_event(chapter, event)

    dimensions = {
        "entities": {"entities": {}, "changes": []},
        "locations": {"character_locations": {}, "changes": []},
        "relations": {"relations": [], "changes": []},
        "knowledge": {"character_knowledge": [], "changes": []},
    }
    routing = {
        "entity_created": "entities",
        "entity_moved": "locations",
        "relation_established": "relations",
        "knowledge_changed": "knowledge",
        "manual_correction": "entities",
    }
    for event in events:
        StoryStateReducer.apply_scene_dimension_event(
            dimensions[routing[event.event_type]], routing[event.event_type], event
        )

    assert dimensions["entities"]["entities"] == chapter["entities"]
    assert (
        dimensions["locations"]["character_locations"] == chapter["character_locations"]
    )
    assert dimensions["relations"]["relations"] == chapter["relations"]
    assert (
        dimensions["knowledge"]["character_knowledge"] == chapter["character_knowledge"]
    )
    assert dimensions["entities"]["changes"] == chapter["changes"]


def test_scene_timeline_and_causality_append_facts() -> None:
    timeline: dict = {}
    StoryStateReducer.apply_scene_dimension_event(
        timeline, "timeline", _Event("timeline_changed", {"new_value": "钟声"})
    )
    causality: dict = {}
    StoryStateReducer.apply_scene_dimension_event(
        causality, "causality", _Event("causality_changed", {"new_value": "北门已开"})
    )
    assert timeline["facts"] == [{"new_value": "钟声"}]
    assert causality["claims"] == [{"new_value": "北门已开"}]
