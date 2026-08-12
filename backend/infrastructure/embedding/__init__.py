"""
Embedding 基础设施

提供本地 BGE ONNX / sentence-transformers 推理和 LRU 缓存。
通过 LLMClient.generate_embedding() 统一路由，调用方无需感知后端切换。
"""

from infrastructure.embedding.cache import EmbeddingCache
from infrastructure.embedding.client import BgeEmbeddingClient

__all__ = ["EmbeddingCache", "BgeEmbeddingClient"]
