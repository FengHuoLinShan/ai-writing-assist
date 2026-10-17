"""The author gets an actionable budget-preview error before any provider I/O."""

import pytest


@pytest.mark.asyncio
async def test_continuous_authorization_read_follows_project_binding_across_roots(
    monkeypatch,
):
    from types import SimpleNamespace

    from modules.story import world_progression_api

    novel_id = "novel-test"
    root = SimpleNamespace(id="latest-root")
    branch = SimpleNamespace(root_id=root.id)
    authorization = {"root_id": "authorized-root", "branch_id": "authorized-branch"}

    async def allow_project(*_args, **_kwargs):
        return None

    async def load_root(*_args, **_kwargs):
        return root

    async def load_branch(*_args, **_kwargs):
        return branch

    async def read_authorization(*_args, **_kwargs):
        return authorization

    monkeypatch.setattr(world_progression_api, "require_active_project", allow_project)
    monkeypatch.setattr(world_progression_api, "_enabled", lambda: None)
    monkeypatch.setattr(world_progression_api, "get_progression_root", load_root)
    monkeypatch.setattr(world_progression_api, "get_progression_branch", load_branch)
    monkeypatch.setattr(
        world_progression_api, "read_continuous_authorization", read_authorization
    )

    result = await world_progression_api.api_read_continuous_authorization(
        "latest-root", "latest-branch", None, novel_id=novel_id
    )

    assert result == authorization


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


@pytest.mark.asyncio
async def test_budget_preview_resolves_scene_before_requesting_confirmation(
    async_client, test_project_id, monkeypatch
):
    from modules.story import world_progression_api

    monkeypatch.setenv("STORY_WORLD_PROGRESSION_ENABLED", "true")

    async def snapshot(_db, novel_id):
        return {
            "novel_id": novel_id,
            "profile": {"provider_id": "offline", "model": "offline-test"},
        }

    async def unexpected_source(*_args, **_kwargs):
        raise AssertionError("cutoff discovery must not read dossiers")

    monkeypatch.setattr(
        world_progression_api, "build_project_llm_execution_snapshot", snapshot
    )
    monkeypatch.setattr(world_progression_api, "_source_for_request", unexpected_source)
    scene_id = "00000000-0000-0000-0000-000000000003"
    response = await async_client.post(
        "/api/story/world-progression/budget-preview",
        json={
            "novel_id": test_project_id,
            "scene_id": scene_id,
            "participants": [
                {
                    "kind": "character",
                    "id": "00000000-0000-0000-0000-000000000002",
                }
            ],
            "request_limit": 10,
            "token_limit": 10000,
            "time_budget_seconds": 600,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "requires_context_confirmation": True,
        "scene_id": scene_id,
    }
