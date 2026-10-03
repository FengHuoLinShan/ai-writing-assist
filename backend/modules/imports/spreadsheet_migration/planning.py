"""按 mapping 把 rows 转成 world/story 迁移请求（计划 §4 L4）。

规则：
- 文件内同名同类型的行合并，值不一致时以作者备注形式记录文件内冲突；
- item_key 由 sheet_key、行号和名称确定性生成（^[a-z0-9_-]{1,64}$）；
- source_hash 为合并行单元格的 sha256；
- AI 条目只合并 ai_items_for_planning 返回的（已通过审查且作者接受的）条目，
  未覆盖/失败行回落规则映射（原文写入 must_happen 或作者备注）。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from core.errors import ValidationError
from modules.imports.spreadsheet_migration import synonyms
from modules.imports.spreadsheet_migration.ai import AiPlanningInput
from modules.imports.spreadsheet_migration.constants import (
    MAX_APPLY_ITEMS,
    MAX_RELATIONS,
)
from modules.story.outline_state.contracts import (
    AuthorMigrationOutlineInput,
    AuthorMigrationStoryItem,
    AuthorMigrationStoryRequest,
)
from modules.world.contracts import (
    AuthorMigrationEntityInput,
    AuthorMigrationRelationInput,
    AuthorMigrationWorldRequest,
    AuthorNote,
)

# L3 集成点：总纲 creative_core 缺失时 story 计划用该合成键表达 conflict，
# 预览渲染时把该键显示为“总纲”。与 outline_state.author_migration.OUTLINE_ITEM_KEY
# 约定同值（L3 分支实现该常量，L8 集成时统一）。
OUTLINE_ITEM_KEY = "__outline__"

_ITEM_KEY_PATTERN = re.compile(r"^[a-z0-9_-]{1,64}$")
_ROW_REF_PATTERN = re.compile(r"^([a-z0-9_-]+):r(\d+)$")
_SYMMETRIC_DIRECTION_VALUES = frozenset(
    {"双向", "对称", "互为", "无向", "both", "symmetric", "mutual"}
)
_ENTITY_DECISIONS = frozenset(
    {"auto", "different_object", "use_existing", "append_note", "skip"}
)
_RELATION_DECISIONS = frozenset({"auto", "skip"})
_STORY_DECISIONS = frozenset({"auto", "skip"})
_RELATION_KINDS = frozenset(
    {"state", "social", "spatial", "causal", "temporal", "epistemic", "intentional"}
)

# 大纲类表（默认等待 AI 结果；未覆盖/失败行回落规则映射，原文逐字保留）。
OUTLINE_SHEET_KINDS = frozenset(
    {
        "chapter_outline",
        "arcs",
        "threads",
        "foreshadowing",
        "story_outline",
        "freeform_outline",
    }
)

# 各故事表的“正文”列落到哪个字段（原文逐字保留的目标）。
_STORY_PRIMARY_FIELD = {
    "chapter_outline": "must_happen",
    "arcs": "arc_goal",
    "threads": "summary",
    "foreshadowing": "surface_meaning",
}

_SHEET_KIND_TO_STORY_KIND = {
    "chapter_outline": "chapter_plan",
    "arcs": "arc",
    "threads": "thread",
    "foreshadowing": "foreshadowing",
}

_STORY_FIELD_WHITELISTS: dict[str, frozenset[str]] = {
    "arc": frozenset({"arc_goal", "core_conflict", "climax", "result", "next_hook"}),
    "thread": frozenset({"thread_type", "summary", "visible_goal", "hidden_truth"}),
    "foreshadowing": frozenset(
        {
            "surface_meaning",
            "hidden_meaning",
            "seed_chapter",
            "payoff_chapter",
            "reinforce_chapters",
        }
    ),
    "chapter_plan": frozenset(
        {"must_happen", "goal", "core_conflict", "emotional_beat", "must_not_happen"}
    ),
}

_CHARACTER_FIELD_TARGETS = frozenset(
    {
        "role",
        "appearance",
        "personality",
        "desire",
        "fear",
        "weakness",
        "current_goal",
        "current_state",
        "stance",
        "voice_style",
        "relationship_summary",
    }
)

_AI_CLEANUP_FIELD_TARGETS = _CHARACTER_FIELD_TARGETS | {"summary", "public_info"}

_CREATIVE_CORE_KEYS = (
    "premise",
    "tone_and_reader_promise",
    "story_engine",
    "ending_direction",
)


def _digest(text: str, length: int) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def _row_ref(sheet_key: str, row: int) -> str:
    return f"{sheet_key}:r{row}"


def _parse_row_ref(ref: str) -> tuple[str, int] | None:
    match = _ROW_REF_PATTERN.fullmatch(ref or "")
    if match is None:
        return None
    return match.group(1), int(match.group(2))


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _rows_hash(rows: list[list[str]]) -> str:
    payload = [[(cell or "") for cell in row] for row in rows]
    return hashlib.sha256(_json_dumps(payload).encode("utf-8")).hexdigest()


def _item_key(sheet_key: str, row: int, name: str) -> str:
    key = f"{sheet_key}-r{row}-{_digest(name, 8)}"
    if not _ITEM_KEY_PATTERN.fullmatch(key):  # pragma: no cover - 防御式
        key = f"i-{_digest(key, 24)}"
    return key[:64]


def _ai_item_key(proposal_ref: str) -> str:
    return f"ai-{_digest(proposal_ref, 16)}"


@dataclass(frozen=True)
class SheetContext:
    """planning 需要的一张表的全部输入（由 service 从会话组装）。"""

    sheet_key: str
    name: str
    kind: str
    header_row: int
    default_entity_type: str | None = None
    columns: dict[str, str] = field(default_factory=dict)
    rows: list[list[str]] = field(default_factory=list)


@dataclass(frozen=True)
class PlannedSource:
    """条目的来源（预览渲染用）。"""

    sheet_key: str
    sheet_name: str
    row: int


@dataclass(frozen=True)
class PlannedLabel:
    """条目的作者语言标签与来源。"""

    label: str
    source: PlannedSource | None = None


@dataclass(frozen=True)
class MigrationPlanRequests:
    """planning 的输出：world/story 请求与渲染辅助信息。"""

    world_request: AuthorMigrationWorldRequest
    story_request: AuthorMigrationStoryRequest
    labels: dict[str, PlannedLabel]
    ai_accepted_refs: tuple[str, ...]


@dataclass
class _EntityAccumulator:
    """同名同类型实体的跨行累计器。"""

    name: str
    entity_type: str
    item_key: str
    source_ref: str
    source: PlannedSource
    rows: list[list[str]] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    summary: str | None = None
    public_info: str | None = None
    hidden_truth: str | None = None
    author_notes: list[tuple[str, str]] = field(default_factory=list)
    character_fields: dict[str, str] = field(default_factory=dict)
    ai_cleanup_applied: bool = False


def _cell(row: list[str], column_key: str) -> str:
    try:
        index = int(column_key[1:])
    except ValueError as exc:
        raise ValidationError(
            "列映射无效，请刷新后重新保存",
            code="migration_column_invalid",
        ) from exc
    if index < 0 or index >= len(row):
        return ""
    return (row[index] or "").strip()


def _header_lookup(sheet: SheetContext) -> dict[str, str]:
    header_row = (
        sheet.rows[sheet.header_row] if sheet.header_row < len(sheet.rows) else []
    )
    return {
        f"c{index}": (cell or "").strip() for index, cell in enumerate(header_row)
    }


def _merge_first(
    current: str | None, incoming: str, header: str
) -> tuple[str | None, tuple[str, str] | None]:
    """合并同名字段：先到先得，值不一致时返回文件内冲突备注。"""
    if not incoming:
        return current, None
    if current is None:
        return incoming, None
    if current != incoming:
        return current, (f"{header}（不一致）", incoming[:2000])
    return current, None


def _append_note(notes: list[tuple[str, str]], label: str, value: str) -> None:
    if len(notes) < 64 and value:
        notes.append((label[:64], value))


def _merge_aliases(target: list[str], text: str) -> None:
    for alias in synonyms.split_aliases(text):
        alias = alias.strip()[:255]
        if alias and alias not in target and len(target) < 64:
            target.append(alias)


def _collect_decisions(
    decisions: dict[str, Any],
) -> tuple[dict[str, dict], dict[str, str]]:
    item_decisions: dict[str, dict] = {}
    for key, value in decisions.items():
        if key == "relation_kind_groups":
            continue
        if isinstance(value, dict):
            item_decisions[key] = value
    groups_raw = decisions.get("relation_kind_groups") or {}
    groups = {
        relation_type: kind
        for relation_type, kind in groups_raw.items()
        if isinstance(kind, str) and kind in _RELATION_KINDS
    }
    return item_decisions, groups


def _decision_action(
    item_decisions: dict[str, dict], item_key: str, allowed: frozenset[str]
) -> str:
    action = (item_decisions.get(item_key) or {}).get("action") or "auto"
    if action not in allowed:
        raise ValidationError(
            "该条目的处理方式无效，请刷新后重新选择",
            code="migration_decision_invalid",
        )
    return action


def _accepted_ai_coverage(
    ai_input: AiPlanningInput | None,
) -> dict[str, set[int]]:
    coverage: dict[str, set[int]] = {}
    if ai_input is None:
        return coverage
    for item in ai_input.items:
        for ref in item.row_refs:
            parsed = _parse_row_ref(ref)
            if parsed is None:
                continue
            sheet_key, row = parsed
            coverage.setdefault(sheet_key, set()).add(row)
    return coverage


def _accumulate_entity_row(
    sheet: SheetContext,
    row_index: int,
    row: list[str],
    targets: list[tuple[str, str]],
    entities: dict[tuple[str, str], _EntityAccumulator],
    entities_by_ref: dict[tuple[str, int], _EntityAccumulator],
) -> None:
    header_by_key = _header_lookup(sheet)
    name = ""
    raw_entity_type = ""
    aliases_text = ""
    summary = ""
    public_info = ""
    hidden_truth = ""
    notes: list[tuple[str, str]] = []
    character_fields: dict[str, str] = {}

    for column_key, target in targets:
        value = _cell(row, column_key)
        header = header_by_key.get(column_key, column_key)
        if not value:
            continue
        if target == "name":
            name = value
        elif target == "entity_type":
            raw_entity_type = value
        elif target == "aliases":
            aliases_text = value
        elif target == "summary":
            summary = value
        elif target == "public_info":
            public_info = value
        elif target == "hidden_truth":
            hidden_truth = value
        elif target == "author_note":
            _append_note(notes, f"表格·{header}", value)
        elif target in _CHARACTER_FIELD_TARGETS:
            if sheet.kind == "characters":
                character_fields[target] = value
            else:
                # character 组只对人物有效，其余表降为作者备注。
                _append_note(notes, f"表格·{header}", value)
    if not name:
        return

    entity_type = (
        synonyms.normalize_entity_type(raw_entity_type)
        if raw_entity_type
        else (
            "character"
            if sheet.kind == "characters"
            else (sheet.default_entity_type or "concept")
        )
    )
    key = (name, entity_type)
    accumulator = entities.get(key)
    if accumulator is None:
        accumulator = _EntityAccumulator(
            name=name[:255],
            entity_type=entity_type,
            item_key=_item_key(sheet.sheet_key, row_index, name),
            source_ref=_row_ref(sheet.sheet_key, row_index),
            source=PlannedSource(sheet.sheet_key, sheet.name, row_index),
        )
        entities[key] = accumulator
    accumulator.rows.append(row)
    entities_by_ref[(sheet.sheet_key, row_index)] = accumulator
    if aliases_text:
        _merge_aliases(accumulator.aliases, aliases_text)

    conflicts: list[tuple[str, str]] = []
    accumulator.summary, conflict = _merge_first(
        accumulator.summary, summary[:5000], "简介"
    )
    if conflict:
        conflicts.append(conflict)
    accumulator.public_info, conflict = _merge_first(
        accumulator.public_info, public_info[:20000], "公开信息"
    )
    if conflict:
        conflicts.append(conflict)
    accumulator.hidden_truth, conflict = _merge_first(
        accumulator.hidden_truth, hidden_truth[:20000], "秘密"
    )
    if conflict:
        conflicts.append(conflict)
    for field_name, value in character_fields.items():
        current, conflict = _merge_first(
            accumulator.character_fields.get(field_name), value[:2000], field_name
        )
        if current is not None:
            accumulator.character_fields[field_name] = current
        if conflict:
            conflicts.append(conflict)
    conflicts.extend(notes)
    for label, value in conflicts:
        _append_note(accumulator.author_notes, label, value)


def _apply_cleanup_payloads(
    ai_input: AiPlanningInput | None,
    entities_by_ref: dict[tuple[str, int], _EntityAccumulator],
) -> None:
    """把已接受的 AI 拆字段结果并入对应实体。"""
    if ai_input is None:
        return
    for item in ai_input.items:
        if item.operation != "cleanup":
            continue
        payload = item.payload or {}
        fields = payload.get("fields") or {}
        remainder = (payload.get("remainder") or "").strip()
        for ref in item.row_refs:
            parsed = _parse_row_ref(ref)
            if parsed is None:
                continue
            accumulator = entities_by_ref.get(parsed)
            if accumulator is None:
                continue
            for field_name, value in fields.items():
                if field_name not in _AI_CLEANUP_FIELD_TARGETS:
                    continue
                if not isinstance(value, str) or not value.strip():
                    continue
                value = value.strip()
                if field_name in _CHARACTER_FIELD_TARGETS:
                    accumulator.character_fields[field_name] = value[:2000]
                elif field_name == "summary":
                    accumulator.summary = value[:5000]
                else:
                    accumulator.public_info = value[:20000]
            if remainder:
                _append_note(accumulator.author_notes, "AI整理·剩余", remainder)
            accumulator.ai_cleanup_applied = True


def _materialize_entities(
    entities: dict[tuple[str, str], _EntityAccumulator],
    item_decisions: dict[str, dict],
    plan_targets: dict[str, str],
) -> list[AuthorMigrationEntityInput]:
    items: list[AuthorMigrationEntityInput] = []
    for accumulator in entities.values():
        action = _decision_action(
            item_decisions, accumulator.item_key, _ENTITY_DECISIONS
        )
        target_entity_id: str | None = None
        if action == "use_existing":
            # 目标对象来自最近一次预览计划中的 target_id（决策 payload 不携带 id）。
            target_entity_id = plan_targets.get(accumulator.item_key)
            if not target_entity_id:
                raise ValidationError(
                    "请先在预览中选择要沿用的已有对象",
                    code="migration_decision_target_missing",
                )
        items.append(
            AuthorMigrationEntityInput(
                item_key=accumulator.item_key,
                source_ref=accumulator.source_ref,
                source_hash=_rows_hash(accumulator.rows),
                name=accumulator.name,
                entity_type=accumulator.entity_type,
                aliases=list(accumulator.aliases),
                summary=accumulator.summary or None,
                public_info=accumulator.public_info or None,
                hidden_truth=accumulator.hidden_truth or None,
                author_notes=[
                    AuthorNote(label=label, value=value)
                    for label, value in accumulator.author_notes
                ],
                character_fields=dict(accumulator.character_fields),
                decision=action,
                target_entity_id=target_entity_id,
            )
        )
    return items


def _build_entities(
    sheets: list[SheetContext],
    ai_input: AiPlanningInput | None,
    item_decisions: dict[str, dict],
    plan_targets: dict[str, str],
    labels: dict[str, PlannedLabel],
) -> list[AuthorMigrationEntityInput]:
    entities: dict[tuple[str, str], _EntityAccumulator] = {}
    entities_by_ref: dict[tuple[str, int], _EntityAccumulator] = {}
    for sheet in sheets:
        if sheet.kind not in {"characters", "world_objects"}:
            continue
        targets = [
            (key, target)
            for key, target in sheet.columns.items()
            if target != "ignore"
        ]
        for row_index in range(sheet.header_row + 1, len(sheet.rows)):
            row = sheet.rows[row_index]
            if not any((cell or "").strip() for cell in row):
                continue
            _accumulate_entity_row(
                sheet, row_index, row, targets, entities, entities_by_ref
            )
    _apply_cleanup_payloads(ai_input, entities_by_ref)
    items = _materialize_entities(entities, item_decisions, plan_targets)
    for accumulator in entities.values():
        labels[accumulator.item_key] = PlannedLabel(
            label=accumulator.name,
            source=accumulator.source,
        )
    return items


def _build_relations(
    sheets: list[SheetContext],
    item_decisions: dict[str, dict],
    relation_kind_groups: dict[str, str],
    name_index: dict[str, str],
    labels: dict[str, PlannedLabel],
) -> list[AuthorMigrationRelationInput]:
    relations: list[AuthorMigrationRelationInput] = []
    for sheet in sheets:
        if sheet.kind != "relations":
            continue
        targets = [
            (key, target)
            for key, target in sheet.columns.items()
            if target != "ignore"
        ]
        for row_index in range(sheet.header_row + 1, len(sheet.rows)):
            row = sheet.rows[row_index]
            if not any((cell or "").strip() for cell in row):
                continue
            source_name = ""
            target_name = ""
            relation_type = ""
            description = ""
            direction = ""
            for column_key, target in targets:
                value = _cell(row, column_key)
                if target == "source_name":
                    source_name = value
                elif target == "target_name":
                    target_name = value
                elif target == "relation_type":
                    relation_type = value
                elif target == "relation_description":
                    description = value
                elif target == "direction":
                    direction = value
            if not (source_name and target_name and relation_type):
                continue
            item_key = _item_key(
                sheet.sheet_key, row_index, f"{source_name}->{target_name}"
            )
            raw_decision = item_decisions.get(item_key) or {}
            relation_kind = raw_decision.get("relation_kind")
            if relation_kind not in _RELATION_KINDS:
                relation_kind = relation_kind_groups.get(relation_type)
                if relation_kind not in _RELATION_KINDS:
                    relation_kind = None
            relations.append(
                AuthorMigrationRelationInput(
                    item_key=item_key,
                    source_ref=_row_ref(sheet.sheet_key, row_index),
                    source_hash=_rows_hash([row]),
                    source_name=source_name[:255],
                    target_name=target_name[:255],
                    source_item_key=name_index.get(source_name),
                    target_item_key=name_index.get(target_name),
                    relation_type=relation_type[:64],
                    relation_kind=relation_kind,
                    description=description[:5000] or None,
                    symmetric=direction.strip().lower() in _SYMMETRIC_DIRECTION_VALUES,
                    decision=_decision_action(
                        item_decisions, item_key, _RELATION_DECISIONS
                    ),
                )
            )
            labels[item_key] = PlannedLabel(
                label=f"{source_name} → {target_name}",
                source=PlannedSource(sheet.sheet_key, sheet.name, row_index),
            )
    return relations


def _story_item_from_row(
    sheet: SheetContext,
    row_index: int,
    row: list[str],
    targets: list[tuple[str, str]],
    item_decisions: dict[str, dict],
    name_index: dict[str, str],
) -> AuthorMigrationStoryItem | None:
    story_kind = _SHEET_KIND_TO_STORY_KIND[sheet.kind]
    primary_field = _STORY_PRIMARY_FIELD[sheet.kind]
    title = ""
    content = ""
    chapter_start: int | None = None
    chapter_end: int | None = None
    fields: dict[str, str] = {}
    related_names: list[str] = []
    pov_name = ""
    numeric_fields: dict[str, str] = {}

    for column_key, target in targets:
        value = _cell(row, column_key)
        if not value:
            continue
        if target == "title":
            title = value
        elif target == "content":
            content = value
        elif target == "chapter_ref":
            parsed = synonyms.parse_chapter_ref(value)
            if parsed is not None:
                chapter_start, chapter_end = parsed
        elif target == "chapter_start":
            parsed = synonyms.parse_chapter_ref(value)
            if parsed is not None:
                chapter_start = parsed[0]
        elif target == "chapter_end":
            parsed = synonyms.parse_chapter_ref(value)
            if parsed is not None:
                chapter_end = parsed[0]
        elif target == "pov_name":
            pov_name = value
        elif target == "related_names":
            related_names = synonyms.split_aliases(value)
        elif target in {"seed_chapter", "payoff_chapter", "reinforce_chapters"}:
            numeric_fields[target] = value
        elif target in _STORY_FIELD_WHITELISTS[story_kind]:
            fields[target] = value[:20000]
        # 其余列（ignore / author_note / 越白名单）不进入故事条目。

    if not (title or content or fields):
        return None

    for target in ("seed_chapter", "payoff_chapter"):
        raw_value = numeric_fields.get(target)
        if raw_value:
            parsed = synonyms.parse_chapter_ref(raw_value)
            if parsed is not None:
                fields[target] = str(parsed[0])
    reinforce_raw = numeric_fields.get("reinforce_chapters")
    if reinforce_raw:
        chapters = []
        for token in synonyms.split_aliases(reinforce_raw):
            parsed = synonyms.parse_chapter_ref(token)
            if parsed is not None:
                chapters.append(str(parsed[0]))
        if chapters:
            fields["reinforce_chapters"] = ",".join(chapters)

    if content:
        existing = fields.get(primary_field)
        fields[primary_field] = (
            content[:20000] if not existing else f"{existing}\n{content}"[:20000]
        )

    if not title:
        if chapter_start is not None:
            title = (
                f"第{chapter_start}-{chapter_end}章"
                if chapter_end is not None and chapter_end != chapter_start
                else f"第{chapter_start}章"
            )
        else:
            title = f"{sheet.name} 第{row_index + 1}行"
    item_key = _item_key(sheet.sheet_key, row_index, title)
    related_keys = [
        name_index[name] for name in related_names if name in name_index
    ][:64]
    return AuthorMigrationStoryItem(
        item_key=item_key,
        source_refs=[_row_ref(sheet.sheet_key, row_index)],
        source_hash=_rows_hash([row]),
        kind=story_kind,
        title=title[:255],
        chapter_start=chapter_start,
        chapter_end=chapter_end,
        fields=fields,
        related_entity_keys=related_keys,
        pov_entity_key=name_index.get(pov_name),
        decision=_decision_action(item_decisions, item_key, _STORY_DECISIONS),
    )


def _story_item_from_ai(
    item: Any,
    name_index: dict[str, str],
    item_decisions: dict[str, dict],
) -> AuthorMigrationStoryItem | None:
    payload = item.payload or {}
    kind = payload.get("kind")
    if kind not in _STORY_FIELD_WHITELISTS:
        return None
    whitelist = _STORY_FIELD_WHITELISTS[kind]
    fields = {
        key: value.strip()[:20000]
        for key, value in payload.items()
        if key in whitelist and isinstance(value, str) and value.strip()
    }
    title = (payload.get("title") or payload.get("name") or "").strip()
    chapter_start = payload.get("chapter_start")
    chapter_end = payload.get("chapter_end")
    chapter_start = chapter_start if isinstance(chapter_start, int) else None
    chapter_end = chapter_end if isinstance(chapter_end, int) else None
    if not title:
        title = f"第{chapter_start}章" if chapter_start is not None else "AI 整理条目"
    related_keys = [
        name_index[str(name)]
        for name in (payload.get("related_names") or [])
        if str(name) in name_index
    ][:64]
    item_key = _ai_item_key(item.proposal_ref)
    return AuthorMigrationStoryItem(
        item_key=item_key,
        source_refs=list(item.row_refs)[:64],
        source_hash=_digest(_json_dumps({"proposal_ref": item.proposal_ref}), 64),
        kind=kind,
        title=title[:255],
        chapter_start=chapter_start,
        chapter_end=chapter_end,
        fields=fields,
        related_entity_keys=related_keys,
        pov_entity_key=name_index.get(str(payload.get("pov_name") or "")),
        decision=_decision_action(item_decisions, item_key, _STORY_DECISIONS),
    )


def _outline_markdown_from_sheet(
    sheet: SheetContext, targets: list[tuple[str, str]]
) -> str:
    parts: list[str] = []
    for row_index in range(sheet.header_row + 1, len(sheet.rows)):
        row = sheet.rows[row_index]
        if not any((cell or "").strip() for cell in row):
            continue
        title = ""
        content = ""
        for column_key, target in targets:
            value = _cell(row, column_key)
            if target == "title":
                title = value
            elif target == "content":
                content = value
        if title and content:
            parts.append(f"{title}\n{content}")
        else:
            parts.append(title or content)
    return "\n\n".join(parts)


def build_migration_requests(
    *,
    migration_id: str,
    sheets: list[SheetContext],
    decisions: dict[str, Any],
    ai_input: AiPlanningInput | None = None,
    plan_targets: dict[str, str] | None = None,
    written_chapter_policy: str = "reference_only",
    outline_head_policy: str = "create_if_missing",
) -> MigrationPlanRequests:
    """按 mapping/decisions/AI 结果构造 world 与 story 迁移请求。"""
    item_decisions, relation_kind_groups = _collect_decisions(decisions)
    labels: dict[str, PlannedLabel] = {}

    entities = _build_entities(
        sheets,
        ai_input,
        item_decisions,
        plan_targets or {},
        labels,
    )
    name_index = {entity.name: entity.item_key for entity in entities}
    for entity in entities:
        for alias in entity.aliases:
            name_index.setdefault(alias, entity.item_key)
    relations = _build_relations(
        sheets, item_decisions, relation_kind_groups, name_index, labels
    )

    story_items: list[AuthorMigrationStoryItem] = []
    outline_parts: list[str] = []
    outline_titles: list[str] = []
    creative_core: dict[str, str] = {}

    accepted_outline_row_refs: set[str] = set()
    if ai_input is not None:
        for item in ai_input.items:
            converted = _story_item_from_ai(item, name_index, item_decisions)
            if converted is not None:
                story_items.append(converted)
                source = None
                if item.row_refs:
                    parsed = _parse_row_ref(item.row_refs[0])
                    if parsed is not None:
                        sheet = _find_sheet(sheets, parsed[0])
                        source = (
                            PlannedSource(parsed[0], sheet.name, parsed[1])
                            if sheet is not None
                            else None
                        )
                labels[converted.item_key] = PlannedLabel(
                    label=converted.title, source=source
                )
                if item.operation == "outline":
                    accepted_outline_row_refs.update(item.row_refs)
                continue
            outline_core = (
                item.operation == "outline"
                and (item.payload or {}).get("kind") == "creative_core"
            )
            if outline_core:
                payload = item.payload or {}
                for core_key in _CREATIVE_CORE_KEYS:
                    value = payload.get(core_key)
                    if isinstance(value, str) and value.strip():
                        creative_core[core_key] = value.strip()[:20000]

    for sheet in sheets:
        targets = [
            (key, target)
            for key, target in sheet.columns.items()
            if target != "ignore"
        ]
        if sheet.kind in _SHEET_KIND_TO_STORY_KIND:
            for row_index in range(sheet.header_row + 1, len(sheet.rows)):
                if _row_ref(sheet.sheet_key, row_index) in accepted_outline_row_refs:
                    continue
                item = _story_item_from_row(
                    sheet,
                    row_index,
                    sheet.rows[row_index],
                    targets,
                    item_decisions,
                    name_index,
                )
                if item is None:
                    continue
                story_items.append(item)
                labels[item.item_key] = PlannedLabel(
                    label=item.title,
                    source=PlannedSource(sheet.sheet_key, sheet.name, row_index),
                )
        elif sheet.kind in {"story_outline", "freeform_outline"}:
            markdown = _outline_markdown_from_sheet(sheet, targets)
            if markdown:
                outline_parts.append(markdown)
                outline_titles.append(sheet.name)

    if len(entities) > MAX_APPLY_ITEMS:
        raise ValidationError(
            f"人物与设定条目超过上限 {MAX_APPLY_ITEMS}，请拆分文件后分次迁移",
            code="migration_items_exceeded",
        )
    if len(relations) > MAX_RELATIONS:
        raise ValidationError(
            f"关系条目超过上限 {MAX_RELATIONS}，请拆分文件后分次迁移",
            code="migration_items_exceeded",
        )
    if len(story_items) > MAX_APPLY_ITEMS:
        raise ValidationError(
            f"大纲结构条目超过上限 {MAX_APPLY_ITEMS}，请拆分文件后分次迁移",
            code="migration_items_exceeded",
        )

    outline: AuthorMigrationOutlineInput | None = None
    if outline_parts or creative_core:
        outline = AuthorMigrationOutlineInput(
            title=outline_titles[0] if outline_titles else None,
            outline_markdown="\n\n".join(outline_parts)[:200000],
            creative_core=creative_core,
            policy=outline_head_policy,
        )

    accepted_refs = tuple(
        sorted(item.proposal_ref for item in (ai_input.items if ai_input else []))
    )
    return MigrationPlanRequests(
        world_request=AuthorMigrationWorldRequest(
            migration_id=migration_id,
            entities=entities,
            relations=relations,
        ),
        story_request=AuthorMigrationStoryRequest(
            migration_id=migration_id,
            items=story_items,
            outline=outline,
            written_chapter_policy=written_chapter_policy,
        ),
        labels=labels,
        ai_accepted_refs=accepted_refs,
    )


def _find_sheet(
    sheets: list[SheetContext], sheet_key: str
) -> SheetContext | None:
    for sheet in sheets:
        if sheet.sheet_key == sheet_key:
            return sheet
    return None


__all__ = [
    "OUTLINE_ITEM_KEY",
    "OUTLINE_SHEET_KINDS",
    "MigrationPlanRequests",
    "PlannedLabel",
    "PlannedSource",
    "SheetContext",
    "build_migration_requests",
]
