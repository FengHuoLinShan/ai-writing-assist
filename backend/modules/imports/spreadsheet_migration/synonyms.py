"""同义词与轻量解析工具（计划 §3.2）— 规则实现。

实体类型归一复用 world contracts 导出的 ``normalize_author_entity_type``
（作者边界，允许自定义类型）；表格迁移的覆盖规则见计划 §4：设定/词条/名词/术语 → concept
（覆盖 ENTITY_TYPE_MAP["设定"]="secret"）、法宝/装备 → item、门派/宗门 →
faction、功法 → skill、境界/修炼体系 → power_system。
"""

from __future__ import annotations

import re

from modules.world.contracts import normalize_author_entity_type

__all__ = [
    "guess_relation_kind",
    "normalize_entity_type",
    "parse_chapter_ref",
    "split_aliases",
]

# 表格迁移的类型覆盖：优先于 world 的 ENTITY_TYPE_MAP。
_SPREADSHEET_ENTITY_TYPE_OVERRIDES: dict[str, str] = {
    "设定": "concept",
    "词条": "concept",
    "名词": "concept",
    "术语": "concept",
    "法宝": "item",
    "装备": "item",
    "门派": "faction",
    "宗门": "faction",
    "功法": "skill",
    "境界": "power_system",
    "修炼体系": "power_system",
}

_RELATION_KIND_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "social",
        (
            "师",
            "徒",
            "父",
            "母",
            "兄",
            "姐",
            "妹",
            "弟",
            "友",
            "敌",
            "恋",
            "夫",
            "妻",
            "仇",
            "盟",
            "同门",
            "上司",
            "下属",
        ),
    ),
    ("spatial", ("位于", "坐落", "相邻")),
    ("causal", ("导致", "引发")),
    ("epistemic", ("知道", "隐瞒", "怀疑")),
    ("intentional", ("想要", "追杀", "保护", "效忠")),
    ("state", ("持有", "拥有", "成员", "属于", "隶属")),
    ("temporal", ("之前", "之后", "继任")),
)

_ALIAS_SPLIT_PATTERN = re.compile(r"[、,，;；/|\r\n]+")

_CN_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}

_CHAPTER_NUMBER = r"(?:[0-9]+|[零〇一二两三四五六七八九十百千万]+)"
_CHAPTER_RANGE_CONNECTOR = r"(?:[-–—~～]|至|到)"
_CHAPTER_WITH_MARKER = re.compile(
    rf"^第\s*({_CHAPTER_NUMBER})\s*[章回节]?\s*"
    rf"(?:{_CHAPTER_RANGE_CONNECTOR}\s*(?:第\s*)?({_CHAPTER_NUMBER})\s*[章回节]?)?\s*$"
)
_CHAPTER_BARE = re.compile(
    rf"^({_CHAPTER_NUMBER})(?:\s*{_CHAPTER_RANGE_CONNECTOR}\s*({_CHAPTER_NUMBER}))?\s*$"
)


def normalize_entity_type(label: str) -> str:
    """把作者的类型标签归一为系统 key 或作者自定义类型。

    空标签返回空字符串（调用方按“未填写”处理）；无法通过 world 作者边界
    校验的极端值按原文小写返回，正式落库时由 Pydantic 契约再拦一次。
    """
    normalized = str(label or "").strip()
    if not normalized:
        return ""
    override = _SPREADSHEET_ENTITY_TYPE_OVERRIDES.get(normalized) or (
        _SPREADSHEET_ENTITY_TYPE_OVERRIDES.get(normalized.casefold())
    )
    if override:
        return override
    try:
        return normalize_author_entity_type(normalized)
    except ValueError:
        return normalized.casefold()


def split_aliases(text: str) -> list[str]:
    """按 、,，;；/| 和换行拆分别名；去空白、去重且保持顺序。"""
    if not text or not str(text).strip():
        return []
    parts = _ALIAS_SPLIT_PATTERN.split(str(text))
    return list(dict.fromkeys(part.strip() for part in parts if part.strip()))


def _chinese_number_to_int(text: str) -> int | None:
    """中文数字（≤ 万级）转 int；无法解析返回 None。"""
    total = 0
    section = 0
    digit = 0
    for char in text:
        if char in _CN_DIGITS:
            digit = _CN_DIGITS[char]
        elif char == "十":
            section += (digit or 1) * 10
            digit = 0
        elif char == "百":
            section += (digit or 1) * 100
            digit = 0
        elif char == "千":
            section += (digit or 1) * 1000
            digit = 0
        elif char == "万":
            section = (section + digit) * 10000
            total += section
            section = 0
            digit = 0
        else:
            return None
    return total + section + digit


def _chapter_token_to_int(token: str | None) -> int | None:
    if token is None:
        return None
    token = token.strip()
    if not token:
        return None
    if token.isdigit():
        return int(token)
    return _chinese_number_to_int(token)


def parse_chapter_ref(text: str) -> tuple[int, int] | None:
    """解析 第N章 / 阿拉伯 / 中文数字 / 区间，返回 (start, end)。

    支持形如 ``第3章``、``第三章``、``第 3-5 章``、``第三章至第五章``、
    ``3-5``、``十二``；无法解析或章号非法（<1、区间倒序）返回 None。
    """
    normalized = str(text or "").strip()
    if not normalized:
        return None
    match = _CHAPTER_WITH_MARKER.match(normalized) or _CHAPTER_BARE.match(normalized)
    if match is None:
        return None
    start = _chapter_token_to_int(match.group(1))
    end = _chapter_token_to_int(match.group(2)) if match.group(2) else start
    if start is None or end is None or start < 1 or end < 1:
        return None
    if end < start:
        return None
    return start, end


def guess_relation_kind(relation_type: str, *, both_characters: bool) -> tuple[str, bool]:
    """按关键词推测关系种类；返回 (kind, guessed)。

    关键词命中时 guessed=False（有依据）；两端兜底（双人物 → social，其余 →
    state）时 guessed=True（推测，需作者确认）。
    """
    normalized = str(relation_type or "").strip()
    if normalized:
        for kind, keywords in _RELATION_KIND_KEYWORDS:
            if any(keyword in normalized for keyword in keywords):
                return kind, False
    if both_characters:
        return "social", True
    return "state", True
