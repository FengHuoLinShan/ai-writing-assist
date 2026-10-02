"""表类型与列映射建议契约（计划 §3.2）— 识别规则实现。

表类型关键词表和列同义词表见计划 §4「L1 解析与识别」；所有建议都是可被
作者在预览中逐表、逐列调整的默认值，confident=False 表示推测性建议。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from modules.imports.spreadsheet_migration.constants import (
    CHARACTER_COLUMN_TARGETS,
    RELATION_COLUMN_TARGETS,
    STORY_COLUMN_TARGETS,
    WORLD_COLUMN_TARGETS,
    ColumnTarget,
    SheetKind,
)
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

_HEADER_SCAN_ROWS = 10
_SHORT_HEADER_CHARS = 20
_LONG_CELL_CHARS = 100
_SUMMARY_AUTHOR_NOTE_CHARS = 5000
_ROLE_AUTHOR_NOTE_CHARS = 64

# 表名关键词（顺序即优先级：关系先于人物，避免「人物关系」误判）。
_SHEET_NAME_KIND_KEYWORDS: tuple[tuple[SheetKind, tuple[str, ...]], ...] = (
    ("relations", ("关系",)),
    ("characters", ("人物", "角色", "人设", "NPC", "npc", "人物小传")),
    (
        "world_objects",
        (
            "地点",
            "势力",
            "组织",
            "门派",
            "宗门",
            "物品",
            "道具",
            "法宝",
            "种族",
            "功法",
            "技能",
            "设定",
            "词条",
            "名词",
            "术语",
            "世界观",
        ),
    ),
    ("chapter_outline", ("细纲", "章纲", "章节大纲")),
    ("arcs", ("卷纲", "分卷", "阶段")),
    ("threads", ("主线", "支线", "剧情线")),
    ("foreshadowing", ("伏笔", "埋线")),
    ("story_outline", ("总纲", "故事大纲")),
    ("skip", ("时间线", "字数", "写作计划")),
)

# 列同义词：按声明顺序匹配，越靠前优先级越高；story 组仅在故事类表中生效。
_ENTITY_HEADER_SYNONYMS: tuple[tuple[ColumnTarget, tuple[str, ...]], ...] = (
    ("name", ("名称", "姓名", "角色名", "人物名", "名字", "name", "Name")),
    ("aliases", ("别名", "外号", "称号", "又名", "昵称", "绰号", "曾用名")),
    ("entity_type", ("类型", "类别", "分类", "种类", "对象类型")),
    ("hidden_truth", ("秘密", "隐藏设定", "真相", "暗线设定")),
    ("public_info", ("公开信息", "明面信息", "表面信息")),
    ("summary", ("简介", "概要", "描述", "说明", "介绍", "概述")),
    (
        "author_note",
        ("人物小传", "背景", "生平", "小传", "传记", "经历", "备注"),
    ),
    ("role", ("身份", "定位", "职业", "头衔", "职务")),
    ("appearance", ("外貌", "长相", "形象", "外表")),
    ("personality", ("性格", "性情", "个性", "特质")),
    ("desire", ("目标", "动机", "欲望", "渴望", "所求")),
    ("fear", ("恐惧", "害怕", "畏惧")),
    ("weakness", ("弱点", "缺点", "软肋", "短板")),
    ("current_goal", ("当前目标", "现阶段目标")),
    ("current_state", ("现状", "近况", "当前状态", "目前状态")),
    ("stance", ("立场", "阵营", "态度", "倾向")),
    ("voice_style", ("口癖", "说话风格", "语言风格", "口头禅", "语气")),
    ("relationship_summary", ("人际", "人际关系", "关系概述", "社交")),
)

_RELATION_HEADER_SYNONYMS: tuple[tuple[ColumnTarget, tuple[str, ...]], ...] = (
    ("relation_type", ("关系", "关系类型", "联系", "关系描述词")),
    ("relation_description", ("描述", "说明", "备注", "详情", "关系说明")),
    ("direction", ("方向", "指向")),
)

# 关系表语境下的“名称列”同义词（第一个 → source，第二个 → target）。
_RELATION_NAME_SYNONYMS = (
    "人物",
    "角色",
    "名称",
    "姓名",
    "名字",
    "对象",
    "对方",
    "甲方",
    "乙方",
    "源",
    "起点",
    "目标",
    "终点",
    "name",
)

_STORY_HEADER_SYNONYMS: tuple[tuple[ColumnTarget, tuple[str, ...]], ...] = (
    ("chapter_ref", ("章号", "章节号", "章节", "章", "chapter")),
    ("title", ("标题", "章节标题", "章名", "题目")),
    ("content", ("内容", "正文", "情节", "梗概", "事件", "剧情", "大纲")),
    ("core_conflict", ("核心冲突", "冲突")),
    ("emotional_beat", ("情绪", "情感", "情绪点", "情感变化")),
    ("must_not_happen", ("不能写", "不能发生", "禁忌", "不许")),
    ("pov_name", ("视角", "视角人物", "POV", "pov", "主视角")),
    ("chapter_start", ("起始章", "开始章", "起章")),
    ("chapter_end", ("结束章", "终章", "止章")),
    ("thread_type", ("线类型", "线别")),
    ("seed_chapter", ("埋设章", "种子章", "埋下")),
    ("payoff_chapter", ("回收章", "兑现章", "揭示章")),
    ("reinforce_chapters", ("强化章", "巩固章")),
    ("surface_meaning", ("表面", "表象", "明面意义")),
    ("hidden_meaning", ("深层", "真实含义", "暗中含义", "深意")),
    ("related_names", ("相关人物", "关联人物", "相关角色", "涉及人物")),
    ("arc_goal", ("卷目标", "阶段目标", "卷纲目标")),
    ("climax", ("高潮", "大高潮")),
    ("result", ("结果", "结局")),
    ("next_hook", ("钩子", "悬念", "下一卷钩子")),
    (
        "author_note",
        ("备注", "说明", "作者备注", "注"),
    ),
)


def _normalize_header(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).casefold()


def _header_matches(header: str, keywords: tuple[str, ...]) -> bool:
    normalized = _normalize_header(header)
    if not normalized:
        return False
    for keyword in keywords:
        normalized_keyword = _normalize_header(keyword)
        if normalized_keyword and (
            normalized == normalized_keyword or normalized_keyword in normalized
        ):
            return True
    return False


def _lookup_header_target(
    header: str,
    table: tuple[tuple[ColumnTarget, tuple[str, ...]], ...],
) -> ColumnTarget | None:
    """先按归一化精确命中，再按包含命中。

    两阶段让「埋设章/回收章」这类具体表头不被泛化的「章」抢先命中。
    """
    normalized = _normalize_header(header)
    if not normalized:
        return None
    for target, keywords in table:
        for keyword in keywords:
            if normalized == _normalize_header(keyword):
                return target
    for target, keywords in table:
        if _header_matches(header, keywords):
            return target
    return None


def _header_synonym_hits(cells: list[str]) -> int:
    """统计一行里命中任一列同义词的单元格数。"""
    hits = 0
    for cell in cells:
        if not str(cell).strip():
            continue
        if (
            _lookup_header_target(cell, _ENTITY_HEADER_SYNONYMS) is not None
            or _lookup_header_target(cell, _STORY_HEADER_SYNONYMS) is not None
            or _lookup_header_target(cell, _RELATION_HEADER_SYNONYMS) is not None
        ):
            hits += 1
    return hits


def detect_header_row(rows: list[list[str]]) -> int:
    """在前 10 行内定位表头行（0 起）。

    评分规则：短单元格多、同义词命中多者优先；只有一个较长非空单元格的
    合并标题行跳过。找不到更好的候选时回落到第 0 行。
    """
    best_row = 0
    best_score = -1.0
    for index, row in enumerate(rows[:_HEADER_SCAN_ROWS]):
        cells = [str(cell).strip() for cell in row]
        non_empty = [cell for cell in cells if cell]
        if not non_empty:
            continue
        # 合并标题行：整行只有一个较长的非空单元格。
        if len(non_empty) == 1 and len(non_empty[0]) > _SHORT_HEADER_CHARS:
            continue
        short_count = sum(1 for cell in non_empty if len(cell) <= _SHORT_HEADER_CHARS)
        synonym_hits = _header_synonym_hits(non_empty)
        score = (
            synonym_hits * 2.0
            + short_count / len(non_empty)
            + min(len(non_empty), 10) * 0.1
        )
        if score > best_score:
            best_row = index
            best_score = score
    return best_row


def _sheet_name_kind(name: str) -> SheetKind | None:
    normalized = _normalize_header(name)
    if not normalized:
        return None
    for kind, keywords in _SHEET_NAME_KIND_KEYWORDS:
        for keyword in keywords:
            normalized_keyword = _normalize_header(keyword)
            if normalized_keyword and normalized_keyword in normalized:
                return kind
    return None


def _column_values(rows: list[list[str]], header_row: int, column_idx: int) -> list[str]:
    values: list[str] = []
    for row in rows[header_row + 1 :]:
        if column_idx < len(row):
            value = row[column_idx].strip()
            if value:
                values.append(value)
    return values


def _detect_matrix_relations(rows: list[list[str]], header_row: int) -> bool:
    """矩阵关系表：首行（除第一格）和首列（除首格）都是名称。"""
    if header_row >= len(rows):
        return False
    header_cells = [str(cell).strip() for cell in rows[header_row]]
    if len(header_cells) < 4:
        return False
    corner = header_cells[0]
    column_names = [cell for cell in header_cells[1:] if cell]
    if len(column_names) < 3:
        return False
    if (
        corner
        and len(corner) > _SHORT_HEADER_CHARS
        and _header_synonym_hits([corner]) == 0
    ):
        return False
    header_hits = _header_synonym_hits(column_names)
    if header_hits >= max(1, len(column_names) // 2):
        return False
    row_names: list[str] = []
    for row in rows[header_row + 1 :]:
        cells = [str(cell).strip() for cell in row]
        if not any(cells):
            continue
        first = cells[0] if cells else ""
        if first:
            row_names.append(first)
    if len(row_names) < 3:
        return False
    return True


def _detect_relations_columns(
    headers: list[str],
) -> bool:
    """两个名称列加一个关系列。"""
    name_columns = 0
    relation_columns = 0
    for header in headers:
        stripped = str(header).strip()
        if not stripped:
            continue
        if _header_matches(stripped, _RELATION_NAME_SYNONYMS):
            name_columns += 1
        elif _lookup_header_target(stripped, _RELATION_HEADER_SYNONYMS) == (
            "relation_type"
        ):
            relation_columns += 1
    return name_columns >= 2 and relation_columns >= 1


def _classify_kind(sheet: ParsedSheet, header_row: int) -> SheetKind:
    """按表名关键词和结构判断表类型。"""
    if sheet.hidden:
        return "skip"
    rows = sheet.rows
    if not rows or not any(any(str(c).strip() for c in row) for row in rows):
        return "skip"
    name_kind = _sheet_name_kind(sheet.name)
    headers = [str(cell) for cell in rows[header_row]] if header_row < len(rows) else []

    if name_kind == "skip":
        return "skip"
    if name_kind is not None:
        return name_kind

    # 结构判断（表名没有线索时）。
    if _detect_matrix_relations(rows, header_row):
        return "relations"
    if _detect_relations_columns(headers):
        return "relations"

    chapter_column = any(
        _lookup_header_target(header, _STORY_HEADER_SYNONYMS) == "chapter_ref"
        for header in headers
        if str(header).strip()
    )
    content_column = any(
        _lookup_header_target(header, _STORY_HEADER_SYNONYMS) == "content"
        for header in headers
        if str(header).strip()
    )
    if chapter_column and content_column:
        return "chapter_outline"

    character_field_hits = sum(
        1
        for header in headers
        if str(header).strip()
        and _lookup_header_target(header, _ENTITY_HEADER_SYNONYMS)
        in CHARACTER_COLUMN_TARGETS
    )
    name_column = any(
        _lookup_header_target(header, _ENTITY_HEADER_SYNONYMS) == "name"
        for header in headers
        if str(header).strip()
    )
    if name_column and character_field_hits >= 1:
        return "characters"

    world_field_hits = sum(
        1
        for header in headers
        if str(header).strip()
        and _lookup_header_target(header, _ENTITY_HEADER_SYNONYMS) in WORLD_COLUMN_TARGETS
    )
    if name_column and world_field_hits >= 2:
        return "world_objects"

    # 像大纲但无可用列 → 自由文本大纲；否则跳过。
    outline_name = any(
        keyword in _normalize_header(sheet.name)
        for keyword in ("大纲", "剧情", "梗概", "故事")
    )
    has_long_content = False
    for column_idx in range(len(headers)):
        values = _column_values(rows, header_row, column_idx)
        if any(len(value) > _LONG_CELL_CHARS for value in values):
            has_long_content = True
            break
    if outline_name or has_long_content:
        return "freeform_outline"
    return "skip"


def _entity_column_target(
    header: str, kind: SheetKind, values: list[str]
) -> tuple[ColumnTarget, bool]:
    """实体类表的列目标；返回 (target, confident)。"""
    stripped = str(header).strip()
    if not stripped:
        return "ignore", True
    target = _lookup_header_target(stripped, _ENTITY_HEADER_SYNONYMS)
    if target is None:
        return "author_note", False
    confident = True
    # character 组只对人物有效；其余实体表转到作者备注。
    if kind == "world_objects" and target in CHARACTER_COLUMN_TARGETS:
        return "author_note", False
    # 长内容按计划改投作者备注（超长简介 / 超长身份）。
    if target == "summary" and any(len(v) > _SUMMARY_AUTHOR_NOTE_CHARS for v in values):
        return "author_note", confident
    if target == "role" and any(len(v) > _ROLE_AUTHOR_NOTE_CHARS for v in values):
        return "author_note", confident
    return target, confident


def _relation_column_target(
    header: str, name_order: dict[str, int]
) -> tuple[ColumnTarget, bool]:
    stripped = str(header).strip()
    if not stripped:
        return "ignore", True
    if _header_matches(stripped, _RELATION_NAME_SYNONYMS):
        order = name_order.get(_normalize_header(stripped))
        if order == 0:
            return "source_name", True
        if order == 1:
            return "target_name", True
        return "author_note", False
    target = _lookup_header_target(stripped, _RELATION_HEADER_SYNONYMS)
    if target is not None:
        return target, True
    return "author_note", False


def _story_column_target(header: str) -> tuple[ColumnTarget, bool]:
    stripped = str(header).strip()
    if not stripped:
        return "ignore", True
    target = _lookup_header_target(stripped, _STORY_HEADER_SYNONYMS)
    if target is not None:
        return target, True
    target = _lookup_header_target(stripped, _ENTITY_HEADER_SYNONYMS)
    if target in {"name", "aliases", "summary", "author_note", "related_names"}:
        if target == "name":
            return "related_names", False
        if target == "summary":
            return "content", False
        return target, False
    return "author_note", False


def _sanitize_target(target: ColumnTarget, kind: SheetKind) -> ColumnTarget:
    """把列目标限制在该表类型可用的目标组内。"""
    if kind == "characters":
        allowed: frozenset[str] = WORLD_COLUMN_TARGETS | CHARACTER_COLUMN_TARGETS
    elif kind == "world_objects":
        allowed = WORLD_COLUMN_TARGETS
    elif kind == "relations":
        allowed = RELATION_COLUMN_TARGETS
    else:
        allowed = STORY_COLUMN_TARGETS
    if target in allowed:
        return target
    return "ignore" if kind == "relations" else "author_note"


def classify_sheet(sheet: ParsedSheet, header_row: int | None = None) -> SheetSuggestion:
    """按表名和表头同义词规则识别表类型并给出列映射建议。"""
    if header_row is None:
        resolved_header_row = detect_header_row(sheet.rows)
    else:
        resolved_header_row = header_row
    if sheet.rows:
        resolved_header_row = max(0, min(resolved_header_row, len(sheet.rows) - 1))
    else:
        resolved_header_row = 0
    kind = _classify_kind(sheet, resolved_header_row)

    headers = (
        [str(cell) for cell in sheet.rows[resolved_header_row]]
        if resolved_header_row < len(sheet.rows)
        else []
    )

    name_order: dict[str, int] = {}
    if kind == "relations":
        seen = 0
        for header in headers:
            if str(header).strip() and _header_matches(header, _RELATION_NAME_SYNONYMS):
                name_order[_normalize_header(header)] = seen
                seen += 1

    columns: list[ColumnSuggestion] = []
    for index, header in enumerate(headers):
        values = _column_values(sheet.rows, resolved_header_row, index)
        if kind in {"characters", "world_objects"}:
            target, confident = _entity_column_target(header, kind, values)
        elif kind == "relations":
            target, confident = _relation_column_target(header, name_order)
        elif kind == "skip":
            target, confident = "ignore", True
        else:
            target, confident = _story_column_target(header)
        columns.append(
            ColumnSuggestion(
                column_key=f"c{index}",
                header=str(header).strip(),
                target=_sanitize_target(target, kind),
                confident=confident,
            )
        )

    return SheetSuggestion(
        kind=kind,
        header_row=resolved_header_row,
        columns=columns,
    )
