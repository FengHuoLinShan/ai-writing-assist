"""状态操作语义门单元测试（V4 审查 A03）。

覆盖审查给出的反例清单：传闻不能变客观事实、计划不等于到达、知识须有
主体、伪造引用拒绝、无证据绑定拦截、仅 entity_id 合法不足以放行。
"""

from __future__ import annotations

import pytest

from modules.evolution.state_gate import gate_scene_events

E1 = "11111111-1111-4111-8111-111111111111"
E2 = "22222222-2222-4222-8222-222222222222"


def _obs(
    observation_id: str,
    modality: str,
    resolutions: dict[str, str] | None = None,
) -> dict:
    """构造编译后的观察条目：mentions 按表面名 → 已解析实体。"""

    return {
        "observation_id": observation_id,
        "predicate": f"predicate-{observation_id[:4]}",
        "modality": modality,
        "quote": "原文引用",
        "mentions": [
            {
                "mention_id": f"m-{surface}",
                "surface": surface,
                "entity_type": "character",
                "resolution": (
                    {
                        "outcome": "reuse",
                        "resolved_entity_id": entity_id,
                    }
                    if entity_id
                    else None
                ),
            }
            for surface, entity_id in (resolutions or {}).items()
        ],
    }


BELIEF_LINZHOU = _obs("b" * 64, "belief", {"林舟": E1})
EVENT_LINZHOU = _obs("e" * 64, "event_observed", {"林舟": E1})
EVENT_QINGZHU = _obs("f" * 64, "event_observed", {"青竹": E2})
STATEMENT_LINZHOU = _obs("c" * 64, "character_statement", {"林舟": E1, "青竹": E2})
PLAN_LINZHOU = _obs("a" * 64, "author_plan", {"林舟": E1})


def test_provider_surface_subject_resolves_only_within_referenced_evidence():
    event = {
        "dimension": "locations",
        "event_type": "entity_moved",
        "subject_surface": "林舟",
        "snapshot_after": {"text_state": "白石城"},
        "source_observation_indices": [0],
    }
    applied, gated = gate_scene_events([event], [EVENT_LINZHOU])
    assert not gated and applied[0]["entity_id"] == E1
    assert gate_scene_events([event], [EVENT_QINGZHU])[1]
    assert gate_scene_events([{**event, "entity_id": E2}], [EVENT_LINZHOU])[1]
    assert gate_scene_events([{**event, "subject_surface": None}], [EVENT_LINZHOU])[1]
    knowledge = {
        "dimension": "knowledge",
        "event_type": "knowledge_changed",
        "subject_surface": "林舟",
        "knowledge_subject": "林舟",
        "source_observation_indices": [0],
        "snapshot_after": {
            "target_type": "event",
            "known_content": "渡口封锁",
            "knowledge_level": "rumor",
        },
    }
    assert (
        gate_scene_events([knowledge], [BELIEF_LINZHOU])[0][0]["knowledge_subject"] == E1
    )


def test_knowledge_cannot_borrow_another_subject_or_launder_a_rumor():
    event = {
        "dimension": "knowledge",
        "event_type": "knowledge_changed",
        "knowledge_subject": "林舟",
        "source_observation_indices": [0, 1],
        "snapshot_after": {
            "target_type": "event",
            "known_content": "封锁消息",
            "knowledge_level": "full",
        },
    }
    _, rejected = gate_scene_events([event], [STATEMENT_LINZHOU, EVENT_LINZHOU])
    assert "knowledge_level_not_grounded" in rejected[0]["_gate_reasons"]
    event["snapshot_after"]["knowledge_level"] = "rumor"
    accepted, rejected = gate_scene_events([event], [STATEMENT_LINZHOU, EVENT_LINZHOU])
    assert not rejected and accepted[0]["snapshot_after"]["character_id"] == E1
    first_id = accepted[0]["snapshot_after"]["id"]
    event["snapshot_after"]["known_content"] = "另一条消息"
    assert (
        gate_scene_events([event], [STATEMENT_LINZHOU, EVENT_LINZHOU])[0][0][
            "snapshot_after"
        ]["id"]
        != first_id
    )
    assert gate_scene_events([event], [EVENT_QINGZHU, EVENT_LINZHOU])[1]
    event["snapshot_after"]["character_id"] = E2
    assert (
        "payload_subject_mismatch"
        in gate_scene_events([event], [STATEMENT_LINZHOU, EVENT_LINZHOU])[1][0][
            "_gate_reasons"
        ]
    )


@pytest.mark.parametrize(
    "event_type",
    ["entity_moved", "entity_removed", "relation_established", "timeline_changed"],
)
def test_belief_cannot_disguise_an_objective_operation_as_knowledge(event_type):
    applied, gated = gate_scene_events(
        [
            {
                "dimension": "knowledge",
                "event_type": event_type,
                "entity_id": E1,
                "knowledge_subject": E1,
                "snapshot_after": {"text_state": "白石城"},
                "source_observation_indices": [0],
            }
        ],
        [BELIEF_LINZHOU],
    )
    assert not applied and "event_dimension_mismatch" in gated[0]["_gate_reasons"]


def test_knowledge_subject_must_resolve_in_its_own_evidence():
    applied, gated = gate_scene_events(
        [
            {
                "dimension": "knowledge",
                "event_type": "knowledge_changed",
                "entity_id": E1,
                "knowledge_subject": E2,
                "snapshot_after": {"knowledge": "城门关闭"},
                "source_observation_indices": [0],
            }
        ],
        [BELIEF_LINZHOU],
    )
    assert (
        not applied
        and "knowledge_subject_unresolved_in_evidence" in gated[0]["_gate_reasons"]
    )


def test_model_cannot_grant_its_events_author_authority():
    from types import SimpleNamespace

    from modules.story.continuity.repositories import EventRepository

    applied, gated = gate_scene_events(
        [
            {
                "dimension": "locations",
                "event_type": "entity_moved",
                "entity_id": E1,
                "snapshot_after": {
                    "text_state": "白石城",
                    "meta": {"author_confirmed": True},
                },
                "source_observation_indices": [0],
            }
        ],
        [EVENT_LINZHOU],
    )
    assert not gated
    assert not EventRepository.is_authority_event(
        SimpleNamespace(source="evolution", snapshot_after=applied[0]["snapshot_after"])
    )


def test_rumor_observation_cannot_ground_objective_state_change() -> None:
    # 反例：观察是 belief（传闻/误信），实体恰好已解析——客观移动提议必须被拦。
    events = [
        {
            "dimension": "locations",
            "event_type": "entity_moved",
            "entity_id": E1,
            "snapshot_after": {"text_state": "白石城"},
            "source_observation_indices": [0],
        }
    ]
    applied, gated = gate_scene_events(events, [BELIEF_LINZHOU])
    assert applied == []
    assert gated[0]["_gate_reasons"] == ["modality_not_grounding"]


def test_event_observed_grounds_objective_state_change() -> None:
    events = [
        {
            "dimension": "locations",
            "event_type": "entity_moved",
            "entity_id": E1,
            "snapshot_after": {"text_state": "白石城"},
            "source_observation_indices": [0],
        }
    ]
    applied, gated = gate_scene_events(events, [EVENT_LINZHOU])
    assert gated == []
    assert applied[0]["source_observation_ids"] == ["e" * 64]
    assert applied[0]["authority_basis"] == "derived_observation"


def test_plan_or_figurative_never_grounds_state() -> None:
    # 计划去某地（author_plan）不能变成已到达。
    events = [
        {
            "dimension": "locations",
            "event_type": "entity_moved",
            "entity_id": E1,
            "snapshot_after": {"text_state": "当铺"},
            "source_observation_indices": [0],
        }
    ]
    applied, gated = gate_scene_events(events, [PLAN_LINZHOU])
    assert applied == []
    assert gated[0]["_gate_reasons"] == ["modality_not_grounding"]


def test_statement_grounds_knowledge_but_requires_subject() -> None:
    # 角色陈述合法建立 knowledge（谁知道什么）……
    events_with_subject = [
        {
            "dimension": "knowledge",
            "event_type": "knowledge_changed",
            "entity_id": E1,
            "snapshot_after": {
                "target_type": "event",
                "known_content": "青竹保管铜钥匙",
                "knowledge_level": "rumor",
            },
            "source_observation_indices": [0],
            "knowledge_subject": E1,
        }
    ]
    applied, gated = gate_scene_events(events_with_subject, [STATEMENT_LINZHOU])
    assert gated == [] and len(applied) == 1

    # ……但缺 knowledge_subject 时必须拦截（契约 knowledge.* 须指明主体）。
    (event,) = events_with_subject
    applied, gated = gate_scene_events(
        [{**event, "knowledge_subject": None}], [STATEMENT_LINZHOU]
    )
    assert applied == []
    assert gated[0]["_gate_reasons"] == ["knowledge_requires_subject"]


def test_statement_cannot_ground_objective_relation_change() -> None:
    # 保管声明（character_statement）不能直接变成客观关系变更（所有权）。
    events = [
        {
            "dimension": "relations",
            "event_type": "relation_established",
            "entity_id": E1,
            "snapshot_after": {"relation": "owner_of", "target": "铜钥匙"},
            "source_observation_indices": [0],
        }
    ]
    applied, gated = gate_scene_events(events, [STATEMENT_LINZHOU])
    assert applied == []
    assert gated[0]["_gate_reasons"] == ["modality_not_grounding"]


def test_fabricated_reference_is_rejected() -> None:
    events = [
        {
            "dimension": "entities",
            "event_type": "manual_correction",
            "entity_id": E1,
            "snapshot_after": {},
            "source_observation_indices": [7],  # 越界：本批只有一条观察
        }
    ]
    applied, gated = gate_scene_events(events, [EVENT_LINZHOU])
    assert applied == []
    assert gated[0]["_gate_reasons"] == ["fabricated_reference", "no_evidence_binding"]


def test_no_reference_is_gated_pending_decision() -> None:
    # 无证据绑定的提议不丢失，但进入待裁定，不取得状态效果。
    events = [
        {
            "dimension": "entities",
            "event_type": "manual_correction",
            "entity_id": E1,
            "snapshot_after": {},
        }
    ]
    applied, gated = gate_scene_events(events, [EVENT_LINZHOU])
    assert applied == []
    assert gated[0]["_gate_reasons"] == ["no_evidence_binding"]


def test_resolved_identity_alone_is_insufficient() -> None:
    # 实体在批次里解析成功，但被引用的证据没有提及它：仍拦。
    observations = [EVENT_LINZHOU, EVENT_QINGZHU]
    events = [
        {
            "dimension": "locations",
            "event_type": "entity_moved",
            "entity_id": E2,  # 青竹在观察 1 解析，但事件只引用观察 0
            "snapshot_after": {},
            "source_observation_indices": [0],
        }
    ]
    applied, gated = gate_scene_events(events, observations)
    assert applied == []
    assert gated[0]["_gate_reasons"] == ["subject_unresolved_in_evidence"]


def test_global_event_still_requires_evidence_binding() -> None:
    # 无实体引用的全局事件（时间线等）不再绕过证据门。
    events = [
        {
            "dimension": "timeline",
            "event_type": "time_advanced",
            "snapshot_after": {"days": 3},
        }
    ]
    applied, gated = gate_scene_events(events, [EVENT_LINZHOU])
    assert applied == [] and gated[0]["_gate_reasons"] == ["no_evidence_binding"]

    applied, gated = gate_scene_events(
        [{**events[0], "source_observation_indices": [0]}], [EVENT_LINZHOU]
    )
    assert gated == [] and len(applied) == 1
