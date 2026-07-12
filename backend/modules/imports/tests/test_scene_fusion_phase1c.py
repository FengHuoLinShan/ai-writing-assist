from __future__ import annotations

import pytest

from modules.imports.llm_schemas import SceneChunk
from modules.imports.scene_fusion import FinalSceneCandidate
from modules.imports.scene_fusion_phase1c import Phase1cSceneFusionService


def _candidate(
    candidate_id: str,
    *,
    chapter: int,
    start: int,
    end: int,
) -> FinalSceneCandidate:
    return FinalSceneCandidate(
        candidate_id=candidate_id,
        phase="phase1b_enrichment",
        title=candidate_id,
        goal=f"goal-{candidate_id}",
        core_conflict=f"conflict-{candidate_id}",
        scene_chunks=[
            SceneChunk(
                chapter_index=chapter,
                start_offset=start,
                end_offset=end,
                source_draft_id=f"draft-{chapter}",
                source_content_hash=str(chapter) * 64,
            )
        ],
        source_candidate_ids=[candidate_id],
        source_chapter_indices=[chapter],
        needs_review=False,
    )


def _chapter(chapter: int, content: str) -> dict:
    return {
        "chapter_index": chapter,
        "content": content,
        "source_draft_id": f"draft-{chapter}",
        "source_content_hash": str(chapter) * 64,
    }


@pytest.mark.asyncio
async def test_phase1c_auto_merges_only_high_confidence_exact_pair() -> None:
    async def decide(_payload):
        return {
            "decision": "merge",
            "confidence": 0.95,
            "reason": "same major narrative objective",
        }

    result = await Phase1cSceneFusionService(decide).run(
        [
            _candidate("left", chapter=1, start=0, end=20),
            _candidate("right", chapter=1, start=20, end=40),
        ],
        [_chapter(1, "x" * 50)],
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].phase == "phase1c_fusion"
    assert [
        (chunk.start_offset, chunk.end_offset)
        for chunk in result.candidates[0].scene_chunks
    ] == [(0, 40)]
    assert result.suggestions == []
    assert result.quality_stats["auto_merged"] == 1


@pytest.mark.asyncio
async def test_phase1c_keeps_same_chapter_independent_scenes() -> None:
    async def decide(payload):
        assert payload["suggestion_kind"] == "intra_chapter"
        return {
            "decision": "keep_separate",
            "confidence": 0.98,
            "reason": "independent major objectives",
        }

    result = await Phase1cSceneFusionService(decide).run(
        [
            _candidate("left", chapter=1, start=0, end=20),
            _candidate("right", chapter=1, start=20, end=40),
        ],
        [_chapter(1, "x" * 50)],
    )

    assert [item.candidate_id for item in result.candidates] == ["left", "right"]
    assert result.suggestions == []


@pytest.mark.asyncio
async def test_phase1c_low_confidence_action_becomes_durable_suggestion_input() -> None:
    async def decide(_payload):
        return {
            "decision": "absorb_right",
            "confidence": 0.81,
            "reason": "right side looks transitional but confidence is insufficient",
        }

    result = await Phase1cSceneFusionService(decide).run(
        [
            _candidate("left", chapter=1, start=0, end=20),
            _candidate("right", chapter=2, start=0, end=20),
        ],
        [
            _chapter(1, "x" * 30),
            _chapter(2, "y" * 30),
        ],
    )

    assert len(result.candidates) == 2
    assert len(result.suggestions) == 1
    assert result.suggestions[0].suggestion_kind == "cross_chapter"
    assert result.suggestions[0].source_candidate_ids == ["left", "right"]


@pytest.mark.asyncio
async def test_phase1c_can_form_one_scene_across_more_than_two_chapters() -> None:
    async def decide(_payload):
        return {
            "decision": "merge",
            "confidence": 0.96,
            "reason": "one continuous major objective",
        }

    result = await Phase1cSceneFusionService(decide).run(
        [
            _candidate("one", chapter=1, start=0, end=20),
            _candidate("two", chapter=2, start=0, end=20),
            _candidate("three", chapter=3, start=0, end=20),
        ],
        [
            _chapter(1, "x" * 30),
            _chapter(2, "y" * 30),
            _chapter(3, "z" * 30),
        ],
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].source_chapter_indices == [1, 2, 3]
    assert result.quality_stats["auto_merged"] == 2


@pytest.mark.asyncio
async def test_phase1c_remaps_pending_boundary_after_later_candidate_merges() -> None:
    async def decide(payload):
        if payload["left"]["candidate_id"] == "one":
            return {
                "decision": "merge",
                "confidence": 0.80,
                "reason": "first boundary needs review",
            }
        return {
            "decision": "merge",
            "confidence": 0.96,
            "reason": "second and third belong together",
        }

    result = await Phase1cSceneFusionService(decide).run(
        [
            _candidate("one", chapter=1, start=0, end=20),
            _candidate("two", chapter=2, start=0, end=20),
            _candidate("three", chapter=3, start=0, end=20),
        ],
        [
            _chapter(1, "x" * 30),
            _chapter(2, "y" * 30),
            _chapter(3, "z" * 30),
        ],
    )

    assert len(result.candidates) == 2
    merged_id = result.candidates[1].candidate_id
    assert result.suggestions[0].source_candidate_ids == ["one", merged_id]
    assert result.suggestions[0].chapter_span == [1, 2, 3]


@pytest.mark.asyncio
async def test_phase1c_does_not_auto_merge_stale_source_binding() -> None:
    async def decide(_payload):
        return {
            "decision": "merge",
            "confidence": 0.99,
            "reason": "same objective",
        }

    stale = _candidate("left", chapter=1, start=0, end=20)
    stale.scene_chunks[0].source_content_hash = "f" * 64
    result = await Phase1cSceneFusionService(decide).run(
        [stale, _candidate("right", chapter=1, start=20, end=40)],
        [_chapter(1, "x" * 50)],
    )

    assert [item.candidate_id for item in result.candidates] == ["left", "right"]
    assert len(result.suggestions) == 1
    assert result.diagnostics[0]["exact_provenance"] is False
