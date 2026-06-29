from modules.writing.conflict_evidence import (
    evidence_location,
    snapshot_location,
)


def test_evidence_location_builds_stable_payload() -> None:
    payload = evidence_location(
        source_module="outline",
        source_type="scene.must_not_happen",
        source_id="scene-1",
        source_label="Scene：东门交涉",
        source_field="禁止发生",
        source_excerpt="主角死亡",
        open_target={"kind": "outline_scene", "scene_id": "scene-1"},
        text_range={"start": 3, "end": 7},
        needs_review_reason=None,
    )

    assert payload == {
        "text_range": {"start": 3, "end": 7},
        "source": {
            "module": "outline",
            "type": "scene.must_not_happen",
            "id": "scene-1",
            "label": "Scene：东门交涉",
            "field": "禁止发生",
            "excerpt": "主角死亡",
        },
        "open_target": {"kind": "outline_scene", "scene_id": "scene-1"},
        "needs_review_reason": None,
    }


def test_snapshot_location_keeps_lightweight_evidence() -> None:
    location = evidence_location(
        source_module="world",
        source_type="map.scene_summary",
        source_id="scene-1",
        source_label="地图：九州",
        source_field="地图风险",
        source_excerpt="粮仓起火：待确认",
        open_target={"kind": "map_object", "map_id": "map-1", "observation_id": "obs-1"},
        text_range={"start": 1, "end": 9},
        needs_review_reason="依赖待确认地图观察",
    )

    trimmed = snapshot_location(location)

    assert trimmed == {
        "source": location["source"],
        "open_target": location["open_target"],
        "needs_review_reason": "依赖待确认地图观察",
    }
    assert "text_range" not in trimmed
