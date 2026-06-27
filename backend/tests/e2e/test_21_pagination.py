"""
全模块分页覆盖 E2E 测试
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.e2e.seed_data import create_base_scene

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


class TestPagination:
    """所有 list 端点的分页行为"""

    @pytest_asyncio.fixture
    async def ctx(self, async_client: AsyncClient, db_session: AsyncSession):
        meta = await create_base_scene(db_session)
        await db_session.flush()
        return async_client, meta["project_id"]

    async def _check(self, client, url):
        """Verify basic pagination structure"""
        resp = await client.get(url)
        assert resp.status_code == 200, f"Pagination check failed: {url}"
        return resp.json()

    async def test_pagination_world_entities_with_limit_respects_page_size(self, ctx):
        """世界实体分页应遵守 limit 参数"""
        # Arrange
        client, pid = ctx

        # Act
        data = await self._check(client, f"/api/world/entities?novel_id={pid}&limit=5")

        # Assert
        items = data.get("items", [])
        assert len(items) <= 5

    async def test_pagination_characters_with_limit_respects_page_size(self, ctx):
        """角色分页应遵守 limit 参数"""
        # Arrange
        client, pid = ctx

        # Act
        data = await self._check(client, f"/api/world/characters?novel_id={pid}&limit=2")

        # Assert
        items = data.get("items", [])
        assert len(items) <= 2

    async def test_pagination_geo_locations_with_limit_respects_page_size(self, ctx):
        pytest.skip("端点已移除: /api/geo/locations")

    async def test_pagination_timeline_events_with_limit_returns_data(self, ctx):
        pytest.skip("端点已移除: /api/novels/{pid}/timeline/events")

    async def test_pagination_outline_threads_with_limit_respects_page_size(self, ctx):
        """大纲剧情线分页应遵守 limit 参数"""
        # Arrange
        client, pid = ctx

        # Act
        data = await self._check(client, f"/api/outline/threads?novel_id={pid}&limit=2")

        # Assert
        items = data.get("items", [])
        assert len(items) <= 2

    async def test_pagination_outline_arcs_with_limit_respects_page_size(self, ctx):
        """大纲篇章纲分页应遵守 limit 参数"""
        # Arrange
        client, pid = ctx

        # Act
        data = await self._check(client, f"/api/outline/arcs?novel_id={pid}&limit=2")

        # Assert
        items = data.get("items", [])
        assert len(items) <= 2

    async def test_pagination_outline_chapters_with_limit_returns_data(self, ctx):
        pytest.skip("端点已移除: /api/outline/chapters")

    async def test_pagination_imports_with_limit_returns_data(self, ctx):
        """导入记录分页应返回数据"""
        # Arrange
        client, pid = ctx

        # Act
        data = await self._check(client, f"/api/imports?novel_id={pid}&limit=2")

        # Assert
        assert data is not None

    async def test_pagination_review_get_by_id_after_create_returns_200(self, ctx):
        pytest.skip("端点已移除: /api/review")

    async def test_pagination_world_entities_with_large_limit_does_not_crash(self, ctx):
        """超大 limit 不应导致分页查询崩溃"""
        # Arrange
        client, pid = ctx

        # Act
        data = await self._check(client, f"/api/world/entities?novel_id={pid}&limit=30")

        # Assert
        items = data.get("items", [])
        assert len(items) <= 30
