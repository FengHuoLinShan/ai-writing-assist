from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from modules.writing.api import router
from tests.support.project_gate import routes_without_leading_active_project_guard


def test_every_writing_route_starts_with_active_project_guard() -> None:
    assert routes_without_leading_active_project_guard(router) == []


@pytest.mark.asyncio
async def test_writing_routes_hide_recycled_and_missing_projects(
    async_client: AsyncClient,
) -> None:
    created = await async_client.post("/api/projects", json={"title": "Writing gate"})
    novel_id = created.json()["id"]
    missing_id = str(uuid.uuid4())

    active = await async_client.get(
        "/api/writing/chapters",
        params={"novel_id": novel_id},
    )
    assert active.status_code == 200

    deleted = await async_client.delete(f"/api/projects/{novel_id}")
    assert deleted.status_code == 204

    for blocked_id in (novel_id, missing_id):
        read = await async_client.get(
            "/api/writing/chapters",
            params={"novel_id": blocked_id},
        )
        write = await async_client.post(
            "/api/writing/drafts/autosave",
            json={"novel_id": blocked_id, "chapter_index": 1, "content": "Blocked"},
        )
        enqueue = await async_client.post(
            "/api/writing/generate",
            json={
                "novel_id": blocked_id,
                "chapter_index": 1,
                "instruction": "Blocked",
                "context_confirmation_id": str(uuid.uuid4()),
            },
        )
        assert read.status_code == 404
        assert write.status_code == 404
        assert enqueue.status_code == 404
