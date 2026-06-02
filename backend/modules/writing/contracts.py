"""
Writing 对外契约

定义其他模块可以安全依赖的正文草稿接口和数据类。
其他模块只能导入 contracts.py 和 facade.py，禁止直接导入 models/repositories/services。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WritingDraftContract:
    """正文草稿契约 — 其他模块通过此契约获取草稿信息"""

    novel_id: str
    chapter_index: int
    title: str | None = None
    content: str | None = None
    version_number: int = 1


# facade 返回类型（Pydantic schema），供跨模块导入使用
from modules.writing.schemas import WritingDraftResponse  # noqa: F401 — facade.create_draft 返回
