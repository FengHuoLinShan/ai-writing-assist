"""表类型与列映射建议契约（计划 §3.2）— L1 车道实现识别规则。"""

from __future__ import annotations

from dataclasses import dataclass, field

from modules.imports.spreadsheet_migration.constants import ColumnTarget, SheetKind
from modules.imports.spreadsheet_migration.parsing import ParsedSheet


@dataclass(frozen=True)
class ColumnSuggestion:
    column_key: str  # f"c{index}"
    header: str
    target: ColumnTarget
    confident: bool


@dataclass(frozen=True)
class SheetSuggestion:
    kind: SheetKind
    header_row: int  # 0 起
    columns: list[ColumnSuggestion] = field(default_factory=list)


__all__ = [
    "ColumnSuggestion",
    "SheetSuggestion",
    "classify_sheet",
    "detect_header_row",
]


def detect_header_row(rows: list[list[str]]) -> int:
    """在前 10 行内定位表头行（0 起）。"""
    raise NotImplementedError("L1 车道实现")


def classify_sheet(sheet: ParsedSheet, header_row: int | None = None) -> SheetSuggestion:
    """按表名和表头同义词规则识别表类型并给出列映射建议。"""
    raise NotImplementedError("L1 车道实现")
