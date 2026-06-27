"""
上下文编译 E2E 测试
"""

from __future__ import annotations

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.e2e.seed_data import create_base_scene


class TestContextCompile:
    @pytest_asyncio.fixture
    async def ctx(self, async_client: AsyncClient, db_session: AsyncSession):
        meta = await create_base_scene(db_session)
        await db_session.flush()
        return async_client, meta["project_id"]

    async def test_compile_minimal(self, ctx):
        client, pid = ctx
        resp = await client.post(
            "/api/context/compile",
            json={
                "novel_id": pid,
                "task": "world",
                "scope": "project",
            },
        )
        assert resp.status_code == 200
        assert resp.json() is not None

    async def test_compile_full(self, ctx):
        client, pid = ctx
        resp = await client.post(
            "/api/context/compile",
            json={
                "novel_id": pid,
                "task": "plot",
                "scope": "full",
                "chapter_index": 5,
            },
        )
        assert resp.status_code == 200

    async def test_compile_with_entities(self, ctx):
        client, pid = ctx
        resp = await client.post(
            "/api/context/compile",
            json={
                "novel_id": pid,
                "task": "world",
                "scope": "chapter",
                "chapter_index": 1,
            },
        )
        assert resp.status_code == 200

    async def test_render_markdown(self, ctx):
        client, pid = ctx
        resp = await client.post(
            "/api/context/render",
            json={
                "novel_id": pid,
                "task": "world",
                "scope": "project",
            },
        )
        assert resp.status_code == 200
        md = resp.json().get("markdown", resp.text)
        assert len(md) > 50

    async def test_reveal_mode_author_safe(self, ctx):
        client, pid = ctx
        resp = await client.post(
            "/api/context/compile",
            json={
                "novel_id": pid,
                "task": "world",
                "scope": "full",
                "reveal_mode": "author_safe",
            },
        )
        assert resp.status_code == 200
