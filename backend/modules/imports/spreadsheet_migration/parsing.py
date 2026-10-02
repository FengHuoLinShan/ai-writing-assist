"""表格解析契约（计划 §3.2）— L1 车道实现解析逻辑，L4 通过 asyncio.to_thread 调用。"""

from __future__ import annotations

from dataclasses import dataclass, field

from modules.imports.spreadsheet_migration.constants import (
    MAX_CELL_CHARS,
    MAX_COLUMNS,
    MAX_ROWS_PER_SHEET,
    MAX_SHEETS_PER_FILE,
)


@dataclass(frozen=True)
class ParsedSheet:
    """一张解析后的工作表；rows 全部为字符串，合并单元格已填充。"""

    sheet_key: str  # f"f{file_idx}s{sheet_idx}"，会话内唯一
    file_key: str  # f"f{file_idx}"
    name: str  # 表名；csv 用去扩展名的文件名
    hidden: bool
    rows: list[list[str]]
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ParsedUpload:
    """一次上传解析出的全部工作表。"""

    file_key: str
    file_name: str
    file_type: str
    size: int
    sha256: str
    sheets: list[ParsedSheet] = field(default_factory=list)


__all__ = [
    "MAX_CELL_CHARS",
    "MAX_COLUMNS",
    "MAX_ROWS_PER_SHEET",
    "MAX_SHEETS_PER_FILE",
    "ParsedSheet",
    "ParsedUpload",
    "parse_xlsx",
    "parse_csv",
]


def parse_xlsx(data: bytes, *, file_key: str, file_name: str) -> ParsedUpload:
    """有界解析 xlsx 字节流；违规抛 ValueError（作者可读）。"""
    raise NotImplementedError("L1 车道实现")


def parse_csv(data: bytes, *, file_key: str, file_name: str) -> ParsedUpload:
    """有界解析 csv 字节流；违规抛 ValueError（作者可读）。"""
    raise NotImplementedError("L1 车道实现")
