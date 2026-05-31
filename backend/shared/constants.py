"""
全局常量定义

所有模块公用的魔数、默认值、预算常量集中在此处。
"""

from __future__ import annotations

from typing import Final

# ============================================================
# Embedding
# ============================================================

DEFAULT_EMBEDDING_DIM: Final[int] = 768
"""默认 embedding 向量维度（bge-base-zh-v1.5）"""

# ============================================================
# 分页
# ============================================================

DEFAULT_PAGE_SIZE: Final[int] = 20
"""默认分页每页条数"""

MAX_PAGE_SIZE: Final[int] = 50
"""最大分页条数"""

# ============================================================
# 相似度阈值（pgvector 余弦距离）
# ============================================================

SIMILARITY_HIGH_CONFIDENCE: Final[float] = 0.88
""">= 0.88 高度疑似同一对象"""

SIMILARITY_MEDIUM_CONFIDENCE: Final[float] = 0.78
"""0.78-0.88 需人工判断"""

SIMILARITY_LOW_CONFIDENCE: Final[float] = 0.65
"""0.65-0.78 语义相关；< 0.65 忽略"""

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
# Context Budget 默认值
# ============================================================

CONTEXT_BUDGET_DEFAULTS: Final[dict[str, int]] = {
    "core_entities": 8,       # 核心对象
    "normal_entities": 8,     # 普通对象
    "characters": 6,          # 人物
    "memories": 10,           # 记忆记录
    "foreshadowings": 5,      # 伏笔
    "timeline_events": 8,     # 时间线事件
    "geo_relationships": 10,  # 地理关系
    "relation_edges": 12,     # 关系边
    "rag_chunks": 8,          # RAG 片段
}
"""Context Compiler 默认各项上限"""

# ============================================================
# LLM 相关
# ============================================================

DEFAULT_LLM_TIMEOUT: Final[int] = 60
"""LLM 调用默认超时（秒）"""

DEFAULT_LLM_MAX_TOKENS: Final[int] = 4096
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
# 实体对象抽取
# ============================================================

ENTITY_EXTRACTION_MIN_IMPORTANCE_STRICT: Final[float] = 0.75
"""严格模式最小重要性值"""

ENTITY_EXTRACTION_MIN_IMPORTANCE_NORMAL: Final[float] = 0.45
"""正常模式最小重要性值"""

# ============================================================
# 矢量索引
# ============================================================

VECTOR_INDEX_LISTS: Final[int] = 100
"""HNSW IVFFlat lists 参数默认值"""

VECTOR_INDEX_EF_CONSTRUCTION: Final[int] = 200
"""HNSW ef_construction 参数默认值"""

VECTOR_INDEX_M: Final[int] = 16
"""HNSW M 参数默认值"""

# ============================================================
# 去重（Dedup）
# ============================================================

DEDUP_RRF_K: Final[int] = 60
"""RRF 平滑常数 k — 排名 1 的得分为 1/(k+1)"""

DEDUP_FUSION_TOP_K: Final[int] = 50
"""各通道（词法/语义）最大召回数"""

DEDUP_PGTRGM_MIN_SIMILARITY: Final[float] = 0.4
"""pg_trgm similarity() DB 层粗筛最低阈值"""

DEDUP_MIN_FINAL_SCORE: Final[float] = 0.58
"""去重建议最终展示最低分"""

DEDUP_CONFLICT_FIELDS: Final[list[str]] = [
    "weapon", "ability", "affiliation", "title", "species", "gender", "age",
]
"""content_json 中需检测冲突的关键字段"""

# ============================================================
# 应用信息
# ============================================================

APP_NAME: Final[str] = "ai-novel-structural-engine"
"""应用名称"""

APP_VERSION: Final[str] = "2.0.0"
"""应用版本"""

API_PREFIX: Final[str] = "/api"
"""API 路由前缀"""

# ============================================================
# 数据库
# ============================================================

DEFAULT_POOL_SIZE: Final[int] = 10
"""默认连接池大小"""

DEFAULT_MAX_OVERFLOW: Final[int] = 20
"""默认最大溢出连接数"""
