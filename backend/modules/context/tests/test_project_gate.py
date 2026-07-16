from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from modules.context.api import router
from tests.support.project_gate import routes_without_leading_active_project_guard


def test_every_context_route_starts_with_active_project_guard() -> None:
    assert routes_without_leading_active_project_guard(router) == []


@pytest.mark.asyncio
async def test_context_routes_hide_recycled_and_missing_projects(
    async_client: AsyncClient,
) -> None:
    created = await async_client.post("/api/projects", json={"title": "Context gate"})
    novel_id = created.json()["id"]
    missing_id = str(uuid.uuid4())

    active = await async_client.post(
        "/api/context/compile",
        json={"novel_id": novel_id, "task": "Compile", "scope": "project"},
    )
    assert active.status_code == 200

    deleted = await async_client.delete(f"/api/projects/{novel_id}")
    assert deleted.status_code == 204

    for blocked_id in (novel_id, missing_id):
        compile_response = await async_client.post(
            "/api/context/compile",
            json={"novel_id": blocked_id, "task": "Compile", "scope": "project"},
        )
        confirm_response = await async_client.post(
            "/api/context/confirm",
            json={
                "novel_id": blocked_id,
                "action": "writing.generate",
                "task": "Confirm",
                "scope": "project",
            },
        )
        maintenance_response = await async_client.post(
            "/api/context/snapshots/maintenance",
            json={"novel_id": blocked_id},
        )
        assert compile_response.status_code == 404
        assert confirm_response.status_code == 404
        assert maintenance_response.status_code == 404
