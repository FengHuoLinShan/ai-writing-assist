"""Author edit baseline (expected_updated_at) contract tests.

Covers the three Phase 2 edit paths: World Bible draft, CoreEntity and
Character profile.  Missing or stale baselines must fail closed with a
recognizable 409 instead of silently overwriting concurrent edits.
"""

from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient


async def _create_project(client: AsyncClient, title: str) -> str:
    response = await client.post("/api/projects", json={"title": title})
    assert response.status_code in {200, 201}, response.text
    return response.json()["id"]


async def _create_entity(client: AsyncClient, novel_id: str) -> dict:
    response = await client.post(
        "/api/world/entities",
        params={"novel_id": novel_id},
        json={
            "entity_type": "character",
            "name": "基线测试角色",
            "status": "canonical",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _create_draft(client: AsyncClient, novel_id: str) -> dict:
    response = await client.post(
        "/api/world/bible/drafts",
        json={"novel_id": novel_id, "title": "基线测试页", "page_type": "background"},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_draft_edit_requires_and_validates_baseline(
    async_client: AsyncClient,
) -> None:
    novel_id = await _create_project(async_client, "工作稿基线")
    draft = await _create_draft(async_client, novel_id)

    missing = await async_client.patch(
        f"/api/world/bible/drafts/{draft['id']}",
        params={"novel_id": novel_id},
        json={"free_text": "没有基线的修改"},
    )
    assert missing.status_code == 409
    assert missing.json()["error"] == "edit_baseline_required"

    stale = await async_client.patch(
        f"/api/world/bible/drafts/{draft['id']}",
        params={"novel_id": novel_id},
        json={
            "free_text": "过期基线的修改",
            "expected_updated_at": (
                datetime.fromisoformat(draft["updated_at"]) - timedelta(seconds=5)
            ).isoformat(),
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"] == "edit_baseline_stale"

    valid = await async_client.patch(
        f"/api/world/bible/drafts/{draft['id']}",
        params={"novel_id": novel_id},
        json={
            "free_text": "带正确基线的修改",
            "expected_updated_at": draft["updated_at"],
        },
    )
    assert valid.status_code == 200, valid.text
    assert valid.json()["free_text"] == "带正确基线的修改"

    # 保存成功后旧基线失效，新基线来自本次响应。
    again = await async_client.patch(
        f"/api/world/bible/drafts/{draft['id']}",
        params={"novel_id": novel_id},
        json={
            "free_text": "第二次修改",
            "expected_updated_at": draft["updated_at"],
        },
    )
    assert again.status_code == 409
    assert again.json()["error"] == "edit_baseline_stale"
    refreshed = await async_client.patch(
        f"/api/world/bible/drafts/{draft['id']}",
        params={"novel_id": novel_id},
        json={
            "free_text": "第二次修改",
            "expected_updated_at": valid.json()["updated_at"],
        },
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["free_text"] == "第二次修改"


@pytest.mark.asyncio
async def test_entity_edit_requires_and_validates_baseline(
    async_client: AsyncClient,
) -> None:
    novel_id = await _create_project(async_client, "对象基线")
    entity = await _create_entity(async_client, novel_id)

    missing = await async_client.put(
        f"/api/world/entities/{entity['id']}",
        params={"novel_id": novel_id},
        json={"summary": "没有基线的修改"},
    )
    assert missing.status_code == 409
    assert missing.json()["error"] == "edit_baseline_required"

    stale = await async_client.put(
        f"/api/world/entities/{entity['id']}",
        params={"novel_id": novel_id},
        json={
            "summary": "过期基线的修改",
            "expected_updated_at": "2020-01-01T00:00:00Z",
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"] == "edit_baseline_stale"

    valid = await async_client.put(
        f"/api/world/entities/{entity['id']}",
        params={"novel_id": novel_id},
        json={
            "summary": "带正确基线的修改",
            "expected_updated_at": entity["updated_at"],
        },
    )
    assert valid.status_code == 200, valid.text
    assert valid.json()["summary"] == "带正确基线的修改"

    reuse = await async_client.put(
        f"/api/world/entities/{entity['id']}",
        params={"novel_id": novel_id},
        json={
            "summary": "复用旧基线",
            "expected_updated_at": entity["updated_at"],
        },
    )
    assert reuse.status_code == 409
    assert reuse.json()["error"] == "edit_baseline_stale"


@pytest.mark.asyncio
async def test_character_profile_edit_requires_and_validates_baseline(
    async_client: AsyncClient,
) -> None:
    novel_id = await _create_project(async_client, "档案基线")
    entity = await _create_entity(async_client, novel_id)
    ensured = await async_client.get(
        f"/api/world/characters/{entity['id']}",
        params={"novel_id": novel_id},
    )
    assert ensured.status_code == 200, ensured.text
    character = ensured.json()

    missing = await async_client.put(
        f"/api/world/characters/{entity['id']}",
        params={"novel_id": novel_id},
        json={"role": "主角"},
    )
    assert missing.status_code == 409
    assert missing.json()["error"] == "edit_baseline_required"

    stale = await async_client.put(
        f"/api/world/characters/{entity['id']}",
        params={"novel_id": novel_id},
        json={
            "role": "主角",
            "expected_updated_at": "2020-01-01T00:00:00Z",
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"] == "edit_baseline_stale"

    valid = await async_client.put(
        f"/api/world/characters/{entity['id']}",
        params={"novel_id": novel_id},
        json={
            "role": "主角",
            "expected_updated_at": character["updated_at"],
        },
    )
    assert valid.status_code == 200, valid.text
    assert valid.json()["role"] == "主角"

    reuse = await async_client.put(
        f"/api/world/characters/{entity['id']}",
        params={"novel_id": novel_id},
        json={
            "role": "配角",
            "expected_updated_at": character["updated_at"],
        },
    )
    assert reuse.status_code == 409
    assert reuse.json()["error"] == "edit_baseline_stale"
