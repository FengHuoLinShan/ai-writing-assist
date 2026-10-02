"""表格迁移 world 落库（ADR-0030，计划 §3.3/§4 L2）— 窄 seam，不复用 adoption package。

plan：只读预览（名称/别名解析、动作判定、关系处理、fingerprint）。
apply：项目排他锁下重算计划并比对指纹，门禁一次性检查，写入 canonical 资产并产出回执。
rollback：经 applied_change_reversal 逆序处理回执，已改动项保留。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError
from infrastructure.stable_hash import stable_hash
from modules.world.contracts import (
    AuthorMigrationEntityInput,
    AuthorMigrationRelationInput,
    AuthorMigrationWorldRequest,
    FieldConflict,
    MigrationAppliedChange,
    MigrationRollbackResult,
    WorldMigrationItemPlan,
    WorldMigrationPlan,
    WorldMigrationReceipt,
)
from modules.world.models import Character, CoreEntity, EntityRelation
from modules.world.schemas import (
    CharacterUpdate,
    CoreEntityCreate,
    CoreEntityUpdate,
    EntityPromoteRequest,
    EntityRelationCreate,
    EntityRelationUpdate,
)
from modules.world.services.common import require_fresh_understanding_source
from modules.world.services.core.character_service import CharacterService
from modules.world.services.core.dedup_service import EntityDedupService
from modules.world.services.core.entity_alias_service import EntityAliasService
from modules.world.services.core.entity_context_service import EntityContextService
from modules.world.services.core.entity_relation_service import EntityRelationService
from modules.world.services.core.entity_service import WorldEntityService
from modules.world.services.core.review_queue import (
    default_relation_kind,
    suggest_relation_type,
)
from modules.world.services.worldbuilding.applied_change_reversal import (
    character_state,
    entity_state,
    relation_state,
    reverse_applied_changes,
)
from shared.utils import parse_uuid

MIGRATION_SOURCE = "spreadsheet_migration"

_ENTITY_FIELD_NAMES = ("summary", "public_info", "hidden_truth")
_EXCERPT_LIMIT = 200
_ITEM_REF_PREFIX = "item:"
# 可产出实体的计划动作：关系端点可指向这些条目。
_WRITABLE_ENTITY_ACTIONS = frozenset(
    {"create", "fill_empty", "adopt_existing", "existing_ref"}
)

# L1 的 guess_relation_kind 尚未合入；这里按计划 §4 L1 的关键词表实现本地等价兜底。
# 解析顺序仍为：作者覆盖 → review_queue 目录 → 本地关键词/双人物兜底（标记为推测）。
_GUESS_KIND_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
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


def _guess_relation_kind_local(
    relation_type: str, *, both_characters: bool
) -> tuple[str, bool]:
    for kind, keywords in _GUESS_KIND_KEYWORDS:
        if any(keyword in relation_type for keyword in keywords):
            return kind, True
    return ("social" if both_characters else "state"), True


def _norm_name(value: object) -> str:
    return " ".join(str(value or "").strip().split()).casefold()


def _is_empty(value: object) -> bool:
    # 与 focused_adoption.is_empty 同语义：None 或纯空白字符串为空，零值/false 不为空。
    return value is None or isinstance(value, str) and not value.strip()


def _excerpt(value: object) -> str:
    return str(value or "")[:_EXCERPT_LIMIT]


def _notes_block(notes) -> str:
    return "\n".join(f"【表格·{note.label}】{note.value}" for note in notes)


def _stamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC).isoformat()
    return value.astimezone(UTC).isoformat()


def _is_shadow(entity: CoreEntity) -> bool:
    meta = dict((entity.content_json or {}).get("_meta") or {})
    return bool(
        entity.status in {"draft", "candidate"}
        and meta.get("compatibility_shadow") is True
        and meta.get("suggestion_id")
    )


@dataclass
class _PlannedEntity:
    item: AuthorMigrationEntityInput
    action: str = "create"
    target: CoreEntity | None = None
    entity_fills: dict[str, str] = field(default_factory=dict)
    hidden_append: str | None = None
    character_fills: dict[str, str] = field(default_factory=dict)
    aliases_to_add: list[str] = field(default_factory=list)
    conflicts: list[FieldConflict] = field(default_factory=list)
    similar: list[dict] = field(default_factory=list)
    reason_code: str | None = None
    promote: bool = False
    alias_collision: bool = False


@dataclass
class _PlannedRelation:
    item: AuthorMigrationRelationInput
    action: str = "create"
    relation_id: str | None = None
    relation_type: str | None = None
    source_ref: str | None = None
    target_ref: str | None = None
    relation_kind: str | None = None
    kind_guessed: bool = False
    fill_description: str | None = None
    conflicts: list[FieldConflict] = field(default_factory=list)
    reason_code: str | None = None


@dataclass
class _ComposedPlan:
    entities: list[_PlannedEntity]
    relations: list[_PlannedRelation]
    items: list[WorldMigrationItemPlan]
    fingerprint: str


class _Resolver:
    """一次组合计划内的名称/别名解析缓存（同一 novel_id 范围）。"""

    def __init__(self, db: AsyncSession, novel_id: str) -> None:
        self._db = db
        self._novel_id = novel_id
        self._nid = parse_uuid(novel_id, "novel_id")
        self._context = EntityContextService()
        self._dedup = EntityDedupService()
        self._entities: dict[str, CoreEntity | None] = {}
        self._working: dict[str, str] = {}
        self._exact_cache: dict[str, list[str]] = {}
        self._similar_cache: dict[str, list[dict]] = {}
        self._characters: dict[str, Character | None] = {}

    async def prepare_working(self, names: list[str]) -> None:
        self._working = await self._context.find_working_entities_by_names(
            self._db, self._novel_id, names
        )

    async def entity(self, entity_id: str | None) -> CoreEntity | None:
        if not entity_id:
            return None
        if entity_id not in self._entities:
            obj = await self._db.get(
                CoreEntity, parse_uuid(entity_id, "entity_id")
            )
            self._entities[entity_id] = (
                obj if obj is not None and obj.novel_id == self._nid else None
            )
        return self._entities[entity_id]

    async def character(self, entity_id: str) -> Character | None:
        if entity_id not in self._characters:
            row = await self._db.get(Character, parse_uuid(entity_id, "entity_id"))
            self._characters[entity_id] = (
                row if row is not None and row.novel_id == self._nid else None
            )
        return self._characters[entity_id]

    def working_index(self) -> dict[str, str]:
        """解析后的 名称/别名 → 实体 ID 只读快照。"""
        return dict(self._working)

    async def exact_ids(self, name: str) -> list[str]:
        """字面名称精确候选（保留歧义），与 find_exact_identity_candidates 同语义。"""
        if name not in self._exact_cache:
            matches = await self._context.find_exact_identity_candidates(
                self._db, self._novel_id, name
            )
            ids: list[str] = []
            for match in matches:
                if match.existing_entity_id not in ids:
                    ids.append(match.existing_entity_id)
            self._exact_cache[name] = ids
        return self._exact_cache[name]

    async def similar_entities(self, name: str, aliases: list[str]) -> list[dict]:
        key = name
        if key not in self._similar_cache:
            entries: list[dict] = []
            seen: set[str] = set()
            for dup in await self._dedup.find_similar_entities(
                self._db, self._novel_id, name, aliases=aliases or None
            ):
                if dup.existing_entity_id in seen:
                    continue
                seen.add(dup.existing_entity_id)
                entity_type = None
                obj = await self.entity(dup.existing_entity_id)
                if obj is not None:
                    entity_type = obj.entity_type
                entries.append(
                    {
                        "entity_id": dup.existing_entity_id,
                        "name": dup.existing_entity_name,
                        "entity_type": entity_type,
                    }
                )
            self._similar_cache[key] = entries
        return self._similar_cache[key]


async def _shadow_index(
    db: AsyncSession, novel_id: str
) -> dict[str, CoreEntity]:
    rows = (
        (
            await db.execute(
                select(CoreEntity).where(
                    CoreEntity.novel_id == parse_uuid(novel_id, "novel_id"),
                    CoreEntity.status.in_(("draft", "candidate")),
                )
            )
        )
        .scalars()
        .all()
    )
    shadows: dict[str, CoreEntity] = {}
    for row in rows:
        if _is_shadow(row):
            shadows.setdefault(_norm_name(row.name), row)
    return shadows


def _plan_entity_fields(
    planned: _PlannedEntity,
    *,
    character: Character | None,
) -> None:
    item = planned.item
    target = planned.target
    assert target is not None
    notes = _notes_block(item.author_notes)

    for field_name in _ENTITY_FIELD_NAMES[:2]:  # summary / public_info
        incoming = getattr(item, field_name)
        if _is_empty(incoming):
            continue
        current = getattr(target, field_name)
        if _is_empty(current):
            planned.entity_fills[field_name] = str(incoming)
        elif str(current).strip() != str(incoming).strip():
            planned.conflicts.append(
                FieldConflict(
                    field=field_name,
                    current_excerpt=_excerpt(current),
                    incoming_excerpt=_excerpt(incoming),
                )
            )

    explicit = item.hidden_truth
    append_parts: list[str] = []
    if not _is_empty(explicit) and not _is_empty(target.hidden_truth):
        if str(target.hidden_truth).strip() != str(explicit).strip():
            if item.decision == "append_note":
                append_parts.append(str(explicit).strip())
            else:
                planned.conflicts.append(
                    FieldConflict(
                        field="hidden_truth",
                        current_excerpt=_excerpt(target.hidden_truth),
                        incoming_excerpt=_excerpt(explicit),
                    )
                )
    if notes:
        append_parts.append(notes)
    if _is_empty(target.hidden_truth):
        parts = [
            part
            for part in (str(explicit).strip() if not _is_empty(explicit) else None,
                         notes or None)
            if part
        ]
        if parts:
            planned.entity_fills["hidden_truth"] = "\n\n".join(parts)
    elif append_parts:
        planned.hidden_append = "\n\n".join(append_parts)

    # 人物字段只对人物类型的实际目标生效；use_existing 指向其他类型时忽略。
    if target.entity_type == "character" and item.character_fields:
        for field_name, incoming in item.character_fields.items():
            if _is_empty(incoming):
                continue
            current = (
                getattr(character, field_name, None)
                if character is not None
                else None
            )
            if _is_empty(current):
                planned.character_fills[field_name] = str(incoming)
            elif str(current).strip() != str(incoming).strip():
                planned.conflicts.append(
                    FieldConflict(
                        field=field_name,
                        current_excerpt=_excerpt(current),
                        incoming_excerpt=_excerpt(incoming),
                    )
                )


def _plan_aliases(
    planned: _PlannedEntity,
    *,
    name_to_first: dict[str, str],
    working: dict[str, str],
) -> None:
    target_id = str(planned.target.id) if planned.target is not None else None
    existing_alias_texts: set[str] = set()
    if planned.target is not None:
        for alias_item in (planned.target.content_json or {}).get("aliases") or []:
            text = (
                alias_item
                if isinstance(alias_item, str)
                else alias_item.get("alias", "")
            )
            if text:
                existing_alias_texts.add(_norm_name(text))
    for alias in planned.item.aliases:
        normalized = _norm_name(alias)
        if not normalized or normalized == _norm_name(planned.item.name):
            continue
        if normalized in existing_alias_texts:
            continue
        owner_key = name_to_first.get(normalized)
        if owner_key is not None and owner_key != planned.item.item_key:
            planned.alias_collision = True
            continue
        owner_id = working.get(alias)
        if owner_id is not None and owner_id != target_id:
            planned.alias_collision = True
            continue
        planned.aliases_to_add.append(alias)


async def _compose_plan(
    db: AsyncSession, novel_id: str, request: AuthorMigrationWorldRequest
) -> _ComposedPlan:
    resolver = _Resolver(db, novel_id)
    shadows = await _shadow_index(db, novel_id)

    name_to_first: dict[str, str] = {}
    duplicated_keys: set[str] = set()
    lookup_names: set[str] = set()
    for item in request.entities:
        normalized = _norm_name(item.name)
        if normalized in name_to_first:
            duplicated_keys.add(item.item_key)
        else:
            name_to_first[normalized] = item.item_key
        lookup_names.add(item.name)
        lookup_names.update(item.aliases)
    for relation in request.relations:
        lookup_names.add(relation.source_name)
        lookup_names.add(relation.target_name)
    await resolver.prepare_working(
        sorted(name for name in lookup_names if _norm_name(name))
    )
    working = resolver.working_index()

    planned_entities: list[_PlannedEntity] = []
    for item in request.entities:
        planned = _PlannedEntity(item=item)
        planned_entities.append(planned)
        if item.decision == "skip":
            planned.action = "skip"
            continue
        if item.item_key in duplicated_keys:
            planned.action = "conflict"
            planned.reason_code = "duplicate_in_file"
            continue

        if item.decision == "use_existing":
            target = await resolver.entity(item.target_entity_id)
            if target is None or target.status not in (
                "canonical",
                "draft",
                "candidate",
            ):
                planned.action = "conflict"
                planned.reason_code = "target_not_found"
                continue
            if _is_shadow(target):
                planned.action = "needs_review"
                planned.reason_code = "compatibility_shadow"
                continue
            planned.target = target
        else:
            exact_ids = list(await resolver.exact_ids(item.name))
            working_id = working.get(item.name)
            if working_id and working_id not in exact_ids:
                exact_ids.append(working_id)
            canonical_same: CoreEntity | None = None
            canonical_other: list[CoreEntity] = []
            candidates: list[CoreEntity] = []
            ambiguous = False
            for entity_id in exact_ids:
                obj = await resolver.entity(entity_id)
                if obj is None:
                    continue
                if obj.status == "canonical":
                    if obj.entity_type == item.entity_type:
                        if canonical_same is not None:
                            ambiguous = True
                        canonical_same = canonical_same or obj
                    else:
                        canonical_other.append(obj)
                else:
                    candidates.append(obj)
            if ambiguous:
                planned.action = "conflict"
                planned.reason_code = "ambiguous_identity"
                continue
            if canonical_same is not None:
                planned.target = canonical_same
            elif len(candidates) == 1:
                candidate = candidates[0]
                try:
                    await require_fresh_understanding_source(
                        db,
                        novel_id,
                        dict((candidate.content_json or {}).get("_meta") or {}),
                    )
                except ConflictError:
                    planned.action = "conflict"
                    planned.reason_code = "stale_candidate"
                    continue
                planned.target = candidate
                planned.promote = True
            elif len(candidates) > 1:
                planned.action = "conflict"
                planned.reason_code = "ambiguous_identity"
                continue
            elif not exact_ids and shadows.get(_norm_name(item.name)) is not None:
                planned.action = "needs_review"
                planned.reason_code = "compatibility_shadow"
                continue

        if planned.target is not None:
            character = (
                await resolver.character(str(planned.target.id))
                if planned.target.entity_type == "character"
                else None
            )
            _plan_entity_fields(planned, character=character)
            _plan_aliases(planned, name_to_first=name_to_first, working=working)
            if planned.conflicts:
                planned.action = "conflict"
                planned.reason_code = "field_conflict"
            elif planned.promote:
                planned.action = "adopt_existing"
            elif (
                planned.entity_fills
                or planned.hidden_append
                or planned.character_fills
                or planned.aliases_to_add
            ):
                planned.action = "fill_empty"
            else:
                planned.action = "existing_ref"
        else:
            _plan_aliases(planned, name_to_first=name_to_first, working=working)
            # 新建人物的人物字段直接进入自动 scaffold 后的填空，不存在冲突。
            if item.entity_type == "character":
                planned.character_fills = {
                    field_name: str(value)
                    for field_name, value in item.character_fields.items()
                    if not _is_empty(value)
                }
            similar: list[dict] = []
            seen_ids: set[str] = set()
            for other in await _similar_for_type_mismatch(resolver, item, seen_ids):
                similar.append(other)
                seen_ids.add(other["entity_id"])
            for entry in await resolver.similar_entities(item.name, item.aliases):
                if entry["entity_id"] not in seen_ids:
                    similar.append(entry)
                    seen_ids.add(entry["entity_id"])
            if similar:
                planned.similar = similar[:5]
                if item.decision == "different_object":
                    planned.action = "create"
                else:
                    planned.action = "similar_name"
                    planned.reason_code = "similar_name"
                    continue
            planned.action = "create"

        if planned.alias_collision and planned.action in _WRITABLE_ENTITY_ACTIONS:
            planned.action = "alias_collision"
            planned.reason_code = "alias_collision"

    entity_by_key = {planned.item.item_key: planned for planned in planned_entities}

    def _entity_ref(item_key: str) -> tuple[str | None, str | None]:
        planned = entity_by_key.get(item_key)
        if planned is None:
            return None, "endpoint_item_unknown"
        if planned.action == "create":
            return f"{_ITEM_REF_PREFIX}{item_key}", None
        if (
            planned.action in _WRITABLE_ENTITY_ACTIONS
            and planned.target is not None
        ):
            return str(planned.target.id), None
        return None, "endpoint_item_blocked"

    async def _resolve_endpoint(
        name: str, item_key: str | None
    ) -> tuple[str | None, str | None]:
        if item_key:
            ref, reason = _entity_ref(item_key)
            return ref, reason
        first_key = name_to_first.get(_norm_name(name))
        if first_key is not None:
            ref, reason = _entity_ref(first_key)
            return ref, reason
        ids = list(await resolver.exact_ids(name))
        working_id = working.get(name)
        if working_id and working_id not in ids:
            ids.append(working_id)
        if len(ids) > 1:
            return None, "endpoint_ambiguous"
        if ids:
            return ids[0], None
        return None, "endpoint_missing"

    async def _ref_is_character(ref: str) -> bool:
        if ref.startswith(_ITEM_REF_PREFIX):
            planned = entity_by_key.get(ref[len(_ITEM_REF_PREFIX) :])
            return planned is not None and planned.item.entity_type == "character"
        obj = await resolver.entity(ref)
        return obj is not None and obj.entity_type == "character"

    planned_relations: list[_PlannedRelation] = []
    seen_edges: set[tuple] = set()
    for relation in request.relations:
        planned = _PlannedRelation(item=relation)
        planned_relations.append(planned)
        if relation.decision == "skip":
            planned.action = "skip"
            continue
        source_ref, source_reason = await _resolve_endpoint(
            relation.source_name, relation.source_item_key
        )
        if source_ref is None:
            planned.action = "conflict"
            planned.reason_code = source_reason
            continue
        target_ref, target_reason = await _resolve_endpoint(
            relation.target_name, relation.target_item_key
        )
        if target_ref is None:
            planned.action = "conflict"
            planned.reason_code = target_reason
            continue
        if source_ref == target_ref:
            planned.action = "conflict"
            planned.reason_code = "self_loop"
            continue
        # 目录同义词归一化：盟友 → ally_of，与既有边和 canonical 类型对齐；
        # 未命中目录时保留作者原文。
        relation_type = suggest_relation_type(relation.relation_type) or (
            relation.relation_type.strip()
        )
        if relation.symmetric:
            first, second = sorted((source_ref, target_ref))
            edge = (first, second, relation_type)
        else:
            edge = (source_ref, target_ref, relation_type)

        if relation.relation_kind:
            planned.relation_kind = relation.relation_kind
            planned.kind_guessed = False
        else:
            kind = default_relation_kind(relation_type)
            if kind:
                planned.relation_kind = kind
                planned.kind_guessed = False
            else:
                both_characters = await _ref_is_character(
                    source_ref
                ) and await _ref_is_character(target_ref)
                planned.relation_kind, planned.kind_guessed = (
                    _guess_relation_kind_local(
                        relation.relation_type, both_characters=both_characters
                    )
                )
        planned.relation_type = relation_type
        planned.source_ref = source_ref
        planned.target_ref = target_ref

        if not source_ref.startswith(_ITEM_REF_PREFIX) and not target_ref.startswith(
            _ITEM_REF_PREFIX
        ):
            existing = await _find_existing_edge(
                db,
                novel_id,
                source_ref,
                target_ref,
                relation_type,
                symmetric=relation.symmetric,
            )
            if existing is not None:
                planned.relation_id = str(existing.id)
                if existing.status != "canonical":
                    planned.action = "conflict"
                    planned.reason_code = "candidate_edge_exists"
                    continue
                incoming = (relation.description or "").strip() or None
                current = (existing.description or "").strip() or None
                if incoming is None or incoming == current:
                    planned.action = "existing_ref"
                elif current is None:
                    planned.action = "fill_empty"
                    planned.fill_description = incoming
                else:
                    planned.action = "conflict"
                    planned.reason_code = "description_conflict"
                    planned.conflicts.append(
                        FieldConflict(
                            field="description",
                            current_excerpt=_excerpt(current),
                            incoming_excerpt=_excerpt(incoming),
                        )
                    )
        else:
            planned.action = "create"

        # 文件内按（源, 目标, 类型）去重；对称关系视同一条。冲突项不做重复折叠，
        # 保证与既有 canonical 边的描述冲突始终对作者可见。
        if edge in seen_edges and planned.action != "conflict":
            planned.action = "skip"
            planned.reason_code = "duplicate"
            continue
        seen_edges.add(edge)

    items = [
        _entity_plan_item(planned) for planned in planned_entities
    ] + [_relation_plan_item(planned) for planned in planned_relations]

    fingerprint_targets: dict[str, CoreEntity] = {}
    for planned in planned_entities:
        if planned.target is not None:
            fingerprint_targets[str(planned.target.id)] = planned.target
    for planned in planned_relations:
        for ref in (planned.source_ref, planned.target_ref):
            if ref and not ref.startswith(_ITEM_REF_PREFIX):
                obj = await resolver.entity(ref)
                if obj is not None:
                    fingerprint_targets[ref] = obj
    target_stamps = sorted(
        [str(entity.id), _stamp(entity.updated_at)]
        for entity in fingerprint_targets.values()
    )
    fingerprint = stable_hash(
        {
            "targets": target_stamps,
            "items": [item.model_dump(mode="json") for item in items],
        }
    )
    return _ComposedPlan(
        entities=planned_entities,
        relations=planned_relations,
        items=items,
        fingerprint=fingerprint,
    )


async def _similar_for_type_mismatch(
    resolver: _Resolver, item: AuthorMigrationEntityInput, seen_ids: set[str]
) -> list[dict]:
    """同名但类型不同的 canonical 对象进入相似列表，交由作者裁决。"""
    entries: list[dict] = []
    for entity_id in await resolver.exact_ids(item.name):
        if entity_id in seen_ids:
            continue
        obj = await resolver.entity(entity_id)
        if obj is None or obj.status != "canonical":
            continue
        if obj.entity_type == item.entity_type:
            continue
        seen_ids.add(entity_id)
        entries.append(
            {
                "entity_id": str(obj.id),
                "name": obj.name,
                "entity_type": obj.entity_type,
            }
        )
    return entries


def _entity_plan_item(planned: _PlannedEntity) -> WorldMigrationItemPlan:
    fills = list(planned.entity_fills)
    if planned.hidden_append:
        fills.append("hidden_truth")
    fills.extend(planned.character_fills)
    if planned.aliases_to_add:
        fills.append("aliases")
    return WorldMigrationItemPlan(
        item_key=planned.item.item_key,
        kind="entity",
        action=planned.action,
        target_id=str(planned.target.id) if planned.target is not None else None,
        target_label=(
            planned.target.name if planned.target is not None else planned.item.name
        ),
        fills=fills,
        conflicts=planned.conflicts,
        similar=planned.similar,
        reason_code=planned.reason_code,
    )


def _relation_plan_item(planned: _PlannedRelation) -> WorldMigrationItemPlan:
    return WorldMigrationItemPlan(
        item_key=planned.item.item_key,
        kind="relation",
        action=planned.action,
        target_id=planned.relation_id,
        target_label=planned.item.relation_type,
        conflicts=planned.conflicts,
        relation_kind=planned.relation_kind,
        relation_kind_guessed=planned.kind_guessed,
        reason_code=planned.reason_code,
    )


async def _find_existing_edge(
    db: AsyncSession,
    novel_id: str,
    source_id: str,
    target_id: str,
    relation_type: str,
    *,
    symmetric: bool,
) -> EntityRelation | None:
    sid = parse_uuid(source_id, "source_id")
    tid = parse_uuid(target_id, "target_id")
    pairs = [(sid, tid)] + ([(tid, sid)] if symmetric else [])
    stmt = select(EntityRelation).where(
        EntityRelation.novel_id == parse_uuid(novel_id, "novel_id"),
        EntityRelation.relation_type == relation_type,
        EntityRelation.status != "deprecated",
        or_(
            *[
                (EntityRelation.source_id == s) & (EntityRelation.target_id == t)
                for s, t in pairs
            ]
        ),
    )
    rows = (await db.execute(stmt)).scalars().all()
    canonical = [row for row in rows if row.status == "canonical"]
    pool = canonical or rows
    if not pool:
        return None
    return sorted(pool, key=lambda row: str(row.id))[0]


async def plan_author_migration_world(
    db: AsyncSession,
    novel_id: str,
    request: AuthorMigrationWorldRequest,
) -> WorldMigrationPlan:
    """只读计算迁移计划。"""
    # world facade 在模块级导入本文件，project facade 须保持函数内 lazy import，
    # 避免与 modules.project.api → story facade → world facade 构成环。
    from modules.project.facade import require_active_project

    await require_active_project(db, novel_id)
    from modules.world.services.worldbuilding.world_validation_service import (
        WorldValidationService,
    )

    composed = await _compose_plan(db, novel_id, request)
    policy_active = (
        await WorldValidationService().active_policy(db, novel_id) is not None
    )
    return WorldMigrationPlan(
        items=composed.items,
        validation_policy_active=policy_active,
        fingerprint=composed.fingerprint,
    )


async def _locked_entity(db: AsyncSession, novel_id: str, entity_id: str) -> CoreEntity:
    stmt = (
        select(CoreEntity)
        .where(
            CoreEntity.id == parse_uuid(entity_id, "entity_id"),
            CoreEntity.novel_id == parse_uuid(novel_id, "novel_id"),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    obj = (await db.execute(stmt)).scalar_one_or_none()
    if obj is None:
        raise ConflictError(
            "迁移目标已变化，请重新预览", code="migration_preview_stale"
        )
    return obj


async def _locked_relation(
    db: AsyncSession, novel_id: str, relation_id: str
) -> EntityRelation:
    stmt = (
        select(EntityRelation)
        .where(
            EntityRelation.id == parse_uuid(relation_id, "relation_id"),
            EntityRelation.novel_id == parse_uuid(novel_id, "novel_id"),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    obj = (await db.execute(stmt)).scalar_one_or_none()
    if obj is None:
        raise ConflictError(
            "迁移目标已变化，请重新预览", code="migration_preview_stale"
        )
    return obj


async def _execute_plan(
    db: AsyncSession,
    novel_id: str,
    request: AuthorMigrationWorldRequest,
    composed: _ComposedPlan,
    *,
    authorized_by: str,
) -> WorldMigrationReceipt:
    entities_service = WorldEntityService()
    relations_service = EntityRelationService()
    aliases_service = EntityAliasService()
    characters_service = CharacterService()
    applied: list[MigrationAppliedChange] = []
    entity_ids: dict[str, str] = {}
    applied_at = datetime.now(UTC).isoformat()

    def _provenance(source_ref: str, source_hash: str) -> dict:
        return {
            "source": MIGRATION_SOURCE,
            "spreadsheet_migration": {
                "migration_id": request.migration_id,
                "source_ref": source_ref,
                "source_hash": source_hash,
                "authorized_by": authorized_by,
                "applied_at": applied_at,
            },
        }

    for planned in composed.entities:
        item = planned.item
        if planned.action not in _WRITABLE_ENTITY_ACTIONS:
            continue
        if planned.action == "create":
            notes = _notes_block(item.author_notes)
            hidden_parts = [
                part
                for part in (
                    str(item.hidden_truth).strip()
                    if not _is_empty(item.hidden_truth)
                    else None,
                    notes or None,
                )
                if part
            ]
            created = await entities_service.create(
                db,
                novel_id,
                CoreEntityCreate(
                    entity_type=item.entity_type,
                    name=item.name,
                    summary=item.summary,
                    public_info=item.public_info,
                    hidden_truth=("\n\n".join(hidden_parts) or None),
                    content_json={
                        "_meta": _provenance(item.source_ref, item.source_hash)
                    },
                    status="canonical",
                    created_by=MIGRATION_SOURCE,
                    approved_by=authorized_by,
                    force_create=True,
                ),
                _validation_prechecked=True,
            )
            entity_ids[item.item_key] = created.id
            row = await _locked_entity(db, novel_id, created.id)
            applied.append(
                MigrationAppliedChange(
                    item_key=item.item_key,
                    kind="entity",
                    target_id=created.id,
                    operation="create",
                    before={},
                    after_hash=stable_hash(entity_state(row)),
                )
            )
            target_id = created.id
        else:
            assert planned.target is not None
            target_id = str(planned.target.id)
            entity_ids[item.item_key] = target_id
            if planned.action == "adopt_existing":
                row = await _locked_entity(db, novel_id, target_id)
                before_status = row.status
                await entities_service.promote(
                    db,
                    target_id,
                    EntityPromoteRequest(approved_by=authorized_by),
                    novel_id=novel_id,
                    _validation_prechecked=True,
                )
                row = await _locked_entity(db, novel_id, target_id)
                applied.append(
                    MigrationAppliedChange(
                        item_key=item.item_key,
                        kind="entity",
                        target_id=target_id,
                        operation="promote",
                        before={"status": before_status},
                        after_hash=stable_hash(entity_state(row)),
                    )
                )
            if planned.entity_fills or planned.hidden_append:
                update_fields = dict(planned.entity_fills)
                if planned.hidden_append:
                    row = await _locked_entity(db, novel_id, target_id)
                    existing_hidden = str(row.hidden_truth or "").strip()
                    update_fields["hidden_truth"] = "\n\n".join(
                        part
                        for part in (existing_hidden, planned.hidden_append)
                        if part
                    )
                row = await _locked_entity(db, novel_id, target_id)
                before = {
                    field_name: getattr(row, field_name)
                    for field_name in update_fields
                }
                await entities_service.update(
                    db,
                    target_id,
                    CoreEntityUpdate(**update_fields),
                    novel_id=novel_id,
                    _validation_prechecked=True,
                    _automated=True,
                )
                row = await _locked_entity(db, novel_id, target_id)
                applied.append(
                    MigrationAppliedChange(
                        item_key=item.item_key,
                        kind="entity",
                        target_id=target_id,
                        operation="fill_empty",
                        before=before,
                        after_hash=stable_hash(entity_state(row)),
                    )
                )

        for index, alias in enumerate(planned.aliases_to_add):
            row = await _locked_entity(db, novel_id, target_id)
            before_content = copy.deepcopy(row.content_json)
            await aliases_service.create_alias(
                db,
                novel_id,
                target_id,
                alias,
                "name",
                status="confirmed",
                source=MIGRATION_SOURCE,
                reviewed_by=authorized_by,
                _validation_prechecked=True,
            )
            row = await _locked_entity(db, novel_id, target_id)
            applied.append(
                MigrationAppliedChange(
                    item_key=f"{item.item_key}#alias{index}",
                    kind="entity",
                    target_id=target_id,
                    operation="alias",
                    before={"content_json": before_content},
                    after_hash=stable_hash(entity_state(row)),
                )
            )

        if planned.character_fills:
            row = await _locked_entity(db, novel_id, target_id)
            if row.entity_type != "character":  # pragma: no cover - plan 已过滤
                continue
            await characters_service.ensure_for_core_entity(db, row)
            character = await characters_service.repo.get(
                db, parse_uuid(target_id, "entity_id")
            )
            assert character is not None
            before = {
                field_name: getattr(character, field_name)
                for field_name in planned.character_fills
            }
            await characters_service.update(
                db,
                target_id,
                CharacterUpdate(**planned.character_fills),
                novel_id=novel_id,
            )
            character = await characters_service.repo.get(
                db, parse_uuid(target_id, "entity_id")
            )
            assert character is not None
            applied.append(
                MigrationAppliedChange(
                    item_key=f"{item.item_key}#character",
                    kind="character",
                    target_id=target_id,
                    operation="fill_empty",
                    before=before,
                    after_hash=stable_hash(character_state(character)),
                )
            )

    def _resolve(ref: str) -> str:
        if ref.startswith(_ITEM_REF_PREFIX):
            entity_id = entity_ids.get(ref[len(_ITEM_REF_PREFIX) :])
            if entity_id is None:
                raise ConflictError(
                    "关系端点未创建，请重新预览", code="migration_preview_stale"
                )
            return entity_id
        return ref

    for planned in composed.relations:
        relation = planned.item
        if planned.action not in ("create", "fill_empty"):
            continue

        assert planned.source_ref is not None and planned.target_ref is not None
        source_id = _resolve(planned.source_ref)
        target_id = _resolve(planned.target_ref)
        if planned.action == "create":
            created = await relations_service.create(
                db,
                novel_id,
                EntityRelationCreate(
                    source_id=source_id,
                    target_id=target_id,
                    relation_type=planned.relation_type or relation.relation_type,
                    relation_kind=planned.relation_kind,
                    description=relation.description,
                    status="canonical",
                    review_meta=_provenance(
                        relation.source_ref, relation.source_hash
                    ),
                ),
                _validation_prechecked=True,
            )
            row = await _locked_relation(db, novel_id, created.id)
            applied.append(
                MigrationAppliedChange(
                    item_key=relation.item_key,
                    kind="relation",
                    target_id=created.id,
                    operation="relation_create",
                    before={},
                    after_hash=stable_hash(relation_state(row)),
                )
            )
        else:
            assert planned.relation_id is not None
            row = await _locked_relation(db, novel_id, planned.relation_id)
            before = {"description": row.description}
            await relations_service.update(
                db,
                planned.relation_id,
                EntityRelationUpdate(description=planned.fill_description),
                novel_id=novel_id,
            )
            row = await _locked_relation(db, novel_id, planned.relation_id)
            applied.append(
                MigrationAppliedChange(
                    item_key=relation.item_key,
                    kind="relation",
                    target_id=planned.relation_id,
                    operation="relation_fill",
                    before=before,
                    after_hash=stable_hash(relation_state(row)),
                )
            )

    await db.flush()
    return WorldMigrationReceipt(applied_changes=applied, entity_ids=entity_ids)


async def apply_author_migration_world(
    db: AsyncSession,
    novel_id: str,
    request: AuthorMigrationWorldRequest,
    *,
    expected_fingerprint: str,
    authorized_by: str,
) -> WorldMigrationReceipt:
    """按已确认的计划写入；只 flush，不 commit。"""
    from modules.project.facade import require_active_project_exclusive

    await require_active_project_exclusive(db, novel_id)
    composed = await _compose_plan(db, novel_id, request)
    if composed.fingerprint != expected_fingerprint:
        raise ConflictError(
            "迁移预览已过期，请重新预览后再采用",
            code="migration_preview_stale",
        )
    from modules.world.services.worldbuilding.world_validation_service import (
        WorldValidationService,
    )

    # 门禁一次性检查：策略生效时抛出原有 required_validation 错误，什么都不写。
    await WorldValidationService().require_legacy_canon_write_allowed(
        db, novel_id, next_action="spreadsheet_migration_apply"
    )
    return await _execute_plan(
        db, novel_id, request, composed, authorized_by=authorized_by
    )


async def rollback_author_migration_world(
    db: AsyncSession,
    novel_id: str,
    receipt: WorldMigrationReceipt,
    *,
    dry_run: bool,
) -> MigrationRollbackResult:
    """按回执逆序回滚；已改动项保留。"""
    from modules.project.facade import require_active_project_exclusive

    await require_active_project_exclusive(db, novel_id)
    changes: list[dict] = []
    for change in receipt.applied_changes:
        payload = change.model_dump(mode="json")
        payload["id"] = payload.pop("target_id")
        changes.append(payload)
    reversal = await reverse_applied_changes(
        db,
        novel_id,
        changes,
        dry_run=dry_run,
        modified_reason="modified_after_migration",
        referenced_reason="referenced",
        revision_reason="spreadsheet_migration_rollback",
    )
    if not dry_run and reversal.changed:
        from modules.evidence.facade import mark_asset_context_changed

        for entity_id in sorted(reversal.changed):
            await mark_asset_context_changed(
                db,
                novel_id=novel_id,
                asset_type="world_entity",
                asset_id=entity_id,
                reason="spreadsheet_migration_rollback",
            )
        from modules.world.services.core.entity_activity_invalidation import (
            request_entity_activity_reannotation,
        )

        await request_entity_activity_reannotation(db, novel_id)
        from modules.world.services.worldbuilding.synopsis_invalidation import (
            mark_synopsis_source_changed,
        )

        await mark_synopsis_source_changed(
            db,
            novel_id,
            source_type="spreadsheet_migration_rollback",
            source_id="migration_receipt",
        )
    return MigrationRollbackResult(
        reverted=reversal.reverted, kept=reversal.kept
    )
