"""
Writing 对外契约

定义其他模块可以安全依赖的正文草稿接口和数据类。
其他模块只能导入 contracts.py 和 facade.py，禁止直接导入 models/repositories/services。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WritingDraftContract:
    """正文草稿契约 — 其他模块通过此契约获取草稿信息

    所有字段均为只读，不可变对象。
    """

    novel_id: str
    """小说项目 ID"""
    chapter_index: int
    """章节索引"""
    chapter_card_id: str | None = None
    """关联的章节卡 ID"""
    title: str | None = None
    """草稿标题"""
    content: str | None = None
    """草稿正文"""
    version_number: int = 1
    """版本号"""
    status: str = "draft"
    """状态"""


# facade 返回类型（Pydantic schema），供跨模块导入使用
from modules.writing.schemas import WritingDraftResponse  # noqa: F401 — facade.create_draft 返回
