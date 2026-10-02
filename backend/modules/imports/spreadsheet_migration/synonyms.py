"""同义词与轻量解析工具（计划 §3.2）— L1 车道实现。"""

from __future__ import annotations

__all__ = [
    "guess_relation_kind",
    "normalize_entity_type",
    "parse_chapter_ref",
    "split_aliases",
]


def normalize_entity_type(label: str) -> str:
    """把作者的类型标签归一为系统 key 或作者自定义类型。"""
    raise NotImplementedError("L1 车道实现")


def split_aliases(text: str) -> list[str]:
    """按 、,，;；/| 和换行拆分别名。"""
    raise NotImplementedError("L1 车道实现")


def parse_chapter_ref(text: str) -> tuple[int, int] | None:
    """解析 第N章 / 阿拉伯 / 中文数字 / 区间，返回 (start, end)。"""
    raise NotImplementedError("L1 车道实现")


def guess_relation_kind(relation_type: str, *, both_characters: bool) -> tuple[str, bool]:
    """按关键词推测关系种类；返回 (kind, guessed)。"""
    raise NotImplementedError("L1 车道实现")
