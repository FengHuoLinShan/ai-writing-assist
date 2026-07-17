from __future__ import annotations

import hashlib
from typing import Any

import pytest

from modules.imports.llm_schemas import SceneChunk
from modules.imports.scene_enrichment import Phase1bSceneEnricher
from modules.imports.scene_slicing import SceneSliceCandidate


def _chapter(index: int, content: str) -> dict[str, Any]:
    return {
        "chapter_index": index,
        "title": f"第{index}章",
        "content": content,
        "source_draft_id": f"draft-{index}",
        "source_content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
    }


def _scene(
    candidate_id: str,
    *,
    source_window_id: str,
    chunks: list[SceneChunk],
    needs_review: bool = False,
) -> SceneSliceCandidate:
    chapters = sorted({chunk.chapter_index for chunk in chunks})
    return SceneSliceCandidate(
        candidate_id=candidate_id,
        source_window_id=source_window_id,
        source_window_index=1,
        title=f"Scene {candidate_id}",
        goal=f"推进 {candidate_id}",
        core_conflict="",
        core_conflict_status="not_applicable",
        phase1a_confidence=0.91,
        boundary_basis="正文保持同一因果推进。",
        start_chapter=chapters[0],
        end_chapter=chapters[-1],
        boundary_status="complete",
        source_chapter_indices=chapters,
        scene_chunks=chunks,
        needs_review=needs_review,
    )


def _chunk(chapter: dict[str, Any], start: int, end: int) -> SceneChunk:
    return SceneChunk(
        chapter_index=int(chapter["chapter_index"]),
        start_offset=start,
        end_offset=end,
        source_draft_id=str(chapter["source_draft_id"]),
        source_content_hash=str(chapter["source_content_hash"]),
    )


def _context_window(
    window_id: str,
    chapter_range: list[int],
    *,
    character_start: int,
    object_start: int,
) -> dict[str, Any]:
    return {
        "window_id": window_id,
        "left_boundary_context": "",
        "reference_context": {
            "window_id": window_id,
            "range": {"covered": chapter_range, "owned": chapter_range},
            "outline": {
                "scenes": [
                    {
                        "id": f"outline-scene-{window_id}",
                        "title": f"已有 {window_id}",
                    }
                ],
                "arcs": [{"id": f"arc-{window_id}", "title": "篇章"}],
                "plot_threads": [{"id": f"thread-{window_id}", "name": "剧情线"}],
                "warnings": [],
            },
            "characters": [
                {"id": f"character-{index}", "name": f"人物{index}"}
                for index in range(character_start, character_start + 5)
            ],
            "world_objects": [
                {"id": f"object-{index}", "name": f"物品{index}"}
                for index in range(object_start, object_start + 10)
            ],
            "selection_trace": {
                "priority": [
                    "text_mention",
                    "scene_relation",
                    "outline_relation",
                ]
            },
            "content_hash": hashlib.sha256(window_id.encode()).hexdigest(),
        },
    }


@pytest.mark.asyncio
async def test_phase1b_materializes_cross_chapter_chunks_and_related_context() -> None:
    chapters = [
        _chapter(1, "第一章前段|第一章后段"),
        _chapter(2, "第二章完整正文"),
        _chapter(3, "第三章完整正文"),
    ]
    scenes = [
        _scene(
            "previous",
            source_window_id="window-1",
            chunks=[_chunk(chapters[0], 0, 5)],
        ),
        _scene(
            "current",
            source_window_id="window-2",
            chunks=[
                _chunk(chapters[1], 0, len(chapters[1]["content"])),
                _chunk(chapters[2], 0, 4),
            ],
        ),
        _scene(
            "next",
            source_window_id="window-2",
            chunks=[_chunk(chapters[2], 4, len(chapters[2]["content"]))],
        ),
    ]
    captured: dict[str, dict[str, Any]] = {}

    async def llm(payload: dict[str, Any]) -> dict[str, Any]:
        candidate_id = str(payload["locked_scene"]["candidate_id"])
        captured[candidate_id] = payload
        return {
            "emotional_beat": None,
            "must_happen": f"保留 {candidate_id}",
            "must_not_happen": None,
            "narrative_tag": "rising_action",
            "narrative_function": "延续因果推进",
            "basis": "精确正文与冻结结构共同支持。",
            "uncertain_fields": [],
            "confidence": 0.88,
        }

    context = {
        "contract_version": "phase1a-context-v2",
        "fingerprint": "a" * 64,
        "windows": [
            _context_window(
                "window-1",
                [1, 2],
                character_start=100,
                object_start=100,
            ),
            _context_window(
                "window-2",
                [2, 3],
                character_start=1,
                object_start=1,
            ),
        ],
    }

    result = await Phase1bSceneEnricher(llm, concurrency=3).run(
        scenes=scenes,
        chapters=chapters,
        phase1a_context=context,
    )

    payload = captured["current"]
    assert [item["text"] for item in payload["scene_source"]] == [
        chapters[1]["content"],
        chapters[2]["content"][:4],
    ]
    assert payload["source_integrity"]["complete"] is True
    assert payload["source_integrity"]["materialized_chunk_count"] == 2
    assert [
        item["window_id"] for item in payload["related_context"]["source_windows"]
    ] == ["window-2", "window-1"]
    assert (
        payload["related_context"]["adjacent_scenes"]["previous"]["candidate_id"]
        == "previous"
    )
    assert payload["related_context"]["adjacent_scenes"]["next"]["candidate_id"] == "next"
    assert len(payload["related_context"]["characters"]) == 6
    assert len(payload["related_context"]["world_objects"]) == 16
    assert (
        payload["related_context"]["source_windows"][0]["selection_trace"]["priority"][0]
        == "text_mention"
    )
    assert len(payload["context_fingerprint"]) == 64
    candidate = result.candidates[1]
    assert candidate.emotional_beat is None
    assert candidate.must_not_happen is None
    assert candidate.phase1b_field_statuses["emotional_beat"] == "not_applicable"
    assert candidate.phase1b_field_statuses["must_happen"] == "present"
    assert (
        candidate.phase1b_source_fingerprint
        == payload["source_integrity"]["source_fingerprint"]
    )
    assert candidate.needs_review is False

    repeated_fingerprints: dict[str, str] = {}

    async def repeat_llm(repeated_payload: dict[str, Any]) -> dict[str, Any]:
        repeated_fingerprints[repeated_payload["locked_scene"]["candidate_id"]] = (
            repeated_payload["context_fingerprint"]
        )
        return {"narrative_tag": "draft"}

    await Phase1bSceneEnricher(repeat_llm, concurrency=3).run(
        scenes=scenes,
        chapters=chapters,
        phase1a_context=context,
    )
    assert repeated_fingerprints["current"] == payload["context_fingerprint"]


@pytest.mark.asyncio
async def test_phase1b_cross_window_topk_preserves_higher_priority_mentions() -> None:
    chapter = _chapter(2, "当前 Scene 完整正文")
    scene = _scene(
        "ranked-context",
        source_window_id="window-2",
        chunks=[_chunk(chapter, 0, len(chapter["content"]))],
    )
    captured: dict[str, Any] = {}

    async def llm(payload: dict[str, Any]) -> dict[str, Any]:
        captured.update(payload)
        return {"narrative_tag": "draft"}

    def context_window(
        window_id: str,
        chapter_range: list[int],
        character_ids: list[str],
        reason: str,
    ) -> dict[str, Any]:
        return {
            "window_id": window_id,
            "reference_context": {
                "range": {"covered": chapter_range, "owned": chapter_range},
                "outline": {"scenes": [], "arcs": [], "plot_threads": []},
                "characters": [
                    {"id": item_id, "name": item_id} for item_id in character_ids
                ],
                "world_objects": [],
                "selection_trace": {
                    "included": {
                        "characters": [
                            {
                                "id": item_id,
                                "reason": reason,
                                "first_order": index,
                            }
                            for index, item_id in enumerate(character_ids)
                        ],
                        "world_objects": [],
                    }
                },
            },
        }

    context = {
        "contract_version": "phase1a-context-v2",
        "fingerprint": "e" * 64,
        "windows": [
            context_window(
                "window-2",
                [2, 3],
                [f"outline-{index}" for index in range(6)],
                "outline_relation",
            ),
            context_window(
                "window-1",
                [1, 2],
                ["direct-mention"],
                "text_mention",
            ),
        ],
    }

    await Phase1bSceneEnricher(llm).run(
        scenes=[scene],
        chapters=[chapter],
        phase1a_context=context,
    )

    selected_ids = [item["id"] for item in captured["related_context"]["characters"]]
    assert selected_ids[0] == "direct-mention"
    assert len(selected_ids) == 6
    assert "outline-5" not in selected_ids


@pytest.mark.asyncio
async def test_phase1b_keeps_full_oversized_scene_source_without_truncation() -> None:
    content = "甲" * 180_000 + "完整结尾"
    chapter = _chapter(1, content)
    scene = _scene(
        "oversized",
        source_window_id="window-1",
        chunks=[_chunk(chapter, 0, len(content))],
    )
    captured: dict[str, Any] = {}

    async def llm(payload: dict[str, Any]) -> dict[str, Any]:
        captured.update(payload)
        return {
            "narrative_tag": "draft",
            "narrative_function": "完整理解长 Scene",
            "basis": "全文证据。",
        }

    result = await Phase1bSceneEnricher(llm).run(
        scenes=[scene],
        chapters=[chapter],
    )

    assert captured["scene_source"][0]["text"] == content
    assert captured["source_integrity"]["total_chars"] == len(content)
    assert result.candidates[0].phase1b_field_statuses["narrative_tag"] == (
        "not_applicable"
    )


@pytest.mark.parametrize("failure", ["hash", "draft", "offset"])
@pytest.mark.asyncio
async def test_phase1b_invalid_source_fails_closed_without_provider_call(
    failure: str,
) -> None:
    chapter = _chapter(1, "精确正文")
    chunk = _chunk(chapter, 0, len(chapter["content"]))
    if failure == "hash":
        chunk.source_content_hash = "f" * 64
    elif failure == "draft":
        chunk.source_draft_id = "stale-draft"
    else:
        chunk.end_offset = len(chapter["content"]) + 1
    scene = _scene(
        f"invalid-{failure}",
        source_window_id="window-1",
        chunks=[chunk],
    )
    provider_calls = 0

    async def llm(_payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal provider_calls
        provider_calls += 1
        return {"narrative_tag": "hook"}

    result = await Phase1bSceneEnricher(llm).run(
        scenes=[scene],
        chapters=[chapter],
    )

    candidate = result.candidates[0]
    assert provider_calls == 0
    assert result.quality_stats["source_integrity"] == 1
    assert candidate.emotional_beat is None
    assert candidate.must_happen is None
    assert candidate.must_not_happen is None
    assert candidate.narrative_tag == "draft"
    assert set(candidate.phase1b_field_statuses.values()) == {"uncertain"}
    assert candidate.needs_review is True
    assert candidate.fallback_required is True


@pytest.mark.asyncio
async def test_phase1b_schema_valid_empty_output_is_not_retried_or_fabricated() -> None:
    chapter = _chapter(1, "安静地等待天亮。")
    scene = _scene(
        "quiet",
        source_window_id="window-1",
        chunks=[_chunk(chapter, 0, len(chapter["content"]))],
    )
    calls = 0

    async def llm(_payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {}

    result = await Phase1bSceneEnricher(llm).run(
        scenes=[scene],
        chapters=[chapter],
    )

    candidate = result.candidates[0]
    assert calls == 1
    assert candidate.emotional_beat is None
    assert candidate.must_happen is None
    assert candidate.must_not_happen is None
    assert candidate.narrative_tag == "draft"
    assert set(candidate.phase1b_field_statuses.values()) == {"not_applicable"}
    assert candidate.needs_review is False
    assert result.degraded is False


@pytest.mark.asyncio
async def test_phase1b_uncertain_fields_trigger_local_review() -> None:
    chapter = _chapter(1, "他似乎做出了决定。")
    scene = _scene(
        "uncertain",
        source_window_id="window-1",
        chunks=[_chunk(chapter, 0, len(chapter["content"]))],
    )

    async def llm(_payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "must_happen": "他做出决定",
            "narrative_tag": "rising_action",
            "uncertain_fields": ["must_happen"],
            "confidence": 0.52,
        }

    result = await Phase1bSceneEnricher(llm).run(
        scenes=[scene],
        chapters=[chapter],
    )

    candidate = result.candidates[0]
    assert candidate.phase1b_field_statuses["must_happen"] == "uncertain"
    assert candidate.needs_review is True
    assert "must_happen" in candidate.review_reason
