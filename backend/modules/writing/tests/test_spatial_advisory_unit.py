"""Pure spatial input and continuity checks; this module never opens a database."""

import uuid
from types import SimpleNamespace

from modules.writing.services import WritingConflictCheckService


def test_spatial_transitions_require_a_trusted_checkpoint_at_this_scene() -> None:
    before = str(uuid.uuid4())
    after = str(uuid.uuid4())
    mover = str(uuid.uuid4())
    scene = SimpleNamespace(scene_index=3)
    checkpoint = {
        "items": [
            {
                "dimension": "locations",
                "status": "ready",
                "source": "manual",
                "confirmed": True,
                "state_json": {
                    "changes": [
                        {
                            "scene_index": 3,
                            "subject_id": mover,
                            "old_value": {"location_id": before},
                            "new_value": {"location_id": after},
                        }
                    ]
                },
            }
        ]
    }

    assert WritingConflictCheckService._map_spatial_transitions(checkpoint, scene) == [
        {
            "from_location_id": before,
            "to_location_id": after,
            "mover_id": mover,
        }
    ]
    checkpoint["items"][0]["confirmed"] = False
    assert WritingConflictCheckService._map_spatial_transitions(checkpoint, scene) == []
    checkpoint["items"][0]["confirmed"] = True
    assert (
        WritingConflictCheckService._map_spatial_transitions(
            checkpoint, SimpleNamespace(scene_index=4)
        )
        == []
    )


def test_same_object_in_two_scene_locations_remains_an_advisory() -> None:
    scene = SimpleNamespace(
        id=str(uuid.uuid4()),
        scene_index=3,
        title="同场多地",
        pov_character_id=None,
        structure_meta={},
    )
    subject_id = str(uuid.uuid4())
    checkpoint = {
        "id": str(uuid.uuid4()),
        "dimension": "locations",
        "state_json": {
            "changes": [
                {
                    "subject_id": subject_id,
                    "effective_at": "3",
                    "new_value": {"location_id": str(uuid.uuid4())},
                },
                {
                    "subject_id": subject_id,
                    "effective_at": "3",
                    "new_value": {"location_id": str(uuid.uuid4())},
                },
            ]
        },
    }

    items = WritingConflictCheckService()._space_rule_items(
        scene, checkpoint, map_facts=[]
    )

    assert any(
        item["location_json"]["rule_code"] == "space_simultaneous_presence"
        for item in items
    )
    assert all(item["needs_review"] is True for item in items)

    # Earlier checkpoint history cannot become a contradiction in the current Scene.
    scene.scene_index = 4
    assert (
        WritingConflictCheckService()._space_rule_items(scene, checkpoint, map_facts=[])
        == []
    )
