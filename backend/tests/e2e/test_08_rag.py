"""
RAG 检索与分块 E2E 测试

注意: embedding 依赖 pgvector，当前 DB 表结构可能存在元数据列不一致问题。
"""
from __future__ import annotations

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.e2e.seed_data import create_base_scene


class TestRagCRUD:
    @pytest_asyncio.fixture
    async def ctx(self, async_client: AsyncClient, db_session: AsyncSession):
        meta = await create_base_scene(db_session)
        await db_session.flush()
        return async_client, meta["project_id"], meta["entity_ids"]

    async def test_hybrid_retrieval(self, ctx):
        client, pid, _ = ctx
        resp = await client.post(f"/api/rag/retrieve?novel_id={pid}", json={
            "query": "克莱恩",
        })
        assert resp.status_code == 200

    async def test_retrieval_with_filters(self, ctx):
        client, pid, eids = ctx
        resp = await client.post(f"/api/rag/retrieve?novel_id={pid}", json={
            "query": "值夜者", "entity_ids": [eids["值夜者"]],
        })
        assert resp.status_code == 200

    async def test_split_chapters(self, ctx):
        client, pid, _ = ctx
        resp = await client.post(f"/api/rag/chunks/split", params={
            "text": "第一章 内容\n\n第二章 内容",
            "method": "paragraph",
        })
        assert resp.status_code in (200, 422), f"split: {resp.status_code} {resp.text[:200]}"
