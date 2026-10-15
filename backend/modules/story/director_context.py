"""Frozen, POV-filtered inputs for one scene-director root."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from infrastructure.llm.collaboration import content_hash
from modules.evidence.facade import read_object_dossier_brief
from modules.project.facade import read_author_examples_for_writing
from modules.story.director_state import build_scene_simulation_context
from modules.story.facade import get_scene_story_context
from modules.story.rehearsals import validate_simulation_context_refs
from modules.story.simulation_v3 import SimulationReference, SimulationV3Context

_DOSSIER_GROUP_SIZE = 16
_STYLE_LABELS = {"表达方式", "说话方式", "language style", "speech style"}


def _dump(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    return dump(mode="json") if callable(dump) else {}


def _chunks(items: list[str], size: int = _DOSSIER_GROUP_SIZE) -> Iterable[list[str]]:
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
        merged["world_items"].extend(item.get("world_items") or [])
        merged["continuity_items"].extend(item.get("continuity_items") or [])
        merged["pattern_items"].extend(item.get("pattern_items") or [])
        merged["checkpoint_refs"].extend(item.get("checkpoint_refs") or [])
        merged["world_dossier_fingerprints"].extend(
            item.get("world_dossier_fingerprints") or []
        )
        merged["omitted_count"] += int(item.get("omitted_count") or 0)
        merged["omissions"].extend(item.get("omissions") or [])
        merged["layers"].extend(item.get("layers") or [])
        merged["unknown_layers"].extend(item.get("unknown_layers") or [])
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


def _style_anchors(brief: dict, character_id: str) -> list[dict]:
    result = []
    for item in brief.get("world_items") or []:
        if item.get("entity_id") != character_id:
            continue
        label = str(item.get("facing_label") or "").strip()
        facing = item.get("facing") or {}
        key = str(item.get("field_key") or facing.get("key") or "").strip()
        if label in _STYLE_LABELS or key in _STYLE_LABELS:
            result.append(
                {
                    "label": label or key,
                    "content": item.get("content") or item.get("value"),
                    "source_id": item.get("revision_id") or item.get("entry_id"),
                }
            )
    return result


def _known_participant_ids(
    brief: dict, actor_id: str, participant_ids: set[str]
) -> list[str]:
    known = set()
    for item in brief.get("continuity_items") or []:
        if (
            item.get("entity_id") != actor_id
            or item.get("dimension") != "knowledge"
            or item.get("layer") != "belief"
            or item.get("possibly_false") is True
        ):
            continue
        field = str(item.get("field") or "")
        if not field.startswith("knows:"):
            continue
        subject = field.partition(":")[2]
        if subject in participant_ids:
            known.add(subject)
    return sorted(known)


def _story_card_status(scene_context: dict, actor_id: str, scene_id: str) -> dict:
    """Describe card freshness without promoting free-form card text to POV knowledge."""
    card = next(
        (
            item
            for item in scene_context.get("character_cards", [])
            if str(item.get("character_id") or "") == actor_id
        ),
        None,
    )
    if not card or card.get("stale") or card.get("status") != "active":
        return {"available": False, "omitted": True}
    revision = card.get("revision") or {}
    if (
        str(revision.get("scene_id") or "") != scene_id
        or str(revision.get("character_id") or "") != actor_id
        or revision.get("is_current") is not True
        or revision.get("status") != "active"
    ):
        return {"available": False, "omitted": True}
    revision_id = str(revision.get("id") or "")
    if not revision_id:
        return {"available": False, "omitted": True}
    return {
        "available": True,
        "omitted": True,
        "revision_id": revision_id,
        "content_hash": str(revision.get("content_hash") or ""),
        "reason": (
            "Story 人物卡自由文本缺少逐字段角色知识来源证明，"
            "仅供作者侧 director_only 参考。"
        ),
    }


def _role_source_index(brief: dict) -> dict[str, dict]:
    """Index only IDs actually present in one character's current brief."""
    result: dict[str, dict] = {}
    sections = (
        ("world_items", "world_dossier"),
        ("continuity_items", "continuity"),
        ("pattern_items", "character_pattern"),
    )
    for section, kind in sections:
        for row in brief.get(section) or []:
            fingerprint = content_hash(row)
            for key in ("entry_id", "revision_id", "checkpoint_id"):
                value = row.get(key)
                if value:
                    result[str(value)] = {
                        "kind": kind,
                        "fingerprint": fingerprint,
                        "row": row,
                    }
            for reference in row.get("source_refs") or []:
                for key in ("source_hash", "revision_id", "entry_id", "checkpoint_id"):
                    value = reference.get(key)
                    if value:
                        result[str(value)] = {
                            "kind": kind,
                            "fingerprint": fingerprint,
                            "row": row,
                        }
    return result


async def read_director_source(
    db,
    *,
    novel_id: str,
    scene_id: str,
    character_ids: list[str],
    related_object_ids: list[str],
) -> dict:
    """Read author-only and per-character briefs without mixing their packets."""
    scene_context_value = await get_scene_story_context(
        db,
        novel_id=novel_id,
        scene_id=scene_id,
        character_ids=character_ids,
    )
    if scene_context_value is None:
        raise ValueError("所选场景已不存在或不属于当前作品")
    scene_context = _dump(scene_context_value)
    if (
        scene_context.get("novel_id") != novel_id
        or scene_context.get("scene_id") != scene_id
    ):
        raise ValueError("场景上下文身份与请求不匹配")

    simulation_context = SimulationV3Context(
        participants=[
            SimulationReference(kind="object", id=character_id)
            for character_id in character_ids
        ]
    )
    await validate_simulation_context_refs(db, novel_id, simulation_context)
    if related_object_ids:
        await validate_simulation_context_refs(
            db,
            novel_id,
            SimulationV3Context(
                locations=[
                    SimulationReference(kind="object", id=item)
                    for item in related_object_ids
                ]
            ),
        )
    entity_ids = list(dict.fromkeys([*character_ids, *related_object_ids]))

    author_parts = []
    for chunk in _chunks(entity_ids):
        author_parts.append(
            await read_object_dossier_brief(
                db,
                novel_id=novel_id,
                scene_id=scene_id,
                entity_ids=chunk,
                reveal_mode="author_full",
                content_mode="canonical",
                include_patterns=True,
                only_adopted_patterns=False,
            )
        )
    author_brief = _merge_briefs(author_parts)
    simulation_context = await build_scene_simulation_context(
        db,
        novel_id=novel_id,
        scene_id=scene_id,
        character_ids=character_ids,
        related_object_ids=related_object_ids,
        brief=author_brief,
    )

    role_briefs = {}
    for character_id in character_ids:
        parts = []
        for chunk in _chunks(entity_ids):
            parts.append(
                await read_object_dossier_brief(
                    db,
                    novel_id=novel_id,
                    scene_id=scene_id,
                    entity_ids=chunk,
                    reveal_mode="character",
                    viewpoint_character_id=character_id,
                    content_mode="canonical",
                    include_patterns=True,
                    only_adopted_patterns=False,
                )
            )
        brief = _merge_briefs(parts)
        story_card_status = _story_card_status(scene_context, character_id, scene_id)
        role_briefs[character_id] = {
            "viewpoint": {"kind": "character", "character_id": character_id},
            "brief": brief,
            "style_anchors": _style_anchors(brief, character_id),
            "story_card_status": story_card_status,
            "omissions": [
                {
                    "source": "story_character_card",
                    "reason": story_card_status.get("reason")
                    or "当前角色卡不具备逐字段角色知识来源证明；仅留在 director_only。",
                    "reference_scope_only": True,
                }
            ],
            "source_index": _role_source_index(brief),
            "known_participant_ids": _known_participant_ids(
                brief, character_id, set(character_ids)
            ),
        }

    examples = None
    examples = await read_author_examples_for_writing(db, novel_id)
    source_hash = content_hash(
        {
            "scene_context_hash": scene_context.get("context_hash"),
            "author_brief_fingerprint": author_brief.get("fingerprint"),
            "role_briefs": {
                actor: {
                    "brief": value["brief"].get("fingerprint"),
                    "story_card_status": value.get("story_card_status"),
                }
                for actor, value in sorted(role_briefs.items())
            },
            "author_examples": content_hash(examples) if examples is not None else None,
            "simulation_context": content_hash(
                simulation_context.model_dump(mode="json")
            ),
        }
    )
    return {
        "novel_id": novel_id,
        "scene_id": scene_id,
        "scene_context": scene_context,
        "author_brief": author_brief,
        "role_briefs": role_briefs,
        "author_examples": examples,
        "simulation_context": simulation_context.model_dump(mode="json"),
        "source_hash": source_hash,
    }


def actor_packet(source: dict, actor_id: str, public_stimulus: str) -> str:
    role = source["role_briefs"][actor_id]
    # Hidden author-only constraints and dossier rows never enter this packet.
    return json.dumps(
        {
            "character_view": role["brief"],
            "expression_and_speech_anchors": role["style_anchors"],
            "public_stimulus": public_stimulus,
            "known_participant_ids": role["known_participant_ids"],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def director_only_packet(source: dict, instructions: str, intervention: str) -> str:
    return json.dumps(
        {
            "author_instructions": instructions,
            "author_intervention": intervention,
            "scene_context": source["scene_context"],
            "author_only_dossier": source["author_brief"],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
