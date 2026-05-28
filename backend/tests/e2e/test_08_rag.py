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


class TestRagRebuildIndex:
    """重建索引全流程：创建草稿 → 提交索引任务 → 执行 → 验证 chunks 入库"""

    CHAPTER_CONTENT = (
        "克莱恩·莫雷蒂坐在旧书桌前，翻开了那本泛黄的日记。"
        "罗塞尔大帝的文字映入眼帘，用一种他从未见过的语言书写。\n\n"
        "邓恩·史密斯推门走了进来，目光扫过桌上的日记本。"
        "「值夜者有新的任务给你，」他说道，语气一如既往地沉稳。"
    )

    @pytest_asyncio.fixture
    async def ctx(self, async_client: AsyncClient, db_session: AsyncSession):
        meta = await create_base_scene(db_session)
        await db_session.flush()
        return async_client, meta["project_id"], meta["character_ids"], db_session

    async def test_rebuild_index_creates_chunks(self, ctx):
        """创建草稿 → 通过 facade 执行索引 → 验证 chunks 创建且 character_ids 正确标记"""
        client, pid, cids, db = ctx

        draft_resp = await client.post("/api/writing/drafts", json={
            "novel_id": pid,
            "chapter_index": 1,
            "content": self.CHAPTER_CONTENT,
        })
        assert draft_resp.status_code == 201, f"创建草稿失败: {draft_resp.text[:300]}"

        from modules.rag.facade import index_chapter

        chunk_count = await index_chapter(db, pid, 1)
        assert chunk_count >= 2, f"至少应创建 2 个 chunk（按段落分割），实际: {chunk_count}"

        await db.flush()

        retrieve_resp = await client.post(f"/api/rag/retrieve?novel_id={pid}", json={
            "query": "克莱恩 日记",
        })
        assert retrieve_resp.status_code == 200
        data = retrieve_resp.json()
        assert data["total"] >= 1, f"索引后应能检索到相关 chunk，实际: {data['total']}"

        chunks_resp = await client.get(f"/api/rag/chunks?novel_id={pid}&limit=20")
        assert chunks_resp.status_code == 200
        chunks_data = chunks_resp.json()
        items = chunks_data.get("items", [])

        klein_chunks = [c for c in items if "克莱恩" in c.get("text", "")]
        assert len(klein_chunks) >= 1, "应有包含'克莱恩'的 chunk"

        for chunk in klein_chunks:
            char_ids = chunk.get("character_ids", [])
            assert cids["克莱恩·莫雷蒂"] in char_ids, (
                f"克莱恩相关 chunk 应标记 character_ids 包含克莱恩 ID，"
                f"实际: {char_ids}"
            )

    async def test_rebuild_index_replaces_old_chunks(self, ctx):
        """二次索引应替换旧 chunks，chunk 数量随内容变化"""
        client, pid, _, db = ctx

        await client.post("/api/writing/drafts", json={
            "novel_id": pid,
            "chapter_index": 2,
            "content": "第一段内容。",
        })
        from modules.rag.facade import index_chapter

        count_v1 = await index_chapter(db, pid, 2)
        await db.flush()

        await client.post("/api/writing/drafts", json={
            "novel_id": pid,
            "chapter_index": 2,
            "content": "第一段内容。\n\n第二段新增内容。\n\n第三段更多内容。",
        })
        count_v2 = await index_chapter(db, pid, 2)
        await db.flush()

        assert count_v2 > count_v1, (
            f"二次索引（3段）应比首次（1段）创建更多 chunk，"
            f"v1={count_v1}, v2={count_v2}"
        )

        chunks_resp = await client.get(f"/api/rag/chunks?novel_id={pid}&limit=20")
        assert chunks_resp.status_code == 200
        ch2_chunks = [
            c for c in chunks_resp.json().get("items", [])
            if c.get("chapter_index") == 2
        ]
        assert len(ch2_chunks) == count_v2, (
            f"chapter_index=2 的 chunk 数应等于二次索引创建数，"
            f"实际: {len(ch2_chunks)}, 期望: {count_v2}"
        )
