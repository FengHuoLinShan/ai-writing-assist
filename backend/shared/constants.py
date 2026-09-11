"""
全局常量定义

所有模块公用的魔数、默认值、预算常量集中在此处。
"""

from __future__ import annotations

from typing import Final

# ============================================================
# 分页
# ============================================================

DEFAULT_PAGE_SIZE: Final[int] = 20
"""默认分页每页条数"""

MAX_PAGE_SIZE: Final[int] = 50
"""最大分页条数"""

# ============================================================
# 检索评分权重（混合检索）
# ============================================================

RAG_VECTOR_WEIGHT: Final[float] = 0.50
"""向量检索权重（BGE 中文语义质量更高，适当提高）"""
RAG_KEYWORD_WEIGHT: Final[float] = 0.25
"""关键词检索权重"""
RAG_RELATION_WEIGHT: Final[float] = 0.12
"""关系扩展权重"""
RAG_IMPORTANCE_WEIGHT: Final[float] = 0.13
"""重要性/时效性权重"""

# ============================================================
# LLM 相关
# ============================================================

DEFAULT_LLM_MAX_TOKENS: Final[int] = 12_000
"""LLM 调用默认最大 token 数"""

LLM_RETRY_MAX_ATTEMPTS: Final[int] = 3
"""LLM 调用最大重试次数"""

LLM_RETRY_BASE_DELAY: Final[float] = 1.0
"""LLM 重试基础延迟（秒）"""

# ============================================================
# 任务队列
# ============================================================

TASK_POLL_INTERVAL: Final[float] = 2.0
"""任务轮询间隔（秒）"""

TASK_HEARTBEAT_INTERVAL: Final[float] = 30.0
"""任务心跳间隔（秒）"""

TASK_MAX_HEARTBEAT_GAP: Final[float] = 120.0
"""任务心跳最大间隔无响应视为超时（秒）"""

# ============================================================
# 去重（Dedup）
# ============================================================

DEDUP_FUSION_TOP_K: Final[int] = 50
"""各通道（词法/语义）最大召回数"""

# 级联阈值（双阈值策略）
DEDUP_AUTO_MERGE_THRESHOLD: Final[float] = 0.88
"""≥ 此值自动合并（高置信）"""

DEDUP_REVIEW_THRESHOLD: Final[float] = 0.70
"""0.70–0.88 区间需人工审核"""

DEDUP_DISCARD_THRESHOLD: Final[float] = 0.58
"""< 0.58 直接丢弃"""

DEDUP_CONFLICT_FIELDS: Final[list[str]] = [
    "weapon",
    "ability",
    "affiliation",
    "title",
    "species",
    "gender",
    "age",
]
"""content_json 中需检测冲突的关键字段"""
