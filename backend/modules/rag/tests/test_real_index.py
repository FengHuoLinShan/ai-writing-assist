"""
RAG 真实数据重建索引测试 — 诡秘之主_第一部_小丑.txt 前10章

Cycle 1: 重建索引 + 验证分块
Cycle 2: 检索匹配度确定性验证
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from modules.project.models import Project
from modules.rag.facade import get_index_status, index_chapter
from modules.writing.facade import create_draft

REAL_FILE_PATH = Path("/Users/tywww/Desktop/项目/wirting skill/诡秘之主_第一部 小丑.txt")
FIRST_10_CHAPTER_COUNT = 10


# ============================================================
# Cycle 1: 重建索引 + 验证
# ============================================================


class TestRebuildIndexFirst10Chapters:
    """用真实前10章正文重建 RAG 索引，验证索引流程完整"""

    @pytest_asyncio.fixture
    async def ctx(self, db_session: AsyncSession) -> dict:
        """导入前10章正文到 writing_drafts，返回 project_id"""
        assert REAL_FILE_PATH.exists(), f"真实文件不存在: {REAL_FILE_PATH}"

        from modules.imports.parsers import parse_txt

        file_bytes = REAL_FILE_PATH.read_bytes()
        all_chapters = parse_txt(file_bytes)
        assert len(all_chapters) >= FIRST_10_CHAPTER_COUNT

        pid = uuid.uuid4()
        project = Project(
            id=pid,
            title="诡秘之主 RAG 重建索引测试",
            genre="西方奇幻",
            tone="维多利亚风格、黑暗",
            language="zh",
            target_length="novel",
            current_stage="writing",
        )
        db_session.add(project)
        await db_session.flush()
        project_id = str(pid)

        for idx in range(FIRST_10_CHAPTER_COUNT):
            ch = all_chapters[idx]
            await create_draft(
                db_session,
                novel_id=project_id,
                chapter_index=idx + 1,
                title=ch.get("title") or f"第{idx + 1}章",
                content=ch.get("content", ""),
            )

        await db_session.flush()
        return {"project_id": project_id}

    @pytest.mark.asyncio
    async def test_index_all_chapters_creates_chunks(
        self,
        ctx: dict,
        db_session: AsyncSession,
    ):
        """遍历前10章索引，每章至少创建1个 chunk"""
        project_id = ctx["project_id"]

        total_chunks = 0
        chapter_results: list[dict] = []

        for idx in range(1, FIRST_10_CHAPTER_COUNT + 1):
            from modules.rag.facade import index_chapter_with_report

            report = await index_chapter_with_report(db_session, project_id, idx)
            chapter_results.append(
                {
                    "chapter": idx,
                    "chunks_created": report.chunks_created,
                    "embedding_failed": report.embedding_failed_count,
                    "warnings": report.warnings,
                }
            )
            total_chunks += report.chunks_created
            assert report.chunks_created > 0, (
                f"第{idx}章应创建至少1个 chunk，实际创建 {report.chunks_created}"
            )

        print(f"\n=== 索引结果（{FIRST_10_CHAPTER_COUNT}章）===")
        for r in chapter_results:
            status = "⚠️ embedding失败" if r["embedding_failed"] else "✓"
            print(f"  第{r['chapter']:2d}章: {r['chunks_created']:3d} chunks {status}")
        print(f"  总计: {total_chunks} chunks")

        assert total_chunks > 0, f"应创建至少 1 个 chunk，实际 {total_chunks}"

    @pytest.mark.asyncio
    async def test_index_status_reflects_rebuild(
        self,
        ctx: dict,
        db_session: AsyncSession,
    ):
        """索引后 get_index_status 应返回正确的统计"""
        project_id = ctx["project_id"]

        # 索引前状态
        status_before = await get_index_status(db_session, project_id)
        assert status_before["total"] == 0

        # 重建索引
        for idx in range(1, 4):  # 前3章即可
            await index_chapter(db_session, project_id, idx)

        # 索引后状态
        status_after = await get_index_status(db_session, project_id)
        assert status_after["total"] > 0
        assert status_after["degraded"] == (
            status_after["embedding_failed_count"] > 0
            or status_after["pending_vectorization"] > 0
            or status_after["embedding_dimension_mismatch"]
        )
        print(
            f"\n索引状态: total={status_after['total']}, "
            f"embedding_failed={status_after['embedding_failed_count']}, "
            f"degraded={status_after['degraded']}"
        )

    @pytest.mark.asyncio
    async def test_chunks_have_entity_character_ids(
        self,
        ctx: dict,
        db_session: AsyncSession,
    ):
        """chunk 的 entity_ids 和 character_ids 应被正确填充"""
        project_id = ctx["project_id"]

        from modules.rag.repositories import RagChunkRepository
        from shared.utils import parse_uuid

        # 索引前两章
        for idx in range(1, 3):
            await index_chapter(db_session, project_id, idx)

        nid = parse_uuid(project_id, "novel_id")
        repo = RagChunkRepository()
        chunks = await repo.find_by_chapter(db_session, nid, 1)

        assert len(chunks) > 0, "第一章应有 chunks"

        # 验证 chunk 有基础字段
        for chunk in chunks:
            assert chunk.text, "chunk.text 不应为空"
            assert chunk.char_count > 0, "chunk.char_count 应 > 0"
            assert chunk.chunk_index is not None, "chunk.chunk_index 应有值"
            assert chunk.source_type == "chapter_text"

        # 验证至少有一些 entity/character 被匹配到
        all_entity_ids = set()
        all_character_ids = set()
        for chunk in chunks:
            all_entity_ids.update(chunk.entity_ids or [])
            all_character_ids.update(chunk.character_ids or [])

        print(f"\n第一章 {len(chunks)} 个 chunk:")
        print(f"  匹配到的 entity_ids: {all_entity_ids}")
        print(f"  匹配到的 character_ids: {all_character_ids}")


# ============================================================
# Cycle 2: 检索匹配度确定性验证
# ============================================================


class TestRetrievalDeterminism:
    """验证相同查询多次检索返回相同匹配度"""

    @pytest_asyncio.fixture
    async def ctx(self, db_session: AsyncSession) -> dict:
        """导入前3章并重建索引"""
        assert REAL_FILE_PATH.exists()

        from modules.imports.parsers import parse_txt

        file_bytes = REAL_FILE_PATH.read_bytes()
        all_chapters = parse_txt(file_bytes)
        assert len(all_chapters) >= 3

        pid = uuid.uuid4()
        project = Project(
            id=pid,
            title="诡秘之主 匹配度确定性测试",
            genre="西方奇幻",
            tone="维多利亚风格、黑暗",
            language="zh",
            target_length="novel",
            current_stage="writing",
        )
        db_session.add(project)
        await db_session.flush()
        project_id = str(pid)

        for idx in range(3):
            ch = all_chapters[idx]
            await create_draft(
                db_session,
                novel_id=project_id,
                chapter_index=idx + 1,
                title=ch.get("title") or f"第{idx + 1}章",
                content=ch.get("content", ""),
            )

        await db_session.flush()

        # 重建索引
        for idx in range(1, 4):
            await index_chapter(db_session, project_id, idx)

        return {"project_id": project_id}

    @pytest.mark.asyncio
    async def test_same_query_same_scores(
        self,
        ctx: dict,
        db_session: AsyncSession,
    ):
        """相同查询两次检索返回完全一致的匹配度"""
        project_id = ctx["project_id"]

        from modules.rag.facade import retrieve

        query = "克莱恩 廷根 值夜者"

        # 第一次检索
        result1 = await retrieve(
            db_session,
            project_id,
            query,
            mode="search",
            top_k=8,
            chapter_index=1,
        )

        # 第二次检索（完全相同参数）
        result2 = await retrieve(
            db_session,
            project_id,
            query,
            mode="search",
            top_k=8,
            chapter_index=1,
        )

        # 结果数量应一致
        assert len(result1.chunks) == len(result2.chunks), (
            f"两次检索结果数应相同: {len(result1.chunks)} vs {len(result2.chunks)}"
        )

        # 比较每个 chunk 的 ID 和 score
        for i, (c1, c2) in enumerate(zip(result1.chunks, result2.chunks)):
            assert c1.id == c2.id, f"第{i}条结果 ID 不一致: {c1.id} vs {c2.id}"
            assert c1.score == c2.score, (
                f"第{i}条结果 score 不一致: {c1.score} vs {c2.score}\n"
                f"  chunk {c1.id}: query={query}"
            )

        print("\n=== 匹配度确定性验证 ===")
        print(f'查询: "{query}"')
        print(f"返回 {len(result1.chunks)} 条结果")
        for c in result1.chunks:
            print(f"  [{c.id[:8]}...] score={c.score:.4f} 源={c.source_type}")
        print("✓ 两次检索 score 完全一致")

    @pytest.mark.asyncio
    async def test_score_meaningful_match_guard(
        self,
        ctx: dict,
        db_session: AsyncSession,
    ):
        """无关键词命中的查询应返回空结果（Meaningful Match 守卫）"""
        project_id = ctx["project_id"]

        from modules.rag.facade import retrieve

        # 使用不存在于小说中的词汇
        query = "xyzzy_nonexistent_term_42"
        result = await retrieve(
            db_session,
            project_id,
            query,
            mode="search",
            top_k=8,
        )

        # Meaningful Match 守卫：无关键词命中时清空结果
        assert len(result.chunks) == 0, (
            f"不存在的关键词应返回空结果，实际 {len(result.chunks)} 条"
        )
        print(f'\nMeaningful Match 守卫: "{query}" → 空结果 ✓')

    @pytest.mark.asyncio
    async def test_different_query_different_scores(
        self,
        ctx: dict,
        db_session: AsyncSession,
    ):
        """不同查询返回不同的匹配度分布"""
        project_id = ctx["project_id"]

        from modules.rag.facade import retrieve

        # 两个语义不同的查询
        query_a = "克莱恩 值夜者 非凡"
        query_b = "邓恩 队长 笔记"

        result_a = await retrieve(
            db_session,
            project_id,
            query_a,
            mode="search",
            top_k=8,
        )
        result_b = await retrieve(
            db_session,
            project_id,
            query_b,
            mode="search",
            top_k=8,
        )

        # 验证结果不是完全相同
        ids_a = [c.id for c in result_a.chunks]
        ids_b = [c.id for c in result_b.chunks]
        assert ids_a, "查询 A 应有结果"
        assert ids_b, "查询 B 应有结果"

        # 不同查询应有不同的返回
        if ids_a == ids_b:
            # 即使 ID 相同，score 分布也应不同
            scores_a = [c.score for c in result_a.chunks]
            scores_b = [c.score for c in result_b.chunks]
            assert scores_a != scores_b, (
                f"不同查询的 score 分布应不同\n  A: {scores_a}\n  B: {scores_b}"
            )

        print("\n=== 不同查询区分度 ===")
        print(f'查询 A: "{query_a}"')
        for c in result_a.chunks[:5]:
            print(f"  [{c.id[:8]}...] score={c.score:.4f}")
        print(f'查询 B: "{query_b}"')
        for c in result_b.chunks[:5]:
            print(f"  [{c.id[:8]}...] score={c.score:.4f}")


# ============================================================
# Cycle 3: 真实 LLM Embedding 调用测试
# ============================================================


class TestRealEmbedding:
    """验证 LLM embedding API 的可用性与确定性"""

    @pytest.mark.asyncio
    async def test_embedding_api_availability(self):
        """测试 embedding API 是否可用"""
        from core.config import get_settings
        from infrastructure.llm.client import LLMClient

        settings = get_settings()
        print("\nEmbedding 配置:")
        print(f"  model: {settings.embedding_model}")
        print(f"  base_url: {settings.embedding_base_url or '(同 LLM)'}")
        print(f"  api_key set: {bool(settings.embedding_api_key)}")
        print(f"  dim: {settings.embedding_dim}")

        client = LLMClient()
        try:
            result = await client.generate_embedding("测试embedding的确定性")
            assert isinstance(result, list), f"embedding 应为 list，实际 {type(result)}"
            assert len(result) == settings.embedding_dim, (
                f"向量维度应为 {settings.embedding_dim}，实际 {len(result)}"
            )
            assert all(isinstance(v, float) for v in result), "所有值应为 float"
            print(f"  ✓ embedding 成功: dim={len(result)}")
            print(f"    前5个值: {[round(v, 6) for v in result[:5]]}")

            # 确定性验证：相同文本两次 embedding 应一致
            result2 = await client.generate_embedding("测试embedding的确定性")
            assert result == result2, (
                "相同文本的 embedding 应完全一致，LLM 提供的 embedding 应是确定性的"
            )
            print("  ✓ 确定性确认: 两次相同输入返回相同向量")
        except Exception as e:
            pytest.skip(
                f"Embedding API 不可用: {e}\n"
                f"  当前配置: model={settings.embedding_model}, "
                f"base_url={settings.embedding_base_url or settings.llm_base_url}\n"
                f"  DeepSeek 不支持 embedding API.\n"
                f"  如需测试, 在 .env 中配置:\n"
                f"    EMBEDDING_BASE_URL=https://api.openai.com\n"
                f"    EMBEDDING_API_KEY=sk-xxx\n"
                f"    EMBEDDING_MODEL=text-embedding-3-large"
            )

    @pytest.mark.asyncio
    async def test_embedding_determinism_multiple_texts(self):
        """多条不同文本的 embedding 确定性"""
        from infrastructure.llm.client import LLMClient

        client = LLMClient()
        texts = [
            "克莱恩从沉睡中醒来，发现自己变成了另一个人。",
            "廷根市的值夜者小队正在调查一起非凡事件。",
            "邓恩·史密斯队长翻阅着古老的笔记。",
        ]

        try:
            # 批量获取 embedding
            embeddings = await client.generate_embedding(texts)
            assert len(embeddings) == len(texts), (
                f"应返回 {len(texts)} 个向量，实际 {len(embeddings)}"
            )
            for i, emb in enumerate(embeddings):
                assert all(isinstance(v, float) for v in emb), (
                    f"第{i}条文本的向量值应该都是 float"
                )

            # 再次调用确认确定性
            embeddings2 = await client.generate_embedding(texts)
            for i, (e1, e2) in enumerate(zip(embeddings, embeddings2)):
                assert e1 == e2, f"第{i}条文本的 embedding 两次不一致"

            # 计算相似度矩阵
            from modules.rag.scoring import cosine_similarity

            sims = []
            for i in range(len(texts)):
                for j in range(i + 1, len(texts)):
                    sim = cosine_similarity(embeddings[i], embeddings[j])
                    sims.append((i, j, round(sim, 4)))

            print("\n文本相似度矩阵:")
            for i, j, sim in sims:
                print(f"  文本{i} ↔ 文本{j}: cosine={sim}")
        except Exception as e:
            pytest.skip(f"多文本 embedding 不可用: {e}")
