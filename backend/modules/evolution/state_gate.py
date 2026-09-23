"""状态操作一致性门（V4 审查 A03：观察解释 → 确定性验证 → 领域事件）。

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

move/observe 之辨（只有移动证据才算 traveled）不在本门：那是在场投影
（story/continuity/presence，T03）的职责分层。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

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
            if isinstance(index, int) and 0 <= index < len(compiled_observations)
        ]
        reasons: list[str] = []
        if len(referenced) != len(raw_indices):
            reasons.append("fabricated_reference")
        if not referenced:
            reasons.append("no_evidence_binding")
        elif not any(
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

        if reasons:
            event["_gate_reasons"] = reasons
            gated.append(event)
            continue
        event["source_observation_ids"] = [
            observation["observation_id"] for observation in referenced
        ]
        event["authority_basis"] = "derived_observation"
        applied.append(event)
    return applied, gated


__all__ = ["GROUNDING_MODALITIES", "gate_scene_events"]
