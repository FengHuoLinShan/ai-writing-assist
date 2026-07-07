"""API boundary validation for novel_id parameters."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_world_entities_rejects_non_uuid_query_novel_id(
    async_client: AsyncClient,
) -> None:
    response = await async_client.get(
        "/api/world/entities",
        params={"novel_id": "not-a-uuid"},
    )

    assert response.status_code == 422


async def test_memory_status_rejects_non_uuid_path_novel_id(
    async_client: AsyncClient,
) -> None:
    response = await async_client.get("/api/novels/not-a-uuid/memories/status")

    assert response.status_code == 422
