"""单一状态归约语义内核（V4 E03a，对应 01-EVOLUTION §2.3 / 验收 T04）。

同一契约版本的 MemoryEvent 流只有一个解释内核；章节重放与 Scene 分维度
投影是同一内核的两种投影形状。截止到同一叙事位置时，核心实体状态、
关系、位置和知识必须一致。

统一语义（取代 G0 钉住的分叉）：

1. ``entity_updated`` 作用于未知实体：不凭更新负载创建幻影实体，也不丢弃
   信息——负载进入 ``changes``（观察层），待身份/创建证据补齐后再入核。
2. ``manual_correction`` 及其他观察型事件：两视图一律进入 ``changes``，
   不直接改变核心状态（观察 ≠ 状态操作；让观察影响状态属于 evolution
   类型化操作路径，不在归约器里 reinterpret）。
3. ``knowledge_changed`` 带 ``id``：按 id 去重替换（后写覆盖），保证重放
   幂等；无 ``id`` 时追加。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from modules.story.continuity.schemas import EventType

_STATE_CHANGES_KEY = "changes"


def _event_payload(event: Any) -> dict[str, Any]:
    return deepcopy(event.snapshot_after or {})


def _entity_key(event: Any) -> str | None:
    return str(event.entity_id) if event.entity_id else None


def _apply_entity_event(entities: dict, changes: list, event: Any) -> None:
    event_type = str(event.event_type)
    entity_id = _entity_key(event)
    after = _event_payload(event)
    if event_type == EventType.entity_created and entity_id:
        entities.setdefault(entity_id, {}).update(after)
    elif event_type == EventType.entity_updated and entity_id:
        if entity_id in entities:
            entities[entity_id].update(after)
        else:
            changes.append(after)
    elif event_type == EventType.entity_removed and entity_id:
        entities.pop(entity_id, None)
    else:
        changes.append(after)


def _apply_relation_event(relations: list, changes: list, event: Any) -> None:
    event_type = str(event.event_type)
    after = _event_payload(event)
    if event_type == EventType.relation_ended:
        relation_id = after.get("relation_id") or after.get("id")
        relations[:] = [r for r in relations if r.get("id") != relation_id]
    elif event_type == EventType.relation_established:
        relations.append(after)
    else:
        changes.append(after)


def _apply_location_event(locations: dict, changes: list, event: Any) -> None:
    event_type = str(event.event_type)
    entity_id = _entity_key(event)
    after = _event_payload(event)
    if event_type == EventType.entity_moved and entity_id:
        locations[entity_id] = after
    else:
        changes.append(after)


def _apply_knowledge_event(knowledge: list, changes: list, event: Any) -> None:
    event_type = str(event.event_type)
    after = _event_payload(event)
    if event_type == EventType.knowledge_changed:
        knowledge_id = after.get("id")
        if knowledge_id:
            knowledge[:] = [item for item in knowledge if item.get("id") != knowledge_id]
        knowledge.append(after)
    else:
        changes.append(after)


class StoryStateReducer:
    """纯函数解释内核：事件进、状态出，无 I/O、无隐藏状态。"""

    @staticmethod
    def apply_chapter_event(state: dict[str, Any], event: Any) -> None:
        """章节重放投影：扁平核心状态 + 观察层 ``changes``。"""
        event_type = str(event.event_type)
        if event_type.startswith("relation_"):
            _apply_relation_event(
                state.setdefault("relations", []),
                state.setdefault(_STATE_CHANGES_KEY, []),
                event,
            )
        elif event_type == EventType.entity_moved:
            _apply_location_event(
                state.setdefault("character_locations", {}),
                state.setdefault(_STATE_CHANGES_KEY, []),
                event,
            )
        elif event_type == EventType.knowledge_changed:
            _apply_knowledge_event(
                state.setdefault("character_knowledge", []),
                state.setdefault(_STATE_CHANGES_KEY, []),
                event,
            )
        else:
            _apply_entity_event(
                state.setdefault("entities", {}),
                state.setdefault(_STATE_CHANGES_KEY, []),
                event,
            )

    @staticmethod
    def apply_scene_dimension_event(
        state: dict[str, Any],
        dimension: str,
        event: Any,
    ) -> None:
        """Scene 分维度投影：与章节投影共用同一解释内核。"""
        changes = state.setdefault(_STATE_CHANGES_KEY, [])
        if dimension == "entities":
            _apply_entity_event(state.setdefault("entities", {}), changes, event)
        elif dimension == "relations":
            _apply_relation_event(state.setdefault("relations", []), changes, event)
        elif dimension == "locations":
            _apply_location_event(
                state.setdefault("character_locations", {}), changes, event
            )
        elif dimension == "knowledge":
            _apply_knowledge_event(
                state.setdefault("character_knowledge", []), changes, event
            )
        elif dimension == "timeline":
            state.setdefault("facts", []).append(_event_payload(event))
        elif dimension == "causality":
            state.setdefault("claims", []).append(_event_payload(event))
