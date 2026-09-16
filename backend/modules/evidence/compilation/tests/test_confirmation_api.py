from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_confirmation_is_project_scoped_and_private(
    async_client: AsyncClient,
) -> None:
    project = await async_client.post("/api/projects", json={"title": "Trace owner"})
    other_project = await async_client.post(
        "/api/projects", json={"title": "Trace other"}
    )
    assert project.status_code == 201
    assert other_project.status_code == 201
    novel_id = project.json()["id"]
    other_novel_id = other_project.json()["id"]
    created = await async_client.post(
        "/api/evidence/compilation/confirm",
        json={
            "novel_id": novel_id,
            "action": "writing.generate",
            "task": "生成正文建议",
            "scope": "chapter",
            "chapter_index": 1,
        },
    )
    assert created.status_code == 201, created.text
    confirmation_id = created.json()["id"]

    response = await async_client.get(
        f"/api/evidence/compilation/confirmations/{confirmation_id}",
        params={"novel_id": novel_id},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["id"] == confirmation_id
    assert payload["result_status"] == "confirmed"
    assert payload["stale_reasons"] == []
    assert "compile_options" not in payload
    assert "rendered_context" not in payload

    cross_project = await async_client.get(
        f"/api/evidence/compilation/confirmations/{confirmation_id}",
        params={"novel_id": other_novel_id},
    )
    missing = await async_client.get(
        f"/api/evidence/compilation/confirmations/{uuid.uuid4()}",
        params={"novel_id": novel_id},
    )
    assert cross_project.status_code == 404
    assert missing.status_code == 404
