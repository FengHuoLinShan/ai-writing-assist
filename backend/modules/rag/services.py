"""
RAG 业务逻辑层

提供文本分块、embedding 生成和混合检索服务。
"""

from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from modules.rag.contracts import RagIndexReport, RagResultBundle
from modules.rag.models import RagChunk
from modules.rag.repositories import RagChunkRepository
from modules.rag.schemas import RagChunkCreate
from shared.constants import (
    RAG_IMPORTANCE_WEIGHT,
    RAG_KEYWORD_WEIGHT,
    RAG_RELATION_WEIGHT,
    RAG_VECTOR_WEIGHT,
)

RAG_INDEX_VERSION = "cn-novel-v1"


@dataclass(frozen=True)
class ChineseNovelChunk:
    """中文小说正文分块结果。"""

    chunk_index: int
    text: str
    start_offset: int
    end_offset: int
    char_count: int


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

    DEFAULT_CN_TARGET_LENGTH: int = 900
    DEFAULT_CN_MAX_LENGTH: int = 1400
    DEFAULT_CN_OVERLAP: int = 160

    SCENE_TRANSITION_PATTERNS: list[str] = [
        # 时间跳跃
        "第二天", "次日", "翌日", "几日", "数日", "一个月后",
        "不久之后", "转眼", "转眼间", "黄昏", "清晨",
        "夜晚", "入夜", "黎明", "次日清晨", "翌日清晨", "半夜",
        "过了几日", "又过了几日", "几个月后", "半年后", "一年后",
        "三日后", "七日后", "十日后",
        "那一年", "从此", "多年后", "曾经", "从前", "后来",
        "此刻", "就在这时", "突然", "不一会儿",
        # 空间/视角切换
        "与此同时", "另一边", "另一方面",
        "画面一转", "镜头一转", "视角切",
        # 分隔符
        "***", "---", "===",
        "——", "……",
    ]

    # 地点转换动词 — 在这些词之后紧跟地点时，优先作为切分点
    LOCATION_TRANSITION_VERBS: list[str] = [
        "回到", "来到", "走进", "离开", "返回", "前往",
        "抵达", "步入", "踏入", "跨入",
    ]

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
                sentences = (
                    para.replace("。", "。\n")
                    .replace("！", "！\n")
                    .replace("？", "？\n")
                    .split("\n")
                )
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

    def split_chinese_novel(
        self,
        text: str,
        *,
        target_length: int | None = None,
        max_length: int | None = None,
        overlap: int | None = None,
    ) -> list[ChineseNovelChunk]:
        """面向中文长篇小说的正文分块。

        优先在段落、对话和中文句末标点处切分，并记录原文 offset。
        相邻 chunk 保留少量重叠，便于人物出场和状态变化的前后文召回。
        """
        if not text or not text.strip():
            return []

        target = target_length or self.DEFAULT_CN_TARGET_LENGTH
        max_len = max_length or self.DEFAULT_CN_MAX_LENGTH
        overlap_len = overlap if overlap is not None else self.DEFAULT_CN_OVERLAP
        overlap_len = max(0, min(overlap_len, max_len // 2))

        chunks: list[ChineseNovelChunk] = []
        text_len = len(text)
        start = self._skip_whitespace(text, 0)

        while start < text_len:
            hard_end = min(start + max_len, text_len)
            if hard_end >= text_len:
                end = text_len
            else:
                end = self._choose_cn_boundary_with_scenes(text, start, target, hard_end)

            raw = text[start:end]
            stripped = raw.strip()
            if stripped:
                leading_ws = len(raw) - len(raw.lstrip())
                trailing_ws = len(raw) - len(raw.rstrip())
                adjusted_start = start + leading_ws
                adjusted_end = end - trailing_ws
                chunks.append(
                    ChineseNovelChunk(
                        chunk_index=len(chunks),
                        text=stripped,
                        start_offset=adjusted_start,
                        end_offset=adjusted_end,
                        char_count=len(stripped),
                    ),
                )

            if end >= text_len:
                break

            next_start = max(start + 1, end - overlap_len)
            start = self._skip_whitespace(text, next_start)

        return chunks

    @staticmethod
    def _skip_whitespace(text: str, start: int) -> int:
        while start < len(text) and text[start].isspace():
            start += 1
        return start

    @classmethod
    def _choose_cn_boundary_with_scenes(
        cls,
        text: str,
        start: int,
        target_length: int,
        hard_end: int,
    ) -> int:
        """优先在语义边界（场景转换/地点转换/段落）处切分，回退到标点。

        优先级：场景转换关键词 > 地点转换 > 段落边界 > 句子边界 > 硬截断
        """
        min_end = min(start + max(80, target_length // 2), hard_end)
        target_end = min(start + target_length, hard_end)

        # 搜索窗口内的候选切分点，记录 (位置, 优先级, 距离目标偏差)
        candidates: list[tuple[int, int, float]] = []
        # 优先级: 1=场景转换关键词, 2=地点转换, 3=段落边界, 4=句子边界

        # 1) 场景转换关键词（最高优先级）
        for pattern in cls.SCENE_TRANSITION_PATTERNS:
            pos = text.rfind(pattern, min_end, hard_end)
            if pos >= min_end:
                dist = abs(pos - target_end)
                candidates.append((pos, 1, dist))

        # 2) 地点转换（段落开头出现地点动词）
        for verb in cls.LOCATION_TRANSITION_VERBS:
            # 在段落开头搜索
            para_start = text.rfind("\n\n", min_end, hard_end)
            if para_start < 0:
                para_start = text.rfind("\n", min_end, hard_end)
            if para_start >= min_end:
                para_text = text[para_start:hard_end]
                if verb in para_text[:20]:
                    dist = abs(para_start - target_end)
                    candidates.append((para_start, 2, dist))

        # 3) 段落边界
        para_pos = text.rfind("\n\n", min_end, hard_end)
        if para_pos >= min_end:
            dist = abs(para_pos - target_end)
            candidates.append((para_pos + 2, 3, dist))
        else:
            para_pos = text.rfind("\n", min_end, hard_end)
            if para_pos >= min_end:
                dist = abs(para_pos - target_end)
                candidates.append((para_pos + 1, 3, dist))

        # 4) 句子边界
        for punct in ("。", "！", "？", "”", "」"):
            pos = text.rfind(punct, min_end, hard_end)
            if pos >= min_end:
                dist = abs(pos - target_end)
                candidates.append((pos + 1, 4, dist))

        # 按优先级排序，同优先级按距离
        if candidates:
            candidates.sort(key=lambda x: (x[1], x[2]))
            return candidates[0][0]

        # 无可用边界，硬截断到 target_end
        return min(target_end, hard_end)
        return hard_end

    @staticmethod
    def _choose_cn_boundary(
        text: str,
        start: int,
        target_length: int,
        hard_end: int,
    ) -> int:
        min_end = min(start + max(80, target_length // 2), hard_end)
        target_end = min(start + target_length, hard_end)

        boundary_patterns = ("\n\n", "\r\n\r\n", "。", "！", "？", "”", "」", "\n")
        best = -1
        for pattern in boundary_patterns:
            pos = text.rfind(pattern, min_end, hard_end)
            if pos >= min_end:
                candidate = pos + len(pattern)
                if abs(candidate - target_end) < abs(best - target_end) or best < 0:
                    best = candidate
        if best > start:
            return best
        return hard_end

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

    _CHINESE_SEP_RE = re.compile(r'[\s,，.。!！?？、·]+')

    @staticmethod
    def _smart_tokenize_chinese(query: str) -> list[str]:
        if not query or not query.strip():
            return []
        raw_terms = RetrievalService._CHINESE_SEP_RE.split(query.strip())
        return [term.lower() for term in raw_terms if len(term) >= 2]

    @staticmethod
    def _compute_keyword_score_with_proximity(
        text: str,
        query_terms: list[str],
    ) -> float:
        if not query_terms:
            return 0.0
        text_lower = text.lower()
        matched_count = sum(1 for t in query_terms if t in text_lower)
        overlap_ratio = matched_count / len(query_terms)
        if len(query_terms) <= 1 or matched_count < 2:
            return overlap_ratio
        positions: list[tuple[int, str]] = []
        for term in query_terms:
            idx = text_lower.find(term)
            if idx >= 0:
                positions.append((idx, term))
        if len(positions) < 2:
            return overlap_ratio
        positions.sort(key=lambda x: x[0])
        min_distance = float("inf")
        for i in range(len(positions) - 1):
            dist = positions[i + 1][0] - positions[i][0]
            min_distance = min(min_distance, dist)
        proximity_bonus = max(0.0, 1.0 - min_distance / 500) * 0.2
        return min(1.0, overlap_ratio + proximity_bonus)

    @staticmethod
    def _compute_dynamic_weights(
        query: str,
    ) -> tuple[float, float, float, float]:
        """根据查询长度动态调整权重。

        短查询（<10 字，如人名/地名）：偏向关键词匹配
        长查询（>50 字，如段落描述）：偏向语义向量
        """
        vw = RAG_VECTOR_WEIGHT
        kw = RAG_KEYWORD_WEIGHT
        rw = RAG_RELATION_WEIGHT
        iw = RAG_IMPORTANCE_WEIGHT

        qlen = len(query.strip())
        if qlen < 10:
            # 短查询：关键词更重要
            vw *= 0.6
            kw *= 1.5
        elif qlen > 50:
            # 长查询：语义向量更重要
            vw *= 1.2
            kw *= 0.6

        # 重新归一化到和为 1.0
        total = vw + kw + rw + iw
        return (vw / total, kw / total, rw / total, iw / total)

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
        mode: str = "search",
        top_k: int = 12,
        reference_chapter_index: int | None = None,
        weights: tuple[float, float, float, float] | None = None,
    ) -> list[tuple[RagChunk, float]]:
        """混合检索：关键词 + 关系 + 重要性 + 向量

        评分公式：
          score = vw * vector_score + kw * keyword_score
                + rw * relation_score + iw * importance_score

        Args:
            query_embedding: 查询的 embedding 向量（启用向量检索时传入）
            reference_chapter_index: 参考章节索引，用于时序衰减（即时记忆）
            weights: 可选的权重覆盖 (v, k, r, i)，用于调优；默认使用模块常量

        Returns:
            list[(RagChunk, score)] — 按评分降序排列
        """
        vw, kw, rw, iw = weights or self._compute_dynamic_weights(query)
        # Step 1: 关键词检索
        expanded_query = await _expand_query_with_project_terms(
            db,
            novel_id,
            query,
            entity_ids=entity_ids,
            character_ids=character_ids,
            thread_ids=thread_ids,
        )

        relation_only = (
            mode == "extraction"
            and bool(
                entity_ids
                or character_ids
                or thread_ids
                or chapter_index is not None
            )
        )
        repo_query = "" if relation_only else expanded_query

        keyword_chunks = await self._repo.keyword_search(
            db,
            novel_id,
            repo_query,
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
        query_terms = [q.strip().lower() for q in expanded_query.split() if q.strip()]
        use_chinese_match = not query_terms or all(
            ord(c) > 127 for c in expanded_query.replace(" ", "")
        )
        chinese_query_no_spaces = expanded_query.replace(" ", "").lower()
        chinese_terms = self._smart_tokenize_chinese(expanded_query)
        scored_chunks: list[tuple[RagChunk, float]] = []

        for chunk in unique_chunks:
            if use_chinese_match and chinese_terms:
                if len(chinese_terms) > 1:
                    keyword_score = self._compute_keyword_score_with_proximity(
                        chunk.text, chinese_terms,
                    )
                else:
                    keyword_score = (
                        1.0
                        if chinese_query_no_spaces in chunk.text.lower().replace(" ", "")
                        else 0.0
                    )
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

            # 综合评分（权重可覆盖，用于调优）
            total_score = (
                vw * vector_score
                + kw * keyword_score
                + rw * relation_score
                + iw * importance_score
            )

            # 时序衰减：近期章节权重更高
            if reference_chapter_index is not None:
                decay = self._compute_temporal_decay(
                    chunk.chapter_index, reference_chapter_index, mode,
                )
                total_score *= decay

            scored_chunks.append((chunk, total_score))

        # Step 3: 按评分降序排列，取 top_k
        scored_chunks.sort(key=lambda x: x[1], reverse=True)

        # 如果所有 chunk 都只有 importance 得分（无关键词/关系/向量匹配）
        # 说明查询与内容无实质匹配，返回空结果避免 importance 劫持
        has_meaningful_match = False
        for chunk, _ in scored_chunks[:top_k]:
            if use_chinese_match:
                if chinese_terms and len(chinese_terms) > 1:
                    kw = self._compute_keyword_score_with_proximity(
                        chunk.text, chinese_terms,
                    )
                else:
                    kw = (
                        1.0
                        if chinese_query_no_spaces in chunk.text.lower().replace(" ", "")
                        else 0.0
                    )
            else:
                kw = self._compute_keyword_score(chunk.text, query_terms)
            if kw > 0:
                has_meaningful_match = True
                break

        if not has_meaningful_match and mode == "extraction":
            has_meaningful_match = any(
                self._compute_relation_score(
                    chunk,
                    entity_ids=entity_ids,
                    character_ids=character_ids,
                    thread_ids=thread_ids,
                ) > 0
                or (chapter_index is not None and chunk.chapter_index == chapter_index)
                for chunk, _ in scored_chunks[:top_k]
            )

        if not has_meaningful_match:
            return []

        return scored_chunks[:top_k]

    # ============================================================
    # 内部评分方法
    # ============================================================

    @staticmethod
    def _compute_temporal_decay(
        chunk_chapter_index: int | None,
        reference_chapter_index: int | None,
        mode: str,
    ) -> float:
        """计算时序衰减因子。

        mode="extraction"（伏笔检索）：不衰减，返回 1.0。
        mode="search"（即时记忆）：线性衰减，窗口 10 章，最小权重 0.5。
        """
        if mode == "extraction":
            return 1.0
        if reference_chapter_index is None or chunk_chapter_index is None:
            return 1.0

        MAX_WINDOW = 10
        MIN_WEIGHT = 0.5
        distance = abs(chunk_chapter_index - reference_chapter_index)

        if distance >= MAX_WINDOW:
            return MIN_WEIGHT
        return 1.0 - (distance / MAX_WINDOW) * (1.0 - MIN_WEIGHT)

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
    # 检索编排
    # ============================================================

    @staticmethod
    def _is_rerank_enabled(mode: str) -> bool:
        """检查是否启用 LLM 重排序。extraction 模式且配置开启时生效。"""
        from core.config import get_settings

        if mode not in ("extraction",):
            return False
        return get_settings().reranker_enabled

    def _deduplicate_by_embedding(
        self,
        scored_chunks: list[tuple],
        threshold: float = 0.9,
    ) -> list[tuple]:
        """对检索结果进行语义去重。

        利用 chunk 的 embedding 计算余弦相似度，相似度 > threshold 的两个 chunk
        仅保留 char_count 更大者。无 embedding 时跳过。
        """
        if len(scored_chunks) <= 1:
            return scored_chunks

        keep: list[tuple] = []
        removed_indices: set[int] = set()

        for i, (chunk_a, score_a) in enumerate(scored_chunks):
            if i in removed_indices:
                continue
            keep.append((chunk_a, score_a))

            emb_a = chunk_a.embedding
            if emb_a is None:
                continue
            if not isinstance(emb_a, list):
                continue

            for j, (chunk_b, _score_b) in enumerate(scored_chunks):
                if j <= i or j in removed_indices:
                    continue

                emb_b = chunk_b.embedding
                if emb_b is None:
                    continue
                if not isinstance(emb_b, list):
                    continue
                if len(emb_a) != len(emb_b):
                    continue

                sim = self._cosine_similarity(emb_a, emb_b)
                if sim > threshold:
                    count_a = chunk_a.char_count or 0
                    count_b = chunk_b.char_count or 0
                    if count_a >= count_b:
                        removed_indices.add(j)
                    else:
                        keep.pop()
                        keep.append((chunk_b, _score_b))
                        removed_indices.add(i)
                        break

        return keep

    async def retrieve(
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
        mode: str = "search",
        top_k: int = 12,
        reference_chapter_index: int | None = None,
    ) -> RagResultBundle:
        """混合检索编排：embedding 生成 → 混合搜索 → 去重 → 重排序 → 指标记录

        封装完整检索流水线，返回结构化结果束。
        """
        import time as _time

        _t0 = _time.monotonic()
        top_k = max(1, top_k)
        warnings: list[str] = []
        degraded = False
        query_embedding: list[float] | None = None

        # 尝试生成查询 embedding（带熔断保护）
        if await self._repo.has_embeddings(db, novel_id):
            from modules.rag.circuit_breaker import get_circuit_breaker

            cb = get_circuit_breaker()
            if cb.allow_request():
                try:
                    from infrastructure.llm.client import LLMClient

                    embedding = await LLMClient().generate_embedding(query, is_query=True)
                    if (
                        isinstance(embedding, list)
                        and embedding
                        and isinstance(embedding[0], float)
                    ):
                        query_embedding = embedding
                        cb.record_success()
                    else:
                        cb.record_failure()
                        degraded = True
                        warnings.append("embedding 返回格式异常，已降级")
                except Exception as exc:
                    cb.record_failure()
                    degraded = True
                    warnings.append(
                        f"embedding 生成失败，本次检索已降级，结果可能不准确: {exc}",
                    )
            else:
                degraded = True
                warnings.append("BGE 服务熔断中，本次检索已降级为关键词匹配")

        scored_chunks = await self.hybrid_search(
            db,
            novel_id,
            query,
            query_embedding=query_embedding,
            entity_ids=entity_ids,
            character_ids=character_ids,
            thread_ids=thread_ids,
            chapter_index=chapter_index,
            visibility=visibility,
            mode=mode,
            top_k=top_k,
            reference_chapter_index=reference_chapter_index,
        )

        # 语义去重：移除余弦相似度 > 0.9 的冗余 chunk，保留 char_count 更大者
        deduped_chunks = self._deduplicate_by_embedding(scored_chunks, threshold=0.9)

        # LLM 重排序（可选，仅 extraction 模式或显式开启）
        rerank_enabled = self._is_rerank_enabled(mode)
        if rerank_enabled and len(deduped_chunks) > top_k:
            try:
                from modules.rag.reranker import rerank_results

                deduped_chunks = await rerank_results(
                    query, deduped_chunks, top_k=top_k,
                )
            except Exception as exc:
                warnings.append(f"重排序失败，使用原始排序: {exc}")

        # 截断到 top_k
        deduped_chunks = deduped_chunks[:top_k]

        # 转换为 contract
        from modules.rag.mappers import chunk_orm_to_contract as _to_chunk_contract

        chunk_contracts = [
            _to_chunk_contract(chunk, score)
            for chunk, score in deduped_chunks
        ]

        # 记录检索指标
        _latency_ms = (_time.monotonic() - _t0) * 1000
        from modules.rag.metrics import get_metrics

        get_metrics().record(
            latency_ms=_latency_ms,
            degraded=degraded,
            empty=len(chunk_contracts) == 0,
        )

        return RagResultBundle(
            chunks=chunk_contracts,
            total=len(scored_chunks),
            query=query,
            warnings=warnings,
            degraded=degraded,
        )


def _add_term(
    terms: list[dict[str, str]],
    *,
    term: str | None,
    target_id: str,
    target_type: str,
) -> None:
    value = (term or "").strip()
    if len(value) < 2:
        return
    terms.append({"term": value, "id": target_id, "type": target_type})


async def _load_project_terms(
    db: AsyncSession,
    novel_id: uuid.UUID,
) -> list[dict[str, str]]:
    """加载项目词典：人物、世界对象/别名、剧情线。"""
    terms: list[dict[str, str]] = []
    novel_id_str = str(novel_id)

    from modules.world.facade import list_characters as _list_chars

    chars_list, _ = await _list_chars(db, novel_id_str, limit=999)
    for char in chars_list:
        # Note: char.name/aliases are now on CoreEntity, use entity_terms instead
        _add_term(terms, term="", target_id=str(char.entity_id), target_type="character")

    try:
        from modules.world.facade import list_entity_terms

        entity_terms = await list_entity_terms(db, novel_id_str)
        for item in entity_terms:
            for term in item.get("terms", []):
                _add_term(
                    terms,
                    term=term,
                    target_id=str(item["id"]),
                    target_type="entity",
                )
    except Exception:
        # 世界对象词典失败不应阻断章节索引。
        pass

    # outline 模块已移除，剧情线术语不再录入

    terms.sort(key=lambda x: len(x["term"]), reverse=True)
    return terms


def _match_project_terms(
    text: str,
    terms: list[dict[str, str]],
) -> tuple[list[str], list[str], list[str]]:
    character_ids: list[str] = []
    entity_ids: list[str] = []
    thread_ids: list[str] = []
    seen: set[tuple[str, str]] = set()

    for item in terms:
        term = item["term"]
        if term not in text:
            continue
        key = (item["type"], item["id"])
        if key in seen:
            continue
        seen.add(key)
        if item["type"] == "character":
            character_ids.append(item["id"])
        elif item["type"] == "entity":
            entity_ids.append(item["id"])
        elif item["type"] == "thread":
            thread_ids.append(item["id"])

    return character_ids, entity_ids, thread_ids


def _cn_ngrams(term: str, min_n: int = 2, max_n: int = 4) -> list[str]:
    compact = re.sub(r"\s+", "", term)
    if not compact or not any("\u4e00" <= ch <= "\u9fff" for ch in compact):
        return []
    grams: list[str] = []
    for n in range(min_n, min(max_n, len(compact)) + 1):
        for i in range(0, len(compact) - n + 1):
            gram = compact[i:i + n]
            if gram not in grams:
                grams.append(gram)
    return grams


async def _expand_query_with_project_terms(
    db: AsyncSession,
    novel_id: uuid.UUID,
    query: str,
    *,
    entity_ids: list[str] | None = None,
    character_ids: list[str] | None = None,
    thread_ids: list[str] | None = None,
) -> str:
    """用项目词典扩展查询词，适配中文小说别名/称号。"""
    terms = await _load_project_terms(db, novel_id)
    if not terms:
        return query

    requested: set[tuple[str, str]] = set()
    for cid in character_ids or []:
        requested.add(("character", cid))
    for eid in entity_ids or []:
        requested.add(("entity", eid))
    for tid in thread_ids or []:
        requested.add(("thread", tid))

    compact_query = query.replace(" ", "")
    for item in terms:
        term = item["term"]
        if term in query or term in compact_query or query in term:
            requested.add((item["type"], item["id"]))
            continue
        if any(gram in term for gram in _cn_ngrams(query)):
            requested.add((item["type"], item["id"]))

    expanded: list[str] = [query]
    for item in terms:
        if (item["type"], item["id"]) not in requested:
            continue
        if item["term"] not in expanded:
            expanded.append(item["term"])

    for gram in _cn_ngrams(query):
        if gram not in expanded:
            expanded.append(gram)

    return " ".join(expanded)


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
        """索引指定章节的正文到 RAG 库，返回创建的 chunk 数。"""
        report = await self.index_chapter_with_report(db, novel_id, chapter_index)
        return report.chunks_created

    async def index_chapter_with_report(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
    ):
        """索引指定章节并返回诊断报告。"""
        from modules.rag.contracts import RagIndexReport
        from modules.writing.facade import get_latest_draft_for_chapter

        draft = await get_latest_draft_for_chapter(db, str(novel_id), chapter_index)
        if not draft or not draft.content:
            return RagIndexReport(chapter_index=chapter_index, chunks_created=0)

        chunks = self._chunking.split_chinese_novel(draft.content)
        if not chunks:
            return RagIndexReport(chapter_index=chapter_index, chunks_created=0)

        project_terms = await _load_project_terms(db, novel_id)
        await self._repo.delete_by_chapter(db, novel_id, "chapter_text", chapter_index)

        # 获取实体重要性映射
        entity_importance_map: dict[str, dict[str, object]] = {}
        try:
            from modules.world.facade import get_entity_importance_map

            entity_importance_map = await get_entity_importance_map(db, str(novel_id))
        except Exception:
            pass

        # 构建 embedding 文本：BGE 模型直接使用原始 chunk 文本，不需要上下文前缀
        # OpenAI embedding 模式下前缀在 facade 层拼接（见 facade.retrieve）
        import logging

        logger = logging.getLogger(__name__)
        created_chunks: list[RagChunk] = []
        warnings: list[str] = []

        for cn_chunk in chunks:
            character_ids, entity_ids, thread_ids = _match_project_terms(
                cn_chunk.text, project_terms,
            )

            # 根据匹配实体的重要性计算 chunk 重要性
            chunk_importance = 0.5
            if entity_ids and entity_importance_map:
                max_imp = 0.5
                has_core = False
                for eid in entity_ids:
                    info = entity_importance_map.get(eid)
                    if info:
                        imp_val = float(info["importance"])
                        if imp_val > max_imp:
                            max_imp = imp_val
                        if info.get("importance_level") == "core":
                            has_core = True
                chunk_importance = min(1.0, max_imp + (0.2 if has_core else 0.0))

            chunk_data = RagChunkCreate(
                source_type="chapter_text",
                chapter_index=chapter_index,
                chunk_index=cn_chunk.chunk_index,
                start_offset=cn_chunk.start_offset,
                end_offset=cn_chunk.end_offset,
                char_count=cn_chunk.char_count,
                text=cn_chunk.text,
                summary=self._chunking.extract_summary(cn_chunk.text),
                entity_ids=entity_ids,
                character_ids=character_ids,
                thread_ids=thread_ids,
                visibility="author_only",
                importance=chunk_importance,
                index_version=RAG_INDEX_VERSION,
                embedding_status="pending",
                meta={
                    "chapter_index": chapter_index,
                    "chunk_index": cn_chunk.chunk_index,
                },
            )
            chunk = await self._repo.create(db, novel_id, chunk_data)
            created_chunks.append(chunk)

        await db.flush()

        embedding_failed_count = 0
        if created_chunks:
            try:
                from infrastructure.llm.client import LLMClient

                llm = LLMClient()
                texts = [chunk.text for chunk in created_chunks]
                embeddings = await llm.generate_embedding(texts)
                if (
                    isinstance(embeddings, list)
                    and len(embeddings) == len(created_chunks)
                ):
                    for chunk, emb in zip(created_chunks, embeddings):
                        await self._repo.update_embedding(db, chunk.id, emb)
                        chunk.embedding_status = "succeeded"
                    await db.flush()
                else:
                    raise ValueError("embedding result count does not match chunk count")
            except Exception as exc:
                warning = f"embedding 生成失败，本章检索将降级为关键词/词典匹配: {exc}"
                warnings.append(warning)
                logger.warning(
                    "Failed to generate embeddings for chapter %d: %s",
                    chapter_index,
                    exc,
                )
                embedding_failed_count = len(created_chunks)
                for chunk in created_chunks:
                    chunk.embedding_status = "failed"
                    chunk.embedding_error = str(exc)[:1000]
                    chunk.index_warnings = [warning]
                await db.flush()

        return RagIndexReport(
            chapter_index=chapter_index,
            chunks_created=len(created_chunks),
            warnings=warnings,
            embedding_failed_count=embedding_failed_count,
            chunks_created_ids=[str(c.id) for c in created_chunks],
        )

    async def index_chapter_incremental(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_index: int,
        old_content: str,
        new_content: str,
    ) -> RagIndexReport:
        """增量索引：仅重建变更区域的 chunk。

        使用 difflib.SequenceMatcher 识别文本变更，保留未变区域的已有 chunk。
        变更率 >= 30% 时自动回退到全量重建，避免大量碎片。

        注意：此方法要求 old_content 是上次索引时的原文。
        """
        import difflib

        from modules.rag.contracts import RagIndexReport

        warnings: list[str] = []

        # 变更率检查
        change_ratio = len(new_content) / max(len(old_content), 1)
        if change_ratio > 1.3 or change_ratio < 0.7:
            warnings.append(
                f"文本变更率 {abs(1 - change_ratio):.0%} >= 30%，自动回退全量重建"
            )
            return await self.index_chapter_with_report(db, novel_id, chapter_index)

        # 计算 diff
        matcher = difflib.SequenceMatcher(None, old_content, new_content)
        opcodes = matcher.get_opcodes()

        # 读取已有 chunks
        old_chunks = await self._repo.find_by_chapter(db, novel_id, chapter_index)
        old_by_offset: dict[tuple[int, int], RagChunk] = {}
        for c in old_chunks:
            if c.start_offset is not None and c.end_offset is not None:
                old_by_offset[(c.start_offset, c.end_offset)] = c

        project_terms = await _load_project_terms(db, novel_id)
        created_chunks: list[RagChunk] = []
        embedding_failed_count = 0

        for tag, i1, i2, j1, j2 in opcodes:
            if tag == "equal":
                # 未变区域：保留已有 chunk（匹配 offset）
                for (start, end), chunk in old_by_offset.items():
                    if start >= i1 and end <= i2:
                        created_chunks.append(chunk)
                        del old_by_offset[(start, end)]

            elif tag in ("replace", "insert"):
                # 变更区域：重新分块 + embedding
                new_text = new_content[j1:j2]
                if not new_text.strip():
                    continue

                cn_chunks = self._chunking.split_chinese_novel(new_text)
                for cn_chunk in cn_chunks:
                    character_ids, entity_ids, thread_ids = _match_project_terms(
                        cn_chunk.text, project_terms,
                    )
                    chunk_data = RagChunkCreate(
                        source_type="chapter_text",
                        chapter_index=chapter_index,
                        chunk_index=len(created_chunks),
                        start_offset=j1 + cn_chunk.start_offset,
                        end_offset=j1 + cn_chunk.end_offset,
                        char_count=cn_chunk.char_count,
                        text=cn_chunk.text,
                        summary=self._chunking.extract_summary(cn_chunk.text),
                        entity_ids=entity_ids,
                        character_ids=character_ids,
                        thread_ids=thread_ids,
                        visibility="author_only",
                        importance=0.5,
                        index_version=RAG_INDEX_VERSION,
                        embedding_status="pending",
                    )
                    chunk = await self._repo.create(db, novel_id, chunk_data)
                    created_chunks.append(chunk)

        # 删除不再匹配的旧 chunk
        for (start, end), chunk in old_by_offset.items():
            if chunk.id not in {c.id for c in created_chunks}:
                await self._repo.delete(db, chunk.id)

        await db.flush()

        # 仅对新创建的 chunk 生成 embedding
        new_chunks = [c for c in created_chunks if c.embedding_status == "pending"]
        if new_chunks:
            try:
                from infrastructure.llm.client import LLMClient

                texts = [c.text for c in new_chunks]
                embeddings = await LLMClient().generate_embedding(texts)
                if isinstance(embeddings, list) and len(embeddings) == len(new_chunks):
                    for chunk, emb in zip(new_chunks, embeddings):
                        await self._repo.update_embedding(db, chunk.id, emb)
                        chunk.embedding_status = "succeeded"
                    await db.flush()
            except Exception as exc:
                warning = f"增量 embedding 失败: {exc}"
                warnings.append(warning)
                embedding_failed_count = len(new_chunks)
                for chunk in new_chunks:
                    chunk.embedding_status = "failed"
                    chunk.embedding_error = str(exc)[:1000]
                await db.flush()

        return RagIndexReport(
            chapter_index=chapter_index,
            chunks_created=len(created_chunks),
            warnings=warnings,
            embedding_failed_count=embedding_failed_count,
            chunks_created_ids=[str(c.id) for c in created_chunks],
        )
