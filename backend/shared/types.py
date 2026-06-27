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

type LocationID = str
"""地理地点 ID (UUID hex string)"""

type RelationshipID = str
"""关系 ID (UUID hex string)"""

type MemoryRecordID = str
"""记忆记录 ID (UUID hex string)"""

type TimelineEventID = str
"""时间线事件 ID (UUID hex string)"""

type PlotThreadID = str
"""剧情线 ID (UUID hex string)"""

type ArcID = str
"""篇章 ID (UUID hex string)"""

type ChapterCardID = str
"""章节卡 ID (UUID hex string)"""

type ForeshadowingPlanID = str
"""伏笔计划 ID (UUID hex string)"""

type RevealPlanID = str
"""揭示计划 ID (UUID hex string)"""

type ReviewReportID = str
"""复查报告 ID (UUID hex string)"""

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
