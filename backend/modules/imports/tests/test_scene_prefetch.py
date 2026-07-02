"""Phase 0 scene prefetch batch planning and candidate capture."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from modules.imports.scene_prefetch import (
    Phase0ScenePrefetcher,
    build_phase0_prefetch_batches,
)


class FakeHTTPError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"Error code: {status_code}")


def test_phase0_builds_two_offset_rounds_for_213_chapters() -> None:
    batches = build_phase0_prefetch_batches(
        start_chapter=1,
        end_chapter=213,
        window=5,
    )

    assert batches[0].round_name == "A"
    assert batches[0].chapter_indices == [1, 2, 3, 4, 5]
    assert batches[1].round_name == "A"
    assert batches[1].chapter_indices == [6, 7, 8, 9, 10]

    round_b_first = next(batch for batch in batches if batch.round_name == "B")
    assert round_b_first.chapter_indices == [3, 4, 5, 6, 7]


def test_phase0_builds_tail_batches_for_small_ranges() -> None:
    batches = build_phase0_prefetch_batches(
        start_chapter=10,
        end_chapter=16,
        window=5,
    )

    assert [(batch.round_name, batch.chapter_indices) for batch in batches] == [
        ("A", [10, 11, 12, 13, 14]),
        ("A", [15, 16]),
        ("B", [12, 13, 14, 15, 16]),
    ]


def test_phase0_prefetch_reads_concurrency_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PHASE0_PREFETCH_CONCURRENCY", "3")

    async def llm(_batch):
        return {"scenes": []}

    prefetcher = Phase0ScenePrefetcher(llm=llm)

    assert prefetcher.concurrency == 3


def test_phase0_prefetch_reads_batch_timeout_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PHASE0_PREFETCH_BATCH_TIMEOUT_SECONDS", "7.5")

    async def llm(_batch):
        return {"scenes": []}

    prefetcher = Phase0ScenePrefetcher(llm=llm)

    assert prefetcher.batch_timeout_seconds == 7.5


@pytest.mark.asyncio
async def test_phase0_prefetch_success_returns_candidates_and_quality_stats() -> None:
    async def llm(batch):
        return {
            "scenes": [
                {
                    "title": f"{batch.batch_id} scene",
                    "scene_chunks": [
                        {"chapter_index": batch.chapter_indices[0]},
                    ],
                }
            ],
            "boundary_status": "complete",
            "evidence_anchors": [{"chapter_index": batch.chapter_indices[0]}],
            "merge_hints": [],
            "split_hints": [],
            "confidence": 0.91,
            "missing_or_uncertain_items": [],
        }

    result = await Phase0ScenePrefetcher(llm=llm, concurrency=3).run(
        start_chapter=1,
        end_chapter=6,
    )

    assert result.quality_stats["total_batches"] == 3
    assert result.quality_stats["success"] == 3
    assert result.quality_stats["failed"] == 0
    assert result.quality_stats["high_quality"] == 3
    assert {candidate.quality for candidate in result.candidates} == {"high"}
    assert all(candidate.payload["scenes"] for candidate in result.candidates)


@pytest.mark.asyncio
async def test_phase0_prefetch_empty_results_record_diagnostics_without_raising() -> None:
    async def llm(_batch):
        return {
            "scenes": [],
            "boundary_status": "uncertain",
            "evidence_anchors": [],
            "merge_hints": [],
            "split_hints": [],
            "confidence": 0.2,
            "missing_or_uncertain_items": ["no scene found"],
        }

    result = await Phase0ScenePrefetcher(llm=llm).run(
        start_chapter=1,
        end_chapter=1,
    )

    assert result.quality_stats["total_batches"] == 1
    assert result.quality_stats["empty_result"] == 1
    assert result.candidates[0].quality == "failed"
    assert result.candidates[0].diagnostics["final_error_type"] == "empty_result"


@pytest.mark.asyncio
async def test_phase0_prefetch_exceptions_record_diagnostics_without_raising() -> None:
    async def llm(_batch):
        raise RuntimeError("provider unavailable")

    result = await Phase0ScenePrefetcher(llm=llm).run(
        start_chapter=1,
        end_chapter=1,
    )

    assert result.quality_stats["total_batches"] == 1
    assert result.quality_stats["failed"] == 1
    assert result.candidates[0].quality == "failed"
    assert result.candidates[0].diagnostics["final_status"] == "failed"
    assert result.candidates[0].diagnostics["attempts"] == 1


@pytest.mark.asyncio
async def test_phase0_prefetch_batch_timeout_records_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PHASE0_PREFETCH_BATCH_TIMEOUT_SECONDS", "0.01")

    async def llm(_batch):
        await asyncio.sleep(1)
        return {"scenes": []}

    result = await Phase0ScenePrefetcher(llm=llm, concurrency=1).run(
        start_chapter=1,
        end_chapter=1,
    )

    assert result.quality_stats["total_batches"] == 1
    assert result.quality_stats["failed"] == 1
    assert result.quality_stats["timeout"] == 1
    assert result.candidates[0].diagnostics["final_error_type"] == "timeout"


@pytest.mark.asyncio
async def test_phase0_blocks_only_on_final_422_rate_over_threshold() -> None:
    responses = [
        FakeHTTPError(422),
        FakeHTTPError(422),
        FakeHTTPError(422),
        FakeHTTPError(422),
        {
            "scenes": [
                {
                    "title": "valid",
                    "scene_chunks": [{"chapter_index": 1}],
                }
            ],
            "boundary_status": "complete",
            "evidence_anchors": [{"chapter_index": 1}],
            "confidence": 0.9,
        },
    ]

    async def llm(_batch):
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    result = await Phase0ScenePrefetcher(llm=llm, concurrency=1).run(
        start_chapter=1,
        end_chapter=6,
    )

    assert result.blocked is True
    assert result.block_reason == "phase0_422_rate_exceeded"
    assert result.quality_stats["final_422_rate"] > 0.40


@pytest.mark.asyncio
async def test_phase0_schema_failures_are_diagnostics_not_blockers() -> None:
    async def llm(_batch):
        raise ValidationError.from_exception_data(
            "SceneCandidateOutput",
            [
                {
                    "type": "list_type",
                    "loc": ("scenes",),
                    "input": "not-a-list",
                }
            ],
        )

    result = await Phase0ScenePrefetcher(llm=llm, concurrency=1).run(
        start_chapter=1,
        end_chapter=1,
    )

    assert result.blocked is False
    assert result.block_reason is None
    assert result.quality_stats["schema_error"] == 1
    assert result.quality_stats["final_422_rate"] == 0.0
