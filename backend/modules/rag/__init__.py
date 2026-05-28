# modules/rag — 检索增强模块
# 负责从结构化小说知识库和文本片段中检索与当前创作任务相关的信息
# 提供分块、embedding、关键词检索、混合检索、metadata 过滤等功能

from __future__ import annotations

from modules.rag.contracts import RagChunkContract, RagIndexReport, RagQueryContract
from modules.rag.facade import retrieve
from modules.rag.models import RagChunk
from modules.rag.schemas import (
    RagChunkCreate,
    RagChunkResponse,
    RagQuery,
    RagResult,
    SimilarEntity,
)

__all__ = [
    "RagChunk",
    "RagChunkContract",
    "RagChunkCreate",
    "RagChunkResponse",
    "RagQuery",
    "RagQueryContract",
    "RagIndexReport",
    "RagResult",
    "SimilarEntity",
    "retrieve",
]
