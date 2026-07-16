"""
全模块分页覆盖 E2E 测试
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


class TestPagination:
    """所有 list 端点的分页行为"""

    async def _check(self, client, url):
        """Verify basic pagination structure"""
        resp = await client.get(url)
        assert resp.status_code == 200, f"Pagination check failed: {url}"
        return resp.json()

    async def test_pagination_world_entities_with_limit_respects_page_size(
        self,
        project_client,
    ):
        """世界实体分页应遵守 limit 参数"""
        # Arrange
        client, pid = project_client

        # Act
        data = await self._check(client, f"/api/world/entities?novel_id={pid}&limit=5")

        # Assert
        items = data.get("items", [])
        assert len(items) <= 5

    async def test_pagination_characters_with_limit_respects_page_size(
        self,
        project_client,
    ):
        """角色分页应遵守 limit 参数"""
        # Arrange
        client, pid = project_client

        # Act
        data = await self._check(client, f"/api/world/characters?novel_id={pid}&limit=2")

        # Assert
        items = data.get("items", [])
        assert len(items) <= 2

    async def test_pagination_outline_threads_with_limit_respects_page_size(
        self,
        project_client,
    ):
        """大纲剧情线分页应遵守 limit 参数"""
        # Arrange
        client, pid = project_client

        # Act
        data = await self._check(client, f"/api/outline/threads?novel_id={pid}&limit=2")

        # Assert
        items = data.get("items", [])
        assert len(items) <= 2

    async def test_pagination_outline_arcs_with_limit_respects_page_size(
        self,
        project_client,
    ):
        """大纲篇章纲分页应遵守 limit 参数"""
        # Arrange
        client, pid = project_client

        # Act
        data = await self._check(client, f"/api/outline/arcs?novel_id={pid}&limit=2")

        # Assert
        items = data.get("items", [])
        assert len(items) <= 2

    async def test_pagination_outline_scenes_with_limit_returns_data(
        self,
        project_client,
    ):
        client, pid = project_client
        data = await self._check(client, f"/api/outline/scenes?novel_id={pid}&limit=2")
        assert len(data.get("items", [])) <= 2

    async def test_pagination_imports_with_limit_returns_data(self, project_client):
        """导入记录分页应返回数据"""
        # Arrange
        client, pid = project_client

        # Act
        data = await self._check(client, f"/api/imports?novel_id={pid}&limit=2")

        # Assert
        assert data is not None

    async def test_pagination_world_entities_with_large_limit_does_not_crash(
        self,
        project_client,
    ):
        """超大 limit 不应导致分页查询崩溃"""
        # Arrange
        client, pid = project_client

        # Act
        data = await self._check(client, f"/api/world/entities?novel_id={pid}&limit=30")

        # Assert
        items = data.get("items", [])
        assert len(items) <= 30
