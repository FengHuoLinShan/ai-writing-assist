import json
from types import SimpleNamespace
from uuid import UUID

import pytest

from modules.story.forecast import _read_spatial_planning_fact, _spatial_planning_fact
from modules.story.outline_state.models import Scene


def test_spatial_planning_fact_is_empty_without_a_scene_map_brief():
    scene = SimpleNamespace(id="scene-1")
    assert _spatial_planning_fact(scene, SimpleNamespace(items=[])) is None


def test_spatial_planning_fact_carries_map_revision_and_explicit_limits():
    scene = SimpleNamespace(id="scene-1")
    brief = SimpleNamespace(
        items=[
            SimpleNamespace(
                node_id="map-node",
                revision_id="map-revision",
                revision_hash="a" * 64,
                source_hashes=["b" * 64],
                content=json.dumps(
                    {
                        "当前地点": [{"label": "北门"}],
                        "邻接与通路": [{"from": "北门", "to": "河镇"}],
                        "行程与通行条件": [{"from": "北门", "to": "河镇"}],
                    },
                    ensure_ascii=False,
                ),
            )
        ]
    )

    fact = _spatial_planning_fact(scene, brief)

    assert fact["capability_id"] == "story.spatial_planning.v1"
    assert "旅程分段" in fact["summary"]
    assert fact["source"]["map_revisions"][0]["revision_id"] == "map-revision"
    assert "地图没有真实比例" in fact["unknowns"][1]


def test_spatial_planning_suggests_review_when_recent_visible_scenes_share_one_place():
    scene = SimpleNamespace(id="scene-6")

    def brief(entity_id):
        return SimpleNamespace(
            items=[
                SimpleNamespace(
                    node_id="map-node",
                    revision_id="map-revision",
                    revision_hash="a" * 64,
                    source_hashes=["b" * 64],
                    content=json.dumps(
                        {"当前地点": [{"label": "黑港", "entity_id": entity_id}]},
                        ensure_ascii=False,
                    ),
                )
            ]
        )

    current = brief("place-1")
    recent = [(f"scene-{index}", brief("place-1")) for index in range(1, 6)]
    fact = _spatial_planning_fact(scene, current, recent=recent)
    assert "6 个已标注场景" in fact["summary"]
    assert "黑港" in fact["summary"]
    assert len(fact["source"]["concentration_scenes"]) == 6

    # Same display name with a different adopted entity identity is not one place.
    recent[-3:] = [(f"scene-{index}", brief("place-2")) for index in range(3, 6)]
    fact = _spatial_planning_fact(scene, current, recent=recent)
    assert "过于集中" not in fact["summary"]


def test_spatial_planning_does_not_treat_missing_map_coverage_as_concentration():
    scene = SimpleNamespace(id="scene-6")
    current = SimpleNamespace(
        items=[
            SimpleNamespace(
                node_id="map-node",
                revision_id="map-revision",
                revision_hash="a" * 64,
                source_hashes=[],
                content=json.dumps(
                    {"当前地点": [{"label": "黑港", "entity_id": "place-1"}]}
                ),
            )
        ]
    )
    recent = [(f"scene-{index}", SimpleNamespace(items=[])) for index in range(1, 6)]
    fact = _spatial_planning_fact(scene, current, recent=recent)
    assert "过于集中" not in fact["summary"]
    assert fact["source"].get("concentration_scenes") is None


def test_spatial_planning_does_not_merge_same_name_unbound_features():
    scene = SimpleNamespace(id="scene-6")

    def unbound_brief(feature_number):
        # World brief exposes no stable feature ID for these distinct markers.
        return SimpleNamespace(
            items=[
                SimpleNamespace(
                    node_id="shared-map-node",
                    revision_id=f"map-revision-{feature_number}",
                    revision_hash="a" * 64,
                    source_hashes=[],
                    content=json.dumps(
                        {"当前地点": [{"label": "北门", "entity_id": None}]}
                    ),
                )
            ]
        )

    current = unbound_brief(6)
    recent = [(f"scene-{index}", unbound_brief(index)) for index in range(1, 6)]
    fact = _spatial_planning_fact(scene, current, recent=recent)
    assert fact is not None  # The existing one-Scene map advice remains available.
    assert "过于集中" not in fact["summary"]
    assert fact["source"].get("concentration_scenes") is None


@pytest.mark.asyncio
async def test_spatial_planning_reads_only_current_and_five_previous_scenes(
    db_session, test_project_id, monkeypatch
):
    scenes = [
        Scene(novel_id=UUID(test_project_id), scene_index=index) for index in range(8)
    ]
    scenes[3].status = "deprecated"
    db_session.add_all(scenes)
    await db_session.flush()
    calls = []

    async def read_brief(_db, request):
        calls.append(request.scene_id)
        return SimpleNamespace(
            items=[
                SimpleNamespace(
                    node_id="map-node",
                    revision_id="map-revision",
                    revision_hash="a" * 64,
                    source_hashes=[],
                    content=json.dumps(
                        {"当前地点": [{"label": "黑港", "entity_id": "place-1"}]}
                    ),
                )
            ]
        )

    monkeypatch.setattr("core.container.get", lambda _key: read_brief)
    fact = await _read_spatial_planning_fact(db_session, test_project_id, scenes[6])
    assert "过于集中" in fact["summary"]
    assert calls == [str(scenes[index].id) for index in (6, 0, 1, 2, 4, 5)]
    assert str(scenes[3].id) not in calls
    assert str(scenes[7].id) not in calls
