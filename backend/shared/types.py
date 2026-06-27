"""
全局类型别名

为所有模块提供一致的 UUID 字符串类型别名。
所有 ID 在 API/contract 层以 str 传递，在 ORM 层为 uuid.UUID。
"""

from __future__ import annotations

# ---- 核心 ID 类型别名 ----

type NovelID = str
"""小说项目 ID (UUID hex string)"""

type EntityID = str
"""世界对象 ID (UUID hex string)"""

type CharacterID = str
"""人物 ID (UUID hex string)"""

type RelationshipID = str
"""关系 ID (UUID hex string)"""

type SnapshotID = str
"""记忆快照 ID (UUID hex string)"""

type DraftID = str
"""正文草稿 ID (UUID hex string)"""

type TaskID = str
"""异步任务 ID (UUID hex string)"""

# ---- 通用类型别名 ----

type JSON = dict[str, object]
"""通用 JSON 对象"""

type JSONList = list[object]
"""通用 JSON 数组"""

type ChapterIndex = int
"""章节索引（从 1 开始）"""

type EmbeddingVector = list[float]
"""Embedding 向量"""
