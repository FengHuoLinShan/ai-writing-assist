from __future__ import annotations

import pytest

from modules.imports.deep_import_dedup import DeepImportDedupCoordinator
from modules.imports.llm_schemas import SceneChunk
from modules.imports.scene_fusion import FinalSceneCandidate


def _candidate(
    candidate_id: str,
    *,
    source_ids: list[str],
    chapters: list[int],
    chunks: list[SceneChunk],
    title: str = "灰雾聚会",
    goal: str = "克莱恩建立神秘会面",
    confidence: float = 0.8,
) -> FinalSceneCandidate:
    return FinalSceneCandidate(
        candidate_id=candidate_id,
        title=title,
        goal=goal,
        core_conflict="身份伪装与信息差",
        emotional_beat="谨慎",
        scene_chunks=chunks,
        source_candidate_ids=source_ids,
        source_chapter_indices=chapters,
        confidence=confidence,
    )


def test_scene_dedup_collapses_same_source_and_preserves_cross_chapter_chunks():
    result = DeepImportDedupCoordinator().dedupe_scenes(
        [
            _candidate(
                "scene-a",
                source_ids=["source-1"],
                chapters=[6],
                chunks=[SceneChunk(chapter_index=6, start_paragraph=1)],
                confidence=0.82,
            ),
            _candidate(
                "scene-b",
                source_ids=["source-1"],
                chapters=[7],
                chunks=[SceneChunk(chapter_index=7, start_paragraph=2)],
                confidence=0.88,
            ),
        ]
    )

    assert len(result.candidates) == 1
    merged = result.candidates[0]
    assert merged.operation == "merged"
    assert merged.source_candidate_ids == ["source-1"]
    assert merged.source_chapter_indices == [6, 7]
    assert [chunk.chapter_index for chunk in merged.scene_chunks] == [6, 7]
    assert result.quality_stats["same_workflow_collapsed"] == 1


def test_scene_dedup_keeps_same_title_without_shared_text_anchor_separate():
    result = DeepImportDedupCoordinator().dedupe_scenes(
        [
            _candidate(
                "scene-a",
                source_ids=["source-1"],
                chapters=[6],
                chunks=[SceneChunk(chapter_index=6, start_paragraph=1)],
            ),
            _candidate(
                "scene-b",
                source_ids=["source-2"],
                chapters=[6],
                chunks=[SceneChunk(chapter_index=6, start_paragraph=9)],
            ),
        ]
    )

    assert len(result.candidates) == 2
    assert result.quality_stats["same_workflow_collapsed"] == 0


@pytest.mark.asyncio
async def test_structure_review_applies_only_same_workflow_high_confidence(
    monkeypatch,
):
    from modules.outline import facade as outline_facade

    async def fake_suggest_structure_dedup(*args, **kwargs):
        return {
            "total_assets_scanned": 3,
            "suggestions": [
                {
                    "asset_type": "plot_thread",
                    "action": "merge",
                    "source_asset_id": "source-1",
                    "target_asset_id": "target-1",
                    "source_workflow_id": "wf-1",
                    "target_workflow_id": "wf-1",
                    "confidence": 0.98,
                },
                {
                    "asset_type": "outline_arc",
                    "action": "merge",
                    "source_asset_id": "source-2",
                    "target_asset_id": "target-2",
                    "source_workflow_id": "wf-1",
                    "target_workflow_id": "older-workflow",
                    "confidence": 0.99,
                },
            ],
        }

    async def fake_apply_structure_dedup(*args, **kwargs):
        assert kwargs["confirmed"] is True
        assert [item["source_asset_id"] for item in kwargs["suggestions"]] == [
            "source-1"
        ]
        return {"applied": 1, "skipped": 0, "warnings": []}

    monkeypatch.setattr(
        outline_facade,
        "suggest_structure_dedup",
        fake_suggest_structure_dedup,
    )
    monkeypatch.setattr(
        outline_facade,
        "apply_structure_dedup",
        fake_apply_structure_dedup,
    )

    result = await DeepImportDedupCoordinator().review_structure(
        object(),
        "novel-1",
        workflow_id="wf-1",
    )

    assert result["checked"] == 3
    assert result["suggestions_recorded"] == 2
    assert result["auto_applied"] == 1
    assert result["skipped_external_asset"] == 1
