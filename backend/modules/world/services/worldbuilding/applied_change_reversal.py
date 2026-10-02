"""Applied-change receipt reversal — the shared reverse-order rollback loop.

`focused_adoption.rollback` 与表格迁移（ADR-0030）的 `rollback_author_migration_world`
都消费“回执 + 逆序回滚 + 已改动保留”的同一语义。本模块抽出该逆序循环：

- 逆序遍历回执 ``applied_changes``；
- 逐项按行锁重读当前状态并与回执记录的 after（字典逐字段或 ``after_hash``）比对；
- 新建对象在无外部关系、人物/事件等扩展和世界书引用时软废弃（``deprecated``）；
- 填空/别名/晋升恢复 ``before`` 字段原值；
- 回滚 CoreEntity 前写修订快照，调用方在结束后标记上下文变化并请求重标注。

focused 路径保持原行为（比对失败与被引用统一 ``conflict``）；表格迁移通过参数区分
``modified_after_migration`` 与 ``referenced`` 两种保留原因。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from sqlalchemy import String, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.stable_hash import stable_hash
from modules.world.models import Character, CoreEntity, EntityRelation
from shared.utils import parse_uuid

ENTITY_STATE_KEYS = (
    "name",
    "entity_type",
    "status",
    "summary",
    "public_info",
    "hidden_truth",
    "content_json",
    "importance",
    "importance_level",
    "reveal_level",
)
RELATION_STATE_KEYS = (
    "status",
    "relation_type",
    "relation_kind",
    "description",
    "quote",
    "review_meta",
)
CHARACTER_STATE_KEYS = (
    "name",
    "status",
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
    "secret",
    "meta",
)

# 这些 operation 表示对象由本次写入新建，回滚走软废弃而不是恢复字段。
CREATE_OPERATIONS = frozenset({"create", "relation_create"})
_RELATION_KINDS = frozenset({"entity_relation", "relation"})
_CHARACTER_KINDS = frozenset({"character"})
_ENTITY_KINDS = frozenset({"core_entity", "entity"})


def entity_state(entity) -> dict:
    return {
        key: copy.deepcopy(getattr(entity, key))
        for key in ENTITY_STATE_KEYS
    }


def relation_state(relation) -> dict:
    return {
        key: copy.deepcopy(getattr(relation, key))
        for key in RELATION_STATE_KEYS
    }


def character_state(character) -> dict:
    return {
        key: copy.deepcopy(getattr(character, key))
        for key in CHARACTER_STATE_KEYS
    }


@dataclass
class ReversalOutcome:
    """逆序回滚的单次判定结果。"""

    outcomes: list[dict] = field(default_factory=list)
    # 受影响实体 ID（含关系端点）；dry_run 不写入，保持为空。
    changed: set[str] = field(default_factory=set)
    # 判定为可回滚的 item_key；dry_run 时表示“将会回滚”。
    reverted: list[str] = field(default_factory=list)
    kept: list[dict] = field(default_factory=list)


def _model_and_state(kind: str):
    if kind in _RELATION_KINDS:
        return EntityRelation, relation_state
    if kind in _CHARACTER_KINDS:
        return Character, character_state
    return CoreEntity, entity_state


def _after_matches(current: dict, item: dict) -> bool:
    after = item.get("after")
    if after is None and item.get("after_hash"):
        return stable_hash(current) == item["after_hash"]
    return all(current.get(key) == value for key, value in (after or {}).items())


async def _is_unreferenced_entity(
    db: AsyncSession,
    novel_id: str,
    obj,
    *,
    reverting_relation_ids: set[str] | None = None,
) -> bool:
    conditions = [
        EntityRelation.novel_id == parse_uuid(novel_id),
        EntityRelation.status.in_(("canonical", "candidate")),
        (EntityRelation.source_id == obj.id) | (EntityRelation.target_id == obj.id),
    ]
    if reverting_relation_ids:
        # dry_run 不会真正废弃关系；把本次（计划）回滚的关系排除，
        # 否则迁移自己建立的关系会让新建对象误判为被引用。
        conditions.append(
            EntityRelation.id.not_in(
                [parse_uuid(value, "relation_id") for value in reverting_relation_ids]
            )
        )
    external = await db.scalar(
        select(EntityRelation.id).where(*conditions).limit(1)
    )
    if external is not None:
        return False
    from modules.world.models import WorldBiblePage, WorldBiblePageDraft
    from modules.world.services.core.entity_type_transition_service import (
        EntityTypeTransitionService,
    )

    if await EntityTypeTransitionService()._collect_blockers(db, obj, obj.entity_type):
        return False
    for page_model in (WorldBiblePage, WorldBiblePageDraft):
        linked = await db.scalar(
            select(page_model.id)
            .where(
                page_model.novel_id == obj.novel_id,
                cast(page_model.linked_asset_refs_json, String).contains(str(obj.id)),
            )
            .limit(1)
        )
        if linked is not None:
            return False
    return True


async def reverse_applied_changes(
    db: AsyncSession,
    novel_id: str,
    applied_changes: list[dict],
    *,
    dry_run: bool = False,
    modified_reason: str = "conflict",
    referenced_reason: str | None = None,
    rolled_back_status: str = "rolled_back",
    revision_reason: str = "focused_completion_rollback",
) -> ReversalOutcome:
    """逆序回放回执；返回逐项结果与受影响实体集合，不负责上下文标记。

    ``applied_changes`` 中的条目会被原位标记 ``rolled_back``（dry_run 除外），
    调用方决定是否把该标记持久化回自己的回执存储。
    """
    result = ReversalOutcome()
    reverting_relation_ids: set[str] = set()
    for item in reversed(list(applied_changes or [])):
        if item.get("rolled_back"):
            result.outcomes.append(
                {"item_key": item["item_key"], "status": "already_rolled_back"}
            )
            continue
        model, state_of = _model_and_state(str(item.get("kind", "")))
        pk = getattr(model, "id", None) or getattr(model, "entity_id")
        obj = await db.scalar(
            select(model)
            .where(
                pk == parse_uuid(item["id"]), model.novel_id == parse_uuid(novel_id)
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        current = state_of(obj) if obj is not None else None
        # Compare touched fields for fills; complete resources for new assets/aliases.
        matches = current is not None and _after_matches(current, item)
        referenced = False
        if (
            matches
            and item.get("operation") in CREATE_OPERATIONS
            and model is CoreEntity
        ):
            referenced = not await _is_unreferenced_entity(
                db, novel_id, obj, reverting_relation_ids=reverting_relation_ids
            )
            matches = not referenced
        if not matches:
            reason = modified_reason
            if referenced and referenced_reason is not None:
                reason = referenced_reason
            result.outcomes.append(
                {"item_key": item["item_key"], "status": reason}
            )
            result.kept.append({"item_key": item["item_key"], "reason_code": reason})
            continue
        if not dry_run:
            if model is CoreEntity:
                from modules.world.services.core.entity_revision_service import (
                    EntityRevisionService,
                )

                await EntityRevisionService().create_snapshot(
                    db, str(obj.id), novel_id, revision_reason=revision_reason
                )
            elif model is Character:
                from modules.world.services.core.entity_revision_service import (
                    EntityRevisionService,
                )

                await EntityRevisionService().create_snapshot(
                    db, str(obj.entity_id), novel_id, revision_reason=revision_reason
                )
            if item.get("operation") in CREATE_OPERATIONS:
                obj.status = "deprecated"
            else:
                for key, value in item["before"].items():
                    setattr(obj, key, copy.deepcopy(value))
            item["rolled_back"] = True
        if model is EntityRelation and item.get("operation") in CREATE_OPERATIONS:
            reverting_relation_ids.add(str(obj.id))
        result.outcomes.append(
            {"item_key": item["item_key"], "status": rolled_back_status}
        )
        result.reverted.append(item["item_key"])
        if not dry_run:
            if model is EntityRelation:
                result.changed.update((str(obj.source_id), str(obj.target_id)))
            elif model is Character:
                result.changed.add(str(obj.entity_id))
            else:
                result.changed.add(str(obj.id))
    return result
