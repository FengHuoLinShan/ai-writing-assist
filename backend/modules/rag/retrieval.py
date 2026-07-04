"""
RAG 检索编排

RetrievalOrchestrator 负责完整检索流水线：
embedding 生成 → 查询扩展 → 召回 → 评分 → 去重 → 重排序 → 指标记录 → 契约映射。
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from modules.rag import scoring as rag_scoring
from modules.rag.circuit_breaker import get_circuit_breaker
from modules.rag.contracts import RagResultBundle
from modules.rag.mappers import chunk_orm_to_contract as _to_chunk_contract
from modules.rag.metrics import get_metrics
from modules.rag.models import RagChunk
from modules.rag.query_expansion import QueryExpander
from modules.rag.repositories import RagChunkRepository
from modules.rag.reranker import rerank_results
from modules.rag.scoring import Scorer, keyword_query_terms, smart_tokenize_chinese

EmbedderFn = Callable[..., Awaitable[list[float]]]
RerankerFn = Callable[..., Awaitable[list[tuple]]]
MetricsFn = Callable[[], object]
CircuitBreakerFn = Callable[[], object]

_MAX_TOP_K = 50


async def _default_embedder(query: str, *, is_query: bool = False) -> list[float]:
    """默认 embedding 函数：通过 LLMClient 生成。"""
    from infrastructure.llm.client import LLMClient

    embedding = await LLMClient().generate_embedding(query, is_query=is_query)
    if isinstance(embedding, list) and embedding and isinstance(embedding[0], float):
        return embedding
    return []


def _is_rerank_enabled(mode: str) -> bool:
    """检查是否启用 LLM 重排序。extraction 模式且配置开启时生效。"""
    from core.config import get_settings

    if mode not in ("extraction",):
        return False
    return get_settings().reranker_enabled


class RetrievalOrchestrator:
    """混合检索编排器。

    构造函数显式注入 repo、scorer、query_expander、reranker、embedder、metrics、熔断器，
    默认使用仓库/评分器/容器单例，单元测试可替换为 fake。
    """

    def __init__(
        self,
        repo: RagChunkRepository | None = None,
        scorer: Scorer | None = None,
        query_expander: QueryExpander | None = None,
        *,
        reranker_fn: RerankerFn | None = None,
        embedder_fn: EmbedderFn | None = None,
        metrics: MetricsFn | None = None,
        circuit_breaker: CircuitBreakerFn | None = None,
    ) -> None:
        self._repo = repo or RagChunkRepository()
        self._scorer = scorer or Scorer()
        self._query_expander = query_expander or QueryExpander()
        self._reranker_fn = reranker_fn or rerank_results
        self._embedder_fn = embedder_fn or _default_embedder
        self._metrics = metrics or get_metrics
        self._circuit_breaker = circuit_breaker or get_circuit_breaker

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
        """混合检索：关键词 + 关系 + 重要性 + 向量。

        作为较薄的召回+评分原语，仍包含查询扩展以兼容现有调用方。
        """
        vw, kw, rw, iw = weights or self._scorer.dynamic_weights(query)

        expanded_query = await self._query_expander.expand(
            db,
            novel_id,
            query,
            entity_ids=entity_ids,
            character_ids=character_ids,
            thread_ids=thread_ids,
        )

        relation_only = mode == "extraction" and bool(
            entity_ids or character_ids or thread_ids or chapter_index is not None
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
            limit=top_k * 2,
        )

        candidate_chunks = list(keyword_chunks)

        vector_search = getattr(self._repo, "vector_search", None)
        if query_embedding and vector_search is not None:
            vector_chunks = await vector_search(
                db,
                novel_id,
                query_embedding,
                entity_ids=entity_ids,
                character_ids=character_ids,
                thread_ids=thread_ids,
                chapter_index=chapter_index,
                visibility=visibility,
                top_k=top_k * 2,
            )
            candidate_chunks.extend(chunk for chunk, _score in vector_chunks)

        has_metadata_filter = bool(
            entity_ids or character_ids or thread_ids or chapter_index is not None
        )
        if has_metadata_filter and not relation_only:
            metadata_chunks = await self._repo.keyword_search(
                db,
                novel_id,
                "",
                entity_ids=entity_ids,
                character_ids=character_ids,
                thread_ids=thread_ids,
                chapter_index=chapter_index,
                visibility=visibility,
                limit=top_k * 2,
            )
            candidate_chunks.extend(metadata_chunks)

        # 去重（同一 chunk 可能被多个召回路径匹配）
        seen_ids: set[uuid.UUID] = set()
        unique_chunks: list[RagChunk] = []
        for chunk in candidate_chunks:
            if chunk.id not in seen_ids:
                seen_ids.add(chunk.id)
                unique_chunks.append(chunk)

        # 对中文查询不分词，直接用整个查询做子串匹配
        query_terms = keyword_query_terms(expanded_query)
        use_chinese_match = not query_terms or all(
            ord(c) > 127 for c in expanded_query.replace(" ", "")
        )
        chinese_query_no_spaces = expanded_query.replace(" ", "").lower()
        chinese_terms_list = keyword_query_terms(expanded_query)
        if not chinese_terms_list:
            chinese_terms_list = smart_tokenize_chinese(expanded_query)
        scored_chunks: list[tuple[RagChunk, float]] = []

        for chunk in unique_chunks:
            if use_chinese_match and chinese_terms_list:
                if len(chinese_terms_list) > 1:
                    keyword_score = self._scorer.keyword_score(
                        chunk.text,
                        chinese_terms_list,
                        use_proximity=True,
                    )
                else:
                    keyword_score = (
                        1.0
                        if chinese_query_no_spaces in chunk.text.lower().replace(" ", "")
                        else 0.0
                    )
            else:
                keyword_score = self._scorer.keyword_score(
                    chunk.text,
                    query_terms,
                    use_proximity=False,
                )

            relation_score = self._scorer.relation_score(
                chunk,
                entity_ids=entity_ids,
                character_ids=character_ids,
                thread_ids=thread_ids,
            )

            importance_score = self._scorer.importance_score(chunk)

            vector_score = self._scorer.vector_score(
                chunk.embedding,
                query_embedding or [],
            )

            total_score = (
                vw * vector_score
                + kw * keyword_score
                + rw * relation_score
                + iw * importance_score
            )

            if reference_chapter_index is not None:
                decay = self._scorer.temporal_decay(
                    chunk.chapter_index,
                    reference_chapter_index,
                    mode,
                )
                total_score *= decay

            scored_chunks.append((chunk, total_score))

        scored_chunks.sort(key=lambda x: x[1], reverse=True)

        # 如果所有 chunk 都只有 importance 得分（无关键词/关系/向量匹配）
        # 说明查询与内容无实质匹配，返回空结果避免 importance 劫持
        has_meaningful_match = False
        for chunk, _ in scored_chunks[:top_k]:
            if use_chinese_match and chinese_terms_list:
                if len(chinese_terms_list) > 1:
                    kw_check = self._scorer.keyword_score(
                        chunk.text,
                        chinese_terms_list,
                        use_proximity=True,
                    )
                else:
                    kw_check = (
                        1.0
                        if chinese_query_no_spaces in chunk.text.lower().replace(" ", "")
                        else 0.0
                    )
            else:
                kw_check = self._scorer.keyword_score(
                    chunk.text,
                    query_terms,
                    use_proximity=False,
                )
            if kw_check > 0:
                has_meaningful_match = True
                break
            if query_embedding:
                vector_check = self._scorer.vector_score(
                    chunk.embedding,
                    query_embedding,
                )
                if vector_check > 0:
                    has_meaningful_match = True
                    break

        if not has_meaningful_match and mode == "extraction":
            has_meaningful_match = any(
                self._scorer.relation_score(
                    chunk,
                    entity_ids=entity_ids,
                    character_ids=character_ids,
                    thread_ids=thread_ids,
                )
                > 0
                or (chapter_index is not None and chunk.chapter_index == chapter_index)
                for chunk, _ in scored_chunks[:top_k]
            )

        if not has_meaningful_match:
            return []

        return scored_chunks[:top_k]

    def _deduplicate_by_embedding(
        self,
        scored_chunks: list[tuple],
        threshold: float = 0.9,
        max_candidates: int = 120,
    ) -> list[tuple]:
        """对检索结果进行语义去重。

        利用 chunk 的 embedding 计算余弦相似度，相似度 > threshold 的两个 chunk
        仅保留 char_count 更大者。无 embedding 时跳过。
        """
        if len(scored_chunks) <= 1:
            return scored_chunks

        comparison_window = max(1, min(max_candidates, len(scored_chunks)))
        head = scored_chunks[:comparison_window]
        tail = scored_chunks[comparison_window:]
        keep: list[tuple] = []
        removed_indices: set[int] = set()

        for i, (chunk_a, score_a) in enumerate(head):
            if i in removed_indices:
                continue
            keep.append((chunk_a, score_a))

            emb_a = chunk_a.embedding
            if emb_a is None:
                continue
            if not isinstance(emb_a, list):
                continue

            for j, (chunk_b, _score_b) in enumerate(head):
                if j <= i or j in removed_indices:
                    continue

                emb_b = chunk_b.embedding
                if emb_b is None:
                    continue
                if not isinstance(emb_b, list):
                    continue
                if len(emb_a) != len(emb_b):
                    continue

                sim = rag_scoring.cosine_similarity(emb_a, emb_b)
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

        return [*keep, *tail]

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
        """混合检索编排：embedding 生成 → 混合搜索 → 去重 → 重排序 → 指标记录。"""
        import time as _time

        _t0 = _time.monotonic()
        _embedding_ms: float | None = None
        _search_ms: float | None = None
        _rerank_ms: float | None = None
        top_k = max(1, min(top_k, _MAX_TOP_K))
        warnings: list[str] = []
        degraded = False
        query_embedding: list[float] | None = None

        cb = self._circuit_breaker()
        if await self._repo.has_embeddings(db, novel_id):
            if cb.allow_request():
                try:
                    _embedding_t0 = _time.monotonic()
                    embedding = await self._embedder_fn(query, is_query=True)
                    _embedding_ms = (_time.monotonic() - _embedding_t0) * 1000
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
                    if _embedding_ms is None:
                        _embedding_ms = (_time.monotonic() - _embedding_t0) * 1000
                    cb.record_failure()
                    degraded = True
                    warnings.append(
                        f"embedding 生成失败，本次检索已降级，结果可能不准确: {exc}",
                    )
            else:
                degraded = True
                warnings.append("BGE 服务熔断中，本次检索已降级为关键词匹配")

        _search_t0 = _time.monotonic()
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
        _search_ms = (_time.monotonic() - _search_t0) * 1000

        deduped_chunks = self._deduplicate_by_embedding(scored_chunks, threshold=0.9)

        rerank_enabled = _is_rerank_enabled(mode)
        if rerank_enabled and len(deduped_chunks) > top_k:
            try:
                _rerank_t0 = _time.monotonic()
                deduped_chunks = await self._reranker_fn(
                    query,
                    deduped_chunks,
                    top_k=top_k,
                )
                _rerank_ms = (_time.monotonic() - _rerank_t0) * 1000
            except Exception as exc:
                _rerank_ms = (_time.monotonic() - _rerank_t0) * 1000
                warnings.append(f"重排序失败，使用原始排序: {exc}")
        else:
            _rerank_ms = 0.0

        deduped_chunks = deduped_chunks[:top_k]

        chunk_contracts = [
            _to_chunk_contract(chunk, score) for chunk, score in deduped_chunks
        ]
        for chunk in chunk_contracts:
            if chunk.embedding_status in ("failed", "pending_vectorization"):
                degraded = True
                if chunk.index_warnings:
                    warnings.extend(chunk.index_warnings)
                elif chunk.embedding_status == "failed":
                    warnings.append("召回结果包含 embedding 失败片段，检索可能不准确")
                else:
                    warnings.append("召回结果包含待重新向量化片段，检索可能不准确")
        warnings = list(dict.fromkeys(warnings))

        _latency_ms = (_time.monotonic() - _t0) * 1000
        self._metrics().record(
            latency_ms=_latency_ms,
            degraded=degraded,
            empty=len(chunk_contracts) == 0,
            embedding_ms=_embedding_ms,
            search_ms=_search_ms,
            rerank_ms=_rerank_ms,
        )

        return RagResultBundle(
            chunks=chunk_contracts,
            total=len(scored_chunks),
            query=query,
            warnings=warnings,
            degraded=degraded,
        )
