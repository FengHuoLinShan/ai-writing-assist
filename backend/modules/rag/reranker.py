"""
RAG 重排序器（可选模块）

将混合检索的 top_k*2 候选送入 DeepSeek API 做相关性精排，
提升 long-context 和 extraction 场景下的检索精度。

配置:
    RERANKER_ENABLED=true   # 启用
    RERANKER_MAX_CANDIDATES=24  # 最多重排候选数

默认关闭（search 模式不走重排，extraction 模式可选开启）。
"""

from __future__ import annotations

import json
import logging
import math

from pydantic import BaseModel, ConfigDict, field_validator

from infrastructure.llm.client import LLMClient
from infrastructure.llm.schemas import LLMCallRequest

logger = logging.getLogger(__name__)

_RERANK_PROMPT = """你是一个小说创作助手的检索质量评估器。

请评估以下文本片段与查询的相关性，给出 0.0 到 1.0 的相关性评分。

评分标准:
- 1.0: 完全匹配，文本直接回答了查询
- 0.7-0.9: 高度相关，包含查询涉及的实体或事件
- 0.4-0.6: 部分相关，涉及类似主题
- 0.1-0.3: 微弱相关
- 0.0: 完全不相关

只输出 JSON，格式: {"scores": [0.85, 0.32, ...]}"""


class _RerankerResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scores: list[float]

    @field_validator("scores", mode="before")
    @classmethod
    def _validate_scores(cls, value: object) -> list[float]:
        if not isinstance(value, list):
            raise ValueError("scores must be a list")

        scores: list[float] = []
        for item in value:
            if isinstance(item, bool) or not isinstance(item, int | float):
                raise ValueError("scores entries must be JSON numbers")
            score = float(item)
            if not math.isfinite(score):
                raise ValueError("scores entries must be finite")
            scores.append(score)
        return scores


async def rerank(
    query: str,
    candidates: list[dict],
    *,
    model: str | None = None,
    max_candidates: int = 24,
) -> list[float]:
    """对候选片段进行 LLM 精排。

    Args:
        query: 原始查询文本
        candidates: 候选片段列表，每个含 "text" 字段
        model: LLM 模型名称（默认使用配置中的 llm_model）
        max_candidates: 最多重排候选数（超出截断）

    Returns:
        list[float] — 每个候选的相关性评分 (0.0-1.0)，与输入顺序对应
    """
    if not candidates:
        return []

    # 截断到最大候选数
    trimmed = candidates[:max_candidates]

    # 构建 prompt
    passages = "\n\n".join(f"[{i}] {c['text'][:300]}" for i, c in enumerate(trimmed))
    user_prompt = f"查询: {query}\n\n候选片段:\n{passages}"

    from infrastructure.llm.schemas import LLMMessage

    client = LLMClient()

    try:
        request = LLMCallRequest(
            model=model or client._settings.llm_model,
            messages=[
                LLMMessage(role="system", content=_RERANK_PROMPT),
                LLMMessage(role="user", content=user_prompt),
            ],
            temperature=0.1,
            max_tokens=512,
            response_format={"type": "json_object"},
        )

        response = await client.generate(request)
        data = json.loads(response.content)
        parsed = _RerankerResponse.model_validate(data)

        # 补齐到原始长度
        padded = parsed.scores[: len(trimmed)]
        padded.extend([0.0] * (len(trimmed) - len(padded)))
        padded = [max(0.0, min(1.0, s)) for s in padded]

        # 对于被截断的候选，给默认评分 0.3
        if len(trimmed) < len(candidates):
            padded.extend([0.3] * (len(candidates) - len(trimmed)))

        return padded

    except Exception:
        logger.exception("Reranking failed, returning uniform scores")
        return [0.5] * len(candidates)


async def rerank_results(
    query: str,
    scored_chunks: list[tuple],
    *,
    top_k: int = 12,
    model: str | None = None,
) -> list[tuple]:
    """对混合检索结果进行 LLM 精排，返回重排后的 top_k。

    Args:
        query: 原始查询
        scored_chunks: 混合检索结果，每项为 (RagChunk, score)
        top_k: 最终返回数量
        model: LLM 模型名称

    Returns:
        list[(RagChunk, final_score)] — 重排后的 top_k 结果
    """
    if len(scored_chunks) <= top_k:
        return scored_chunks

    candidates = [
        {"text": chunk.text, "original_score": score} for chunk, score in scored_chunks
    ]

    rerank_scores = await rerank(query, candidates, model=model)

    # 融合原始评分与 LLM 精排评分
    reranked: list[tuple] = []
    for i, (chunk, orig_score) in enumerate(scored_chunks):
        llm_score = rerank_scores[i] if i < len(rerank_scores) else 0.5
        # 原始评分 30% + LLM 评分 70%
        final = 0.3 * orig_score + 0.7 * llm_score
        reranked.append((chunk, final))

    reranked.sort(key=lambda x: x[1], reverse=True)
    return reranked[:top_k]
