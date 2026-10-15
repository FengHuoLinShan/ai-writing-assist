"""Unified read-only notices for author/Story validity conflicts and gaps."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import or_, select

from core.container import get
from core.service_keys import STORY_SCENE_SOURCE
from infrastructure.stable_hash import stable_hash
from modules.project.facade import read_object_dossier_settings
from modules.world.map_atlas_models import MapAtlasNode, MapAtlasRevision
from modules.world.map_spatial_anchors import resolve_anchor, resolve_validity
from modules.world.map_structure_schemas import MapDocument
from modules.world.models import CoreEntity, EntityRelation, WorldObjectDossierEntry
from modules.world.schemas.dossier import DossierAnchor, DossierValidity
from modules.world.validity_policy import (
    exact_story_field_observation,
    exact_story_relation_observation,
    resolve_map_declaration_validity,
)
from shared.utils import parse_uuid

SOURCE_ID = "world.object_validity"
NOTICE_LIMIT = 100


def _anchor_interval(row: WorldObjectDossierEntry) -> DossierValidity | None:
    if not any(
        (
            row.start_anchor_kind,
            row.start_anchor_id,
            row.end_anchor_kind,
            row.end_anchor_id,
        )
    ):
        return None
    return DossierValidity(
        start=(
            DossierAnchor(kind=row.start_anchor_kind, id=row.start_anchor_id)
            if row.start_anchor_kind and row.start_anchor_id
            else None
        ),
        end=(
            DossierAnchor(kind=row.end_anchor_kind, id=row.end_anchor_id)
            if row.end_anchor_kind and row.end_anchor_id
            else None
        ),
    )


def _author_active(interval, scenes: list[dict[str, Any]], cutoff: int):
    result = resolve_validity(interval, scenes)
    if not result.valid:
        return None, result.reason or "author_interval_anchor_invalid"
    return bool(
        (result.start_scene_index is None or result.start_scene_index <= cutoff)
        and (result.end_scene_index is None or cutoff <= result.end_scene_index)
    ), None


def _notice(
    *,
    key: str,
    category: str,
    target: dict[str, Any],
    summary: str,
    status: str,
    gap: str | None,
    basis: dict[str, Any],
    evidence: list[dict[str, Any]],
    page: str,
) -> dict[str, Any]:
    return {
        "notice_key": key,
        "source_id": SOURCE_ID,
        "category": category,
        "severity": "medium"
        if status in {"author_priority", "story_override"}
        else "low",
        "target": target,
        "summary": summary,
        "evidence": evidence,
        "basis_fingerprint": stable_hash(basis),
        "stale": False,
        "actions": [
            {"kind": "navigate", "page": page, "label": "核对有效期"},
            {"op_id": "assistant.notice.set_disposition", "label": "处理提醒"},
        ],
        "disposition_ref": {},
        "status": "unread",
    }


async def list_object_validity_notices(
    db, novel_id: str, scope: dict[str, object]
) -> list[dict[str, Any]]:
    novel_uuid = parse_uuid(novel_id, "novel_id")
    scene_id = str(scope.get("scene_id") or "")
    if not scene_id:
        return []
    scene_port = get(STORY_SCENE_SOURCE)
    temporal_scenes = await scene_port.read_temporal_anchor_scenes(db, novel_id)
    cutoff, anchor_error = resolve_anchor(
        DossierAnchor(kind="scene", id=scene_id), temporal_scenes, endpoint="start"
    )
    if anchor_error or cutoff is None:
        return []
    scene = await scene_port.get_scene_contract(db, novel_id, scene_id)
    scene_index = getattr(scene, "scene_index", None) if scene is not None else None
    if isinstance(scene_index, bool) or not isinstance(scene_index, int):
        return []
    try:
        setting = await read_object_dossier_settings(db, novel_id)
        allow_override = setting["allow_story_override"] is True
        policy_version = setting["version"]
        policy_gap = None
    except (TypeError, ValueError):
        allow_override = False
        policy_version = None
        policy_gap = "project_override_setting_unavailable"
    story_view = await scene_port.get_scene_state_view(
        db,
        novel_id,
        scene_id,
        viewpoint={"kind": "author"},
        include_dimensions=["entities", "relations"],
    )
    notices: list[dict[str, Any]] = []

    entry_rows = (
        await db.execute(
            select(WorldObjectDossierEntry, CoreEntity.entity_type)
            .join(
                CoreEntity,
                (CoreEntity.id == WorldObjectDossierEntry.entity_id)
                & (CoreEntity.novel_id == WorldObjectDossierEntry.novel_id),
            )
            .where(
                WorldObjectDossierEntry.novel_id == novel_uuid,
                WorldObjectDossierEntry.status == "active",
                CoreEntity.status == "canonical",
                or_(
                    WorldObjectDossierEntry.start_anchor_kind.is_not(None),
                    WorldObjectDossierEntry.end_anchor_kind.is_not(None),
                ),
            )
            .order_by(WorldObjectDossierEntry.created_at, WorldObjectDossierEntry.id)
            .limit(NOTICE_LIMIT + 1)
        )
    ).all()
    for row, entity_type in entry_rows[:NOTICE_LIMIT]:
        if len(notices) >= NOTICE_LIMIT:
            break
        interval = _anchor_interval(row)
        if interval is None:
            continue
        author_active, anchor_gap = _author_active(interval, temporal_scenes, cutoff)
        if anchor_gap is None and author_active is False:
            continue
        observation = (
            exact_story_field_observation(
                story_view,
                entity_id=str(row.entity_id),
                entity_type=str(entity_type),
                field_key=str(row.story_field_key),
                cutoff_scene_index=scene_index,
            )
            if row.story_field_key
            else None
        )
        status = "gap"
        gap = (
            anchor_gap or policy_gap or observation.gap
            if observation is not None
            else anchor_gap or policy_gap or "story_field_alignment_not_declared"
        )
        if (
            gap is None
            and author_active is True
            and observation is not None
            and observation.value != row.content
        ):
            status = "story_override" if allow_override else "author_priority"
        elif gap is None:
            continue
        evidence = [
            {
                "kind": "world_dossier",
                "entry_id": str(row.id),
                "validity": interval.model_dump(mode="json"),
                "source_refs": row.source_refs_json or [],
            }
        ]
        if observation and (observation.source_refs or observation.author_confirmed):
            evidence.append(
                {
                    "kind": "story_field",
                    "event_id": observation.event_id,
                    "scene_index": observation.scene_index,
                    "source_refs": observation.source_refs,
                    "author_confirmed": observation.author_confirmed,
                }
            )
        summary = (
            "同一对象与结构化 Story 状态字段出现可信剧情变化"
            if status in {"author_priority", "story_override"}
            else "作者档案有效期或精确 Story 字段对应暂不可核实"
        )
        notices.append(
            _notice(
                key=f"{SOURCE_ID}:dossier:{row.entry_group_id}",
                category="author_validity",
                target={
                    "scene_id": scene_id,
                    "entity_id": str(row.entity_id),
                    "entry_id": str(row.id),
                    "story_field_key": row.story_field_key,
                },
                summary=summary,
                status=status,
                gap=gap,
                basis={
                    "entry_id": str(row.id),
                    "revision_number": row.revision_number,
                    "validity": interval.model_dump(mode="json"),
                    "story_field_key": row.story_field_key,
                    "story_observation": observation.value if observation else None,
                    "story_event_id": observation.event_id if observation else None,
                    "story_source_refs": observation.source_refs if observation else None,
                    "allow_override": allow_override,
                    "policy_version": policy_version,
                    "gap": gap,
                },
                evidence=evidence,
                page="world",
            )
        )

    relation_rows = (
        await db.scalars(
            select(EntityRelation)
            .where(
                EntityRelation.novel_id == novel_uuid,
                EntityRelation.status == "canonical",
                EntityRelation.validity_json.is_not(None),
            )
            .order_by(EntityRelation.created_at, EntityRelation.id)
            .limit(NOTICE_LIMIT + 1)
        )
    ).all()
    for relation in relation_rows[:NOTICE_LIMIT]:
        if len(notices) >= NOTICE_LIMIT:
            break
        try:
            interval = DossierValidity.model_validate(relation.validity_json)
        except PydanticValidationError:
            interval = None
        if interval is None:
            continue
        author_active, anchor_gap = _author_active(interval, temporal_scenes, cutoff)
        observation = exact_story_relation_observation(
            story_view,
            relation_id=str(relation.id),
            cutoff_scene_index=scene_index,
        )
        status = "gap"
        gap = anchor_gap or policy_gap or observation.gap
        if (
            gap is None
            and author_active is not None
            and (observation.status == "active") != author_active
        ):
            status = "story_override" if allow_override else "author_priority"
        elif gap is None:
            continue
        evidence = [
            {
                "kind": "world_relation",
                "relation_id": str(relation.id),
                "validity": interval.model_dump(mode="json"),
            }
        ]
        if observation.source_refs:
            evidence.append(
                {
                    "kind": "story_relation",
                    "event_id": observation.event_id,
                    "scene_index": observation.scene_index,
                    "source_refs": observation.source_refs,
                }
            )
        notices.append(
            _notice(
                key=f"{SOURCE_ID}:relation:{relation.id}",
                category="author_validity",
                target={"scene_id": scene_id, "relation_id": str(relation.id)},
                summary=(
                    "同一稳定关系声明的 Story 观察和作者有效期冲突"
                    if status in {"author_priority", "story_override"}
                    else "关系有效期或对应 Story 来源暂不可核实"
                ),
                status=status,
                gap=gap,
                basis={
                    "relation_id": str(relation.id),
                    "source_id": str(relation.source_id),
                    "target_id": str(relation.target_id),
                    "relation_type": relation.relation_type,
                    "validity": interval.model_dump(mode="json"),
                    "story_status": observation.status,
                    "story_event_id": observation.event_id,
                    "story_source_refs": observation.source_refs,
                    "allow_override": allow_override,
                    "policy_version": policy_version,
                    "gap": gap,
                },
                evidence=evidence,
                page="world",
            )
        )

    map_rows = (
        await db.execute(
            select(MapAtlasNode, MapAtlasRevision)
            .join(
                MapAtlasRevision,
                (MapAtlasRevision.id == MapAtlasNode.current_revision_id)
                & (MapAtlasRevision.node_id == MapAtlasNode.id)
                & (MapAtlasRevision.novel_id == MapAtlasNode.novel_id),
            )
            .where(
                MapAtlasNode.novel_id == novel_uuid,
                MapAtlasNode.status == "adopted",
                MapAtlasNode.merged_into_node_id.is_(None),
                MapAtlasRevision.status == "saved",
            )
            .order_by(MapAtlasNode.updated_at.desc(), MapAtlasNode.id)
            .limit(100)
        )
    ).all()
    for node, revision in map_rows:
        if len(notices) >= NOTICE_LIMIT:
            break
        try:
            document = MapDocument.model_validate(revision.document)
        except PydanticValidationError:
            continue
        for kind, items in (
            ("feature", document.features),
            ("constraint", document.constraints),
            ("journey", document.journeys),
        ):
            if len(notices) >= NOTICE_LIMIT:
                break
            for item in items:
                if len(notices) >= NOTICE_LIMIT:
                    break
                if item.effective is None:
                    continue
                author_active, anchor_gap = _author_active(
                    item.effective, temporal_scenes, cutoff
                )
                decision = resolve_map_declaration_validity(
                    author_active=author_active,
                    anchor_gap=anchor_gap,
                    story_view=story_view,
                    novel_id=novel_id,
                    cutoff_scene_id=scene_id,
                    node_id=str(node.id),
                    revision_id=str(revision.id),
                    declaration_kind=kind,
                    declaration_id=str(item.id),
                    cutoff_scene_index=scene_index,
                    allow_story_override=allow_override,
                    policy_gap=policy_gap,
                )
                if decision.status == "consistent":
                    continue
                status = decision.status or "gap"
                gap = decision.gap
                observation = decision.observation
                evidence = [
                    {
                        "kind": "world_map_declaration",
                        "node_id": str(node.id),
                        "revision_id": str(revision.id),
                        "declaration_id": str(item.id),
                        "declaration_kind": kind,
                        "validity": item.effective.model_dump(mode="json"),
                    }
                ]
                if observation is not None and observation.gap is None:
                    evidence.append(
                        {
                            "kind": "story_map_declaration",
                            "event_id": observation.event_id,
                            "scene_index": observation.scene_index,
                            "source_refs": observation.source_refs or [],
                            "author_confirmed": observation.author_confirmed,
                            "identity_ref": observation.identity_ref,
                        }
                    )
                notices.append(
                    _notice(
                        key=f"{SOURCE_ID}:map:{node.id}:{kind}:{item.id}",
                        category="author_validity",
                        target={
                            "scene_id": scene_id,
                            "node_id": str(node.id),
                            "map_item_id": str(item.id),
                            "map_item_kind": kind,
                            "revision_id": str(revision.id),
                        },
                        summary=(
                            "同一地图声明的 Story 状态与作者有效期冲突"
                            if status in {"author_priority", "story_override"}
                            else "地图结构有效期或 Story 对应来源暂不可核实"
                        ),
                        status=status,
                        gap=gap,
                        basis={
                            "node_id": str(node.id),
                            "revision_id": str(revision.id),
                            "map_item_id": str(item.id),
                            "map_item_kind": kind,
                            "validity": item.effective.model_dump(mode="json"),
                            "story_status": observation.status if observation else None,
                            "story_event_id": observation.event_id
                            if observation
                            else None,
                            "story_identity_ref_hash": (
                                stable_hash(observation.identity_ref)
                                if observation and observation.identity_ref
                                else None
                            ),
                            "story_source_refs": (
                                observation.source_refs if observation else None
                            ),
                            "author_active": decision.author_active,
                            "allow_override": allow_override,
                            "policy_version": policy_version,
                            "gap": gap,
                        },
                        evidence=evidence,
                        page="map",
                    )
                )
    return notices[:NOTICE_LIMIT]


NOTICE_SOURCE_SPEC = {
    "source_id": SOURCE_ID,
    "label": "作者有效期核对",
    "list_notices": list_object_validity_notices,
    "timeout_seconds": 2.0,
}
