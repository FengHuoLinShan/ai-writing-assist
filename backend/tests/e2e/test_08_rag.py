"""
RAG 检索与分块 E2E 测试

注意: embedding 依赖 pgvector，当前 DB 表结构可能存在元数据列不一致问题。
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.e2e.seed_data import create_base_scene

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


class TestRagCRUD:
    """RAG 基础操作 E2E 测试 — 覆盖检索、过滤、文本分块"""

    async def test_rag_retrieve_with_character_query_returns_200(
        self,
        base_scene_client,
    ):
        """使用角色名称查询 RAG 检索应返回 200"""
        client, pid, _ = base_scene_client

        # Act
        resp = await client.post(
            f"/api/evidence/indexing/retrieve?novel_id={pid}", json={"query": "克莱恩"}
        )

        # Assert
        assert resp.status_code == 200

    async def test_rag_retrieve_with_entity_filter_returns_200(
        self,
        base_scene_client,
    ):
        """使用实体 ID 过滤的 RAG 检索应返回 200"""
        client, pid, eids = base_scene_client

        # Arrange
        payload = {"query": "值夜者", "entity_ids": [eids["值夜者"]]}

        # Act
        resp = await client.post(
            f"/api/evidence/indexing/retrieve?novel_id={pid}", json=payload
        )

        # Assert
        assert resp.status_code == 200

    async def test_rag_split_text_with_paragraph_method_returns_200_or_422(
        self,
        base_scene_client,
    ):
        """段落分块接口应返回 200 或 422"""
        client, _pid, _ = base_scene_client

        # Arrange
        params = {
            "text": "第一章 内容\n\n第二章 内容",
            "method": "paragraph",
        }

        # Act
        resp = await client.post("/api/evidence/indexing/chunks/split", params=params)

        # Assert
        assert resp.status_code in (200, 422), (
            f"split: {resp.status_code} {resp.text[:200]}"
        )


class TestRagRebuildIndex:
    """RAG rebuild E2E with a deterministic embedding provider."""

    CHAPTER_CONTENT = (
        "克莱恩·莫雷蒂坐在旧书桌前，翻开了那本泛黄的日记。"
        "罗塞尔大帝的文字映入眼帘，用一种他从未见过的语言书写。\n\n"
        "邓恩·史密斯推门走了进来，目光扫过桌上的日记本。"
        "「值夜者有新的任务给你，」他说道，语气一如既往地沉稳。"
    )

    @pytest_asyncio.fixture
    async def ctx(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ):
        from core.config import get_settings

        embedding = [0.1] * get_settings().embedding_dim

        async def _deterministic_embedding(_self, value, **_kwargs):
            if isinstance(value, list):
                return [embedding.copy() for _ in value]
            return embedding.copy()

        monkeypatch.setattr(
            "infrastructure.llm.client.LLMClient.generate_embedding",
            _deterministic_embedding,
        )
        meta = await create_base_scene(db_session)
        await db_session.flush()
        return async_client, meta["project_id"], meta["entity_ids"], db_session

    async def test_rag_index_chapter_creates_chunks_with_character_tags(self, ctx):
        """创建草稿后执行索引应生成带 character_ids 标记的 chunks"""
        client, pid, eids, db = ctx

        # Arrange
        draft_resp = await client.post(
            "/api/writing/drafts",
            json={
                "novel_id": pid,
                "chapter_index": 1,
                "content": self.CHAPTER_CONTENT,
            },
        )
        assert draft_resp.status_code == 201, f"创建草稿失败: {draft_resp.text[:300]}"

        from modules.evidence.facade import index_chapter

        # Act
        chunk_count = await index_chapter(db, pid, 1)
        await db.flush()

        # Assert
        assert chunk_count >= 1

        # Act — 检索验证
        retrieve_resp = await client.post(
            f"/api/evidence/indexing/retrieve?novel_id={pid}",
            json={
                "query": "克莱恩 日记",
            },
        )

        # Assert
        assert retrieve_resp.status_code == 200
        data = retrieve_resp.json()
        assert data["total"] >= 1, f"索引后应能检索到相关 chunk，实际: {data['total']}"

        # Act — 验证 chunks 标记
        chunks_resp = await client.get(
            f"/api/evidence/indexing/chunks?novel_id={pid}&limit=20"
        )

        # Assert
        assert chunks_resp.status_code == 200
        chunks_data = chunks_resp.json()
        items = chunks_data.get("items", [])

        klein_chunks = [c for c in items if "克莱恩" in c.get("text", "")]
        assert len(klein_chunks) >= 1, "应有包含'克莱恩'的 chunk"

        for chunk in klein_chunks:
            char_ids = chunk.get("character_ids", [])
            assert eids["克莱恩·莫雷蒂"] in char_ids, (
                f"克莱恩相关 chunk 应标记 character_ids 包含克莱恩 ID，实际: {char_ids}"
            )

    async def test_rag_index_chapter_reindex_replaces_old_chunks(self, ctx):
        """二次索引同一章节应绑定新 draft 并移除旧源 chunks。"""
        client, pid, _, db = ctx

        # Arrange
        first = await client.post(
            "/api/writing/drafts",
            json={
                "novel_id": pid,
                "chapter_index": 2,
                "content": "仅旧版索引词。",
            },
        )
        assert first.status_code == 201, first.text
        first_draft_id = first.json()["draft"]["id"]
        from modules.evidence.facade import index_chapter

        # Act — 首次索引
        count_v1 = await index_chapter(db, pid, 2)
        await db.flush()
        assert count_v1 >= 1

        # Arrange — 更新草稿为更多段落
        second = await client.post(
            "/api/writing/drafts",
            json={
                "novel_id": pid,
                "chapter_index": 2,
                "content": "仅新版索引词。\n\n新版的补充内容。",
            },
        )
        assert second.status_code == 201, second.text
        second_draft = second.json()["draft"]

        # Act — 二次索引
        count_v2 = await index_chapter(db, pid, 2)
        await db.flush()

        # Assert
        assert count_v2 >= 1

        # Act — 验证数据库中 chapter 2 的 chunk 数量
        chunks_resp = await client.get(
            f"/api/evidence/indexing/chunks?novel_id={pid}&limit=20"
        )

        # Assert
        assert chunks_resp.status_code == 200
        ch2_chunks = [
            c for c in chunks_resp.json().get("items", []) if c.get("chapter_index") == 2
        ]
        assert len(ch2_chunks) == count_v2, (
            f"chapter_index=2 的 chunk 数应等于二次索引创建数，"
            f"实际: {len(ch2_chunks)}, 期望: {count_v2}"
        )
        assert {chunk["source_id"] for chunk in ch2_chunks} == {second_draft["id"]}
        assert all(
            chunk["source_content_hash"] == second_draft["content_hash"]
            for chunk in ch2_chunks
        )
        indexed_text = "\n".join(chunk["text"] for chunk in ch2_chunks)
        assert "仅新版索引词" in indexed_text
        assert "仅旧版索引词" not in indexed_text
        assert first_draft_id not in {chunk["source_id"] for chunk in ch2_chunks}
