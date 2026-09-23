"""状态操作结构一致性门（V4 审查 A03：观察解释 → 确定性验证 → 领域事件）。

旧门只做身份检查（``entity_id`` 是否被 reuse 解析），观察与状态操作之间
没有语义绑定：传闻（belief/hypothesis/character_statement）观察恰好提及
已解析实体时，模型单方面声称的客观状态变化会被放行。本模块把门的语义
收紧为三条可确定性校验的规则：

1. **证据绑定**：每个 scene_event 必须引用本批观察（``source_observation_indices``
   指向同一采样响应里的观察序号）；无引用或引用越界（伪造）一律拦截。
2. **modality 分级**：客观状态维度（entities/relations/locations/timeline/
   causality）只接受 ``event_observed`` 观察作证据；character_statement/
   belief/hypothesis 只能支撑 knowledge 维度（谁知道什么），不能把传闻
   变成客观事实。author_plan/figurative/unclear 不支撑任何状态操作。
3. **主体要求**：knowledge 维度事件必须携带 ``knowledge_subject``（谁知道），
   对应契约 ``TypedStateOperation`` 的 knowledge.* 校验。

被拦下的提议不丢失：连同拦截原因进入 ``gated_scene_events`` 与回执的
pending_decisions，留给作者裁定。通过的事件被附加 ``source_observation_ids``
（宿主派生的稳定观察身份，非模型可控）与 ``authority_basis``，使领域写入
携带可审计的证据链。

这些确定性检查不能证明语义蕴含。pipeline 还须经 state_review 独立回读正文，
通过后才可写状态；在场投影区分出现与有来源的移动（T03）。
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from modules.story.contracts import STATE_EVENT_DIMENSIONS

# 各状态维度接受的观察 modality（证据分级）。
# 客观维度只认叙述者视角观察到的 event_observed；knowledge 维度额外接受
# 言说/信念/假设——它们合法地建立"某角色的认知"，而不是客观事实。
# author_plan（大纲层意图）、figurative（比喻）、unclear 不支撑任何状态操作。
GROUNDING_MODALITIES: dict[str, frozenset[str]] = {
    "entities": frozenset({"event_observed"}),
    "relations": frozenset({"event_observed"}),
    "locations": frozenset({"event_observed"}),
    "timeline": frozenset({"event_observed"}),
    "causality": frozenset({"event_observed"}),
    "knowledge": frozenset(
        {"event_observed", "character_statement", "belief", "hypothesis"}
    ),
}

# modality 是否支撑某维度：非白名单维度（模型输出的新造维度）交由
# MemoryService 的维度校验拒绝，本门不重复。
KNOWLEDGE_DIMENSION = "knowledge"


def _mention_resolves_to(mention: dict[str, Any], entity_id: str) -> bool:
    resolution = mention.get("resolution") or {}
    return (
        resolution.get("outcome") == "reuse"
        and resolution.get("resolved_entity_id") == entity_id
    )


def _observation_grounds(
    observation: dict[str, Any],
    *,
    dimension: str,
    entity_id: str | None,
) -> bool:
    """单条观察是否为该维度（及主体，若主张实体）提供合法证据。"""

    allowed = GROUNDING_MODALITIES.get(dimension)
    if allowed is None or observation.get("modality") not in allowed:
        return False
    if entity_id is None:
        return True
    # 主张实体的操作：实体必须在这条被引用的观察里被提及并解析（reuse）。
    return any(
        _mention_resolves_to(mention, entity_id)
        for mention in observation.get("mentions") or []
    )


def gate_scene_events(
    events: Iterable[dict[str, Any]],
    compiled_observations: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """逐项验证模型提议的 scene_events：通过 → 领域事件；否则 → 待裁定提议。

    ``compiled_observations`` 是管线编译产物（含 observation_id、modality、
    mentions 与解析结论）。返回 ``(applied_events, gated_events)``；两者都是
    携带证据信息的独立副本，不改动调用方输入。
    """

    from modules.story.facade import validate_machine_event_snapshot

    applied: list[dict[str, Any]] = []
    gated: list[dict[str, Any]] = []
    for event in events:
        event = dict(event)
        dimension = str(event.get("dimension") or "")
        entity_id = str(event.get("entity_id") or "") or None
        raw_indices = event.get("source_observation_indices") or []
        referenced = [
            compiled_observations[index]
            for index in raw_indices
            if type(index) is int and 0 <= index < len(compiled_observations)
        ]
        reasons: list[str] = []

        def resolve_surface(surface):
            identities = {
                mention["resolution"]["resolved_entity_id"]
                for observation in referenced
                for mention in observation.get("mentions", [])
                if mention.get("surface") == surface
                and (mention.get("resolution") or {}).get("outcome") == "reuse"
                and mention["resolution"].get("resolved_entity_id")
            }
            return next(iter(identities)) if len(identities) == 1 else None

        if event.get("subject_surface"):
            resolved = resolve_surface(event["subject_surface"])
            if resolved is None or entity_id not in {None, resolved}:
                reasons.append("subject_unresolved_in_evidence")
            else:
                entity_id = event["entity_id"] = resolved
        if dimension in {"entities", "locations", "relations"} and not entity_id:
            reasons.append("subject_required")
        if event.get("knowledge_subject"):
            event["knowledge_subject"] = (
                resolve_surface(event["knowledge_subject"]) or event["knowledge_subject"]
            )
        expected_dimension = STATE_EVENT_DIMENSIONS.get(event.get("event_type"))
        if expected_dimension is not None and dimension != expected_dimension:
            reasons.append("event_dimension_mismatch")
        if len(referenced) != len(raw_indices):
            reasons.append("fabricated_reference")
        if not referenced:
            reasons.append("no_evidence_binding")
        elif not all(
            _observation_grounds(observation, dimension=dimension, entity_id=entity_id)
            for observation in referenced
        ):
            # 区分两种主因便于裁定：实体从未解析 vs 证据 modality 不足。
            if entity_id is not None and not any(
                _mention_resolves_to(mention, entity_id)
                for observation in referenced
                for mention in observation.get("mentions") or []
            ):
                reasons.append("subject_unresolved_in_evidence")
            else:
                reasons.append("modality_not_grounding")
        if dimension == KNOWLEDGE_DIMENSION and not event.get("knowledge_subject"):
            reasons.append("knowledge_requires_subject")
        elif dimension == KNOWLEDGE_DIMENSION and not all(
            _observation_grounds(
                observation,
                dimension=dimension,
                entity_id=str(event["knowledge_subject"]),
            )
            for observation in referenced
        ):
            reasons.append("knowledge_subject_unresolved_in_evidence")

        if reasons:
            event["_gate_reasons"] = reasons
            gated.append(event)
            continue
        after = dict(event.get("snapshot_after") or {})
        resolved_ids = {
            mention["resolution"]["resolved_entity_id"]
            for observation in referenced
            for mention in observation.get("mentions", [])
            if (mention.get("resolution") or {}).get("outcome") == "reuse"
        }
        if dimension == "entities" and event.get("event_type") in {
            "entity_created",
            "entity_updated",
        }:
            if after.get("id") not in (None, entity_id):
                reasons.append("payload_subject_mismatch")
            after.setdefault("id", entity_id)
        if event.get("event_type") == "relation_established":
            if after.get("source_id") not in (None, entity_id) or after.get(
                "target_id"
            ) not in tuple(resolved_ids):
                reasons.append("relation_endpoints_unresolved")
            after.setdefault("source_id", entity_id)
        if event.get("event_type") == "knowledge_changed":
            subject = event.get("knowledge_subject")
            if after.get("character_id") not in (None, subject) or (
                after.get("target_id") and after["target_id"] not in tuple(resolved_ids)
            ):
                reasons.append("payload_subject_mismatch")
            if (
                not all(item.get("modality") == "event_observed" for item in referenced)
                and after.get("knowledge_level") != "rumor"
            ):
                reasons.append("knowledge_level_not_grounded")
            after["character_id"] = subject
            identity = json.dumps(
                [
                    subject,
                    {
                        key: value
                        for key, value in after.items()
                        if key not in {"id", "meta"}
                    },
                    sorted(item["observation_id"] for item in referenced),
                ],
                sort_keys=True,
                ensure_ascii=False,
            )
            after["id"] = str(uuid5(NAMESPACE_URL, "evolution:knowledge:" + identity))
        try:
            validate_machine_event_snapshot(event.get("event_type"), after)
        except (ValueError, TypeError):
            reasons.append("state_payload_not_materializable")
        if reasons:
            event["_gate_reasons"] = reasons
            gated.append(event)
            continue
        event["source_observation_ids"] = [
            observation["observation_id"] for observation in referenced
        ]
        event["authority_basis"] = "derived_observation"
        # Story 持久化的是 snapshot_after；顶层证据字段不能只留在冻结负载里。
        after["meta"] = {
            **(after.get("meta") or {}),
            "author_confirmed": False,
            "source_observation_ids": event["source_observation_ids"],
            "source_receipts": [
                {
                    "observation_id": observation["observation_id"],
                    "source_ref": observation.get("source_ref"),
                    "evidence_quotes": observation.get("evidence_quotes", []),
                }
                for observation in referenced
            ],
            "authority_basis": event["authority_basis"],
        }
        if dimension == KNOWLEDGE_DIMENSION:
            after["knowledge_subject"] = event["knowledge_subject"]
        event["snapshot_after"] = after
        applied.append(event)
    return applied, gated


__all__ = ["GROUNDING_MODALITIES", "gate_scene_events"]
