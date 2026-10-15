import json
from types import SimpleNamespace

from modules.story.forecast import _spatial_planning_fact


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
