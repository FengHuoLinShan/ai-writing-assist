from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from modules.project.models import Project


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        (
            "POST",
            "/api/rag/chunks",
            {
                "json": {"source_type": "chapter_text", "text": "secret"},
            },
        ),
        ("GET", "/api/rag/chunks", {}),
        ("POST", "/api/rag/retrieve", {"json": {"query": "secret"}}),
    ],
)
async def test_rag_query_scoped_endpoints_hide_recycled_project(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_project_id: str,
    method: str,
    path: str,
    kwargs: dict,
) -> None:
    project = await db_session.get(Project, uuid.UUID(test_project_id))
    project.deleted_at = datetime.now(UTC)
    await db_session.flush()

    response = await async_client.request(
        method,
        path,
        params={"novel_id": test_project_id},
        **kwargs,
    )

    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/rag/rebuild", "/api/rag/retry-embeddings"])
async def test_rag_body_scoped_enqueue_hides_recycled_project(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_project_id: str,
    path: str,
) -> None:
    project = await db_session.get(Project, uuid.UUID(test_project_id))
    project.deleted_at = datetime.now(UTC)
    await db_session.flush()

    response = await async_client.post(path, json={"novel_id": test_project_id})

    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "params"),
    [
        ("GET", "/api/rag/metrics", {}),
        ("POST", "/api/rag/chunks/split", {"text": "one\ntwo"}),
    ],
)
async def test_rag_global_tools_remain_project_guard_exempt(
    async_client: AsyncClient,
    method: str,
    path: str,
    params: dict[str, str],
) -> None:
    response = await async_client.request(method, path, params=params)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_split_tool_rejects_overlap_that_cannot_advance(
    async_client: AsyncClient,
) -> None:
    response = await async_client.post(
        "/api/rag/chunks/split",
        params={"text": "测试文本" * 100, "chunk_size": 100, "overlap": 100},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/rag/chunks", "/api/rag/retrieve"])
async def test_rag_body_endpoints_reject_missing_body(
    async_client: AsyncClient,
    test_project_id: str,
    path: str,
) -> None:
    response = await async_client.post(
        path,
        params={"novel_id": test_project_id},
    )

    assert response.status_code == 422
