"""
RAG 混合检索评分

纯评分函数与 Scorer 类。输入为 chunk、查询词、embedding、过滤条件等，
输出 0.0-1.0 之间的分项评分与综合评分。
"""

from __future__ import annotations

import math
import re

from modules.evidence.indexing.models import RagChunk
from shared.constants import (
    RAG_IMPORTANCE_WEIGHT,
    RAG_KEYWORD_WEIGHT,
    RAG_RELATION_WEIGHT,
    RAG_VECTOR_WEIGHT,
)

_CHINESE_SEP_RE = re.compile(r"[\s,，.。!！?？、·]+")


def smart_tokenize_chinese(query: str) -> list[str]:
    """中文查询分词：按常见分隔符切分，过滤单字。"""
    if not query or not query.strip():
        return []
    raw_terms = _CHINESE_SEP_RE.split(query.strip())
    return [term.lower() for term in raw_terms if len(term) >= 2]


def keyword_query_terms(query: str) -> list[str]:
    """提取 SQL 召回/评分共用关键词，兼容无空格中文复合查询。"""
    terms: list[str] = []
    for raw_term in (q.strip() for q in query.split()):
        if not raw_term:
            continue
        term = raw_term.lower()
        terms.append(term)
        compact = re.sub(r"\s+", "", term)
        if len(compact) < 4 or not any("\u4e00" <= ch <= "\u9fff" for ch in compact):
            continue
        for size in range(2, min(4, len(compact)) + 1):
            for idx in range(0, len(compact) - size + 1):
                terms.append(compact[idx : idx + size])
    return list(dict.fromkeys(terms))


def compute_keyword_score_with_proximity(
    text: str,
    query_terms: list[str],
) -> float:
    """计算关键词匹配评分，邻近词额外加分。"""
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


def compute_keyword_score(text: str, query_terms: list[str]) -> float:
    """计算关键词匹配评分（基于查询词在文本中的出现比例）。"""
    if not query_terms:
        return 0.0

    text_lower = text.lower()
    match_count = sum(1 for term in query_terms if term in text_lower)
    return match_count / len(query_terms)


def compute_relation_score(
    chunk: RagChunk,
    *,
    entity_ids: list[str] | None = None,
    character_ids: list[str] | None = None,
    thread_ids: list[str] | None = None,
) -> float:
    """计算关系匹配评分。

    基于 chunk 关联的 entity/character/thread ID 与查询过滤条件的重叠度。
    """
    total_fields = 0
    matched_score = 0.0

    chunk_entities: list[str] = chunk.entity_ids or []
    if entity_ids:
        total_fields += 1
        entity_set = {e.lower() for e in entity_ids}
        chunk_entity_set = {e.lower() for e in chunk_entities}
        if entity_set and chunk_entity_set:
            overlap = len(entity_set & chunk_entity_set)
            matched_score += overlap / len(entity_set)

    chunk_characters: list[str] = chunk.character_ids or []
    if character_ids:
        total_fields += 1
        char_set = {c.lower() for c in character_ids}
        chunk_char_set = {c.lower() for c in chunk_characters}
        if char_set and chunk_char_set:
            overlap = len(char_set & chunk_char_set)
            matched_score += overlap / len(char_set)

    chunk_threads: list[str] = chunk.thread_ids or []
    if thread_ids:
        total_fields += 1
        thread_set = {t.lower() for t in thread_ids}
        chunk_thread_set = {t.lower() for t in chunk_threads}
        if thread_set and chunk_thread_set:
            overlap = len(thread_set & chunk_thread_set)
            matched_score += overlap / len(thread_set)

    if total_fields == 0:
        return 0.0
    return matched_score / total_fields


def compute_temporal_decay(
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

    max_window = 10
    min_weight = 0.5
    distance = abs(chunk_chapter_index - reference_chapter_index)

    if distance >= max_window:
        return min_weight
    return 1.0 - (distance / max_window) * (1.0 - min_weight)


def compute_dynamic_weights(
    query: str,
) -> tuple[float, float, float, float]:
    """根据查询长度动态调整权重并归一化到和为 1.0。"""
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

    total = vw + kw + rw + iw
    return (vw / total, kw / total, rw / total, iw / total)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """计算余弦相似度。零向量或维度不一致时返回 0.0。"""
    if not a or not b or len(a) != len(b):
        return 0.0

    dot = sum(ai * bi for ai, bi in zip(a, b))
    norm_a = math.sqrt(sum(ai * ai for ai in a))
    norm_b = math.sqrt(sum(bi * bi for bi in b))

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    return dot / (norm_a * norm_b)


class Scorer:
    """RAG 混合检索评分器。

    不依赖外部状态，所有评分逻辑以纯函数/方法形式提供，便于独立测试。
    """

    def keyword_score(
        self,
        text: str,
        query_terms: list[str],
        *,
        use_proximity: bool = False,
    ) -> float:
        if use_proximity:
            return compute_keyword_score_with_proximity(text, query_terms)
        return compute_keyword_score(text, query_terms)

    def relation_score(
        self,
        chunk: RagChunk,
        *,
        entity_ids: list[str] | None = None,
        character_ids: list[str] | None = None,
        thread_ids: list[str] | None = None,
    ) -> float:
        return compute_relation_score(
            chunk,
            entity_ids=entity_ids,
            character_ids=character_ids,
            thread_ids=thread_ids,
        )

    def vector_score(
        self,
        chunk_embedding: list[float] | bytes | None,
        query_embedding: list[float],
    ) -> float:
        if chunk_embedding is None or query_embedding is None:
            return 0.0
        if isinstance(chunk_embedding, list) and len(chunk_embedding) == len(
            query_embedding,
        ):
            return max(0.0, cosine_similarity(query_embedding, chunk_embedding))
        return 0.0

    def importance_score(self, chunk: RagChunk) -> float:
        return float(chunk.importance)

    def temporal_decay(
        self,
        chunk_chapter_index: int | None,
        reference_chapter_index: int | None,
        mode: str,
    ) -> float:
        return compute_temporal_decay(
            chunk_chapter_index,
            reference_chapter_index,
            mode,
        )

    def dynamic_weights(self, query: str) -> tuple[float, float, float, float]:
        return compute_dynamic_weights(query)
