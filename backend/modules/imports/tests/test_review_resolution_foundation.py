from types import SimpleNamespace

from modules.imports.scene_slicing import SceneSliceCandidate, _coordinate_window_edges
from modules.world.services.worldbuilding.adoption_package_service import (
    partition_post_import_items,
)


def test_window_conflict_only_marks_boundary_chapters():
    def window(index, leading, trailing):
        return SimpleNamespace(
            window=SimpleNamespace(
                window_index=index,
                window_id=str(index),
                owned_start=1 if index == 1 else 11,
                owned_end=10 if index == 1 else 20,
            ),
            diagnostics={
                "window_edges": {
                    "leading_relation": leading,
                    "trailing_relation": trailing,
                }
            },
        )

    candidates = [
        SceneSliceCandidate(
            candidate_id=str(ch),
            source_window_id="1" if ch <= 10 else "2",
            source_window_index=1 if ch <= 10 else 2,
            start_chapter=ch,
            end_chapter=ch,
        )
        for ch in (1, 9, 10, 11, 12, 20)
    ]
    result = _coordinate_window_edges(
        [window(1, "new_scene", "continues_right"), window(2, "new_scene", "complete")],
        candidates,
    )
    assert len(result["mismatches"]) == 1
    assert [item.start_chapter for item in candidates if item.needs_review] == [10, 11]


def test_partition_preserves_every_item_and_local_reference_scope():
    for count in (31, 32, 33, 300):
        entities = [
            {
                "item_key": f"e{i}",
                "kind": "core_entity",
                "payload": {"entity_id": f"id{i}"},
            }
            for i in range(count)
        ]
        relation = {
            "item_key": "r",
            "kind": "entity_relation",
            "payload": {"source_ref": "local:e0", "target_ref": f"local:e{count - 1}"},
        }
        batches = partition_post_import_items([*entities, relation])
        assert all(len(batch) <= 32 for batch in batches)
        assert len([item for batch in batches for item in batch]) == count + 1
        for batch in batches:
            keys = {item["item_key"] for item in batch}
            for item in batch:
                for key in ("source_ref", "target_ref"):
                    ref = item["payload"].get(key, "")
                    assert not ref.startswith("local:") or ref[6:] in keys
        assert relation["payload"]["source_ref"] == "local:e0"
