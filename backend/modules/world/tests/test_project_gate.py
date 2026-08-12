"""World and world-map API active-project gate regressions."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_recycled_project_is_hidden_from_world_query_body_and_atlas_apis(
    async_client: AsyncClient,
) -> None:
    created = await async_client.post(
        "/api/projects",
        json={"title": "world gate", "language": "zh"},
    )
    assert created.status_code == 201
    novel_id = created.json()["id"]
    deleted = await async_client.delete(f"/api/projects/{novel_id}")
    assert deleted.status_code == 204

    responses = [
        await async_client.get(
            "/api/world/entities",
            params={"novel_id": novel_id},
        ),
        await async_client.get(f"/api/world/map-atlas/{novel_id}/atlas"),
        await async_client.post(
            "/api/world/generation-center/chat",
            json={
                "novel_id": novel_id,
                "source_context": {"kind": "project"},
                "target": {"kind": "core_entity", "template": "none"},
                "messages": [{"role": "user", "content": "hello"}],
            },
        ),
        await async_client.post(
            "/api/world/generation-prompt-templates/validate",
            json={"novel_id": novel_id, "prompt_text": "Create {{ name }}"},
        ),
    ]

    assert [response.status_code for response in responses] == [404, 404, 404, 404]
    assert all("Project" in response.text for response in responses)


@pytest.mark.asyncio
async def test_global_world_template_catalog_does_not_require_project(
    async_client: AsyncClient,
) -> None:
    response = await async_client.get("/api/world/bible/templates")

    assert response.status_code == 200
    assert isinstance(response.json(), list)
