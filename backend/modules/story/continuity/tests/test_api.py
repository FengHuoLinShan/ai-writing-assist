from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from modules.project.models import Project


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "suffix", "params"),
    [
        ("GET", "/panorama", {"chapter_index": 1}),
        ("GET", "/events", {}),
        ("GET", "/events/entity-1/timeline", {}),
        ("POST", "/snapshots/capture", {"chapter_index": 1}),
        ("GET", "/snapshots", {}),
        ("POST", "/rebuild", {"from_chapter": 1}),
        ("GET", "/status", {}),
    ],
)
async def test_memory_api_hides_recycled_project(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_project_id: str,
    method: str,
    suffix: str,
    params: dict[str, int],
) -> None:
    project = await db_session.get(Project, uuid.UUID(test_project_id))
    project.deleted_at = datetime.now(UTC)
    await db_session.flush()

    response = await async_client.request(
        method,
        f"/api/novels/{test_project_id}/memories{suffix}",
        params=params,
    )

    assert response.status_code == 404
