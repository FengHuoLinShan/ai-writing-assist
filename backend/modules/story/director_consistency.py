"""Deterministic checks over typed IDs and current Evidence receipts only."""

from __future__ import annotations

import json

from modules.story.director_schemas import (
    DirectorCandidateEvent,
    DirectorConsistency,
    DirectorConsistencyFinding,
    DirectorMaterial,
)
from modules.story.simulation_v3 import SimulationIntent


def _check_reference(
    reference,
    *,
    object_ids: set[str],
    map_node_ids: set[str],
    candidates: dict[str, str],
    actor_visible_object_ids: set[str] | None = None,
    actor_visible_map_node_ids: set[str] | None = None,
):
    if reference is None:
        return None
    if reference.kind == "object":
        if reference.id not in object_ids:
            raise ValueError("推演输出引用了未核验或不属于当前作品的对象")
        if (
            actor_visible_object_ids is not None
            and reference.id not in actor_visible_object_ids
        ):
            raise ValueError("人物意图引用了该人物当前可知资料中不存在的对象")
    elif reference.kind == "map_node":
        if reference.id not in map_node_ids:
            raise ValueError("推演输出引用了未核验或未采用的地图地点")
        if (
            actor_visible_map_node_ids is not None
            and reference.id not in actor_visible_map_node_ids
        ):
            raise ValueError("人物意图引用了该人物当前可知资料中不存在的地点")
    elif reference.kind == "candidate":
        existing = candidates.get(reference.id)
        if existing is not None and existing != reference.label:
            raise ValueError("同一导演候选 ID 被用于不同内容")
        candidates[reference.id] = reference.label or ""
    else:
        raise ValueError("对象、物件和地点必须引用已核验身份或导演候选")
    return reference.model_dump(mode="json")


def validate_intents(
    intents: list[SimulationIntent],
    *,
    participant_ids: set[str],
    known_participant_ids: dict[str, set[str]],
    role_visible_object_ids: dict[str, set[str]],
    role_visible_map_node_ids: dict[str, set[str]],
    existing_object_ids: set[str],
    existing_map_node_ids: set[str],
) -> dict[str, str]:
    candidates: dict[str, str] = {}
    for intent in intents:
        actor = intent.actor.id
        visible = {actor, *known_participant_ids.get(actor, set())}
        if intent.actor.kind != "object" or actor not in participant_ids:
            raise ValueError("人物意图必须绑定到本轮已核验参与者")
        if any(
            item.kind != "object" or item.id not in visible for item in intent.audience
        ):
            raise ValueError("人物意图收聽者超出该角色已知范围")
        for reference in (intent.resource, intent.recipient, intent.destination):
            _check_reference(
                reference,
                object_ids=existing_object_ids,
                map_node_ids=existing_map_node_ids,
                candidates=candidates,
                actor_visible_object_ids=role_visible_object_ids.get(actor, set()),
                actor_visible_map_node_ids=role_visible_map_node_ids.get(actor, set()),
            )
        if (
            intent.kind == "speak"
            and intent.visibility == "whisper"
            and not intent.audience
        ):
            raise ValueError("私语必须指定角色可知的接收者")
    return candidates


def validate_material_references(
    materials: list[DirectorMaterial],
    *,
    participant_ids: set[str],
    known_event_ids: set[str],
    known_event_index: dict[str, dict],
    event_observers: dict[str, set[str]],
    known_source_index: dict[str, dict],
    role_source_indexes: dict[str, dict[str, dict]],
    existing_object_ids: set[str],
    existing_map_node_ids: set[str],
) -> list[DirectorMaterial]:
    candidates: dict[str, str] = {}
    result = []
    for material in materials:
        if any(item not in participant_ids for item in material.perceiver_ids):
            material.perceiver_ids = [
                item for item in material.perceiver_ids if item in participant_ids
            ]
            material.perception_status = "unknown"
            material.perception_note = "模型给出的感知者不在本轮参与者范围，已降为待核实"
        known_source_ids = set(known_source_index)
        valid_source_ids = known_source_ids | known_event_ids
        if any(source_id not in valid_source_ids for source_id in material.source_ids):
            material.source_kind = "director_inference"
            material.source_ids = []

        typed_source_ids = {
            source_id
            for source_id in material.source_ids
            if source_id in known_source_index
            and known_source_index[source_id].get("kind") == material.source_kind
        }
        event_source_ids = set(material.source_ids) & known_event_ids
        if material.source_kind == "observed_event":
            source_ids = event_source_ids
        else:
            source_ids = typed_source_ids
        if (
            material.source_kind not in {"director_inference", "candidate"}
            and not source_ids
        ):
            material.source_kind = "director_inference"
            material.source_ids = []
            material.source_fingerprints = {}
        else:
            material.source_ids = sorted(source_ids)
            material.source_fingerprints = {
                item: (
                    known_source_index[item]["fingerprint"]
                    if item in known_source_index
                    else known_event_index[item]["fingerprint"]
                )
                for item in material.source_ids
            }

        for reference in material.object_refs:
            from modules.story.simulation_v3 import SimulationReference

            parsed = SimulationReference.model_validate(reference)
            _check_reference(
                parsed,
                object_ids=existing_object_ids,
                map_node_ids=existing_map_node_ids,
                candidates=candidates,
            )
        material.candidate_only = (
            material.candidate_only
            or material.source_kind == "candidate"
            or any(
                item.get("kind") == "candidate"
                for item in material.object_refs
                if isinstance(item, dict)
            )
        )
        material.conflict_status = "unknown"
        material.perception_status = "unknown"
        material.perception_note = "感知范围无法由当前结构化资料核实"
        permitted_perceivers: set[str] = set()
        if "inner" in material.senses:
            owner = material.internal_character_id
            if owner not in participant_ids:
                material.perceiver_ids = []
                material.perception_status = "unknown"
                material.perception_note = "内心活动缺少可核验的所属人物"
            else:
                material.perceiver_ids = [owner]
                permitted_perceivers = {owner}
                material.perception_status = "known"
                material.perception_note = "内心活动仅属于这名人物"
        elif material.source_kind == "observed_event" and material.source_ids:
            raw_observers = (
                set.intersection(
                    *(event_observers.get(item, set()) for item in material.source_ids)
                )
                if material.source_ids
                else set()
            )
            permitted_perceivers = {
                item.partition(":")[2]
                for item in raw_observers
                if item.startswith("object:")
                and item.partition(":")[2] in participant_ids
            }
            material.perception_note = "人物必须在所有所引事件的观察回执中"
        elif (
            material.source_kind
            in {
                "world_dossier",
                "continuity",
                "character_pattern",
                "story_character_card",
            }
            and material.source_ids
        ):
            permitted_perceivers = {
                actor
                for actor in participant_ids
                if set(material.source_ids).issubset(
                    set(role_source_indexes.get(actor, {}))
                )
            }
            material.perception_note = "仅将该人物当前角色资料包中包含的全部来源视为已知"
        claimed = set(material.perceiver_ids) & participant_ids
        material.perceiver_ids = sorted(permitted_perceivers)
        material.disabled_for_character_ids = sorted(
            participant_ids - permitted_perceivers
        )
        if material.perceiver_ids:
            material.perception_status = "known"
        elif claimed:
            material.perception_status = "impossible"
            material.perception_note = "模型声称的感知者缺少角色资料或事件观察回执依据"
        if material.candidate_only or material.source_kind in {
            "candidate",
            "director_inference",
        }:
            material.perceiver_ids = []
            material.disabled_for_character_ids = sorted(participant_ids)
            material.perception_status = "unknown"
            material.perception_note = "候选或导演发挥没有结构化的角色感知依据"

        exact_values: dict[tuple[str, str], set[str]] = {}
        for source_id in material.source_ids:
            entry = known_source_index.get(source_id) or {}
            if entry.get("kind") != "continuity":
                continue
            row = entry.get("row") or {}
            provenance = row.get("provenance") or {}
            if provenance.get("status") != "exact" or not row.get("checkpoint_id"):
                continue
            subject = str(row.get("entity_id") or "")
            field = f"{row.get('dimension') or ''}:{row.get('field') or ''}"
            if subject and field != ":":
                exact_values.setdefault((subject, field), set()).add(
                    json.dumps(row.get("value"), sort_keys=True, ensure_ascii=False)
                )
        conflicts = [key for key, values in exact_values.items() if len(values) > 1]
        if conflicts:
            material.conflict_status = "conflict"
            material.perception_note += "；所引精确连续性记录彼此冲突"
        result.append(material)
    return result


def validate_candidate_events(
    events: list[DirectorCandidateEvent],
    *,
    existing_object_ids: set[str],
    existing_map_node_ids: set[str],
    known_source_index: dict[str, dict],
    known_event_index: dict[str, dict],
) -> list[DirectorCandidateEvent]:
    candidates: dict[str, str] = {}
    from modules.story.simulation_v3 import SimulationReference

    for event in events:
        if event.applied_to_state is not False or event.candidate_only is not True:
            raise ValueError("导演新增事件必须保持候选且不能写入模拟状态")
        for raw in event.references:
            reference = SimulationReference.model_validate(raw)
            _check_reference(
                reference,
                object_ids=existing_object_ids,
                map_node_ids=existing_map_node_ids,
                candidates=candidates,
            )
        normalized = []
        for basis in event.basis:
            if basis.source_kind == "director_inference":
                normalized.append(
                    basis.model_copy(
                        update={"source_id": None, "source_fingerprint": None}
                    )
                )
            else:
                reference = known_event_index.get(
                    basis.source_id or ""
                ) or known_source_index.get(basis.source_id or "")
                if reference and reference.get("kind") == basis.source_kind:
                    normalized.append(
                        basis.model_copy(
                            update={"source_fingerprint": reference["fingerprint"]}
                        )
                    )
                else:
                    normalized.append(
                        basis.model_copy(
                            update={
                                "source_kind": "director_inference",
                                "source_id": None,
                                "source_fingerprint": None,
                                "note": (
                                    "新增事件没有匹配的结构化依据；"
                                    + "保留为导演候选发挥。"
                                ),
                            }
                        )
                    )
        event.basis = normalized
    return events


def build_consistency(
    *,
    source: dict,
    intents: list[SimulationIntent],
    candidates: dict[str, str],
    materials: list[DirectorMaterial],
    candidate_events: list[DirectorCandidateEvent],
    object_ids: set[str],
    map_node_ids: set[str],
) -> DirectorConsistency:
    findings = [
        DirectorConsistencyFinding(
            severity="notice",
            field="candidate",
            statement=f"导演引入候选（{label}），尚未建立世界对象或正史事实。",
        )
        for label in candidates.values()
    ]
    findings.extend(
        DirectorConsistencyFinding(
            severity="conflict",
            subject_id=material.material_id,
            field="typed_source_conflict",
            statement="素材引用的精确连续性来源在同一人物与字段上给出互相矛盾的值。",
            source_refs=[
                {"kind": material.source_kind, "id": item} for item in material.source_ids
            ],
        )
        for material in materials
        if material.conflict_status == "conflict"
    )
    findings.extend(
        DirectorConsistencyFinding(
            severity="notice",
            subject_id=event.candidate_id,
            field="candidate_event",
            statement=f"导演提出候选事件“{event.label}”，未应用到本轮状态或正史。",
        )
        for event in candidate_events
    )
    for reference in sorted(object_ids):
        findings.append(
            DirectorConsistencyFinding(
                severity="notice",
                subject_id=reference,
                field="world_object_identity",
                statement="对象身份在当前作品中通过 Story/World 校验。",
                source_refs=[{"kind": "typed_object_id", "id": reference}],
            )
        )
    for reference in sorted(map_node_ids):
        findings.append(
            DirectorConsistencyFinding(
                severity="notice",
                subject_id=reference,
                field="map_node_identity",
                statement="地点身份通过当前作品已采用地图节点校验。",
                source_refs=[{"kind": "typed_map_node_id", "id": reference}],
            )
        )
    unknown_checks = [
        "作者设定有效期覆盖规则与项目开关尚未接入（C0c）；本轮不据此裁定冲突。",
        "人物生死与外观缺少本轮可用的结构化校验来源；本轮不据自然语言作真值判定。",
        "持有物、知情与位置只接受当前精确结构来源和模拟协议类型字段；没有覆盖的项目保持未知。",
        "导演文本中的语义性性格判断不参与确定性检查。",
    ]
    brief = source.get("author_brief") or {}
    unknown_checks.extend(brief.get("omissions") or [])
    exact_values: dict[tuple[str, str, str], dict[str, set[str]]] = {}
    for item in brief.get("continuity_items") or []:
        provenance = item.get("provenance") or {}
        checkpoint_id = str(item.get("checkpoint_id") or "")
        if provenance.get("status") != "exact" or not checkpoint_id:
            continue
        subject_id = str(item.get("entity_id") or "")
        dimension = str(item.get("dimension") or "")
        field = str(item.get("field") or "")
        if not subject_id or not dimension or not field:
            continue
        value_hash = json.dumps(item.get("value"), sort_keys=True, ensure_ascii=False)
        exact_values.setdefault((subject_id, dimension, field), {}).setdefault(
            value_hash, set()
        ).add(checkpoint_id)
    for (subject_id, dimension, field), values in sorted(exact_values.items()):
        if len(values) <= 1:
            continue
        findings.append(
            DirectorConsistencyFinding(
                severity="conflict",
                subject_id=subject_id,
                field=f"{dimension}:{field}",
                statement="当前 Scene 可用的精确结构化来源对同一字段给出不同值。",
                source_refs=[
                    {"kind": "continuity_checkpoint", "id": checkpoint_id}
                    for checkpoint_id in sorted(set().union(*values.values()))
                ],
            )
        )
    coverage = "partial" if unknown_checks else "complete"
    if brief.get("coverage") == "unknown" or brief.get("unknown_layers"):
        coverage = "unknown"
    checked_fields = {
        f"{item.get('dimension')}:{item.get('field')}"
        for item in brief.get("continuity_items") or []
        if (item.get("provenance") or {}).get("status") == "exact"
        and item.get("checkpoint_id")
    }
    return DirectorConsistency(
        coverage=coverage,
        checked_facts=[
            "当前作品与 Scene 身份",
            "已选人物的 canonical World 身份",
            "被引用对象/地图地点身份与采用状态",
            "动作效果通过 simulation_v3 的有限结算与状态回放",
            *[f"当前精确来源字段：{item}" for item in sorted(checked_fields)],
        ],
        unavailable_checks=list(dict.fromkeys(unknown_checks)),
        findings=findings,
    )
