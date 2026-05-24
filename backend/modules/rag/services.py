"""
RAG 业务逻辑层

提供文本分块、embedding 生成和混合检索服务。
"""

from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.rag.models import RagChunk
from modules.rag.repositories import RagChunkRepository
from modules.rag.schemas import (
    RagChunkCreate,
    RagChunkResponse,
    SimilarEntity,
)
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
# EmbeddingService
# ============================================================

class EmbeddingService:
    """Embedding 生成服务

    MVP 阶段提供预留接口。
    生产环境应接入 OpenAI Embedding API 或本地 embedding 模型。
    """

    async def generate_embedding(
        self,
        text: str,
        model: str | None = None,
    ) -> list[float] | None:
        """生成文本 embedding（预留接口）

        当前返回 None，表示未接入 embedding 服务。
        生产环境应：
        1. 调用 LLM provider 的 embedding API
        2. 或使用本地 embedding 模型
        3. 返回符合 embedding_dim 的 float 列表

        Args:
            text: 要生成 embedding 的文本
            model: 模型名称（可选，使用默认模型）

        Returns:
            list[float] | None — 嵌入向量或 None（未接入时）
        """
        # 预留接口 — 后续接入具体 embedding 实现
        return None

    async def generate_embeddings_batch(
        self,
        texts: list[str],
        model: str | None = None,
    ) -> list[list[float] | None]:
        """批量生成 embedding（预留接口）"""
        return [await self.generate_embedding(t, model) for t in texts]


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
        self._embedding = EmbeddingService()

    async def hybrid_search(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        query: str,
        *,
        entity_ids: list[str] | None = None,
        character_ids: list[str] | None = None,
        thread_ids: list[str] | None = None,
        chapter_index: int | None = None,
        visibility: str | None = None,
        top_k: int = 12,
    ) -> list[tuple[RagChunk, float]]:
        """混合检索：关键词 + 关系 + 重要性 + 向量（预留）

        评分公式：
          score = 0.45 * vector_score (预留时取 0)
                + 0.30 * keyword_score
                + 0.15 * relation_score
                + 0.10 * importance_score

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

        scored_chunks: list[tuple[Any, float]] = []

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

            # 向量评分（预留，当前为 0）
            vector_score = 0.0

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

    async def find_similar_entities(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        candidate_embedding: list[float],
        entity_type: str | None = None,
        top_k: int = 8,
    ) -> list[SimilarEntity]:
        """查找语义相似的实体（预留接口）

        当前返回空列表，因为内存 SQLite 不支持 pgvector。
        生产环境中应:
        1. 查询 world_entities 表（带 embedding 列）
        2. 使用余弦距离: embedding <=> :candidate
        3. 可选按 entity_type 过滤
        4. 返回名称和相似度

        Args:
            db: 数据库 session
            novel_id: 小说项目 ID
            candidate_embedding: 候选对象的 embedding 向量
            entity_type: 可选的实体类型过滤
            top_k: 返回的最大结果数

        Returns:
            list[SimilarEntity] — 相似实体列表
        """
        # 预留接口 — 后续接入 pgvector 语义相似查询
        return []

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

    @staticmethod
    def _normalize_scores(
        scored_chunks: list[tuple[RagChunk, float]],
    ) -> list[tuple[RagChunk, float]]:
        """Min-max 归一化评分到 0.0-1.0 范围"""
        if not scored_chunks:
            return scored_chunks

        scores = [s for _, s in scored_chunks]
        min_s = min(scores)
        max_s = max(scores)

        if max_s - min_s < 0.001:
            return [(c, 1.0) for c, _ in scored_chunks]

        return [
            (c, (s - min_s) / (max_s - min_s))
            for c, s in scored_chunks
        ]
