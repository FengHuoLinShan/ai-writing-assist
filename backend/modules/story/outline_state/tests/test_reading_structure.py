"""The reading owner can freeze every Phase 3 call without hidden provider I/O."""

import json

import pytest

from modules.story.facade import (
    build_reading_structure_request,
    materialize_reading_structure_review,
    prepare_reading_structure_review,
)


@pytest.mark.parametrize("bad", [None, "missing", "duplicate", "foreign", "quote"])
def test_frozen_structure_review_requires_exact_item_coverage_and_sources(bad):
    scenes = [
        {
            "scene_id": f"scene-{index}",
            "scene_index": index,
            "start_chapter": index + 1,
            "end_chapter": index + 1,
            "summary": text,
            "_evidence": {"status": "exact", "sources": [{"text": text}]},
        }
        for index, text in enumerate(["林舟在城门等候。", "三日后，他仍在等待。"])
    ]
    raw = {
        "plot_threads": [
            {
                "title": "等待",
                "summary": "林舟持续等待。",
                "confidence": 0.95,
                "supporting_scene_ids": [item["scene_id"] for item in scenes],
            }
        ]
    }
    request, schema = build_reading_structure_request(scenes, {})
    assert schema.model_validate(raw).plot_threads
    assert all(scene["summary"] in request.messages[1].content for scene in scenes)
    requests = prepare_reading_structure_review(raw, scenes)
    results = []
    for request, schema in requests:
        units = json.loads(request.messages[1].content)["review_items"]
        reviews = [
            {
                "candidate_id": item["candidate_id"],
                "verdict": "supported",
                "confidence": 0.95,
                "evidence": [{"quote": item["scene_text"]}],
            }
            for item in units
        ]
        if bad == "missing":
            reviews.pop()
        elif bad == "duplicate":
            reviews.append(reviews[0])
        elif bad == "foreign":
            reviews[0]["candidate_id"] = "another-project"
        elif bad == "quote":
            reviews[0]["evidence"] = [{"quote": "林舟离开了。"}]
        results.append(schema.model_validate({"reviews": reviews}).model_dump())
    result = materialize_reading_structure_review(raw, scenes, results)
    thread = result["output"]["plot_threads"][0]
    assert thread["needs_review"] is (bad is not None)
    assert thread["evidence_gate"]["status"] == ("needs_review" if bad else "passed")
    with pytest.raises(ValueError, match="incomplete"):
        materialize_reading_structure_review(raw, scenes, [])


def test_review_cannot_borrow_quotes_from_a_different_text_chunk():
    scenes = [
        {
            "scene_id": "long-scene",
            "start_chapter": 1,
            "end_chapter": 1,
            "summary": "长场景",
            "_evidence": {"status": "exact", "sources": [{"text": "甲" * 48000 + "乙"}]},
        }
    ]
    raw = {
        "foreshadowing": [
            {
                "title": "甲乙",
                "summary": "线索",
                "confidence": 0.95,
                "supporting_scene_ids": ["long-scene"],
            }
        ]
    }
    results = []
    for request, _ in prepare_reading_structure_review(raw, scenes):
        units = json.loads(request.messages[1].content)["review_items"]
        results.append(
            {
                "reviews": [
                    {
                        "candidate_id": item["candidate_id"],
                        "verdict": "supported",
                        "confidence": 1,
                        "evidence": [
                            {
                                "quote": "乙"
                                if item["scene_text"].startswith("甲")
                                else "甲"
                            }
                        ],
                    }
                    for item in units
                ]
            }
        )
    result = materialize_reading_structure_review(raw, scenes, results)
    assert result["output"]["foreshadowing"][0]["needs_review"]
