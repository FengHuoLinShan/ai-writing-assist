"""
RAG 混合检索权重自动调优

利用 rag_chunk 自带的结构化标注（entity_ids / character_ids）作为弱标签，
零人工标注自动构建评估集，网格搜索最优权重组合。

用法:
    python -m modules.rag.tuning --novel-id <uuid> --chapters 1-30

或从 JSON 测试集运行:
    python -m modules.rag.tuning --test-file eval_queries.json
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import math

# 将 backend 目录加入 path（允许从项目根直接运行）
import os as _os
import sys
import time
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.redaction import redact_diagnostic

logger = logging.getLogger(__name__)

_backend = _os.path.dirname(
    _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
)
if _backend not in sys.path:
    sys.path.insert(0, _backend)


@dataclass
class EvalQuery:
    query: str
    relevant_ids: set[str]
    chapter_index: int | None = None


@dataclass
class EvalResult:
    weights: tuple[float, float, float, float]
    mrr: float = 0.0
    ndcg_at_5: float = 0.0
    ndcg_at_10: float = 0.0
    precision_at_5: float = 0.0
    recall_at_5: float = 0.0
    avg_latency_ms: float = 0.0


@dataclass
class _EmbeddingFailureLogState:
    warning_emitted: bool = False
    failure_count: int = 0


@dataclass
class TuningReport:
    best: EvalResult = field(default_factory=lambda: EvalResult((0, 0, 0, 0)))
    top5: list[EvalResult] = field(default_factory=list)
    total_combinations: int = 0
    total_queries: int = 0
    elapsed_seconds: float = 0.0


def _dcg(scores: list[float], k: int) -> float:
    """Discounted Cumulative Gain @ k"""
    dcg = 0.0
    for i, s in enumerate(scores[:k]):
        dcg += (2.0**s - 1.0) / math.log2(i + 2)
    return dcg


def _ndcg(predicted_ranks: list[str], relevant_ids: set[str], k: int) -> float:
    """Normalized DCG @ k"""
    if not relevant_ids:
        return 0.0
    # 预测结果的相关性评分：相关=1，不相关=0
    rels = [1.0 if rid in relevant_ids else 0.0 for rid in predicted_ranks[:k]]
    dcg = _dcg(rels, k)
    # 理想排序：所有相关结果排最前
    ideal_rels = sorted(
        [1.0] * min(len(relevant_ids), k) + [0.0] * max(0, k - len(relevant_ids)),
        reverse=True,
    )
    idcg = _dcg(ideal_rels, k)
    if idcg == 0.0:
        return 0.0
    return dcg / idcg


def _mrr(predicted_ranks: list[str], relevant_ids: set[str]) -> float:
    """Mean Reciprocal Rank"""
    for i, rid in enumerate(predicted_ranks):
        if rid in relevant_ids:
            return 1.0 / (i + 1)
    return 0.0


async def build_eval_set(
    db: AsyncSession,
    novel_id: uuid.UUID,
    start_chapter: int = 1,
    end_chapter: int | None = None,
    max_queries: int = 200,
) -> list[EvalQuery]:
    """从已索引的 rag_chunks 自动构建评估集。

    逻辑：取 chunk 前 80 字作为查询，共享 entity_id 的其他 chunk 视为相关。
    过滤掉相关 chunk 少于 2 的查询。
    """
    from modules.rag.models import RagChunk

    conditions = [
        RagChunk.novel_id == novel_id,
        RagChunk.source_type == "chapter_text",
        RagChunk.chapter_index >= start_chapter,
    ]
    if end_chapter is not None:
        conditions.append(RagChunk.chapter_index <= end_chapter)

    stmt = (
        select(RagChunk)
        .where(*conditions)
        .order_by(RagChunk.chapter_index.asc(), RagChunk.chunk_index.asc())
    )
    result = await db.execute(stmt)
    chunks: list[RagChunk] = list(result.scalars().all())

    if not chunks:
        print("没有找到已索引的 chunk，请先运行索引")
        return []

    # 构建 entity_id → chunk_ids 的倒排索引
    entity_to_chunks: dict[str, set[str]] = {}
    for c in chunks:
        for eid in c.entity_ids or []:
            entity_to_chunks.setdefault(eid, set()).add(str(c.id))

    queries: list[EvalQuery] = []
    for c in chunks:
        if len(queries) >= max_queries:
            break

        # 查询文本：取前 80 字
        query_text = c.text[:80].strip()
        if len(query_text) < 10:
            continue

        # 收集所有共享 entity 的 chunk（排除自身）
        relevant: set[str] = set()
        for eid in c.entity_ids or []:
            for chunk_id in entity_to_chunks.get(eid, set()):
                if chunk_id != str(c.id):
                    relevant.add(chunk_id)

        if len(relevant) < 2:
            continue

        queries.append(
            EvalQuery(
                query=query_text,
                relevant_ids=relevant,
                chapter_index=c.chapter_index,
            )
        )

    return queries


async def evaluate_weights(
    db: AsyncSession,
    novel_id: uuid.UUID,
    queries: list[EvalQuery],
    weights: tuple[float, float, float, float],
    top_k: int = 10,
    *,
    _embedding_failure_log_state: _EmbeddingFailureLogState | None = None,
) -> EvalResult:
    """用给定权重评估检索质量。"""
    from infrastructure.llm.client import LLMClient
    from modules.rag.retrieval import RetrievalOrchestrator

    retrieval = RetrievalOrchestrator()
    mrr_sum = 0.0
    ndcg5_sum = 0.0
    ndcg10_sum = 0.0
    p5_sum = 0.0
    r5_sum = 0.0
    total_latency = 0.0
    valid = 0
    failure_log_state = _embedding_failure_log_state or _EmbeddingFailureLogState()

    for eq in queries:
        t0 = time.monotonic()

        # 生成查询 embedding
        query_embedding = None
        embedding_client = None
        try:
            embedding_client = LLMClient()
            emb = await embedding_client.generate_embedding(eq.query, is_query=True)
            if isinstance(emb, list) and emb and isinstance(emb[0], float):
                query_embedding = emb  # type: ignore[assignment]
        except Exception as exc:
            failure_log_state.failure_count += 1
            if not failure_log_state.warning_emitted:
                logger.warning(
                    "rag_tuning_embedding_failed novel_id=%s chapter_index=%s; "
                    "continuing_without_vector; subsequent_failures_suppressed; "
                    "reason=%s",
                    novel_id,
                    eq.chapter_index,
                    redact_diagnostic(exc, limit=300),
                )
                failure_log_state.warning_emitted = True
        finally:
            if embedding_client is not None:
                close = getattr(embedding_client, "close", None)
                if callable(close):
                    await close()

        scored = await retrieval.hybrid_search(
            db,
            novel_id,
            eq.query,
            query_embedding=query_embedding,
            reference_chapter_index=eq.chapter_index,
            weights=weights,
            top_k=top_k,
        )

        elapsed = (time.monotonic() - t0) * 1000
        total_latency += elapsed

        predicted_ids = [str(c.id) for c, _ in scored]
        mrr_sum += _mrr(predicted_ids, eq.relevant_ids)
        ndcg5_sum += _ndcg(predicted_ids, eq.relevant_ids, 5)
        ndcg10_sum += _ndcg(predicted_ids, eq.relevant_ids, 10)

        # Precision & Recall @ 5
        top5 = set(predicted_ids[:5])
        hits = top5 & eq.relevant_ids
        p5_sum += len(hits) / min(5, len(predicted_ids[:5])) if predicted_ids[:5] else 0.0
        r5_sum += len(hits) / len(eq.relevant_ids) if eq.relevant_ids else 0.0

        valid += 1

    n = max(valid, 1)
    return EvalResult(
        weights=weights,
        mrr=round(mrr_sum / n, 4),
        ndcg_at_5=round(ndcg5_sum / n, 4),
        ndcg_at_10=round(ndcg10_sum / n, 4),
        precision_at_5=round(p5_sum / n, 4),
        recall_at_5=round(r5_sum / n, 4),
        avg_latency_ms=round(total_latency / n, 1),
    )


def generate_weight_combinations() -> list[tuple[float, float, float, float]]:
    """生成网格搜索的权重组合（步长 0.05，sum=1.0）"""
    combos: list[tuple[float, float, float, float]] = []
    for vw in [round(x * 0.05, 2) for x in range(6, 13)]:  # 0.30 ~ 0.60
        for kw in [round(x * 0.05, 2) for x in range(3, 9)]:  # 0.15 ~ 0.40
            for rw in [round(x * 0.05, 2) for x in range(1, 6)]:  # 0.05 ~ 0.25
                iw = round(1.0 - vw - kw - rw, 2)
                if 0.05 <= iw <= 0.20:
                    combos.append((vw, kw, rw, iw))
    return combos


async def run_tuning(
    db: AsyncSession,
    novel_id: str,
    start_chapter: int = 1,
    end_chapter: int | None = None,
    max_queries: int = 200,
    fast_mode: bool = False,
) -> TuningReport:
    """执行完整调优流程。"""
    nid = uuid.UUID(hex=novel_id)
    t_start = time.monotonic()

    # 1. 构建评估集
    print(
        f"构建评估集 (novel={novel_id}, chapters={start_chapter}-{end_chapter or '∞'})..."
    )
    queries = await build_eval_set(db, nid, start_chapter, end_chapter, max_queries)
    if not queries:
        print("评估集为空，无法调优")
        return TuningReport()
    print(f"评估集: {len(queries)} 条查询")

    # 2. 生成权重组合
    combos = generate_weight_combinations()
    if fast_mode:
        # 快模式：步长 0.1，大幅减少组合数
        combos = [
            (vw, kw, rw, round(1.0 - vw - kw - rw, 2))
            for vw in [0.35, 0.45, 0.55]
            for kw in [0.20, 0.25, 0.30]
            for rw in [0.10, 0.15]
            if 0.05 <= round(1.0 - vw - kw - rw, 2) <= 0.20
        ]
    print(f"权重组合: {len(combos)} 个{' (fast mode)' if fast_mode else ''}")

    # 3. 网格搜索
    results: list[EvalResult] = []
    embedding_failure_log_state = _EmbeddingFailureLogState()
    for i, w in enumerate(combos):
        result = await evaluate_weights(
            db,
            nid,
            queries,
            w,
            _embedding_failure_log_state=embedding_failure_log_state,
        )
        results.append(result)
        if (i + 1) % 50 == 0 or i == 0:
            print(
                f"  [{i + 1}/{len(combos)}] "
                f"v={w[0]:.2f} k={w[1]:.2f} r={w[2]:.2f} i={w[3]:.2f}  "
                f"MRR={result.mrr:.4f}"
            )

    # 4. 排序取最优
    results.sort(key=lambda r: r.mrr, reverse=True)
    elapsed = time.monotonic() - t_start

    return TuningReport(
        best=results[0],
        top5=results[:5],
        total_combinations=len(combos),
        total_queries=len(queries),
        elapsed_seconds=round(elapsed, 1),
    )


def print_report(report: TuningReport) -> None:
    print("\n" + "=" * 60)
    print("RAG 权重调优报告")
    print("=" * 60)
    print(f"总组合数: {report.total_combinations}")
    print(f"评估查询: {report.total_queries}")
    print(f"耗时: {report.elapsed_seconds}s")
    print()

    print("Top 5 权重组合:")
    print("-" * 60)
    print(
        f"{'排名':<4} {'vector':<8} {'keyword':<8} {'relation':<8} "
        f"{'importance':<10} {'MRR':<8} {'NDCG@5':<8} {'NDCG@10':<8} {'P@5':<8}"
    )
    print("-" * 60)
    for rank, r in enumerate(report.top5, 1):
        print(
            f"{rank:<4} {r.weights[0]:<8.2f} {r.weights[1]:<8.2f} "
            f"{r.weights[2]:<8.2f} {r.weights[3]:<10.2f} "
            f"{r.mrr:<8.4f} {r.ndcg_at_5:<8.4f} "
            f"{r.ndcg_at_10:<8.4f} {r.precision_at_5:<8.4f}"
        )
    print()

    best = report.best
    print(
        f"推荐权重: vector={best.weights[0]:.2f} "
        f"keyword={best.weights[1]:.2f} relation={best.weights[2]:.2f} "
        f"importance={best.weights[3]:.2f}"
    )
    print(
        f"指标: MRR={best.mrr:.4f} NDCG@5={best.ndcg_at_5:.4f} "
        f"P@5={best.precision_at_5:.4f} "
        f"avg_latency={best.avg_latency_ms:.1f}ms"
    )

    # 输出可直接使用的 Python 常量
    print("\n# 粘贴到 backend/shared/constants.py:")
    print(f"RAG_VECTOR_WEIGHT: Final[float] = {best.weights[0]:.2f}")
    print(f"RAG_KEYWORD_WEIGHT: Final[float] = {best.weights[1]:.2f}")
    print(f"RAG_RELATION_WEIGHT: Final[float] = {best.weights[2]:.2f}")
    print(f"RAG_IMPORTANCE_WEIGHT: Final[float] = {best.weights[3]:.2f}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="RAG 权重自动调优")
    parser.add_argument("--novel-id", required=True, help="小说项目 ID (UUID hex)")
    parser.add_argument("--chapters", default="1-30", help="章节范围，如 1-30")
    parser.add_argument("--max-queries", type=int, default=200, help="最大评估查询数")
    parser.add_argument(
        "--fast", action="store_true", help="快速模式 (步长 0.1, 约 20 个组合)"
    )
    parser.add_argument("--database-url", default="", help="数据库 URL (默认使用配置)")
    args = parser.parse_args()

    # 解析章节范围
    parts = args.chapters.split("-")
    start_chapter = int(parts[0])
    end_chapter = int(parts[1]) if len(parts) > 1 else None

    # 数据库连接
    from core.database import get_session

    async with get_session() as db:
        report = await run_tuning(
            db,
            novel_id=args.novel_id,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            max_queries=args.max_queries,
            fast_mode=args.fast,
        )
        print_report(report)


if __name__ == "__main__":
    asyncio.run(main())
