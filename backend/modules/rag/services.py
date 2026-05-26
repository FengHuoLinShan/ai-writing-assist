"""
RAG 业务逻辑层

提供文本分块、embedding 生成和混合检索服务。
"""

from __future__ import annotations

import math
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from modules.rag.models import RagChunk
from modules.rag.repositories import RagChunkRepository
from modules.rag.schemas import RagChunkCreate
from shared.constants import (
    RAG_IMPORTANCE_WEIGHT,
    RAG_KEYWORD_WEIGHT,
    RAG_RELATION_WEIGHT,
    RAG_VECTOR_WEIGHT,
)


# ============================================================
# ChunkingService
# ============================================================

class ChunkingService:
    """文本分块服务

    将长文本分割为适合检索的片段。
    MVP 简单实现：按段落分割，每段为一个 chunk。
    后续可扩展为滑动窗口、语义分割等策略。
    """

    DEFAULT_MAX_CHUNK_LENGTH: int = 2000
    """默认最大 chunk 长度（字符数）"""

    def split_by_paragraphs(
        self,
        text: str,
        max_length: int | None = None,
    ) -> list[str]:
        """按段落分割文本

        每个段落为一个 chunk。
        如果段落超过 max_length，则进一步按句号分割。

        Args:
            text: 要分割的文本
            max_length: 最大 chunk 长度

        Returns:
            str 列表，每个元素为一个 chunk
        """
        max_len = max_length or self.DEFAULT_MAX_CHUNK_LENGTH
        if not text.strip():
            return []

        # 先按段落（两个换行符）分割
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

        chunks: list[str] = []
        for para in paragraphs:
            if len(para) <= max_len:
                chunks.append(para)
            else:
                # 超长段落按句号分割
                sentences = para.replace("。", "。\n").replace("！", "！\n").replace("？", "？\n").split("\n")
                current = ""
                for sentence in sentences:
                    s = sentence.strip()
                    if not s:
                        continue
                    if len(current) + len(s) < max_len:
                        current += s
                    else:
                        if current:
                            chunks.append(current)
                        current = s
                if current:
                    chunks.append(current)

        return chunks

    def split_by_length(
        self,
        text: str,
        chunk_size: int = 1000,
        overlap: int = 100,
    ) -> list[str]:
        """按固定长度分割文本（带重叠）

        Args:
            text: 要分割的文本
            chunk_size: 每个 chunk 的目标字符数
            overlap: 相邻 chunk 的重叠字符数

        Returns:
            str 列表
        """
        if not text.strip():
            return []

        chunks: list[str] = []
        start = 0
        text_len = len(text)

        while start < text_len:
            end = min(start + chunk_size, text_len)
            # 尽量在段落或句子边界结束
            if end < text_len:
                # 尝试在最后一个句号处断开
                last_period = text.rfind("。", start, end)
                if last_period > start + chunk_size // 2:
                    end = last_period + 1
                else:
                    # 尝试在最后一个换行处断开
                    last_newline = text.rfind("\n", start, end)
                    if last_newline > start + chunk_size // 2:
                        end = last_newline + 1

            chunks.append(text[start:end].strip())
            start = end - overlap if end < text_len else text_len

        return chunks

    def extract_summary(self, chunk_text: str, max_length: int = 200) -> str:
        """提取片段摘要

        取片段前若干字符作为摘要。

        Args:
            chunk_text: 片段文本
            max_length: 摘要最大长度

        Returns:
            摘要字符串
        """
        if len(chunk_text) <= max_length:
            return chunk_text
        return chunk_text[:max_length].rstrip() + "…"


# ============================================================
# RetrievalService
# ============================================================

class RetrievalService:
    """混合检索服务

    组合关键词检索、关系匹配、重要性评分进行混合排序。
    向量检索作为预留接口，有 pgvector 时启用。
    """

    def __init__(self) -> None:
        self._repo = RagChunkRepository()
        self._chunking = ChunkingService()

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """计算余弦相似度

        Args:
            a: 向量 A
            b: 向量 B

        Returns:
            -1.0 ~ 1.0 的余弦相似度，零向量时返回 0.0
        """
        if not a or not b or len(a) != len(b):
            return 0.0

        dot = sum(ai * bi for ai, bi in zip(a, b))
        norm_a = math.sqrt(sum(ai * ai for ai in a))
        norm_b = math.sqrt(sum(bi * bi for bi in b))

        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0

        return dot / (norm_a * norm_b)

    async def hybrid_search(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        query: str,
        *,
        query_embedding: list[float] | None = None,
        entity_ids: list[str] | None = None,
        character_ids: list[str] | None = None,
        thread_ids: list[str] | None = None,
        chapter_index: int | None = None,
        visibility: str | None = None,
        top_k: int = 12,
    ) -> list[tuple[RagChunk, float]]:
        """混合检索：关键词 + 关系 + 重要性 + 向量

        评分公式：
          score = 0.45 * vector_score
                + 0.30 * keyword_score
                + 0.15 * relation_score
                + 0.10 * importance_score

        Args:
            query_embedding: 查询的 embedding 向量（启用向量检索时传入）

        Returns:
            list[(RagChunk, score)] — 按评分降序排列
        """
        # Step 1: 关键词检索
        keyword_chunks = await self._repo.keyword_search(
            db,
            novel_id,
            query,
            entity_ids=entity_ids,
            character_ids=character_ids,
            thread_ids=thread_ids,
            chapter_index=chapter_index,
            visibility=visibility,
            limit=top_k * 2,  # 扩大召回以进行重排序
        )

        # 去重（同一 chunk 可能被多个关键词匹配）
        seen_ids: set[uuid.UUID] = set()
        unique_chunks: list[RagChunk] = []
        for chunk in keyword_chunks:
            if chunk.id not in seen_ids:
                seen_ids.add(chunk.id)
                unique_chunks.append(chunk)

        # Step 2: 计算每个 chunk 的混合评分
        # 对中文查询不分词，直接用整个查询做子串匹配
        query_lower = query.lower().strip()
        query_terms = [q.strip().lower() for q in query.split() if q.strip()]
        use_chinese_match = not query_terms or all(
            ord(c) > 127 for c in query.replace(" ", "")
        )
        scored_chunks: list[tuple[RagChunk, float]] = []

        for chunk in unique_chunks:
            # 关键词评分：中文用全查询子串匹配，英文用词匹配
            if use_chinese_match and query_lower:
                keyword_score = 1.0 if query_lower in chunk.text.lower() else 0.0
            else:
                keyword_score = self._compute_keyword_score(chunk.text, query_terms)

            # 关系评分：匹配的 entity/character/thread ID 数量
            relation_score = self._compute_relation_score(
                chunk,
                entity_ids=entity_ids,
                character_ids=character_ids,
                thread_ids=thread_ids,
            )

            # 重要性/新颖性评分
            importance_score = chunk.importance

            # 向量评分（有 query_embedding 时启用）
            vector_score = 0.0
            if query_embedding is not None and chunk.embedding is not None:
                # chunk.embedding 可能是 bytes（SQLite）或 list[float]（pgvector）
                chunk_emb = chunk.embedding
                if isinstance(chunk_emb, list) and len(chunk_emb) == len(query_embedding):
                    vector_score = self._cosine_similarity(query_embedding, chunk_emb)
                # 余弦相似度范围 [-1, 1] 映射到 [0, 1] 作为评分
                vector_score = max(0.0, vector_score)

            # 综合评分
            total_score = (
                RAG_VECTOR_WEIGHT * vector_score
                + RAG_KEYWORD_WEIGHT * keyword_score
                + RAG_RELATION_WEIGHT * relation_score
                + RAG_IMPORTANCE_WEIGHT * importance_score
            )

            scored_chunks.append((chunk, total_score))

        # Step 3: 按评分降序排列，取 top_k
        scored_chunks.sort(key=lambda x: x[1], reverse=True)

        # 如果所有 chunk 都只有 importance 得分（无关键词/关系/向量匹配）
        # 说明查询与内容无实质匹配，返回空结果避免 importance 劫持
        has_meaningful_match = False
        for chunk, _ in scored_chunks[:top_k]:
            if use_chinese_match:
                kw = 1.0 if query_lower in chunk.text.lower() else 0.0
            else:
                kw = self._compute_keyword_score(chunk.text, query_terms)
            if kw > 0:
                has_meaningful_match = True
                break

        if not has_meaningful_match:
            return []

        return scored_chunks[:top_k]

    # ============================================================
    # 内部评分方法
    # ============================================================

    @staticmethod
    def _compute_keyword_score(text: str, query_terms: list[str]) -> float:
        """计算关键词匹配评分

        基于查询词在文本中的出现比例。

        Args:
            text: 待评分的文本
            query_terms: 查询词列表（小写）

        Returns:
            0.0-1.0 的评分
        """
        if not query_terms:
            return 0.0

        text_lower = text.lower()
        match_count = sum(1 for term in query_terms if term in text_lower)
        return match_count / len(query_terms)

    @staticmethod
    def _compute_relation_score(
        chunk: RagChunk,
        *,
        entity_ids: list[str] | None = None,
        character_ids: list[str] | None = None,
        thread_ids: list[str] | None = None,
    ) -> float:
        """计算关系匹配评分

        基于 chunk 关联的 entity/character/thread ID 与查询过滤条件的重叠度。

        Args:
            chunk: RAG 片段
            entity_ids: 查询过滤的实体 ID 列表
            character_ids: 查询过滤的人物 ID 列表
            thread_ids: 查询过滤的剧情线 ID 列表

        Returns:
            0.0-1.0 的评分
        """
        total_fields = 0
        matched_score = 0.0

        # 实体匹配
        chunk_entities: list[str] = chunk.entity_ids or []
        if entity_ids:
            total_fields += 1
            entity_set = set(e.lower() for e in entity_ids)
            chunk_entity_set = set(e.lower() for e in chunk_entities)
            if entity_set and chunk_entity_set:
                overlap = len(entity_set & chunk_entity_set)
                matched_score += overlap / len(entity_set)

        # 人物匹配
        chunk_characters: list[str] = chunk.character_ids or []
        if character_ids:
            total_fields += 1
            char_set = set(c.lower() for c in character_ids)
            chunk_char_set = set(c.lower() for c in chunk_characters)
            if char_set and chunk_char_set:
                overlap = len(char_set & chunk_char_set)
                matched_score += overlap / len(char_set)

        # 剧情线匹配
        chunk_threads: list[str] = chunk.thread_ids or []
        if thread_ids:
            total_fields += 1
            thread_set = set(t.lower() for t in thread_ids)
            chunk_thread_set = set(t.lower() for t in chunk_threads)
            if thread_set and chunk_thread_set:
                overlap = len(thread_set & chunk_thread_set)
                matched_score += overlap / len(thread_set)

        if total_fields == 0:
            return 0.0
        return matched_score / total_fields


# ============================================================
# IndexingService
# ============================================================

class IndexingService:
    """章节索引服务

    将章节正文处理为 RAG chunk 并生成 embedding。
    编排了读取草稿、分割、角色匹配、去重创建和批量 embedding 的全流程。
    """

    def __init__(self) -> None:
        self._repo = RagChunkRepository()
        self._chunking = ChunkingService()

    async def index_chapter(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
    ) -> int:
        """索引指定章节的正文到 RAG 库

        1. 读取该章节最新草稿
        2. 按段落分割为 chunk
        3. 文本匹配已有角色名，标记 character_ids
        4. 删除该章节旧 chunk（替换）
        5. 创建新 chunk
        6. 批量生成 embedding（失败不阻塞）

        Args:
            db: 数据库 session
            novel_id: 小说项目 UUID
            chapter_index: 章节索引

        Returns:
            int — 创建的 chunk 数量（无草稿返回 0）
        """
        from modules.writing.facade import get_latest_draft_for_chapter

        draft = await get_latest_draft_for_chapter(db, str(novel_id), chapter_index)
        if not draft or not draft.content:
            return 0

        # 1. 分割为段落
        paragraphs = self._chunking.split_by_paragraphs(draft.content)
        if not paragraphs:
            return 0

        # 2. 加载所有角色名（用于文本匹配）
        from modules.character.facade import list_characters as _list_chars

        chars_list, _ = await _list_chars(db, str(novel_id), limit=999)
        char_name_map: dict[str, str] = {}
        for c in chars_list:
            char_name_map[c.name] = str(c.id)

        # 3. 删除旧 chunk
        await self._repo.delete_by_chapter(db, novel_id, "chapter_text", chapter_index)

        # 4. 创建新 chunk（记录 ID 和文本用于批量 embedding）
        import logging

        logger = logging.getLogger(__name__)
        created = 0
        created_chunks: list[tuple[uuid.UUID, str]] = []
        for para in paragraphs:
            matched_char_ids: list[str] = []
            for name, cid in char_name_map.items():
                if name in para:
                    matched_char_ids.append(cid)

            chunk_data = RagChunkCreate(
                source_type="chapter_text",
                chapter_index=chapter_index,
                text=para,
                character_ids=matched_char_ids,
                visibility="author_only",
                importance=0.5,
                meta={"chapter_index": chapter_index},
            )
            chunk = await self._repo.create(db, novel_id, chunk_data)
            created_chunks.append((chunk.id, para))
            created += 1

        await db.flush()

        # 5. 批量生成 embedding
        if created_chunks:
            try:
                from infrastructure.llm.client import LLMClient

                llm = LLMClient()
                texts = [t for _, t in created_chunks]
                embeddings = await llm.generate_embedding(texts)
                if isinstance(embeddings, list) and len(embeddings) == len(created_chunks):
                    for (chunk_id, _), emb in zip(created_chunks, embeddings):
                        await self._repo.update_embedding(db, chunk_id, emb)
                    await db.flush()
            except Exception as exc:
                logger.warning("Failed to generate embeddings for chapter %d: %s", chapter_index, exc)

        return created

