from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from modules.outline.api import router
from tests.support.project_gate import routes_without_leading_active_project_guard


def test_every_outline_route_starts_with_active_project_guard() -> None:
    assert routes_without_leading_active_project_guard(router) == []


@pytest.mark.asyncio
async def test_outline_routes_hide_recycled_and_missing_projects(
    async_client: AsyncClient,
) -> None:
    created = await async_client.post("/api/projects", json={"title": "Outline gate"})
    novel_id = created.json()["id"]
    missing_id = str(uuid.uuid4())

    active = await async_client.get(
        "/api/outline/threads",
        params={"novel_id": novel_id},
    )
    assert active.status_code == 200

    deleted = await async_client.delete(f"/api/projects/{novel_id}")
    assert deleted.status_code == 204

    for blocked_id in (novel_id, missing_id):
        read = await async_client.get(
            "/api/outline/threads",
            params={"novel_id": blocked_id},
        )
        write = await async_client.post(
            "/api/outline/scenes",
            params={"novel_id": blocked_id},
            json={"scene_index": 0, "title": "Blocked"},
        )
        enqueue = await async_client.post(
            "/api/outline/generate",
                json={
                    "contract_version": "outline_layer_v2",
                    "novel_id": blocked_id,
                    "context_confirmation_id": str(uuid.uuid4()),
                    "target": "plot_thread",
                    "mode": "create",
                    "instruction": "创建剧情线",
                    "selected_thread_ids": [],
                    "selected_arc_ids": [],
                    "selected_scene_ids": [],
                    "start_chapter": 1,
                "end_chapter": 2,
            },
        )
        assert read.status_code == 404
        assert write.status_code == 404
        assert enqueue.status_code == 404
