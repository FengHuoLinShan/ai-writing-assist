"""Optional, source-bound spatial discovery for Evolution Scene reads."""

from __future__ import annotations

import asyncio
import hashlib
import json
import unicodedata
from collections import defaultdict
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from infrastructure.llm.collaboration import content_hash
from modules.evolution.contracts import ObservationModality
from modules.world.contracts import (
    MapSpatialClue,
    MapSpatialClueBatch,
    MapSpatialClueCallRef,
    MapSpatialClueContext,
    MapSpatialClueReview,
    MapSpatialClueSourceBinding,
    MapSpatialClueTypeProposalDraft,
    ModelVocabularyProposal,
    VocabularyEvidence,
    VocabularyReviewReceipt,
    VocabularyTraits,
    vocabulary_evidence_hash,
    vocabulary_proposal_hash,
)

SPATIAL_VERSION = 1
SPATIAL_METHOD_ID = "evolution.spatial_discover.v1"
SPATIAL_REVIEW_METHOD_ID = "evolution.spatial_review.v1"
SPATIAL_TYPE_LIMIT = 32
SPATIAL_CLUE_LIMIT = 64
SPATIAL_ENDPOINT_LIMIT = 128
SPATIAL_DENSITY_THRESHOLD = 1
SPATIAL_DENSITY_TERMS = (
    "地点",
    "地方",
    "房间",
    "门口",
    "道路",
    "街道",
    "城市",
    "村庄",
    "城镇",
    "山",
    "河",
    "湖",
    "桥",
    "楼",
    "院子",
    "入口",
    "出口",
    "东",
    "西",
    "南",
    "北",
    "上方",
    "下方",
    "相邻",
    "相通",
    "通往",
    "经过",
    "穿过",
    "抵达",
    "离开",
    "通行",
    "楼层",
)
LOCATION_ENTITY_TYPES = frozenset(
    {"location", "place", "region", "city", "district", "settlement", "space"}
)

SpatialVocabularyKind = Literal[
    "space", "level", "feature", "relation", "transport", "traveler", "access_condition"
]
SpatialClueKind = Literal[
    "contains",
    "bearing",
    "adjacency",
    "connection",
    "journey",
    "access_condition",
    "effective_change",
]
SpatialVerdict = Literal["supported", "unsupported", "uncertain"]


class SpatialModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SpatialQuantityProposal(SpatialModel):
    minimum: float | None = Field(default=None, ge=0)
    maximum: float | None = Field(default=None, ge=0)
    unit: str = Field(min_length=1, max_length=32)


class SpatialTypeProposal(SpatialModel):
    kind: SpatialVocabularyKind
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    aliases: list[str] = Field(default_factory=list, max_length=24)
    traits: VocabularyTraits = Field(default_factory=VocabularyTraits)


class SpatialClueProposal(SpatialModel):
    kind: SpatialClueKind
    subject_ref: str | None = Field(default=None, max_length=24)
    subject_surface: str = Field(min_length=1, max_length=200)
    target_ref: str | None = Field(default=None, max_length=24)
    target_surface: str | None = Field(default=None, max_length=200)
    relation: str | None = Field(default=None, max_length=96)
    modality: ObservationModality
    quote: str = Field(min_length=1, max_length=2000)
    type: SpatialTypeProposal | None = None
    transport_label: str | None = Field(default=None, max_length=200)
    duration: SpatialQuantityProposal | None = None
    distance: SpatialQuantityProposal | None = None
    access_conditions: list[str] = Field(default_factory=list, max_length=16)
    change_label: str | None = Field(default=None, max_length=200)


class SpatialDiscoveryOutput(SpatialModel):
    clues: list[SpatialClueProposal] = Field(default_factory=list, max_length=64)
    unresolved: list[str] = Field(default_factory=list, max_length=32)
    coverage: Literal["inspected", "partial"] = "inspected"
    coverage_note: str = Field(min_length=1, max_length=2000)


class SpatialClueReviewDecision(SpatialModel):
    clue_index: int = Field(ge=0)
    verdict: SpatialVerdict
    reason: str = Field(min_length=1, max_length=2000)
    type_verdict: SpatialVerdict | None = None
    reviewed_evidence_indices: list[int] = Field(default_factory=list, max_length=32)


class SpatialReviewOutput(SpatialModel):
    reviews: list[SpatialClueReviewDecision] = Field(default_factory=list, max_length=64)
    coverage_note: str = Field(min_length=1, max_length=2000)


SPATIAL_DISCOVERY_PROMPT = (
    "你只从给定的当前 Scene 正文提取可复核的空间线索。"
    "正文之外的故事、后续 Scene、常识推测和地图想象都不能作证。"
    "只输出原文明确支持的包含、方位、相邻、相通、行程声明、通行条件或生效变化；"
    "保留 belief、hypothesis、character_statement、author_plan 等模态，"
    "不把传闻升级为客观事实。逐字 quote 必须是当前正文中的连续原文。"
    "端点优先选择输入 endpoints 中与原文对应的 endpoint_ref，"
    "并逐字保留 subject_surface/target_surface；不编造 ID。"
    "没有明确身份时 ref 留空，surface 保留正文文字。已有类型按输入名称/别名选择；"
    "只有确实不同的类型才提议，建议的计算 traits 必须有原文语义依据。"
    "已有 archived/merged 类型不可重建或引用。单次 Scene 只提供涌现线索，"
    "不宣称类型已验证。数量受 schema 上限约束，未覆盖内容写入 unresolved，"
    "并如实标记 partial。"
)

SPATIAL_REVIEW_PROMPT = (
    "你是与抽取调用分离的独立审查者。逐项核对本批抽取结果、当前 Scene 原文、"
    "身份候选、类型快照和严格更早 Scene 的线索/词表证据。"
    "只根据逐字原文判断线索关系、端点、模态和新类型语义，不用常识补全；"
    "不支持或不确定时明确指出。提议的类型必须保留名称、描述、别名和 traits 原义。"
    "对已有 emerging 类型，逐条核对所有 prior+current 证据。"
    "reviewed_evidence_indices 必须列出你实际检查的每个 evidence 下标；"
    "没有完整检查全部证据，不得判 supported。"
    "你的响应只给逐项 verdict，不修改候选内容、不编造证据或身份。"
)


def spatial_method_fingerprint() -> str:
    """Hash method-only inputs; project vocabulary and clues stay in read sets."""
    return content_hash(
        {
            "version": SPATIAL_VERSION,
            "discovery_method": SPATIAL_METHOD_ID,
            "review_method": SPATIAL_REVIEW_METHOD_ID,
            "discovery_prompt": SPATIAL_DISCOVERY_PROMPT,
            "review_prompt": SPATIAL_REVIEW_PROMPT,
            "discovery_schema": SpatialDiscoveryOutput.model_json_schema(),
            "review_schema": SpatialReviewOutput.model_json_schema(),
            "density_terms": SPATIAL_DENSITY_TERMS,
            "density_threshold": SPATIAL_DENSITY_THRESHOLD,
            "location_entity_types": sorted(LOCATION_ENTITY_TYPES),
            "limits": {
                "types": SPATIAL_TYPE_LIMIT,
                "clues": SPATIAL_CLUE_LIMIT,
                "endpoints": SPATIAL_ENDPOINT_LIMIT,
            },
        }
    )


def spatial_discovery_messages(inputs: dict[str, Any], *, review: bool = False):
    from infrastructure.llm.schemas import LLMMessage

    prompt = SPATIAL_REVIEW_PROMPT if review else SPATIAL_DISCOVERY_PROMPT
    return [
        LLMMessage(role="system", content=prompt),
        LLMMessage(
            role="user",
            content=json.dumps(
                inputs, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ),
        ),
    ]


def _normalized(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return "".join(
        char
        for char in value
        if not unicodedata.category(char).startswith(("P", "Z")) and not char.isspace()
    )


def _density_hits(scene_text: str, endpoints: list[dict], context: MapSpatialClueContext):
    text = _normalized(scene_text)
    terms = set(SPATIAL_DENSITY_TERMS)
    terms.update(item.name for item in context.types)
    terms.update(alias for item in context.types for alias in item.aliases)
    lexical = sorted(
        term for term in terms if _normalized(term) and _normalized(term) in text
    )
    locations = sorted(
        {
            item["surface"]
            for item in endpoints
            if (item.get("entity_type") or "").casefold() in LOCATION_ENTITY_TYPES
        }
    )
    return {
        "lexical": lexical,
        "location_endpoints": locations,
        "count": len(lexical) + len(locations),
    }


def _source_binding(source, content_mode: str) -> MapSpatialClueSourceBinding:
    data = source.model_dump(mode="json")
    ranges = [
        {key: value for key, value in item.items() if key != "additional_sources"}
        for item in [data, *data.get("additional_sources", [])]
    ]
    return MapSpatialClueSourceBinding(
        **ranges[0], content_mode=content_mode, additional_sources=ranges[1:]
    )


def _exact_source_hash(scene_text: str, quote: str, source) -> str | None:
    if not isinstance(quote, str) or not quote:
        return None
    start = scene_text.find(quote)
    if start < 0 or scene_text.find(quote, start + 1) >= 0:
        return None
    end = start + len(quote)
    cursor = 0
    matches = []
    for part in source.ranges():
        if part.end_offset is None:
            return None
        next_cursor = cursor + part.end_offset - part.start_offset
        if start >= cursor and end <= next_cursor:
            matches.append(part.content_hash)
        cursor = next_cursor
    return matches[0] if len(matches) == 1 else None


def _current_endpoints(payload):
    observations = payload.get("compiled_observations") or []
    world_context = (payload.get("world_result") or {}).get("context") or {}
    candidates = world_context.get("identity_candidates") or []
    new_ids = world_context.get("_new_entity_ids") or {}
    accepted_candidate_ids = {str(value) for value in new_ids.values()}
    by_id: dict[str, dict] = {}
    surfaces: dict[str, set[str]] = defaultdict(set)
    for observation in observations:
        for mention in observation.get("mentions") or []:
            surface = str(mention.get("surface") or "").strip()
            if not surface:
                continue
            surfaces[surface].add(str(mention.get("entity_type") or ""))
            resolution = mention.get("resolution") or {}
            entity_id = resolution.get("resolved_entity_id")
            if entity_id:
                key = str(entity_id)
                by_id.setdefault(
                    key, {"entity_id": key, "state": None, "surfaces": set()}
                )
                by_id[key]["surfaces"].add(surface)
                if key in accepted_candidate_ids:
                    by_id[key]["state"] = "candidate"
    for item in candidates:
        surface = str(item.get("name") or "").strip()
        if surface:
            surfaces[surface].add(str(item.get("entity_type") or ""))
    return by_id, surfaces


def _endpoint_inputs(payload, context):
    by_id, surfaces = _current_endpoints(payload)
    endpoint_ids = list(by_id)[:SPATIAL_ENDPOINT_LIMIT]
    endpoint_surfaces = sorted(surfaces)[:SPATIAL_ENDPOINT_LIMIT]
    states = {str(key): value for key, value in context.endpoint_states.items()}
    current_candidates = {
        key for key, item in by_id.items() if item.get("state") == "candidate"
    }
    states.update({key: "candidate" for key in current_candidates})
    eligible_ids = [key for key in by_id if key in states]
    allowed = {key: states[key] for key in eligible_ids[:SPATIAL_ENDPOINT_LIMIT]}
    names_by_id = {
        entity_id: sorted(item["surfaces"])
        for entity_id, item in by_id.items()
        if entity_id in allowed
    }
    candidates = []
    ref_map = {}
    for ordinal, entity_id in enumerate(sorted(allowed)):
        for surface in names_by_id.get(entity_id, []):
            types = sorted(surfaces.get(surface, {""}))
            for entity_type in types:
                if len(candidates) >= SPATIAL_ENDPOINT_LIMIT:
                    break
                ref = f"ep{len(candidates)}"
                candidates.append(
                    {
                        "endpoint_ref": ref,
                        "surface": surface,
                        "entity_type": entity_type or None,
                        "state": allowed[entity_id],
                    }
                )
                ref_map[ref] = {
                    "entity_id": entity_id,
                    "state": allowed[entity_id],
                    "surface": surface,
                }
            if len(candidates) >= SPATIAL_ENDPOINT_LIMIT:
                break
        if len(candidates) >= SPATIAL_ENDPOINT_LIMIT:
            break
    allowed = {value["entity_id"]: value["state"] for value in ref_map.values()}
    return (
        endpoint_ids,
        endpoint_surfaces,
        candidates,
        ref_map,
        allowed,
        surfaces,
        max(0, len(eligible_ids) - len(allowed)),
    )


def _review_receipt(payload, verdict, *, evidence_hash, proposal_hash):
    return MapSpatialClueReview(
        proposal_call=MapSpatialClueCallRef(journal_key="scene_spatial_discovery"),
        review_call=MapSpatialClueCallRef(journal_key="scene_spatial_review"),
        proposal_hash=proposal_hash,
        evidence_hash=evidence_hash,
        verdict=verdict,
    )


def _canonical_digest(value: dict[str, Any]) -> str:
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _find_type(proposal: SpatialTypeProposal, context: MapSpatialClueContext):
    wanted = {
        _normalized(proposal.name),
        *(_normalized(item) for item in proposal.aliases),
    }
    matches = []
    for item in context.types:
        if item.kind != proposal.kind:
            continue
        names = {_normalized(item.name), *(_normalized(alias) for alias in item.aliases)}
        if wanted & names:
            matches.append(item)
    return matches


def _type_review_context(
    raw: SpatialClueProposal, context: MapSpatialClueContext, scene_id: str
):
    if raw.type is None:
        return None
    matches = _find_type(raw.type, context)
    if len(matches) == 1:
        item = matches[0]
        if item.status in {"archived", "merged"}:
            return {"kind": "tombstone", "type": item.model_dump(mode="json")}
        if item.status == "active":
            return {"kind": "active", "type": item.model_dump(mode="json")}
        if item.status == "emerging" and item.source == "model" and item.proposal_run_id:
            evidence = [item.model_dump(mode="json") for item in item.evidence]
            return {
                "kind": "emerging",
                "type": item.model_dump(mode="json"),
                "evidence": evidence,
            }
    if not matches:
        return {"kind": "new", "proposal": raw.type.model_dump(mode="json")}
    return {
        "kind": "ambiguous",
        "matches": [item.model_dump(mode="json") for item in matches],
    }


def _make_clues(*, frozen, source, content_mode, context, discovery, review, preparation):
    scene_text = frozen.payload["scene_text"]
    scene_id = UUID(str(frozen.payload["scene_id"]))
    attempt_uuid = UUID(str(frozen.attempt_id))
    endpoint_ref_map = preparation["endpoint_ref_map"]
    allowed_endpoints = preparation["allowed_endpoints"]
    decisions = {}
    duplicate_indexes = set()
    for item in review.reviews:
        if item.clue_index in decisions:
            duplicate_indexes.add(item.clue_index)
        decisions[item.clue_index] = item

    clues = []
    gaps = []
    seen_proposals = set()
    seen_clue_keys = set()
    for index, raw in enumerate(discovery.clues):
        source_hash = _exact_source_hash(scene_text, raw.quote, source)
        if source_hash is None:
            gaps.append(
                {"reason": "quote_missing_ambiguous_or_cross_source", "clue_index": index}
            )
            continue
        subject = _endpoint_from_output(
            raw.subject_ref, raw.subject_surface, endpoint_ref_map
        )
        target = (
            _endpoint_from_output(raw.target_ref, raw.target_surface, endpoint_ref_map)
            if raw.target_surface is not None
            else None
        )
        if subject is None or (
            raw.kind in {"contains", "bearing", "adjacency", "connection", "journey"}
            and target is None
        ):
            gaps.append(
                {"reason": "endpoint_reference_not_in_input", "clue_index": index}
            )
            continue

        type_ref = type_revision_id = type_kind = None
        draft = proposal = None
        type_context = _type_review_context(raw, context, str(scene_id))
        decision = decisions.get(index)
        if raw.type is not None and type_context:
            if type_context["kind"] == "active":
                item = next(
                    item
                    for item in context.types
                    if item.id == UUID(type_context["type"]["id"])
                )
                type_ref, type_revision_id, type_kind = (
                    item.id,
                    item.revision_id,
                    item.kind,
                )
            elif type_context["kind"] == "new":
                marker = (raw.type.kind, _normalized(raw.type.name))
                if (
                    decision
                    and decision.type_verdict == "supported"
                    and marker not in seen_proposals
                ):
                    draft = MapSpatialClueTypeProposalDraft(
                        kind=raw.type.kind,
                        name=raw.type.name,
                        description=raw.type.description,
                        aliases=raw.type.aliases,
                        traits=raw.type.traits,
                        proposal_run_id=attempt_uuid,
                    )
                    seen_proposals.add(marker)
                elif decision and decision.type_verdict != "supported":
                    gaps.append(
                        {
                            "reason": "new_type_not_independently_supported",
                            "clue_index": index,
                        }
                    )
            elif type_context["kind"] == "emerging":
                type_item = type_context["type"]
                prior = [
                    VocabularyEvidence.model_validate(item)
                    for item in type_context["evidence"]
                ]
                current = VocabularyEvidence(
                    scene_id=scene_id, quote=raw.quote, source_hash=source_hash
                )
                evidence = [*prior, current]
                evidence_hash = vocabulary_evidence_hash(evidence)
                fields = _VocabularyFields(
                    name=type_item["name"],
                    description=type_item.get("description", ""),
                    aliases=type_item.get("aliases", []),
                    traits=type_item.get("traits", {}),
                )
                proposal_hash = vocabulary_proposal_hash(type_item["kind"], fields)
                enough = len({str(item.scene_id) for item in evidence}) >= 2
                review_supported = bool(
                    decision
                    and decision.type_verdict == "supported"
                    and set(decision.reviewed_evidence_indices)
                    == set(range(len(evidence)))
                    and len(decision.reviewed_evidence_indices) == len(evidence)
                )
                if enough:
                    proposal = ModelVocabularyProposal(
                        **fields.model_dump(),
                        kind=type_item["kind"],
                        proposal_run_id=UUID(str(type_item["proposal_run_id"])),
                        evidence=evidence,
                        independent_review=VocabularyReviewReceipt(
                            reviewer_run_id=attempt_uuid,
                            proposal_run_id=UUID(str(type_item["proposal_run_id"])),
                            proposal_hash=proposal_hash,
                            evidence_hash=evidence_hash,
                            verdict="passed" if review_supported else "failed",
                        ),
                    )
                else:
                    gaps.append(
                        {
                            "reason": "emerging_type_lacks_two_scene_evidence",
                            "clue_index": index,
                        }
                    )
            elif type_context["kind"] in {"tombstone", "ambiguous"}:
                gaps.append(
                    {"reason": f"type_{type_context['kind']}", "clue_index": index}
                )

        if decision is None or index in duplicate_indexes:
            verdict = "uncertain"
            gaps.append(
                {"reason": "independent_review_missing_or_duplicate", "clue_index": index}
            )
        else:
            verdict = decision.verdict
        evidence_hash = vocabulary_evidence_hash(
            [
                VocabularyEvidence(
                    scene_id=scene_id, quote=raw.quote, source_hash=source_hash
                )
            ]
        )
        placeholder = MapSpatialClueReview(
            proposal_call=MapSpatialClueCallRef(journal_key="scene_spatial_discovery"),
            review_call=MapSpatialClueCallRef(journal_key="scene_spatial_review"),
            proposal_hash="0" * 64,
            evidence_hash=evidence_hash,
            verdict=verdict,
        )
        attributes = {
            "transport_label": raw.transport_label,
            "duration": raw.duration.model_dump(mode="json") if raw.duration else None,
            "distance": raw.distance.model_dump(mode="json") if raw.distance else None,
            "access_conditions": raw.access_conditions,
            "change_label": raw.change_label,
        }
        if raw.kind == "effective_change":
            attributes["effective"] = {"start": {"kind": "scene", "id": str(scene_id)}}
        key_base = {
            "scene_id": str(scene_id),
            "source_manifest_hash": frozen.source_manifest_hash,
            "proposal": raw.model_dump(mode="json"),
            "subject": subject,
            "target": target,
        }
        key = content_hash(key_base)
        if key in seen_clue_keys:
            gaps.append({"reason": "duplicate_clue_in_scene", "clue_index": index})
            continue
        seen_clue_keys.add(key)
        clue_data = {
            "clue_key": key,
            "kind": raw.kind,
            "subject": subject,
            "target": target,
            "relation": raw.relation,
            "type_ref": type_ref,
            "type_revision_id": type_revision_id,
            "type_kind": type_kind,
            "type_proposal_draft": draft.model_dump(mode="json") if draft else None,
            "type_proposal": proposal.model_dump(mode="json") if proposal else None,
            "modality": raw.modality,
            "quote": raw.quote,
            "attributes": attributes,
            "review": placeholder,
        }
        clue_without_review = MapSpatialClue.model_validate(clue_data)
        review_body = _review_receipt(
            frozen.payload,
            verdict,
            evidence_hash=evidence_hash,
            proposal_hash=_canonical_digest(
                clue_without_review.model_dump(mode="json", exclude={"review"})
            ),
        )
        clues.append(clue_without_review.model_copy(update={"review": review_body}))

    endpoint_allowlist = [
        {"entity_id": UUID(entity_id), "state": state}
        for entity_id, state in sorted(allowed_endpoints.items())
    ]
    type_allowlist = [
        {"type_ref": item.id, "type_revision_id": item.revision_id, "kind": item.kind}
        for item in context.types
        if item.status == "active"
    ]
    batch = MapSpatialClueBatch(
        run_id=frozen.run_id,
        attempt_id=frozen.attempt_id,
        scene_id=str(scene_id),
        scene_index=int(frozen.payload["scene_index"]),
        source_manifest_hash=frozen.source_manifest_hash,
        source_binding=_source_binding(source, content_mode),
        method_fingerprint=spatial_method_fingerprint(),
        allowed_endpoint_ids=endpoint_allowlist,
        allowed_type_revisions=type_allowlist,
        clues=clues,
    )
    return batch, gaps


class _VocabularyFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    aliases: list[str] = Field(default_factory=list, max_length=24)
    traits: VocabularyTraits = Field(default_factory=VocabularyTraits)


def _endpoint_from_output(endpoint_ref, surface, refs):
    surface = str(surface or "").strip()
    if not surface:
        return None
    if endpoint_ref is None:
        return {"surface": surface}
    match = refs.get(endpoint_ref)
    if not match or _normalized(match["surface"]) != _normalized(surface):
        return None
    return {"entity_id": match["entity_id"], "state": match["state"]}


async def _persist_result(db, store, frozen, result, *, status, gaps, read_set=None):
    await store.require_project_owner(frozen.run_id)
    await store.load_run(frozen.run_id, for_update=True)
    latest = await store.load_frozen(frozen.run_id, frozen.attempt_id)
    payload = dict(latest.payload)
    if gaps:
        coverage = dict(payload.get("optional_step_coverage") or {})
        state = dict(coverage.get("spatial") or {})
        state.update(status=status, gaps=[*state.get("gaps", []), *gaps])
        coverage["spatial"] = state
        payload["optional_step_coverage"] = coverage
    else:
        coverage = dict(payload.get("optional_step_coverage") or {})
        coverage["spatial"] = {**coverage.get("spatial", {}), "status": status}
        payload["optional_step_coverage"] = coverage
    payload["spatial_discovery_result"] = {
        **result,
        "status": status,
        "gaps": gaps,
        **({"consumer_read_set": read_set} if read_set else {}),
    }
    updated = latest.model_copy(update={"payload": payload})
    await store.replace_frozen_payload(updated)
    await db.commit()
    return updated


async def finish_scene_spatial(db, store, frozen, source, caller):
    if frozen.payload.get("spatial_version") != SPATIAL_VERSION:
        return frozen
    if frozen.payload.get("spatial_discovery_result"):
        return frozen
    payload = dict(frozen.payload)
    content_mode = payload.get("source_content_mode")
    if content_mode not in {"working", "canonical"}:
        return await _persist_result(
            db,
            store,
            frozen,
            {},
            status="stale",
            gaps=[{"reason": "source_content_mode_missing"}],
        )
    if not caller:
        return await _persist_result(
            db,
            store,
            frozen,
            {},
            status="not_run",
            gaps=[{"reason": "sampler_unavailable"}],
        )
    from core.container import get
    from core.service_keys import WORLD_READ_SPATIAL_DISCOVERY_CONTEXT

    by_id, surfaces = _current_endpoints(payload)
    try:
        read_context = get(WORLD_READ_SPATIAL_DISCOVERY_CONTEXT)
        context = await read_context(
            db,
            frozen.novel_id,
            run_id=frozen.run_id,
            scene_id=str(payload["scene_id"]),
            scene_index=int(payload["scene_index"]),
            endpoint_ids=sorted(by_id)[:SPATIAL_ENDPOINT_LIMIT],
            endpoint_surfaces=sorted(surfaces)[:SPATIAL_ENDPOINT_LIMIT],
            type_limit=SPATIAL_TYPE_LIMIT,
            clue_limit=SPATIAL_CLUE_LIMIT,
        )
        context = MapSpatialClueContext.model_validate(context)
        current_scene_index = int(payload["scene_index"])
        earlier_clues = [
            item for item in context.clues if item.scene_index < current_scene_index
        ]
        future_clue_count = len(context.clues) - len(earlier_clues)
        if future_clue_count:
            context = context.model_copy(
                update={
                    "clues": earlier_clues,
                    "omitted_clues": context.omitted_clues + future_clue_count,
                }
            )
        (
            endpoint_ids,
            endpoint_surfaces,
            endpoints,
            ref_map,
            allowed,
            surface_types,
            omitted_endpoints,
        ) = _endpoint_inputs(payload, context)
    except asyncio.CancelledError:
        raise
    except KeyError as exc:
        return await _persist_result(
            db,
            store,
            frozen,
            {},
            status="not_run",
            gaps=[
                {"reason": "spatial_context_port_unavailable", "detail": str(exc)[:200]}
            ],
        )
    except Exception as exc:
        return await _persist_result(
            db,
            store,
            frozen,
            {},
            status="stale",
            gaps=[
                {"reason": "spatial_context_stale_or_invalid", "detail": str(exc)[:300]}
            ],
        )
    preparation = {
        "method_fingerprint": spatial_method_fingerprint(),
        "read_scope_run_id": frozen.run_id,
        "context": context.model_dump(mode="json"),
        "endpoint_ids": endpoint_ids,
        "endpoint_surfaces": endpoint_surfaces,
        "endpoints": endpoints,
        "endpoint_ref_map": ref_map,
        "allowed_endpoints": allowed,
        "surface_types": {key: sorted(value) for key, value in surface_types.items()},
        "omitted_endpoints": omitted_endpoints,
        "source_binding": _source_binding(source, content_mode).model_dump(mode="json"),
        "source_content_mode": content_mode,
        "source_manifest_hash": frozen.source_manifest_hash,
        "scene_text": payload["scene_text"],
        "compiled_observations": payload.get("compiled_observations", []),
    }
    read_set = content_hash(preparation)
    await store.require_project_owner(frozen.run_id)
    await store.load_run(frozen.run_id, for_update=True)
    latest = await store.load_frozen(frozen.run_id, frozen.attempt_id)
    if "spatial_preparation" not in latest.payload:
        latest = latest.model_copy(
            update={"payload": {**latest.payload, "spatial_preparation": preparation}}
        )
        await store.replace_frozen_payload(latest)
        await db.commit()
    else:
        preparation = latest.payload["spatial_preparation"]
        context = MapSpatialClueContext.model_validate(preparation["context"])
        ref_map = preparation["endpoint_ref_map"]
        read_set = content_hash(preparation)
    if preparation["method_fingerprint"] != spatial_method_fingerprint():
        raise ValueError("spatial discovery method changed after authorization")
    density = _density_hits(payload["scene_text"], preparation["endpoints"], context)
    if density["count"] < SPATIAL_DENSITY_THRESHOLD:
        return await _persist_result(
            db,
            store,
            latest,
            {"density": density, "method_fingerprint": preparation["method_fingerprint"]},
            status="inspected",
            gaps=[{"reason": "low_spatial_density", "density": density}],
            read_set=read_set,
        )
    discovery_inputs = {
        "scene_id": payload["scene_id"],
        "scene_index": payload["scene_index"],
        "source_manifest_hash": frozen.source_manifest_hash,
        "source_content_mode": content_mode,
        "scene_text": payload["scene_text"],
        "observations": payload.get("compiled_observations", []),
        "endpoints": preparation["endpoints"],
        "types": context.model_dump(mode="json")["types"],
        "clues": context.model_dump(mode="json")["clues"],
        "endpoint_states": context.endpoint_states,
        "omitted_types": context.omitted_types,
        "omitted_clues": context.omitted_clues,
        "omitted_endpoints": preparation["omitted_endpoints"],
        "method_fingerprint": preparation["method_fingerprint"],
    }
    from modules.evolution.optional_step_budget import OptionalStepQuotaExhaustedError
    from modules.evolution.pipeline import (
        SamplePendingReconciliationError,
        _run_scene_call,
    )
    from modules.evolution.state_review import (
        SceneCallFailedError,
        settled_output_failure,
    )

    async def run(key, method, request_inputs):
        nonlocal latest
        latest = await _run_scene_call(
            db,
            store,
            latest,
            source,
            journal_key=key,
            inputs={
                "method": method,
                "method_fingerprint": preparation["method_fingerprint"],
                "source_manifest_hash": frozen.source_manifest_hash,
                "attempt_id": frozen.attempt_id,
                "inputs": request_inputs,
            },
            call_inputs={"inputs": request_inputs},
            call=(lambda **kwargs: caller("discover_spatial", **kwargs))
            if key == "scene_spatial_discovery"
            else (lambda **kwargs: caller("review_spatial", **kwargs)),
            session_gate=getattr(caller, "session_gate", None),
        )
        return latest.payload[key]

    gaps = []
    try:
        generated = await run(
            "scene_spatial_discovery", SPATIAL_METHOD_ID, discovery_inputs
        )
    except OptionalStepQuotaExhaustedError as exc:
        latest = await store.load_frozen(frozen.run_id, frozen.attempt_id)
        return await _persist_result(
            db,
            store,
            latest,
            {"method_fingerprint": preparation["method_fingerprint"]},
            status="not_run",
            gaps=[{"reason": exc.reason, "journal_key": exc.journal_key}],
            read_set=read_set,
        )
    except SamplePendingReconciliationError as exc:
        latest = await store.load_frozen(frozen.run_id, frozen.attempt_id)
        journal = latest.payload.get("scene_spatial_discovery") or {}
        status = "not_run" if settled_output_failure(journal) else "unknown"
        return await _persist_result(
            db,
            store,
            latest,
            {"method_fingerprint": preparation["method_fingerprint"]},
            status=status,
            gaps=[{"reason": "request_requires_reconciliation", "journal_key": str(exc)}],
            read_set=read_set,
        )
    except SceneCallFailedError:
        latest = await store.load_frozen(frozen.run_id, frozen.attempt_id)
        journal = latest.payload.get("scene_spatial_discovery") or {}
        status = "not_run" if settled_output_failure(journal) else "unknown"
        return await _persist_result(
            db,
            store,
            latest,
            {"method_fingerprint": preparation["method_fingerprint"]},
            status=status,
            gaps=[
                {
                    "reason": "spatial_extraction_failed",
                    "journal_key": "scene_spatial_discovery",
                }
            ],
            read_set=read_set,
        )
    try:
        generated_output = SpatialDiscoveryOutput.model_validate(generated["result"])
    except Exception as exc:
        return await _persist_result(
            db,
            store,
            latest,
            {"method_fingerprint": preparation["method_fingerprint"]},
            status="not_run",
            gaps=[{"reason": "spatial_output_invalid", "detail": str(exc)[:300]}],
            read_set=read_set,
        )
    if not generated_output.clues:
        gaps = [
            {"reason": "model_reported_unresolved", "note": note}
            for note in generated_output.unresolved
        ]
        if generated_output.coverage == "partial":
            gaps.append({"reason": "partial_spatial_output"})
        return await _persist_result(
            db,
            store,
            latest,
            {
                "method_fingerprint": preparation["method_fingerprint"],
                "coverage_note": generated_output.coverage_note,
                "coverage": generated_output.coverage,
                "unresolved": generated_output.unresolved,
                "clue_count": 0,
                "density": density,
            },
            status="inspected",
            gaps=gaps,
            read_set=read_set,
        )
    review_inputs = {
        **discovery_inputs,
        "proposal": generated_output.model_dump(mode="json"),
        "type_review_context": [
            _type_review_context(item, context, payload["scene_id"])
            for item in generated_output.clues
        ],
    }
    try:
        reviewed = await run(
            "scene_spatial_review", SPATIAL_REVIEW_METHOD_ID, review_inputs
        )
    except OptionalStepQuotaExhaustedError as exc:
        latest = await store.load_frozen(frozen.run_id, frozen.attempt_id)
        return await _persist_result(
            db,
            store,
            latest,
            {
                "method_fingerprint": preparation["method_fingerprint"],
                "proposal_count": len(generated_output.clues),
            },
            status="inspected",
            gaps=[{"reason": exc.reason, "journal_key": exc.journal_key}],
            read_set=read_set,
        )
    except SamplePendingReconciliationError as exc:
        latest = await store.load_frozen(frozen.run_id, frozen.attempt_id)
        journal = latest.payload.get("scene_spatial_review") or {}
        status = "inspected" if settled_output_failure(journal) else "unknown"
        return await _persist_result(
            db,
            store,
            latest,
            {
                "method_fingerprint": preparation["method_fingerprint"],
                "proposal_count": len(generated_output.clues),
            },
            status=status,
            gaps=[{"reason": "request_requires_reconciliation", "journal_key": str(exc)}],
            read_set=read_set,
        )
    except SceneCallFailedError:
        latest = await store.load_frozen(frozen.run_id, frozen.attempt_id)
        journal = latest.payload.get("scene_spatial_review") or {}
        status = "inspected" if settled_output_failure(journal) else "unknown"
        return await _persist_result(
            db,
            store,
            latest,
            {
                "method_fingerprint": preparation["method_fingerprint"],
                "proposal_count": len(generated_output.clues),
            },
            status=status,
            gaps=[
                {"reason": "spatial_review_failed", "journal_key": "scene_spatial_review"}
            ],
            read_set=read_set,
        )
    try:
        review_output = SpatialReviewOutput.model_validate(reviewed["result"])
    except Exception as exc:
        return await _persist_result(
            db,
            store,
            latest,
            {
                "method_fingerprint": preparation["method_fingerprint"],
                "proposal_count": len(generated_output.clues),
            },
            status="inspected",
            gaps=[{"reason": "spatial_review_output_invalid", "detail": str(exc)[:300]}],
            read_set=read_set,
        )
    try:
        batch, build_gaps = _make_clues(
            frozen=latest,
            source=source,
            content_mode=content_mode,
            context=context,
            discovery=generated_output,
            review=review_output,
            preparation=preparation,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return await _persist_result(
            db,
            store,
            latest,
            {
                "method_fingerprint": preparation["method_fingerprint"],
                "proposal_count": len(generated_output.clues),
            },
            status="inspected",
            gaps=[
                {"reason": "spatial_batch_validation_failed", "detail": str(exc)[:300]}
            ],
            read_set=read_set,
        )
    gaps.extend(build_gaps)
    if generated_output.coverage == "partial":
        gaps.append({"reason": "partial_spatial_output"})
    gaps.extend(
        {"reason": "unresolved_scope", "note": note}
        for note in generated_output.unresolved
    )
    return await _persist_result(
        db,
        store,
        latest,
        {
            "method_fingerprint": preparation["method_fingerprint"],
            "coverage_note": generated_output.coverage_note,
            "coverage": generated_output.coverage,
            "review_coverage_note": review_output.coverage_note,
            "clue_count": len(batch.clues),
            "proposal_count": len(generated_output.clues),
            "density": density,
            "batch": batch.model_dump(mode="json"),
        },
        status="inspected",
        gaps=gaps,
        read_set=read_set,
    )


async def apply_spatial_discovery(db, novel_id: str, frozen):
    """Write candidate clues through World DI only; never writes map heads."""
    result = frozen.payload.get("spatial_discovery_result") or {}
    if result.get("status") in {"unknown", "not_run", "stale"}:
        return None
    batch = result.get("batch")
    if not batch:
        return None
    from core.container import get
    from core.service_keys import WORLD_STAGE_SPATIAL_DISCOVERY

    stage = get(WORLD_STAGE_SPATIAL_DISCOVERY)
    return await stage(db, novel_id, batch)


async def request_spatial_auto_drafts(
    db,
    novel_id: str,
    *,
    run_id: str,
    build_key: str,
    through_scene_id: str,
    through_scene_index: int,
    port,
):
    """Ask World to build one idempotent aggregate candidate batch."""
    from modules.world.contracts import MapAutoDraftBuildRequest, MapAutoDraftBuildResult

    request = MapAutoDraftBuildRequest(
        run_id=run_id,
        build_key=build_key,
        through_scene_id=UUID(str(through_scene_id)),
        through_scene_index=through_scene_index,
        # World queries only eligible, independently reviewed clues in this run.
        clue_ids=None,
    )
    result = await port(db, novel_id, request)
    return MapAutoDraftBuildResult.model_validate(result)


__all__ = [
    "SPATIAL_VERSION",
    "SpatialClueProposal",
    "SpatialClueReviewDecision",
    "SpatialDiscoveryOutput",
    "SpatialReviewOutput",
    "SpatialTypeProposal",
    "apply_spatial_discovery",
    "finish_scene_spatial",
    "request_spatial_auto_drafts",
    "spatial_discovery_messages",
    "spatial_method_fingerprint",
]
