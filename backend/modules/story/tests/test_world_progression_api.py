"""The author gets an actionable budget-preview error before any provider I/O."""

import pytest


@pytest.mark.asyncio
async def test_budget_preview_requires_a_connected_account_model(
    async_client, test_project_id, monkeypatch
):
    monkeypatch.setenv("STORY_WORLD_PROGRESSION_ENABLED", "true")
    response = await async_client.post(
        "/api/story/world-progression/budget-preview",
        json={
            "novel_id": test_project_id,
            "participants": [
                {
                    "kind": "character",
                    "id": "00000000-0000-0000-0000-000000000002",
                }
            ],
            "request_limit": 1,
            "token_limit": 1,
            "time_budget_seconds": 1,
        },
    )
    assert response.status_code == 409
    assert "连接并验证模型" in response.json()["detail"]
