"""
Import 对外契约

定义其他模块可以安全依赖的导入模块数据接口。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ImportContract:
    """导入记录契约 — 其他模块通过此契约获取导入元信息"""
    novel_id: str
    file_name: str
    file_type: str
    file_size: int
    total_chapters: int
    imported_chapters: int
    status: str
    error_message: str | None = None


# facade 返回类型（Pydantic schema），供跨模块导入使用
from modules.imports.schemas import ImportResponse  # noqa: F401 — facade.import_file 返回
