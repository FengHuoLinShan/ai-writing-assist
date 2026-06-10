"""
RAG 检索与分块 E2E 测试

注意: embedding 依赖 pgvector，当前 DB 表结构可能存在元数据列不一致问题。
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.e2e.seed_data import create_base_scene

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


class TestRagCRUD:
    """RAG 基础操作 E2E 测试 — 覆盖检索、过滤、文本分块"""

    @pytest.fixture
    async def ctx(self, async_client: AsyncClient, db_session: AsyncSession):
        meta = await create_base_scene(db_session)
        await db_session.flush()
        return async_client, meta["project_id"], meta["entity_ids"]

    async def test_rag_retrieve_with_character_query_returns_200(
        self, ctx
    ):
        """使用角色名称查询 RAG 检索应返回 200"""
        client, pid, _ = ctx

        # Act
        resp = await client.post(f"/api/rag/retrieve?novel_id={pid}", json={"query": "克莱恩"})

        # Assert
        assert resp.status_code == 200

    async def test_rag_retrieve_with_entity_filter_returns_200(
        self, ctx
    ):
        """使用实体 ID 过滤的 RAG 检索应返回 200"""
        client, pid, eids = ctx

        # Arrange
        payload = {"query": "值夜者", "entity_ids": [eids["值夜者"]]}

        # Act
        resp = await client.post(f"/api/rag/retrieve?novel_id={pid}", json=payload)

        # Assert
        assert resp.status_code == 200

    async def test_rag_split_text_with_paragraph_method_returns_200_or_422(
        self, ctx
    ):
        """段落分块接口应返回 200 或 422"""
        client, pid, _ = ctx

        # Arrange
        params = {
            "text": "第一章 内容\n\n第二章 内容",
            "method": "paragraph",
        }

        # Act
        resp = await client.post("/api/rag/chunks/split", params=params)

        # Assert
        assert resp.status_code in (200, 422), f"split: {resp.status_code} {resp.text[:200]}"


@pytest.mark.skip(reason="LLM embedding API 不可用")
class TestRagRebuildIndex:
    """RAG 重建索引 E2E 测试 — 覆盖创建草稿、索引、验证 chunks 入库与替换"""

    CHAPTER_CONTENT = (
        "克莱恩·莫雷蒂坐在旧书桌前，翻开了那本泛黄的日记。"
        "罗塞尔大帝的文字映入眼帘，用一种他从未见过的语言书写。\n\n"
        "邓恩·史密斯推门走了进来，目光扫过桌上的日记本。"
        "「值夜者有新的任务给你，」他说道，语气一如既往地沉稳。"
    )

    @pytest.fixture
    async def ctx(self, async_client: AsyncClient, db_session: AsyncSession):
        meta = await create_base_scene(db_session)
        await db_session.flush()
        return async_client, meta["project_id"], meta["entity_ids"], db_session

    async def test_rag_index_chapter_creates_chunks_with_character_tags(
        self, ctx
    ):
        """创建草稿后执行索引应生成带 character_ids 标记的 chunks"""
        client, pid, eids, db = ctx

        # Arrange
        draft_resp = await client.post("/api/writing/drafts", json={
            "novel_id": pid,
            "chapter_index": 1,
            "content": self.CHAPTER_CONTENT,
        })
        assert draft_resp.status_code == 201, f"创建草稿失败: {draft_resp.text[:300]}"

        from modules.rag.facade import index_chapter

        # Act
        chunk_count = await index_chapter(db, pid, 1)
        await db.flush()

        # Assert
        assert chunk_count >= 2, f"至少应创建 2 个 chunk（按段落分割），实际: {chunk_count}"

        # Act — 检索验证
        retrieve_resp = await client.post(f"/api/rag/retrieve?novel_id={pid}", json={
            "query": "克莱恩 日记",
        })

        # Assert
        assert retrieve_resp.status_code == 200
        data = retrieve_resp.json()
        assert data["total"] >= 1, f"索引后应能检索到相关 chunk，实际: {data['total']}"

        # Act — 验证 chunks 标记
        chunks_resp = await client.get(f"/api/rag/chunks?novel_id={pid}&limit=20")

        # Assert
        assert chunks_resp.status_code == 200
        chunks_data = chunks_resp.json()
        items = chunks_data.get("items", [])

        klein_chunks = [c for c in items if "克莱恩" in c.get("text", "")]
        assert len(klein_chunks) >= 1, "应有包含'克莱恩'的 chunk"

        for chunk in klein_chunks:
            char_ids = chunk.get("character_ids", [])
            assert eids["克莱恩·莫雷蒂"] in char_ids, (
                f"克莱恩相关 chunk 应标记 character_ids 包含克莱恩 ID，"
                f"实际: {char_ids}"
            )

    async def test_rag_index_chapter_reindex_replaces_old_chunks(
        self, ctx
    ):
        """二次索引同一章节应替换旧 chunks，数量随内容变化"""
        client, pid, _, db = ctx

        # Arrange
        await client.post("/api/writing/drafts", json={
            "novel_id": pid,
            "chapter_index": 2,
            "content": "第一段内容。",
        })
        from modules.rag.facade import index_chapter

        # Act — 首次索引
        count_v1 = await index_chapter(db, pid, 2)
        await db.flush()

        # Arrange — 更新草稿为更多段落
        await client.post("/api/writing/drafts", json={
            "novel_id": pid,
            "chapter_index": 2,
            "content": "第一段内容。\n\n第二段新增内容。\n\n第三段更多内容。",
        })

        # Act — 二次索引
        count_v2 = await index_chapter(db, pid, 2)
        await db.flush()

        # Assert
        assert count_v2 > count_v1, (
            f"二次索引（3段）应比首次（1段）创建更多 chunk，"
            f"v1={count_v1}, v2={count_v2}"
        )

        # Act — 验证数据库中 chapter 2 的 chunk 数量
        chunks_resp = await client.get(f"/api/rag/chunks?novel_id={pid}&limit=20")

        # Assert
        assert chunks_resp.status_code == 200
        ch2_chunks = [
            c for c in chunks_resp.json().get("items", [])
            if c.get("chapter_index") == 2
        ]
        assert len(ch2_chunks) == count_v2, (
            f"chapter_index=2 的 chunk 数应等于二次索引创建数，"
            f"实际: {len(ch2_chunks)}, 期望: {count_v2}"
        )
