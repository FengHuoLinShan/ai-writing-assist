from __future__ import annotations

import pytest

from modules.imports.deep_import_dedup import StructureReviewAgent


@pytest.mark.asyncio
async def test_structure_review_redacts_credentials_from_degraded_error(monkeypatch):
    from modules.story import facade as outline_facade

    secret = "private-token-value"

    async def fail_suggestion(*args, **kwargs):
        raise RuntimeError(f"Authorization: Bearer {secret} api_key={secret}")

    monkeypatch.setattr(
        outline_facade,
        "suggest_structure_dedup",
        fail_suggestion,
    )

    result = await StructureReviewAgent().review(
        object(),
        "novel-1",
        workflow_id="wf-1",
    )

    assert result["degraded"] == 1
    assert secret not in result["error_message"]
    assert "[REDACTED]" in result["error_message"]


@pytest.mark.asyncio
async def test_structure_review_applies_only_same_workflow_high_confidence(
    monkeypatch,
):
    from modules.story import facade as outline_facade

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
        assert [item["source_asset_id"] for item in kwargs["suggestions"]] == ["source-1"]
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

    result = await StructureReviewAgent().review(
        object(),
        "novel-1",
        workflow_id="wf-1",
    )

    assert result["checked"] == 3
    assert result["suggestions_recorded"] == 2
    assert result["auto_applied"] == 1
    assert result["skipped_external_asset"] == 1
    assert result["current_workflow_asset_outcomes"] == {
        "review": 1,
        "not_adopted": 1,
        "affected": 2,
        "review_asset_ids": ["outline_arc:source-2"],
        "not_adopted_asset_ids": ["plot_thread:source-1"],
    }


@pytest.mark.asyncio
async def test_structure_review_ignores_old_only_suggestion_pairs(monkeypatch):
    from modules.story import facade as outline_facade

    async def fake_suggest_structure_dedup(*args, **kwargs):
        return {
            "total_assets_scanned": 4,
            "suggestions": [
                {
                    "asset_type": "plot_thread",
                    "action": "needs_review",
                    "source_asset_id": "old-a",
                    "target_asset_id": "old-b",
                    "source_workflow_id": "older-1",
                    "target_workflow_id": "older-2",
                    "confidence": 0.8,
                },
                {
                    "asset_type": "outline_arc",
                    "action": "merge",
                    "source_asset_id": "old-c",
                    "target_asset_id": "old-d",
                    "source_workflow_id": "older-1",
                    "target_workflow_id": "older-2",
                    "confidence": 0.99,
                },
            ],
        }

    monkeypatch.setattr(
        outline_facade,
        "suggest_structure_dedup",
        fake_suggest_structure_dedup,
    )

    result = await StructureReviewAgent().review(
        object(),
        "novel-1",
        workflow_id="wf-current",
    )

    assert result["skipped_external_asset"] == 2
    assert result["current_workflow_asset_outcomes"] == {
        "review": 0,
        "not_adopted": 0,
        "affected": 0,
        "review_asset_ids": [],
        "not_adopted_asset_ids": [],
    }


@pytest.mark.asyncio
async def test_structure_review_counts_many_to_many_pairs_as_unique_assets(monkeypatch):
    from modules.story import facade as outline_facade

    async def fake_suggest_structure_dedup(*args, **kwargs):
        return {
            "total_assets_scanned": 3,
            "suggestions": [
                {
                    "asset_type": "plot_thread",
                    "action": "needs_review",
                    "source_asset_id": source,
                    "target_asset_id": target,
                    "source_workflow_id": "wf-current",
                    "target_workflow_id": "wf-current",
                    "confidence": 0.8,
                }
                for source, target in (
                    ("asset-a", "asset-b"),
                    ("asset-a", "asset-c"),
                    ("asset-b", "asset-c"),
                )
            ],
        }

    monkeypatch.setattr(
        outline_facade,
        "suggest_structure_dedup",
        fake_suggest_structure_dedup,
    )

    result = await StructureReviewAgent().review(
        object(),
        "novel-1",
        workflow_id="wf-current",
    )

    assert result["suggestions_recorded"] == 3
    assert result["current_workflow_asset_outcomes"] == {
        "review": 3,
        "not_adopted": 0,
        "affected": 3,
        "review_asset_ids": [
            "plot_thread:asset-a",
            "plot_thread:asset-b",
            "plot_thread:asset-c",
        ],
        "not_adopted_asset_ids": [],
    }
