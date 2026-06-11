"""
草稿写入与版本管理 E2E 测试
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.e2e.seed_data import create_base_scene, create_full_scene

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


class TestWritingDraft:
    """草稿写入与版本管理 E2E 测试"""

    @pytest_asyncio.fixture
    async def ctx(self, async_client: AsyncClient, db_session: AsyncSession):
        meta = await create_base_scene(db_session)
        await db_session.flush()
        return async_client, meta["project_id"]

    async def test_writing_draft_create_with_content_returns_version_one(self, ctx):
        """创建草稿应返回版本号为 1"""
        # Arrange
        client, pid = ctx

        # Act
        resp = await client.post(
            "/api/writing/drafts",
            json={
                "novel_id": pid,
                "chapter_index": 1,
                "title": "第1章",
                "content": "第一章正文内容...",
            },
        )

        # Assert
        assert resp.status_code == 201
        assert resp.json()["draft"]["version_number"] == 1

    async def test_writing_draft_create_same_chapter_increments_version(self, ctx):
        """同一章节多次创建草稿应递增版本号"""
        # Arrange
        client, pid = ctx
        resp = await client.post(
            "/api/writing/drafts",
            json={
                "novel_id": pid,
                "chapter_index": 1,
                "title": "第1章",
                "content": "v1内容",
            },
        )
        assert resp.status_code == 201
        v1_id = resp.json()["draft"]["id"]

        # Act
        resp2 = await client.post(
            "/api/writing/drafts",
            json={
                "novel_id": pid,
                "chapter_index": 1,
                "title": "第1章",
                "content": "v2内容（新建版本）",
            },
        )

        # Assert
        assert resp2.status_code == 201
        assert resp2.json()["draft"]["version_number"] == 2, (
            f"版本号应为 2, 实际 {resp2.json()['draft']['version_number']}"
        )

    async def test_writing_draft_get_latest_by_chapter_returns_draft(self, ctx):
        """按章节获取最新草稿应返回对应草稿"""
        # Arrange
        client, pid = ctx
        await client.post(
            "/api/writing/drafts",
            json={
                "novel_id": pid,
                "chapter_index": 1,
                "title": "第1章",
                "content": "正文",
            },
        )

        # Act
        resp = await client.get(f"/api/writing/chapters/1/draft?novel_id={pid}")

        # Assert
        assert resp.status_code == 200
        assert resp.json()["chapter_index"] == 1

    async def test_writing_draft_get_versions_returns_history(self, ctx):
        """获取章节版本历史应返回 200"""
        # Arrange
        client, pid = ctx

        # Act
        resp = await client.get(f"/api/writing/chapters/1/versions?novel_id={pid}")

        # Assert
        assert resp.status_code == 200

    async def test_writing_draft_delete_existing_returns_204(self, ctx):
        """删除已有草稿应返回 204（需保证章节至少保留一个版本）"""
        # Arrange
        client, pid = ctx
        await client.post(
            "/api/writing/drafts",
            json={
                "novel_id": pid,
                "chapter_index": 99,
                "title": "待删除",
                "content": "v1内容",
            },
        )
        create = await client.post(
            "/api/writing/drafts",
            json={
                "novel_id": pid,
                "chapter_index": 99,
                "title": "待删除",
                "content": "v2内容",
            },
        )
        did = create.json()["draft"]["id"]

        # Act
        del_resp = await client.delete(f"/api/writing/drafts/{did}?novel_id={pid}")

        # Assert
        assert del_resp.status_code == 204


class TestWritingMissingFlows:
    """草稿与其他模块联动 E2E 测试"""

    @pytest_asyncio.fixture
    async def ctx(self, async_client: AsyncClient, db_session: AsyncSession):
        meta = await create_full_scene(db_session)
        await db_session.flush()
        return async_client, meta["project_id"]

    async def test_writing_draft_and_outline_get_by_chapter_returns_both(self, ctx):
        pytest.skip("端点已移除: /api/outline/chapters/by-index/{idx}")

    async def test_writing_save_and_analyze_returns_draft_id_and_status(self, ctx):
        pytest.skip("端点已移除: /api/writing/save-and-analyze")

    async def test_writing_draft_update_status_to_approved_returns_200(self, ctx):
        pytest.skip("端点已移除: draft 无 status 字段，无法更新 approved 状态")
