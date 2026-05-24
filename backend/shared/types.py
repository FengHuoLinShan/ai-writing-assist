"""
全局类型别名

为所有模块提供一致的 UUID 字符串类型别名。
所有 ID 在 API/contract 层以 str 传递，在 ORM 层为 uuid.UUID。
"""

from __future__ import annotations

from typing import TypeAlias

# ---- 核心 ID 类型别名 ----

NovelID: TypeAlias = str
"""小说项目 ID (UUID hex string)"""

EntityID: TypeAlias = str
"""世界对象 ID (UUID hex string)"""

CharacterID: TypeAlias = str
"""人物 ID (UUID hex string)"""

LocationID: TypeAlias = str
"""地理地点 ID (UUID hex string)"""

RelationshipID: TypeAlias = str
"""关系 ID (UUID hex string)"""

MemoryRecordID: TypeAlias = str
"""记忆记录 ID (UUID hex string)"""

TimelineEventID: TypeAlias = str
"""时间线事件 ID (UUID hex string)"""

PlotThreadID: TypeAlias = str
"""剧情线 ID (UUID hex string)"""

ArcID: TypeAlias = str
"""篇章 ID (UUID hex string)"""

ChapterCardID: TypeAlias = str
"""章节卡 ID (UUID hex string)"""

ForeshadowingPlanID: TypeAlias = str
"""伏笔计划 ID (UUID hex string)"""

RevealPlanID: TypeAlias = str
"""揭示计划 ID (UUID hex string)"""

ReviewReportID: TypeAlias = str
"""复查报告 ID (UUID hex string)"""

DraftID: TypeAlias = str
"""正文草稿 ID (UUID hex string)"""

TaskID: TypeAlias = str
"""异步任务 ID (UUID hex string)"""

# ---- 通用类型别名 ----

JSON: TypeAlias = dict[str, object]
"""通用 JSON 对象"""

JSONList: TypeAlias = list[object]
"""通用 JSON 数组"""

ChapterIndex: TypeAlias = int
"""章节索引（从 1 开始）"""

EmbeddingVector: TypeAlias = list[float]
"""Embedding 向量"""
