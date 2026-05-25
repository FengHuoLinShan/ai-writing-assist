"""
草稿写入与版本管理 E2E 测试
"""
from __future__ import annotations

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.e2e.seed_data import create_base_scene


class TestWritingDraft:
    @pytest_asyncio.fixture
    async def ctx(self, async_client: AsyncClient, db_session: AsyncSession):
        meta = await create_base_scene(db_session)
        await db_session.flush()
        return async_client, meta["project_id"]

    async def test_save_draft(self, ctx):
        client, pid = ctx
        resp = await client.post("/api/writing/drafts", json={
            "novel_id": pid, "chapter_index": 1,
            "title": "第1章", "content": "第一章正文内容...",
        })
        assert resp.status_code == 201
        assert resp.json()["version_number"] == 1

    async def test_draft_version_increment(self, ctx):
        client, pid = ctx
        resp = await client.post("/api/writing/drafts", json={
            "novel_id": pid, "chapter_index": 1,
            "title": "第1章", "content": "v1内容",
        })
        assert resp.status_code == 201
        v1_id = resp.json()["id"]

        # Create new version by posting again with same chapter_index
        resp2 = await client.post("/api/writing/drafts", json={
            "novel_id": pid, "chapter_index": 1,
            "title": "第1章", "content": "v2内容（新建版本）",
        })
        assert resp2.status_code == 201
        assert resp2.json()["version_number"] == 2, f"版本号应为 2, 实际 {resp2.json()['version_number']}"

    async def test_get_latest_chapter_draft(self, ctx):
        client, pid = ctx
        await client.post("/api/writing/drafts", json={
            "novel_id": pid, "chapter_index": 1,
            "title": "第1章", "content": "正文",
        })
        resp = await client.get(f"/api/writing/chapters/1/draft?novel_id={pid}")
        assert resp.status_code == 200
        assert resp.json()["chapter_index"] == 1

    async def test_get_version_history(self, ctx):
        client, pid = ctx
        resp = await client.get(f"/api/writing/chapters/1/versions?novel_id={pid}")
        assert resp.status_code == 200

    async def test_delete_draft(self, ctx):
        client, pid = ctx
        create = await client.post("/api/writing/drafts", json={
            "novel_id": pid, "chapter_index": 99,
            "title": "待删除", "content": "内容",
        })
        did = create.json()["id"]
        del_resp = await client.delete(f"/api/writing/drafts/{did}?novel_id={pid}")
        assert del_resp.status_code == 204
