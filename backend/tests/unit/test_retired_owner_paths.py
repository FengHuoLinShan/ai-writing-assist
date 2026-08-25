"""Retired owner-migration HTTP prefixes stay closed."""

import pytest
from httpx import AsyncClient


@pytest.mark.parametrize(
    "path",
    [
        "/api/rag/metrics",
        "/api/context/evidence-health",
        "/api/settings/llm-defaults",
    ],
)
async def test_retired_owner_paths_return_404(
    async_client: AsyncClient,
    path: str,
) -> None:
    response = await async_client.get(path)
    assert response.status_code == 404
