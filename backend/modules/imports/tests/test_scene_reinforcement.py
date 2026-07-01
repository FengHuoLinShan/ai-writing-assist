"""Phase 1a scene reinforcement behavior."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from modules.imports.scene_candidates import SceneCandidate
from modules.imports.scene_reinforcement import Phase1aSceneReinforcer


class FakeHTTPError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"Error code: {status_code}")


def make_candidate(
    *,
    source_round: str = "A",
    source_batch_id: str = "A-0001-1-2",
    source_batch_index: int = 1,
    source_chapter_indices: list[int] | None = None,
    quality: str = "high",
    title: str = "phase0 scene",
) -> SceneCandidate:
    chapter_indices = source_chapter_indices or [1, 2]
    return SceneCandidate(
        candidate_id=f"phase0-{source_batch_id}-{quality}",
        source_round=source_round,
        source_batch_id=source_batch_id,
        source_batch_index=source_batch_index,
        source_chapter_indices=chapter_indices,
        quality=quality,
        payload={
            "scenes": [
                {
                    "title": title,
                    "scene_chunks": [
                        {"chapter_index": chapter_indices[0]},
                    ],
                }
            ],
            "boundary_status": "complete",
            "evidence_anchors": [{"chapter_index": chapter_indices[0]}],
            "confidence": 0.9 if quality == "high" else 0.4,
        },
        diagnostics={"final_status": "failed", "final_error_type": "timeout"}
        if quality == "failed"
        else {},
    )


def make_chapters(start: int, end: int) -> list[dict]:
    return [
        {
            "chapter_index": index,
            "title": f"第{index}章",
            "content": f"chapter {index} text",
        }
        for index in range(start, end + 1)
    ]


def success_output(payloads: list[dict]) -> dict:
    first_chapter = payloads[-1]["batch"]["chapter_indices"][0]
    return {
        "scenes": [
            {
                "title": f"reinforced {payloads[-1]['batch']['batch_id']}",
                "scene_chunks": [{"chapter_index": first_chapter}],
            }
        ],
        "boundary_status": "complete",
        "evidence_anchors": [{"chapter_index": first_chapter, "quote": "anchor"}],
        "merge_hints": [{"reason": "possible continuation"}],
        "split_hints": [{"reason": "long sequence"}],
        "confidence": 0.88,
        "missing_or_uncertain_items": ["minor timeline gap"],
    }


@pytest.mark.asyncio
async def test_phase1a_reinforces_rounds_separately() -> None:
    payloads: list[dict] = []

    async def llm(payload: dict) -> dict:
        payloads.append(payload)
        return success_output(payloads)

    result = await Phase1aSceneReinforcer(llm=llm).run(
        phase0_candidates=[
            make_candidate(
                source_round="A",
                source_batch_id="A-0001-1-2",
                source_batch_index=1,
                source_chapter_indices=[1, 2],
            ),
            make_candidate(
                source_round="B",
                source_batch_id="B-0001-2-3",
                source_batch_index=1,
                source_chapter_indices=[2, 3],
            ),
        ],
        chapters=make_chapters(1, 3),
    )

    assert {candidate.source_round for candidate in result.candidates} == {"A", "B"}
    assert result.did_merge_rounds is False
    assert [payload["round"] for payload in payloads] == ["A", "B"]
    assert all(
        candidate.payload["boundary_status"] == "complete"
        for candidate in result.candidates
    )


@pytest.mark.asyncio
async def test_prev_next_summaries_follow_chapter_order_not_input_order() -> None:
    payloads: list[dict] = []

    async def llm(payload: dict) -> dict:
        payloads.append(payload)
        return success_output(payloads)

    await Phase1aSceneReinforcer(llm=llm, concurrency=1).run(
        phase0_candidates=[
            make_candidate(
                source_batch_id="A-0003-5-6",
                source_batch_index=3,
                source_chapter_indices=[5, 6],
                title="third",
            ),
            make_candidate(
                source_batch_id="A-0001-1-2",
                source_batch_index=1,
                source_chapter_indices=[1, 2],
                title="first",
            ),
            make_candidate(
                source_batch_id="A-0002-3-4",
                source_batch_index=2,
                source_chapter_indices=[3, 4],
                title="second",
            ),
        ],
        chapters=make_chapters(1, 6),
    )

    middle_payload = payloads[1]
    assert middle_payload["batch"]["batch_id"] == "A-0002-3-4"
    assert middle_payload["previous_batch_summary"]["batch_id"] == "A-0001-1-2"
    assert middle_payload["next_batch_summary"]["batch_id"] == "A-0003-5-6"


@pytest.mark.asyncio
async def test_phase0_references_are_classified_for_llm_payload() -> None:
    payloads: list[dict] = []

    async def llm(payload: dict) -> dict:
        payloads.append(payload)
        return success_output(payloads)

    await Phase1aSceneReinforcer(llm=llm).run(
        phase0_candidates=[
            make_candidate(quality="high", title="strong ref"),
            make_candidate(quality="low", title="weak ref"),
            make_candidate(quality="failed", title="failed ref"),
        ],
        chapters=make_chapters(1, 2),
    )

    references = payloads[0]["phase0_references"]
    assert references["strong"][0]["payload"]["scenes"][0]["title"] == "strong ref"
    assert references["weak"][0]["payload"]["scenes"][0]["title"] == "weak ref"
    assert references["failed_diagnostics"][0]["diagnostics"]["final_error_type"] == (
        "timeout"
    )


@pytest.mark.asyncio
async def test_phase1a_blocks_on_final_422_rate_over_threshold() -> None:
    calls = 0

    async def llm(_payload: dict) -> dict:
        nonlocal calls
        calls += 1
        if calls <= 6:
            raise FakeHTTPError(422)
        return {
            "scenes": [
                {
                    "title": "valid",
                    "scene_chunks": [{"chapter_index": 5}],
                }
            ],
            "boundary_status": "complete",
            "confidence": 0.9,
        }

    result = await Phase1aSceneReinforcer(llm=llm, concurrency=1).run(
        phase0_candidates=[
            make_candidate(
                source_batch_id=f"A-{index:04d}-{index}-{index}",
                source_batch_index=index,
                source_chapter_indices=[index],
            )
            for index in range(1, 6)
        ],
        chapters=make_chapters(1, 5),
    )

    assert result.blocked is True
    assert result.block_reason == "phase1a_422_rate_exceeded"
    assert result.quality_stats["final_422_rate"] > 0.40


@pytest.mark.asyncio
async def test_schema_empty_and_timeout_diagnostics_do_not_block() -> None:
    responses = [
        ValidationError.from_exception_data(
            "SceneCandidateOutput",
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

    result = await Phase1aSceneReinforcer(llm=llm, concurrency=1).run(
        phase0_candidates=[
            make_candidate(
                source_batch_id=f"A-{index:04d}-{index}-{index}",
                source_batch_index=index,
                source_chapter_indices=[index],
            )
            for index in range(1, 4)
        ],
        chapters=make_chapters(1, 3),
    )

    assert result.blocked is False
    assert result.block_reason is None
    assert result.quality_stats["schema_error"] == 1
    assert result.quality_stats["empty_result"] == 1
    assert result.quality_stats["timeout"] == 1
    assert result.quality_stats["final_422_rate"] == 0.0


@pytest.mark.asyncio
async def test_phase1a_does_not_require_db_or_call_outline_create_scene(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    async def fake_create_scene(*_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr("modules.outline.facade.create_scene", fake_create_scene)

    async def llm(_payload: dict) -> dict:
        return {
            "scenes": [{"title": "candidate", "scene_chunks": [{"chapter_index": 1}]}],
            "boundary_status": "complete",
            "confidence": 0.9,
        }

    result = await Phase1aSceneReinforcer(llm=llm).run(
        phase0_candidates=[make_candidate()],
        chapters=make_chapters(1, 2),
    )

    assert called is False
    assert result.candidates[0].payload["scenes"][0]["title"] == "candidate"
