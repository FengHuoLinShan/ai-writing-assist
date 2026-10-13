"""Shared chapter anchors preserve the original permissive payload semantics."""

from modules.story.contracts import scene_chapter_indices


def test_chapter_anchors_combine_sources_and_ignore_invalid_values():
    scene = {
        "chapter_ids": ["2", 2, "bad", None, "-1"],
        "scene_chunks": [
            {"chapter_index": 3},
            {"chapter_id": "4"},
            {"chapter_index": 0, "chapter_id": "5"},
            {"chapter_index": "bad"},
            None,
            "unknown",
        ],
    }
    assert scene_chapter_indices(scene) == {-1, 2, 3, 4, 5}
    assert scene_chapter_indices({}) == set()
