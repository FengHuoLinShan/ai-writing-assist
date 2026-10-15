"""Freeze an author-cutoff Story and three-view evidence packet for one root."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from core.container import get
from core.service_keys import WORLD_READ_OBJECT_VALIDITY_NOTICES
from infrastructure.llm.collaboration import content_hash
from modules.evidence.facade import read_object_dossier_brief
from modules.story.director_state import build_scene_simulation_context
from modules.story.facade import get_scene_state_view, get_scene_story_context
from modules.story.outline_state.facade import get_scenes_by_chapter
from modules.story.outline_state.services import (
    OutlineArcService,
    PlotThreadService,
    SceneService,
)
from modules.story.rehearsals import validate_simulation_context_refs
from modules.story.simulation_v3 import (
    SimulationReference,
    SimulationRoute,
)
from modules.story.world_progression_schemas import (
    ProgressionParticipant,
    ProgressionTarget,
)
from modules.writing.facade import get_latest_effective_chapter_index

_ENTITY_GROUP_SIZE = 16


def _dump(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    return dump(mode="json") if callable(dump) else {}


def _chunks(items: list[str], size: int = _ENTITY_GROUP_SIZE) -> Iterable[list[str]]:
    for offset in range(0, len(items), size):
        yield items[offset : offset + size]


def _merge_briefs(items: list[dict]) -> dict:
    merged: dict[str, Any] = {
        "world_items": [],
        "continuity_items": [],
        "pattern_items": [],
        "checkpoint_refs": [],
        "world_dossier_fingerprints": [],
        "omitted_count": 0,
        "omissions": [],
        "layers": [],
        "unknown_layers": [],
        "coverage": "complete",
        "fingerprints": [],
    }
    for item in items:
        for name in (
            "world_items",
            "continuity_items",
            "pattern_items",
            "checkpoint_refs",
            "world_dossier_fingerprints",
            "omissions",
            "layers",
            "unknown_layers",
        ):
            merged[name].extend(item.get(name) or [])
        merged["omitted_count"] += int(item.get("omitted_count") or 0)
        if item.get("coverage") != "complete":
            merged["coverage"] = item.get("coverage") or "unknown"
        merged["fingerprints"].append(item.get("fingerprint"))
    for name in (
        "checkpoint_refs",
        "world_dossier_fingerprints",
        "omissions",
        "layers",
        "unknown_layers",
    ):
        merged[name] = list(
            {json.dumps(value, sort_keys=True): value for value in merged[name]}.values()
        )
    merged["world_items"].sort(
        key=lambda item: (item.get("entity_id", ""), item.get("entry_id", ""))
    )
    merged["continuity_items"].sort(
        key=lambda item: (
            item.get("entity_id", ""),
            item.get("dimension", ""),
            item.get("field", ""),
            item.get("checkpoint_id", ""),
        )
    )
    merged["pattern_items"].sort(key=lambda item: item.get("entry_id", ""))
    merged["fingerprint"] = content_hash(merged["fingerprints"])
    return merged


def _source_ids(brief: dict) -> set[str]:
    result: set[str] = set()
    for section, keys in (
        ("world_items", ("entry_id", "revision_id", "fingerprint")),
        ("continuity_items", ("checkpoint_id", "event_id", "fingerprint")),
        ("pattern_items", ("entry_id", "revision_id", "fingerprint")),
    ):
        for item in brief.get(section) or []:
            for key in keys:
                value = item.get(key)
                if value:
                    result.add(str(value))
    return result


def _validity_notice_packet(notices: list[dict]) -> list[dict]:
    """Keep typed author-only validity evidence without importing notice prose."""
    result = []
    for notice in notices:
        typed_evidence = []
        for evidence in notice.get("evidence") or []:
            row = {"kind": evidence.get("kind")}
            for key in (
                "entry_id",
                "relation_id",
                "node_id",
                "revision_id",
                "declaration_id",
                "declaration_kind",
                "scene_index",
                "event_id",
                "author_confirmed",
                "story_status",
                "validity",
                "identity_ref",
            ):
                if key in evidence:
                    row[key] = evidence[key]
            typed_evidence.append(row)
        result.append(
            {
                "notice_key": notice.get("notice_key"),
                "validity_decision": notice.get("validity_decision", "gap"),
                "target": notice.get("target") or {},
                "basis_fingerprint": notice.get("basis_fingerprint"),
                "evidence": typed_evidence,
            }
        )
    return result


def _life_state_checks(author_state: dict, participants: list[ProgressionParticipant]):
    dimensions = [
        item
        for item in author_state.get("dimensions", [])
        if item.get("dimension") == "entities"
    ]
    dimension = dimensions[0] if dimensions else {}
    facts = dimension.get("facts") or []
    checks = []
    for participant in participants:
        exact = [
            fact
            for fact in facts
            if fact.get("subject_id") == participant.id
            and fact.get("field") == "life_status"
            and fact.get("layer") == "fact"
            and fact.get("confidence") == "confirmed"
            and (fact.get("source") or {}).get("provenance", {}).get("status")
            == "exact"
        ]
        if len(exact) == 1:
            fact = exact[0]
            checks.append(
                {
                    "participant_id": participant.id,
                    "status": "verified_typed_fact",
                    "value": fact.get("value"),
                    "event_id": (fact.get("source") or {}).get("provenance", {}).get(
                        "event_id"
                    ),
                }
            )
        else:
            checks.append(
                {
                    "participant_id": participant.id,
                    "status": "unknown",
                    "reason": (
                        "life_status_missing_or_ambiguous"
                        if dimension.get("status") == "ok"
                        else dimension.get("gap_reason") or "entity_state_unavailable"
                    ),
                }
            )
    return checks


async def _latest_written_scene(db, novel_id: str) -> dict:
    chapter_index = await get_latest_effective_chapter_index(db, novel_id)
    if chapter_index < 1:
        raise ValueError("当前作品还没有可作为截止点的已写章节")
    scenes = await get_scenes_by_chapter(db, novel_id, chapter_index)
    candidates = [item for item in scenes if item.get("status") != "deprecated"]
    if not candidates:
        raise ValueError("最新已写章节尚未关联可用 Scene，请先选择截止 Scene")
    return max(
        candidates,
        key=lambda item: (int(item.get("scene_index") or 0), str(item.get("id"))),
    )


async def _read_targets(
    db, novel_id: str, targets: list[ProgressionTarget]
) -> list[dict]:
    result = []
    for target in targets:
        if target.kind == "outline_arc":
            item = await OutlineArcService().get(db, target.id, novel_id=novel_id)
            if item is None or item.status == "deprecated":
                raise ValueError("目标篇章不存在或已归档")
        elif target.kind == "plot_thread":
            item = await PlotThreadService().get(db, target.id, novel_id=novel_id)
            if item is None or item.status == "deprecated":
                raise ValueError("目标剧情线不存在或已归档")
        else:
            item = await SceneService().get(db, target.id, novel_id=novel_id)
            meta = item.structure_meta or {} if item is not None else {}
            if (
                item is None
                or item.status == "deprecated"
                or meta.get("planning_state") != "planned"
            ):
                raise ValueError("目标 Scene 不存在或不是计划节点")
        result.append(
            {
                "kind": target.kind,
                "id": target.id,
                "must_reach": target.must_reach,
                "asset": _dump(item),
            }
        )
    return result


async def read_progression_source(
    db,
    *,
    novel_id: str,
    scene_id: str | None,
    participants: list[ProgressionParticipant],
    targets: list[ProgressionTarget],
    map_reader=None,
) -> dict:
    """Read only adopted World facts and POV-safe evidence at a real Story cutoff."""
    if scene_id is None:
        latest = await _latest_written_scene(db, novel_id)
        scene_id = str(latest["id"])
    else:
        latest = None

    character_ids = [item.id for item in participants if item.kind == "character"]
    participant_ids = [item.id for item in participants]
    scene_value = await get_scene_story_context(
        db,
        novel_id=novel_id,
        scene_id=scene_id,
        character_ids=character_ids,
    )
    if scene_value is None:
        raise ValueError("截止 Scene 不存在或不属于当前作品")
    scene_context = _dump(scene_value)
    if (
        scene_context.get("novel_id") != novel_id
        or scene_context.get("scene_id") != scene_id
    ):
        raise ValueError("截止 Scene 上下文身份不匹配")

    object_validity_notices = await get(WORLD_READ_OBJECT_VALIDITY_NOTICES)(
        db, novel_id, {"scene_id": scene_id}
    )
    validity_notice_packet = _validity_notice_packet(object_validity_notices)

    author_state = _dump(
        await get_scene_state_view(
            db,
            novel_id,
            scene_id,
            viewpoint={"kind": "author"},
            include_dimensions=["timeline", "entities"],
        )
    )
    timeline_dimensions = [
        item
        for item in author_state.get("dimensions", [])
        if item.get("dimension") == "timeline"
    ]
    timeline_dimension = timeline_dimensions[0] if timeline_dimensions else {}
    time_basis = {
        "cutoff": {
            "scene_id": scene_id,
            "scene_index": author_state.get(
                "scene_index", scene_context.get("scene_index")
            ),
            "chapter_index": author_state.get("chapter_index"),
        },
        "checkpoint_status": timeline_dimension.get("status", "missing"),
        "gap_reason": timeline_dimension.get("gap_reason"),
        "facts": [
            item
            for item in timeline_dimension.get("facts", [])
            if (
                timeline_dimension.get("status") == "ok"
                and item.get("layer") == "fact"
                and item.get("confidence") == "confirmed"
                and (item.get("source") or {}).get("provenance", {}).get("status")
                == "exact"
            )
        ],
        "unsupported_dependencies": author_state.get("unsupported_dependencies", []),
        "source_fingerprint": author_state.get("state_fingerprint"),
    }
    life_state_checks = _life_state_checks(author_state, participants)

    target_assets = await _read_targets(db, novel_id, targets)
    author_parts = []
    for group in _chunks(participant_ids):
        author_parts.append(
            _dump(
                await read_object_dossier_brief(
                    db,
                    novel_id=novel_id,
                    scene_id=scene_id,
                    entity_ids=group,
                    reveal_mode="author_full",
                    content_mode="canonical",
                    include_patterns=True,
                    only_adopted_patterns=True,
                )
            )
        )
    author_brief = _merge_briefs(author_parts)
    world_by_id = {
        str(item.get("entity_id")): item
        for item in author_brief.get("world_items") or []
        if item.get("entity_id")
    }
    for participant in participants:
        item = world_by_id.get(participant.id)
        if item is None or item.get("status") not in {None, "canonical", "adopted"}:
            raise ValueError("参与者身份没有当前已采用的 World 证明")
        entity_type = str(item.get("entity_type") or "")
        allowed = (
            {"character"}
            if participant.kind == "character"
            else {"group", "organization"}
        )
        if entity_type not in allowed:
            if entity_type == "faction":
                raise ValueError("势力参与者等待势力路线图前置阶段")
            raise ValueError("参与者类型与已证明的 World 身份不一致")

    role_briefs: dict[str, dict] = {}
    for participant in participants:
        parts = []
        for group in _chunks(participant_ids):
            result = await read_object_dossier_brief(
                db,
                novel_id=novel_id,
                scene_id=scene_id,
                entity_ids=group,
                reveal_mode="character" if participant.kind == "character" else "reader",
                viewpoint_character_id=participant.id
                if participant.kind == "character"
                else None,
                content_mode="canonical",
                include_patterns=True,
                only_adopted_patterns=True,
            )
            parts.append(_dump(result))
        brief = _merge_briefs(parts)
        visible_ids = {participant.id}
        visible_ids.update(
            str(item.get("entity_id"))
            for item in brief.get("world_items") or []
            if item.get("entity_id")
        )
        visible_ids.update(
            str(item.get("entity_id"))
            for item in brief.get("continuity_items") or []
            if item.get("entity_id")
        )
        role_briefs[participant.id] = {
            "viewpoint": (
                {"kind": "character", "character_id": participant.id}
                if participant.kind == "character"
                else {"kind": "group", "basis": "reader_visible_only"}
            ),
            "brief": brief,
            "known_participant_ids": sorted(set(participant_ids) & visible_ids),
            "known_entity_ids": sorted(visible_ids),
            "source_ids": sorted(_source_ids(brief)),
            "coverage": brief.get("coverage", "unknown"),
        }

    simulation_context = await build_scene_simulation_context(
        db,
        novel_id=novel_id,
        scene_id=scene_id,
        character_ids=character_ids,
        related_object_ids=[],
        brief=author_brief,
    )
    simulation_context = simulation_context.model_copy(
        update={
            "participants": list(
                {
                    item.state_key: item
                    for item in [
                        *simulation_context.participants,
                        *[
                            SimulationReference(kind="object", id=item.id)
                            for item in participants
                            if item.kind == "group"
                        ],
                    ]
                }.values()
            )
        }
    )
    await validate_simulation_context_refs(
        db,
        novel_id,
        simulation_context,
    )
    map_state = {
        "routes": [],
        "actor_routes": {actor_id: [] for actor_id in participant_ids},
        "coverage": "not_compared",
        "unknowns": ["结构化推进地图读取器未接入"],
        "fingerprint": None,
        "revision_fingerprints": [],
    }
    if map_reader is None:
        # Cross-module calls go through the frozen World facade; composition can
        # inject this explicitly in focused tests without creating a second reader.
        from modules.world.facade import read_map_progression_state

        map_reader = read_map_progression_state
    if map_reader is not None:
        value = await map_reader(
            db,
            novel_id=novel_id,
            scene_id=scene_id,
            scene_index=int(scene_context["scene_index"]),
            actor_ids=participant_ids,
        )
        map_state = _dump(value)
        for actor_id, role in role_briefs.items():
            role["journey_routes"] = map_state.get("actor_routes", {}).get(actor_id, [])
            role["known_route_ids"] = sorted(
                str(item.get("route_ref_id"))
                for item in role["journey_routes"]
                if item.get("route_ref_id")
            )
    else:
        for role in role_briefs.values():
            role["journey_routes"] = []
            role["known_route_ids"] = []
    locations = {item.state_key: item for item in simulation_context.locations}
    routes = {
        (item.origin.state_key, item.destination.state_key): item
        for item in simulation_context.routes
    }
    for item in map_state.get("routes") or []:
        origin = SimulationReference(kind=item["origin_kind"], id=str(item["origin_id"]))
        destination = SimulationReference(
            kind=item["destination_kind"], id=str(item["destination_id"])
        )
        locations[origin.state_key] = origin
        locations[destination.state_key] = destination
        routes[(origin.state_key, destination.state_key)] = SimulationRoute(
            origin=origin, destination=destination
        )
    simulation_context = simulation_context.model_copy(
        update={"locations": list(locations.values()), "routes": list(routes.values())}
    )
    await validate_simulation_context_refs(db, novel_id, simulation_context)
    target_hash = content_hash(target_assets)
    source_hash = content_hash(
        {
            "scene_context": scene_context.get("context_hash"),
            "time_basis": time_basis,
            "scene_id": scene_id,
            "author_brief": author_brief.get("fingerprint"),
            "object_validity_notices": validity_notice_packet,
            "life_state_checks": life_state_checks,
            "role_briefs": {
                actor: value["brief"].get("fingerprint")
                for actor, value in sorted(role_briefs.items())
            },
            "targets": target_hash,
            "map_state": map_state.get("fingerprint"),
            "simulation_context": simulation_context.model_dump(mode="json"),
        }
    )
    return {
        "novel_id": novel_id,
        "scene_id": scene_id,
        "scene_index": scene_context.get("scene_index"),
        "latest_written_scene": latest,
        "scene_context": scene_context,
        "time_basis": time_basis,
        "life_state_checks": life_state_checks,
        "object_validity_notices": validity_notice_packet,
        "validity_notice_limit_reached": len(object_validity_notices) >= 100,
        "author_brief": author_brief,
        "author_source_ids": sorted(_source_ids(author_brief)),
        "role_briefs": role_briefs,
        "simulation_context": simulation_context.model_dump(mode="json"),
        "targets": target_assets,
        "target_hash": target_hash,
        "map_state": map_state,
        "context_groups": {
            "entity_group_size": _ENTITY_GROUP_SIZE,
            "group_count": (len(participant_ids) + _ENTITY_GROUP_SIZE - 1)
            // _ENTITY_GROUP_SIZE,
            "participant_count": len(participant_ids),
        },
        "coverage": {
            "author": author_brief.get("coverage", "unknown"),
            "characters": {
                actor: value["coverage"] for actor, value in role_briefs.items()
            },
            "group_packets": "reader_visible_only",
            "map_routes": map_state.get("coverage", "not_compared"),
            "object_validity": (
                "limit_reached"
                if len(object_validity_notices) >= 100
                else "complete"
            ),
        },
        "source_hash": source_hash,
    }
