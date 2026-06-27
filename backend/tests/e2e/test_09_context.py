"""
上下文编译 E2E 测试
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.e2e.seed_data import create_base_scene

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


class TestContextCompile:
    """上下文编译 E2E 测试"""

    @pytest_asyncio.fixture
    async def ctx(self, async_client: AsyncClient, db_session: AsyncSession):
        meta = await create_base_scene(db_session)
        await db_session.flush()
        return async_client, meta["project_id"]

    async def test_context_compile_with_project_scope_returns_200(self, ctx):
        """使用 project scope 编译上下文应返回 200"""
        # Arrange
        client, pid = ctx

        # Act
        resp = await client.post(
            "/api/context/compile",
            json={
                "novel_id": pid,
                "task": "world",
                "scope": "project",
            },
        )

        # Assert
        assert resp.status_code == 200
        assert resp.json() is not None

    async def test_context_compile_with_full_scope_and_chapter_returns_200(self, ctx):
        """使用 full scope 和指定章节编译上下文应返回 200"""
        # Arrange
        client, pid = ctx

        # Act
        resp = await client.post(
            "/api/context/compile",
            json={
                "novel_id": pid,
                "task": "plot",
                "scope": "full",
                "chapter_index": 5,
            },
        )

        # Assert
        assert resp.status_code == 200

    async def test_context_compile_with_chapter_scope_returns_200(self, ctx):
        """使用 chapter scope 编译上下文应返回 200"""
        # Arrange
        client, pid = ctx

        # Act
        resp = await client.post(
            "/api/context/compile",
            json={
                "novel_id": pid,
                "task": "world",
                "scope": "chapter",
                "chapter_index": 1,
            },
        )

        # Assert
        assert resp.status_code == 200

    async def test_context_render_with_project_scope_returns_markdown(self, ctx):
        """渲染 project scope 上下文应返回有效 Markdown"""
        # Arrange
        client, pid = ctx

        # Act
        resp = await client.post(
            "/api/context/render",
            json={
                "novel_id": pid,
                "task": "world",
                "scope": "project",
            },
        )

        # Assert
        assert resp.status_code == 200
        md = resp.json().get("markdown", resp.text)
        assert len(md) > 50

    async def test_context_compile_with_author_safe_reveal_returns_200(self, ctx):
        """使用 author_safe reveal 模式编译上下文应返回 200"""
        # Arrange
        client, pid = ctx

        # Act
        resp = await client.post(
            "/api/context/compile",
            json={
                "novel_id": pid,
                "task": "world",
                "scope": "full",
                "reveal_mode": "author_safe",
            },
        )

        # Assert
        assert resp.status_code == 200
