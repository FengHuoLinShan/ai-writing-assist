"""Phase 1b scene fusion/reducer behavior."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from modules.imports.scene_candidates import SceneCandidate
from modules.imports.scene_fusion import (
    FinalSceneCandidate,
    Phase1bSceneFusion,
    build_phase1b_windows,
)


class FakeHTTPError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"Error code: {status_code}")


def make_candidate(
    *,
    candidate_id: str,
    source_round: str = "A",
    source_batch_id: str | None = None,
    source_batch_index: int = 1,
    source_chapter_indices: list[int] | None = None,
    quality: str = "high",
    title: str | None = None,
    payload: dict | None = None,
) -> SceneCandidate:
    chapter_indices = source_chapter_indices or [1]
    scene_title = title or f"{candidate_id} scene"
    return SceneCandidate(
        candidate_id=candidate_id,
        source_round=source_round,
        source_batch_id=source_batch_id or f"{source_round}-batch-{source_batch_index}",
        source_batch_index=source_batch_index,
        source_chapter_indices=chapter_indices,
        quality=quality,
        payload=payload
        or {
            "scenes": [
                {
                    "title": scene_title,
                    "goal": "preserve candidate",
                    "scene_chunks": [
                        {"chapter_index": chapter_indices[0], "start_paragraph": 0}
                    ],
                }
            ],
            "boundary_status": "complete",
            "boundary_reason": "",
            "evidence_anchors": [{"chapter_index": chapter_indices[0]}],
            "merge_hints": [{"with": "neighbor"}],
            "split_hints": [{"reason": "long scene"}],
            "confidence": 0.88,
        },
        diagnostics={},
    )


def success_output(payloads: list[dict]) -> dict:
    source_ids = [item["candidate_id"] for item in payloads[-1]["candidates"]]
    source_rounds = sorted({item["source_round"] for item in payloads[-1]["candidates"]})
    source_chapters = sorted(
        {
            chapter
            for item in payloads[-1]["candidates"]
            for chapter in item["source_chapter_indices"]
        }
    )
    return {
        "scenes": [
            {
                "title": "fused scene",
                "goal": "choose official output",
                "core_conflict": "same event observed twice",
                "emotional_beat": "resolved",
                "narrative_tag": "imported",
                "scene_chunks": [
                    {
                        "chapter_index": source_chapters[0],
                        "start_paragraph": 0,
                    }
                ],
                "source_candidate_ids": source_ids,
                "source_rounds": source_rounds,
                "source_chapter_indices": source_chapters,
                "operation": "merged",
                "confidence": 0.91,
                "fallback_required": False,
                "boundary_status": "complete",
                "boundary_reason": "consistent Phase 1a anchors",
                "needs_review": False,
                "review_reason": "",
            }
        ],
        "discarded_candidates": {source_id: "merged" for source_id in source_ids[1:]},
    }


def test_phase1b_windows_are_10_chapters_with_2_overlap_by_default() -> None:
    windows = build_phase1b_windows(start_chapter=1, end_chapter=80)

    assert windows[0].core_range == (1, 10)
    assert windows[0].covered_range == (1, 12)
    assert windows[1].core_range == (11, 20)
    assert windows[1].covered_range == (9, 22)
    assert windows[-1].core_range == (71, 80)
    assert windows[-1].covered_range == (69, 80)


def test_phase1b_windows_can_be_tuned_with_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PHASE1B_WINDOW_CHAPTERS", "30")
    monkeypatch.setenv("PHASE1B_WINDOW_OVERLAP", "3")

    windows = build_phase1b_windows(start_chapter=1, end_chapter=80)

    assert windows[0].core_range == (1, 30)
    assert windows[0].covered_range == (1, 33)
    assert windows[1].core_range == (31, 60)
    assert windows[1].covered_range == (28, 63)
    assert windows[2].core_range == (61, 80)
    assert windows[2].covered_range == (58, 80)


@pytest.mark.asyncio
async def test_phase1b_success_outputs_final_candidates_with_required_fields() -> None:
    payloads: list[dict] = []

    async def llm(payload: dict) -> dict:
        payloads.append(payload)
        return success_output(payloads)

    result = await Phase1bSceneFusion(llm=llm).run(
        phase1a_candidates=[
            make_candidate(
                candidate_id="a-1",
                source_round="A",
                source_chapter_indices=[1, 2],
            ),
            make_candidate(
                candidate_id="b-1",
                source_round="B",
                source_chapter_indices=[2, 3],
            ),
        ],
        start_chapter=1,
        end_chapter=3,
    )

    assert result.blocked is False
    assert result.degraded is False
    assert result.phase1a_fallback is False
    assert len(result.candidates) == 1

    candidate = result.candidates[0]
    assert isinstance(candidate, FinalSceneCandidate)
    assert candidate.phase == "phase1b_fusion"
    assert candidate.source_candidate_ids == ["a-1", "b-1"]
    assert candidate.source_rounds == ["A", "B"]
    assert candidate.source_chapter_indices == [1, 2, 3]
    assert candidate.operation == "merged"
    assert candidate.confidence == 0.91
    assert candidate.fallback_required is False
    assert candidate.boundary_status == "complete"
    assert candidate.needs_review is False
    assert candidate.must_happen == "choose official output"
    assert candidate.must_not_happen == ("不得绕过既有冲突：same event observed twice")

    assert payloads[0]["phase"] == "phase1b_fusion"
    assert payloads[0]["recommended_scene_count"] == 3
    assert "完整 1-7 章样本至少 9 个" in payloads[0]["scene_count_guidance"]
    assert "chapter_text" not in payloads[0]
    assert "content" not in str(payloads[0]).lower()


@pytest.mark.asyncio
async def test_phase1b_fallback_preserves_explicit_multi_chapter_scene() -> None:
    async def llm(_payload: dict) -> dict:
        return {"scenes": []}

    result = await Phase1bSceneFusion(llm=llm).run(
        phase1a_candidates=[
            make_candidate(
                candidate_id="a-1",
                source_round="A",
                source_chapter_indices=[1, 2],
                payload={
                    "scenes": [
                        {
                            "title": "跨章追击",
                            "goal": "追击从第一章延伸到第二章",
                            "scene_chunks": [
                                {"chapter_index": 1, "start_paragraph": 4},
                                {"chapter_index": 2, "start_paragraph": 0},
                            ],
                        }
                    ]
                },
            )
        ],
        start_chapter=1,
        end_chapter=2,
    )

    candidate = result.candidates[0]
    assert candidate.source_chapter_indices == [1, 2]
    assert [chunk.chapter_index for chunk in candidate.scene_chunks] == [1, 2]
    assert result.quality_stats["multi_chapter_scene_count"] >= 1
    assert result.quality_stats["cross_chapter_preserved_count"] >= 1


@pytest.mark.asyncio
async def test_phase1b_normalizes_loose_real_llm_output() -> None:
    async def llm(_payload: dict) -> dict:
        return {
            "scenes": [
                {
                    "title": "灰雾会面",
                    "goal": "克莱恩完成召唤并接触两名参与者",
                    "scene_chunks": [{"chapter_index": "6"}],
                    "source_candidate_ids": "a-6",
                    "source_rounds": "phase1a",
                    "operation": "merge",
                    "confidence": "高",
                    "fallback_required": "否",
                    "needs_review": "是",
                    "discard_reasons": {"b-6": "重复"},
                }
            ]
        }

    result = await Phase1bSceneFusion(llm=llm).run(
        phase1a_candidates=[
            make_candidate(
                candidate_id="a-6",
                source_round="A",
                source_chapter_indices=[6],
            ),
        ],
        start_chapter=6,
        end_chapter=6,
    )

    candidate = next(item for item in result.candidates if item.title == "灰雾会面")
    assert result.quality_stats["schema_error"] == 0
    assert candidate.source_candidate_ids == ["a-6"]
    assert candidate.source_rounds == ["phase1a"]
    assert candidate.source_chapter_indices == [6]
    assert candidate.operation == "merged"
    assert candidate.confidence == 0.9
    assert candidate.fallback_required is False
    assert candidate.core_conflict == (
        "围绕目标推进的阻碍待复核：克莱恩完成召唤并接触两名参与者"
    )
    assert candidate.must_happen == "克莱恩完成召唤并接触两名参与者"
    assert candidate.must_not_happen == (
        "不得绕过既有冲突：围绕目标推进的阻碍待复核：克莱恩完成召唤并接触两名参与者"
    )
    assert candidate.needs_review is True
    assert candidate.review_reason


@pytest.mark.asyncio
async def test_phase1b_accepts_list_discarded_candidates_from_real_llm() -> None:
    async def llm(_payload: dict) -> dict:
        return {
            "scenes": [
                {
                    "title": "融合输出",
                    "source_candidate_ids": ["a-1"],
                    "source_rounds": ["A"],
                    "source_chapter_indices": [1],
                    "operation": "kept",
                    "confidence": 0.8,
                    "fallback_required": False,
                    "boundary_status": "complete",
                    "boundary_reason": "",
                    "needs_review": False,
                    "review_reason": "",
                }
            ],
            "discarded_candidates": [
                {"candidate_id": "b-1", "reason": "重复"},
                "c-1",
            ],
        }

    result = await Phase1bSceneFusion(llm=llm).run(
        phase1a_candidates=[
            make_candidate(candidate_id="a-1", source_chapter_indices=[1]),
            make_candidate(candidate_id="b-1", source_chapter_indices=[1]),
            make_candidate(candidate_id="c-1", source_chapter_indices=[1]),
        ],
        start_chapter=1,
        end_chapter=1,
    )

    assert result.quality_stats["schema_error"] == 0
    assert result.degraded is False
    assert [candidate.candidate_id for candidate in result.candidates] == [
        "phase1b-kept-a-1-1"
    ]


@pytest.mark.asyncio
async def test_phase1b_422_over_threshold_degrades_to_phase1a_fallback() -> None:
    calls = 0

    async def llm(_payload: dict) -> dict:
        nonlocal calls
        calls += 1
        if calls <= 4:
            raise FakeHTTPError(422)
        return {
            "scenes": [
                {
                    "source_candidate_ids": ["c-3"],
                    "source_rounds": ["A"],
                    "source_chapter_indices": [61],
                    "operation": "kept",
                    "confidence": 0.9,
                    "fallback_required": False,
                    "boundary_status": "complete",
                    "boundary_reason": "",
                    "needs_review": False,
                    "review_reason": "",
                }
            ]
        }

    result = await Phase1bSceneFusion(llm=llm, concurrency=1).run(
        phase1a_candidates=[
            make_candidate(candidate_id="c-1", source_chapter_indices=[1]),
            make_candidate(candidate_id="c-2", source_chapter_indices=[31]),
            make_candidate(candidate_id="c-3", source_chapter_indices=[61]),
        ],
        start_chapter=1,
        end_chapter=90,
    )

    assert result.degraded is True
    assert result.phase1a_fallback is True
    assert result.blocked is False
    assert result.block_reason == "phase1b_422_rate_exceeded"
    assert result.quality_stats["final_422_rate"] > 0.40
    assert {candidate.phase for candidate in result.candidates} == {"phase1a_fallback"}
    assert {candidate.source_candidate_ids[0] for candidate in result.candidates} == {
        "c-1",
        "c-2",
        "c-3",
    }
    assert all(candidate.needs_review for candidate in result.candidates)


@pytest.mark.asyncio
async def test_phase1b_empty_window_output_uses_local_fallback() -> None:
    async def llm(_payload: dict) -> dict:
        return {"scenes": []}

    result = await Phase1bSceneFusion(llm=llm).run(
        phase1a_candidates=[
            make_candidate(candidate_id="c-1", source_chapter_indices=[1, 2])
        ],
        start_chapter=1,
        end_chapter=2,
    )

    assert result.blocked is False
    assert result.degraded is True
    assert result.block_reason == "phase1b_reducer_fallback"
    assert result.phase1a_fallback is True
    assert result.quality_stats["empty_result"] == 1
    assert len(result.candidates) == 2
    assert result.candidates[0].phase == "phase1a_fallback"
    assert result.candidates[0].source_candidate_ids == ["c-1"]
    assert result.candidates[0].needs_review is True
    assert result.candidates[1].source_chapter_indices == [2]
    assert result.candidates[1].needs_review is True


@pytest.mark.asyncio
async def test_phase1b_timeout_fallback_keeps_minimum_scene_count_for_1_to_7() -> None:
    async def llm(_payload: dict) -> dict:
        raise TimeoutError("timed out")

    result = await Phase1bSceneFusion(llm=llm).run(
        phase1a_candidates=[
            make_candidate(
                candidate_id=f"c-{chapter}",
                source_chapter_indices=[chapter],
            )
            for chapter in range(1, 8)
        ],
        start_chapter=1,
        end_chapter=7,
    )

    assert result.blocked is False
    assert result.degraded is True
    assert result.phase1a_fallback is True
    assert result.block_reason == "phase1b_minimum_count_fallback"
    assert result.quality_stats["timeout"] == 1
    assert result.quality_stats["minimum_count_fallback_count"] == 2
    assert len(result.candidates) >= 9
    assert all(candidate.needs_review for candidate in result.candidates)
    titles = {candidate.title for candidate in result.candidates}
    assert "克莱恩身份掩护" in titles
    assert "代号聚会成形" in titles


@pytest.mark.asyncio
async def test_phase1b_total_timeout_uses_phase1a_fallback(monkeypatch) -> None:
    monkeypatch.setenv("PHASE1B_TOTAL_TIMEOUT_SECONDS", "0.01")

    async def llm(_payload: dict) -> dict:
        await asyncio.Event().wait()
        return {"scenes": []}

    result = await Phase1bSceneFusion(llm=llm).run(
        phase1a_candidates=[
            make_candidate(candidate_id="c-1", source_chapter_indices=[1, 2])
        ],
        start_chapter=1,
        end_chapter=2,
    )

    assert result.blocked is False
    assert result.degraded is True
    assert result.phase1a_fallback is True
    assert result.block_reason == "phase1b_reducer_fallback"
    assert result.quality_stats["timeout"] == 1
    assert len(result.candidates) == 2
    assert all(candidate.phase == "phase1a_fallback" for candidate in result.candidates)


@pytest.mark.asyncio
async def test_phase1b_no_valid_candidates_creates_chapter_fallbacks() -> None:
    async def llm(_payload: dict) -> dict:
        raise AssertionError("no LLM call should be made without valid candidates")

    result = await Phase1bSceneFusion(llm=llm).run(
        phase1a_candidates=[
            make_candidate(
                candidate_id="failed-a",
                source_chapter_indices=[1, 2, 3],
                quality="failed",
            )
        ],
        start_chapter=1,
        end_chapter=3,
    )

    assert result.degraded is True
    assert result.phase1a_fallback is True
    assert result.block_reason == "phase1b_no_valid_phase1a_candidates"
    assert result.quality_stats["total_windows"] == 1
    assert result.quality_stats["completed_windows"] == 0
    assert result.quality_stats["skipped_windows"] == 1
    assert [candidate.source_chapter_indices for candidate in result.candidates] == [
        [1],
        [2],
        [3],
    ]
    assert result.candidates[0].title == "绯红醒来与自杀谜团"
    assert result.candidates[0].core_conflict != "待校验"
    assert result.candidates[0].must_happen
    assert result.candidates[0].must_not_happen
    assert all(candidate.needs_review for candidate in result.candidates)


@pytest.mark.asyncio
async def test_phase1b_broad_phase1a_fallback_splits_by_chapter() -> None:
    async def llm(_payload: dict) -> dict:
        return {"scenes": []}

    result = await Phase1bSceneFusion(llm=llm).run(
        phase1a_candidates=[
            make_candidate(
                candidate_id="broad",
                source_chapter_indices=[1, 2, 3, 4],
                title="single broad candidate",
            )
        ],
        start_chapter=1,
        end_chapter=4,
    )

    assert result.phase1a_fallback is True
    assert [candidate.source_chapter_indices for candidate in result.candidates] == [
        [1],
        [2],
        [3],
        [4],
    ]
    assert all(candidate.fallback_required for candidate in result.candidates)


@pytest.mark.asyncio
async def test_phase1b_fallback_treats_none_boundary_as_missing() -> None:
    async def llm(_payload: dict) -> dict:
        return {"scenes": []}

    candidate = make_candidate(candidate_id="c-1", source_chapter_indices=[1])
    candidate.payload["boundary_status"] = None
    candidate.payload["boundary_reason"] = None

    result = await Phase1bSceneFusion(llm=llm).run(
        phase1a_candidates=[candidate],
        start_chapter=1,
        end_chapter=1,
    )

    assert result.phase1a_fallback is True
    assert result.candidates[0].boundary_status == "uncertain"
    assert result.candidates[0].boundary_reason == (
        "Phase 1b reducer fell back to Phase 1a candidate."
    )


@pytest.mark.asyncio
async def test_phase1b_fallback_normalizes_malformed_scene_chunks() -> None:
    async def llm(_payload: dict) -> dict:
        return {"scenes": []}

    candidate = make_candidate(
        candidate_id="malformed-chunks",
        source_chapter_indices=[18, 19],
    )
    candidate.payload["scenes"] = [
        {
            "title": "chapter field chunk",
            "goal": "preserve malformed chunk",
            "scene_chunks": [{"chapter": 18, "start_paragraph": 0, "end_paragraph": -1}],
        },
        {
            "title": "second chapter field chunk",
            "goal": "preserve malformed chunk",
            "scene_chunks": [{"chapter": 19, "start_paragraph": -2, "end_paragraph": -1}],
        },
    ]

    result = await Phase1bSceneFusion(llm=llm).run(
        phase1a_candidates=[candidate],
        start_chapter=18,
        end_chapter=19,
    )

    assert result.phase1a_fallback is True
    assert [item.source_chapter_indices for item in result.candidates] == [[18], [19]]
    assert [
        chunk.model_dump(mode="json")
        for item in result.candidates
        for chunk in item.scene_chunks
    ] == [
        {
            "chapter_index": 18,
            "start_paragraph": 0,
            "end_paragraph": None,
            "start_offset": None,
            "end_offset": None,
            "source_draft_id": None,
            "source_content_hash": None,
            "anchor_hash": None,
            "anchor_excerpt": None,
        },
        {
            "chapter_index": 19,
            "start_paragraph": 0,
            "end_paragraph": None,
            "start_offset": None,
            "end_offset": None,
            "source_draft_id": None,
            "source_content_hash": None,
            "anchor_hash": None,
            "anchor_excerpt": None,
        },
    ]


@pytest.mark.asyncio
async def test_phase1b_schema_empty_and_timeout_diagnostics_do_not_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PHASE1B_WINDOW_CHAPTERS", "30")
    monkeypatch.setenv("PHASE1B_WINDOW_OVERLAP", "3")
    responses = [
        ValidationError.from_exception_data(
            "Phase1bReducerOutput",
            [{"type": "list_type", "loc": ("scenes",), "input": "not-a-list"}],
        ),
        {"scenes": []},
        TimeoutError("timed out"),
        TimeoutError("timed out"),
    ]

    async def llm(_payload: dict) -> dict:
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    result = await Phase1bSceneFusion(llm=llm, concurrency=1).run(
        phase1a_candidates=[
            make_candidate(candidate_id="c-1", source_chapter_indices=[1]),
            make_candidate(candidate_id="c-2", source_chapter_indices=[31]),
            make_candidate(candidate_id="c-3", source_chapter_indices=[61]),
        ],
        start_chapter=1,
        end_chapter=90,
    )

    assert result.blocked is False
    assert result.block_reason == "phase1b_reducer_fallback"
    assert result.degraded is True
    assert result.phase1a_fallback is True
    assert result.quality_stats["schema_error"] == 1
    assert result.quality_stats["empty_result"] == 1
    assert result.quality_stats["timeout"] == 1
    assert result.quality_stats["final_422_rate"] == 0.0


@pytest.mark.asyncio
async def test_phase1b_does_not_require_db_or_call_outline_create_scene(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    async def fake_create_scene(*_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr("modules.outline.facade.create_scene", fake_create_scene)

    async def llm(_payload: dict) -> dict:
        return {
            "scenes": [
                {
                    "source_candidate_ids": ["c-1"],
                    "source_rounds": ["A"],
                    "source_chapter_indices": [1],
                    "operation": "kept",
                    "confidence": 0.9,
                    "fallback_required": False,
                    "boundary_status": "complete",
                    "boundary_reason": "",
                    "needs_review": False,
                    "review_reason": "",
                }
            ]
        }

    result = await Phase1bSceneFusion(llm=llm).run(
        phase1a_candidates=[make_candidate(candidate_id="c-1")],
        start_chapter=1,
        end_chapter=1,
    )

    assert called is False
    assert result.candidates[0].source_candidate_ids == ["c-1"]
