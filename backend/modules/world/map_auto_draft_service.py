"""Deterministic, author-reviewed map drafts built from persisted spatial clues."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError, ValidationError
from modules.project.facade import (
    require_active_project,
    require_active_project_exclusive,
)
from modules.world.map_atlas_models import MapAtlasNode, MapAtlasRevision
from modules.world.map_atlas_service import MapAtlasService
from modules.world.map_auto_draft_models import MapAutoDraftBatchRecord
from modules.world.map_auto_draft_schemas import (
    MapAutoDraftBatchProgress,
    MapAutoDraftBuildRequest,
    MapAutoDraftBuildResult,
    MapAutoDraftHierarchyAlternative,
    MapAutoDraftHierarchyConflict,
    MapAutoDraftListItem,
    MapAutoDraftListResponse,
    MapAutoDraftRedoRequest,
    MapAutoDraftResumeRequest,
    MapAutoDraftRevisionRef,
    MapAutoDraftTrayItem,
    MapAutoDraftTrayPlacementPreview,
    MapAutoDraftTrayPlacementPreviewRequest,
    MapAutoDraftTrayPlacementRequest,
    MapAutoDraftTrayPlacementResponse,
)
from modules.world.map_spatial_clue_models import MapSpatialClueRecord
from modules.world.map_spatial_clue_schemas import (
    MapSpatialClue,
    MapSpatialClueEndpoint,
    MapSpatialClueSourceBinding,
)
from modules.world.map_spatial_clue_service import (
    _matching_source_hash,
    _resolve_binding,
    _revalidate_stored_clue,
    _scene_contract,
)
from modules.world.map_structure_geometry import diagnose, geometry_hash, layout
from modules.world.map_structure_schemas import (
    STRUCTURE_LEVELS,
    MapDocument,
    MapFeature,
    MapProblem,
    MapSource,
    SpatialConstraint,
    SpatialJourney,
)
from modules.world.models import CoreEntity, EntityRelation
from modules.writing.facade import build_manuscript_range_ref, read_manuscript_range
from shared.utils import parse_uuid

AUTO_DRAFT_FEATURE_LIMIT = 200
AUTO_DRAFT_CHUNKS_PER_CALL = 20
AUTO_DRAFT_METHOD_VERSION = "map-auto-draft.v1"
_AUTO_DRAFT_CONTEXT_PREFIX = "auto-draft:"
_SPATIAL_RELATIONS = {
    "north",
    "south",
    "east",
    "west",
    "northeast",
    "northwest",
    "southeast",
    "southwest",
    "adjacent",
    "connects",
    "passes_through",
    "along_street",
    "entrance_to",
    "faces",
    "inside",
}
_PARENT_SOURCE_PRIORITY = {
    "world_adopted": 4,
    "saved_map": 3,
    "reviewed_clue": 2,
    "world_candidate": 1,
}


def _digest(value: Any) -> str:
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _method_fingerprint() -> str:
    return _digest(
        {
            "version": AUTO_DRAFT_METHOD_VERSION,
            "layout_version": 1,
            "feature_limit": AUTO_DRAFT_FEATURE_LIMIT,
            "kernel": "map_structure_geometry.layout.v1",
        }
    )


def _feature_id(entity_id: uuid.UUID) -> str:
    return f"e_{entity_id.hex}"


def _constraint_id(clue_id: uuid.UUID) -> str:
    return f"clue_{clue_id.hex}"


def _tray_item_id(batch_id: uuid.UUID, clue_id: uuid.UUID, side: str) -> uuid.UUID:
    return uuid.uuid5(batch_id, f"{clue_id}:{side}")


def _batch_marker(batch_id: uuid.UUID, shard_index: int) -> str:
    return f"{_AUTO_DRAFT_CONTEXT_PREFIX}{batch_id}:{shard_index}"


def _marker_batch_id(value: str | None) -> uuid.UUID | None:
    if not value or not value.startswith(_AUTO_DRAFT_CONTEXT_PREFIX):
        return None
    try:
        return uuid.UUID(value[len(_AUTO_DRAFT_CONTEXT_PREFIX) :].split(":", 1)[0])
    except (ValueError, TypeError):
        return None


def auto_draft_review_base(revision: MapAtlasRevision) -> uuid.UUID | None:
    """The saved head used for review CAS is separate from candidate lineage."""
    summary = revision.change_summary or {}
    if "auto_draft_review_base_revision_id" not in summary:
        raise ConflictError("自动草图缺少正式比较基线，请重新生成")
    value = summary["auto_draft_review_base_revision_id"]
    return parse_uuid(value, "review_base_revision_id") if value else None


def _response(batch: MapAutoDraftBatchRecord) -> MapAutoDraftBuildResult:
    return MapAutoDraftBuildResult(
        batch_id=batch.id,
        fingerprint=batch.input_fingerprint,
        status=batch.status,
        cursor=batch.cursor,
        total_chunks=len((batch.plan_json or {}).get("shards", [])),
        completed_chunks=batch.cursor,
        revisions=[
            MapAutoDraftRevisionRef.model_validate(item)
            for item in (batch.result_refs or [])
        ],
        tray_items=[
            MapAutoDraftTrayItem.model_validate(item) for item in (batch.tray_items or [])
        ],
        conflicts=[
            MapAutoDraftHierarchyConflict.model_validate(item)
            for item in (batch.conflicts or [])
        ],
        diagnostics=[batch.stale_reason] if batch.stale_reason else [],
    )


def _jsonable_endpoint(endpoint: MapSpatialClueEndpoint) -> dict:
    return endpoint.model_dump(mode="json")


def _map_source_key(source: MapSource) -> str:
    return source.model_dump_json(exclude_none=True)


async def _load_build_rows(
    db: AsyncSession, novel_id: str, request: MapAutoDraftBuildRequest
) -> list[MapSpatialClueRecord]:
    if request.clue_ids is None:
        rows = (
            await db.scalars(
                select(MapSpatialClueRecord)
                .where(
                    MapSpatialClueRecord.novel_id == parse_uuid(novel_id, "novel_id"),
                    MapSpatialClueRecord.run_id == request.run_id,
                    MapSpatialClueRecord.scene_index <= request.through_scene_index,
                )
                .order_by(
                    MapSpatialClueRecord.scene_index,
                    MapSpatialClueRecord.id,
                )
            )
        ).all()
        return list(rows)

    if len(set(request.clue_ids)) != len(request.clue_ids):
        raise ValidationError("空间线索引用不能重复")
    requested = set(request.clue_ids)
    rows = (
        await db.scalars(
            select(MapSpatialClueRecord)
            .where(
                MapSpatialClueRecord.novel_id == parse_uuid(novel_id, "novel_id"),
                MapSpatialClueRecord.id.in_(requested),
            )
            .order_by(MapSpatialClueRecord.scene_index, MapSpatialClueRecord.id)
        )
    ).all()
    if {row.id for row in rows} != requested:
        raise NotFoundError("部分空间线索不存在或不属于当前作品")
    if any(
        row.run_id != request.run_id or row.scene_index > request.through_scene_index
        for row in rows
    ):
        raise ValidationError("空间线索超出当前运行或截止 Scene")
    return list(rows)


async def _unique_canonical_source(
    db: AsyncSession,
    novel_id: str,
    row: MapSpatialClueRecord,
    clue: MapSpatialClue,
    resolved_sources: list[dict],
) -> tuple[MapSource | None, str | None]:
    if row.source_content_mode != "canonical":
        return None, "working_source"
    matches: list[tuple[dict, int]] = []
    for source in resolved_sources:
        text = source["text"]
        start = 0
        while (position := text.find(clue.quote, start)) >= 0:
            matches.append((source, position))
            start = position + 1
    if len(matches) != 1:
        return None, "ambiguous_source_quote"
    source, position = matches[0]
    parent_ref = source["source_ref"]
    start_offset = parent_ref.start_offset + position
    end_offset = start_offset + len(clue.quote)
    ref = await build_manuscript_range_ref(
        db,
        novel_id,
        draft_id=str(parent_ref.draft_id),
        start_offset=start_offset,
        end_offset=end_offset,
        content_mode="canonical",
    )
    if ref.source_hash != parent_ref.source_hash:
        raise ValidationError("空间线索原文来源已变化")
    read = await read_manuscript_range(db, novel_id, ref, before=0, after=0)
    quote = read.text[read.highlight_start : read.highlight_end]
    if (
        quote != clue.quote
        or ref.range_hash != hashlib.sha256(quote.encode()).hexdigest()
    ):
        raise ValidationError("空间线索引文范围无法精确定位")
    return (
        MapSource(
            kind="source_range",
            id=ref.draft_id,
            source_hash=ref.source_hash,
            quote=clue.quote,
            source_ref=asdict(ref),
        ),
        None,
    )


async def _validated_clue_inputs(
    db: AsyncSession,
    novel_id: str,
    rows: list[MapSpatialClueRecord],
    *,
    through_scene_index: int,
    run_id: str | None = None,
) -> tuple[list[dict], list[dict]]:
    valid: list[dict] = []
    invalid: list[dict] = []
    for row in rows:
        try:
            clue = MapSpatialClue.model_validate(row.clue_payload)
            if row.status == "pending_verification":
                # A clue awaiting independent verification has no map effect.
                # Keep it in the spatial review queue; do not project it into a
                # map tray or let it influence deterministic layout.
                continue
            if row.scene_index > through_scene_index:
                raise ValidationError("空间线索超出本次草图的截止 Scene")
            if run_id is not None and row.run_id != run_id:
                raise ValidationError("空间线索不属于本次阅读运行")
            if row.status not in {"pending_review", "adopted"}:
                raise ValidationError("空间线索不再处于可审状态")
            binding = MapSpatialClueSourceBinding.model_validate(row.source_binding)
            if row.source_content_mode != binding.content_mode:
                raise ValidationError("空间线索来源模式已经变化")
            endpoints = await _revalidate_stored_clue(
                db,
                novel_id,
                row,
                clue,
                allow_identity_transitions=True,
            )
            resolved_sources = await _resolve_binding(
                db, novel_id, row.scene_id, row.scene_index, binding
            )
            _matching_source_hash(clue, resolved_sources)
            source, source_issue = await _unique_canonical_source(
                db, novel_id, row, clue, resolved_sources
            )
            valid.append(
                {
                    "row": row,
                    "clue": clue,
                    "binding": binding,
                    "endpoints": endpoints,
                    "resolved_sources": resolved_sources,
                    "source": source,
                    "source_issue": source_issue,
                }
            )
        except (
            ConflictError,
            NotFoundError,
            ValidationError,
            ValueError,
            TypeError,
        ) as exc:
            try:
                clue = MapSpatialClue.model_validate(row.clue_payload)
            except (ValidationError, ValueError, TypeError):
                invalid.append({"row": row, "clue": None, "reason": "source_stale"})
            else:
                invalid.append(
                    {
                        "row": row,
                        "clue": clue,
                        "reason": "source_stale",
                        "detail": str(exc)[:300],
                    }
                )
    return valid, invalid


def _endpoint_entity_id(
    endpoint: MapSpatialClueEndpoint, resolved: dict
) -> uuid.UUID | None:
    if endpoint.entity_id is None:
        return None
    entity = resolved.get(str(endpoint.entity_id))
    return entity.id if entity is not None else None


async def _hierarchy_edges(
    db: AsyncSession,
    novel_id: str,
    entity_ids: set[uuid.UUID],
    clue_inputs: list[dict],
) -> tuple[dict[uuid.UUID, dict], list[MapAutoDraftHierarchyConflict]]:
    edges: dict[uuid.UUID, list[dict]] = {}
    if entity_ids:
        relation_rows = (
            await db.scalars(
                select(EntityRelation).where(
                    EntityRelation.novel_id == parse_uuid(novel_id, "novel_id"),
                    EntityRelation.relation_kind == "spatial",
                    EntityRelation.status.in_(["canonical", "candidate"]),
                    EntityRelation.relation_type.in_(["located_at", "contains"]),
                    or_(
                        EntityRelation.source_id.in_(entity_ids),
                        EntityRelation.target_id.in_(entity_ids),
                    ),
                )
            )
        ).all()
        for relation in relation_rows:
            if relation.relation_type == "located_at":
                child_id, parent_id = relation.source_id, relation.target_id
            else:
                parent_id, child_id = relation.source_id, relation.target_id
            if child_id == parent_id:
                continue
            source = (
                "world_adopted" if relation.status == "canonical" else "world_candidate"
            )
            edges.setdefault(child_id, []).append(
                {"parent_id": parent_id, "source": source, "source_id": str(relation.id)}
            )

    saved_nodes = (
        await db.scalars(
            select(MapAtlasNode).where(
                MapAtlasNode.novel_id == parse_uuid(novel_id, "novel_id"),
                MapAtlasNode.status == "adopted",
                MapAtlasNode.location_entity_id.is_not(None),
            )
        )
    ).all()
    saved_by_id = {node.id: node for node in saved_nodes}
    for node in saved_nodes:
        parent = saved_by_id.get(node.parent_id)
        if (
            node.location_entity_id in entity_ids
            and parent is not None
            and parent.location_entity_id is not None
        ):
            edges.setdefault(node.location_entity_id, []).append(
                {
                    "parent_id": parent.location_entity_id,
                    "source": "saved_map",
                    "source_id": str(node.id),
                }
            )

    for item in clue_inputs:
        clue = item["clue"]
        if clue.kind != "contains" or clue.target is None:
            continue
        parent_id = _endpoint_entity_id(clue.subject, item["endpoints"])
        child_id = _endpoint_entity_id(clue.target, item["endpoints"])
        if parent_id is None or child_id is None or parent_id == child_id:
            continue
        edges.setdefault(child_id, []).append(
            {
                "parent_id": parent_id,
                "source": "reviewed_clue",
                "source_id": str(item["row"].id),
            }
        )

    chosen: dict[uuid.UUID, dict] = {}
    conflicts: list[MapAutoDraftHierarchyConflict] = []
    for child_id, candidates in edges.items():
        candidates.sort(
            key=lambda item: (str(item["parent_id"]), item["source"], item["source_id"])
        )
        highest = max(_PARENT_SOURCE_PRIORITY[item["source"]] for item in candidates)
        top = sorted(
            (
                item
                for item in candidates
                if _PARENT_SOURCE_PRIORITY[item["source"]] == highest
            ),
            key=lambda item: (str(item["parent_id"]), item["source_id"]),
        )
        winner = top[0]
        chosen[child_id] = winner
        alternatives = [
            MapAutoDraftHierarchyAlternative(
                parent_entity_id=item["parent_id"],
                source=item["source"],
                source_id=item["source_id"],
            )
            for item in sorted(
                candidates,
                key=lambda item: (
                    -_PARENT_SOURCE_PRIORITY[item["source"]],
                    str(item["parent_id"]),
                    item["source_id"],
                ),
            )
            if item != winner
        ]
        parent_ids = {item["parent_id"] for item in top}
        if len(parent_ids) > 1 or any(
            item["parent_id"] != winner["parent_id"] for item in candidates
        ):
            conflicts.append(
                MapAutoDraftHierarchyConflict(
                    child_entity_id=child_id,
                    chosen_parent_entity_id=winner["parent_id"],
                    chosen_source=winner["source"],
                    alternatives=alternatives,
                    fingerprint=_digest(
                        {
                            "child": str(child_id),
                            "winner": winner,
                            "candidates": candidates,
                        }
                    ),
                )
            )

    # A cycle is never turned into a map parent chain.
    for start in list(chosen):
        path: list[uuid.UUID] = []
        current = start
        while current in chosen:
            if current in path:
                cycle = path[path.index(current) :]
                for child_id in cycle:
                    chosen.pop(child_id, None)
                break
            path.append(current)
            current = chosen[current]["parent_id"]
    return chosen, conflicts


def _level_for_depth(depth: int) -> str:
    return ("region", "city", "district", "street", "interior")[min(depth, 4)]


async def _entity_rows(
    db: AsyncSession, novel_id: str, ids: set[uuid.UUID]
) -> dict[uuid.UUID, CoreEntity]:
    if not ids:
        return {}
    rows = (
        await db.scalars(
            select(CoreEntity).where(
                CoreEntity.novel_id == parse_uuid(novel_id, "novel_id"),
                CoreEntity.id.in_(ids),
            )
        )
    ).all()
    return {row.id: row for row in rows}


async def _build_dependency_fingerprint(db, novel_id: str, inputs: list[dict]) -> str:
    """Freeze identity and hierarchy inputs across committed shard calls."""
    entities = {
        entity.id: entity for item in inputs for entity in item["endpoints"].values()
    }
    parents, conflicts = await _hierarchy_edges(db, novel_id, set(entities), inputs)
    parent_entities = await _entity_rows(
        db, novel_id, {edge["parent_id"] for edge in parents.values()}
    )
    entities.update(parent_entities)
    return _digest(
        {
            "clues": sorted(
                (str(item["row"].id), item["row"].fingerprint) for item in inputs
            ),
            "entities": sorted(
                (str(entity.id), entity.entity_type, entity.status)
                for entity in entities.values()
            ),
            "parents": {str(child): edge for child, edge in parents.items()},
            "conflicts": sorted(item.fingerprint for item in conflicts),
        }
    )


async def _ensure_location_nodes(
    db: AsyncSession,
    novel_id: str,
    entities: dict[uuid.UUID, CoreEntity],
    parents: dict[uuid.UUID, dict],
) -> dict[uuid.UUID, MapAtlasNode]:
    location_ids = {
        entity_id
        for entity_id, entity in entities.items()
        if entity.entity_type.casefold() == "location"
        and entity.status in {"canonical", "candidate", "draft"}
    }
    if not location_ids:
        return {}
    existing = (
        await db.scalars(
            select(MapAtlasNode)
            .where(
                MapAtlasNode.novel_id == parse_uuid(novel_id, "novel_id"),
                MapAtlasNode.location_entity_id.in_(location_ids),
                MapAtlasNode.level.in_(STRUCTURE_LEVELS),
            )
            .order_by(
                MapAtlasNode.status.desc(),
                MapAtlasNode.updated_at.desc(),
                MapAtlasNode.id,
            )
        )
    ).all()
    nodes: dict[uuid.UUID, MapAtlasNode] = {}
    for node in existing:
        nodes.setdefault(node.location_entity_id, node)
    for entity_id in sorted(location_ids, key=str):
        if entity_id in nodes:
            continue
        entity = entities[entity_id]
        semantic_key = f"entity:{entity_id}"
        collision = await db.scalar(
            select(MapAtlasNode.id).where(
                MapAtlasNode.novel_id == parse_uuid(novel_id, "novel_id"),
                MapAtlasNode.semantic_key == semantic_key,
            )
        )
        if collision:
            semantic_key = f"auto-spatial:{entity_id}"
        node = MapAtlasNode(
            novel_id=parse_uuid(novel_id, "novel_id"),
            parent_id=None,
            location_entity_id=entity_id,
            semantic_key=semantic_key,
            title=entity.name[:255],
            level="region",
            status="provisional",
        )
        db.add(node)
        await db.flush()
        nodes[entity_id] = node

    # Only provisional, auto-owned hierarchy can change; adopted node trees win.
    for entity_id, node in nodes.items():
        if node.status != "provisional":
            continue
        edge = parents.get(entity_id)
        parent = nodes.get(edge["parent_id"]) if edge else None
        if parent is None or parent.id == node.id:
            node.parent_id = None
            node.level = "region"
            continue
        node.parent_id = parent.id
        depth = 1
        cursor = edge["parent_id"]
        seen = {entity_id}
        while cursor in parents and cursor not in seen and depth < 5:
            seen.add(cursor)
            cursor = parents[cursor]["parent_id"]
            depth += 1
        node.level = _level_for_depth(depth)
    await db.flush()
    return nodes


def _new_tray_item(
    batch_id: uuid.UUID,
    node_id: uuid.UUID,
    clue_row: MapSpatialClueRecord,
    endpoint: MapSpatialClueEndpoint,
    side: str,
    reason: str,
) -> dict:
    item_id = _tray_item_id(batch_id, clue_row.id, side)
    return {
        "item_id": item_id,
        "node_id": node_id,
        "clue_id": clue_row.id,
        "scene_id": clue_row.scene_id,
        "scene_index": clue_row.scene_index,
        "endpoint_side": side,
        "endpoint": _jsonable_endpoint(endpoint),
        "quote": "",
        "source_mode": clue_row.source_content_mode,
        "reason": reason,
        "fingerprint": "0" * 64,
        "placed_feature_id": None,
    }


async def _make_plan(
    db: AsyncSession,
    novel_id: str,
    request: MapAutoDraftBuildRequest,
    batch_id: uuid.UUID,
    clue_rows: list[MapSpatialClueRecord],
    input_fingerprint: str,
    *,
    force_redo_reason: str | None = None,
) -> tuple[dict, list[dict], list[dict]]:
    valid, invalid = await _validated_clue_inputs(
        db,
        novel_id,
        clue_rows,
        through_scene_index=request.through_scene_index,
        run_id=request.run_id,
    )
    endpoint_ids: set[uuid.UUID] = set()
    for item in valid:
        for entity in item["endpoints"].values():
            if entity.entity_type.casefold() == "location":
                endpoint_ids.add(entity.id)
    parents, conflicts = await _hierarchy_edges(db, novel_id, endpoint_ids, valid)
    parent_ids = {item["parent_id"] for item in parents.values()}
    entities = await _entity_rows(db, novel_id, endpoint_ids | parent_ids)
    parents = {
        child: edge
        for child, edge in parents.items()
        if child in entities
        and edge["parent_id"] in entities
        and entities[edge["parent_id"]].entity_type.casefold() == "location"
    }
    nodes = await _ensure_location_nodes(db, novel_id, entities, parents)
    children: dict[uuid.UUID, list[uuid.UUID]] = {}
    for child_id, edge in parents.items():
        if child_id in nodes and edge["parent_id"] in nodes:
            children.setdefault(edge["parent_id"], []).append(child_id)
    for values in children.values():
        values.sort(key=lambda item: (entities[item].name.casefold(), str(item)))

    clue_ids_by_node: dict[uuid.UUID, set[uuid.UUID]] = {}
    feature_ids_by_node: dict[uuid.UUID, set[uuid.UUID]] = {}
    tray_specs: list[tuple[MapSpatialClueRecord, MapSpatialClue, str, str]] = []
    valid_by_row = {item["row"].id: item for item in valid}
    for item in valid:
        row, clue = item["row"], item["clue"]
        bound = {
            side: _endpoint_entity_id(endpoint, item["endpoints"])
            for side, endpoint in (("subject", clue.subject), ("target", clue.target))
            if endpoint is not None
        }
        location_ids = {
            entity_id
            for entity_id in bound.values()
            if entity_id in entities
            and entities[entity_id].entity_type.casefold() == "location"
        }
        owner_id = next(
            (
                bound.get(side)
                for side in ("subject", "target")
                if bound.get(side) in nodes
            ),
            None,
        )
        if owner_id is None and location_ids:
            owner_id = min(location_ids, key=str)
        for side, endpoint in (("subject", clue.subject), ("target", clue.target)):
            if endpoint is None:
                continue
            entity_id = bound.get(side)
            if entity_id is None:
                tray_specs.append((row, clue, side, "unresolved_endpoint"))
            elif entity_id not in nodes:
                tray_specs.append((row, clue, side, "endpoint_not_location"))
        if item["source_issue"] == "ambiguous_source_quote":
            for side in ("subject", "target"):
                if side == "subject" or clue.target is not None:
                    tray_specs.append((row, clue, side, "ambiguous_source_quote"))

        if owner_id is None:
            continue
        # Every clue is owned by one deterministic shard. Both bound location
        # endpoints are included in that shard so cross-branch connections are
        # represented instead of silently disappearing from separate maps.
        owner_node_id = nodes[owner_id].id
        node_feature_ids = feature_ids_by_node.setdefault(owner_node_id, set())
        node_feature_ids.add(owner_id)
        node_feature_ids.update(location_ids)
        clue_ids_by_node.setdefault(owner_node_id, set()).add(row.id)

        if clue.modality != "event_observed":
            for side, endpoint in (("subject", clue.subject), ("target", clue.target)):
                if endpoint is not None:
                    tray_specs.append((row, clue, side, "non_event_modality"))

    for conflict in conflicts:
        for item in valid:
            if item["clue"].kind != "contains":
                continue
            for side, endpoint in (
                ("subject", item["clue"].subject),
                ("target", item["clue"].target),
            ):
                if (
                    endpoint is not None
                    and _endpoint_entity_id(endpoint, item["endpoints"])
                    == conflict.child_entity_id
                ):
                    tray_specs.append(
                        (item["row"], item["clue"], side, "hierarchy_conflict")
                    )

    for item in invalid:
        row, clue = item["row"], item["clue"]
        if clue is None:
            continue
        for side, endpoint in (("subject", clue.subject), ("target", clue.target)):
            if endpoint is not None:
                tray_specs.append((row, clue, side, item["reason"]))

    if tray_specs and not nodes:
        node = MapAtlasNode(
            novel_id=parse_uuid(novel_id, "novel_id"),
            parent_id=None,
            location_entity_id=None,
            semantic_key=f"auto-spatial-unplaced:{batch_id}",
            title="空间线索待放置",
            level="region",
            status="provisional",
        )
        db.add(node)
        await db.flush()
        nodes[uuid.UUID(int=0)] = node
        clue_ids_by_node[node.id] = set()

    assigned_node_ids = set(clue_ids_by_node)
    if nodes:
        fallback_node = min(nodes.values(), key=lambda item: (item.level, str(item.id)))
        for row, clue, side, _reason in tray_specs:
            endpoint = clue.subject if side == "subject" else clue.target
            valid_item = valid_by_row.get(row.id)
            entity = (
                valid_item["endpoints"].get(str(endpoint.entity_id))
                if endpoint is not None
                and endpoint.entity_id is not None
                and valid_item is not None
                else None
            )
            tray_node = nodes.get(entity.id) if entity is not None else None
            assigned_node_ids.add((tray_node or fallback_node).id)

    hierarchy_snapshot = {
        str(child): str(edge["parent_id"]) for child, edge in parents.items()
    }
    shards = []
    for entity_id, node in sorted(
        nodes.items(), key=lambda pair: (pair[1].level, str(pair[1].id))
    ):
        if node.id not in assigned_node_ids:
            continue
        selected_set = set(feature_ids_by_node.get(node.id, set()))
        if entity_id.int != 0 and node.id in clue_ids_by_node:
            selected_set.add(entity_id)
        selected_entities = sorted(
            selected_set, key=lambda item: (entities[item].name.casefold(), str(item))
        )
        if len(selected_entities) > AUTO_DRAFT_FEATURE_LIMIT:
            overflow_ids = selected_entities[AUTO_DRAFT_FEATURE_LIMIT:]
            selected_entities = selected_entities[:AUTO_DRAFT_FEATURE_LIMIT]
            for clue_id in clue_ids_by_node.get(node.id, set()):
                item = next(
                    (value for value in valid if value["row"].id == clue_id), None
                )
                if item is None:
                    continue
                for side, endpoint in (
                    ("subject", item["clue"].subject),
                    ("target", item["clue"].target),
                ):
                    if (
                        endpoint is not None
                        and _endpoint_entity_id(endpoint, item["endpoints"])
                        in overflow_ids
                    ):
                        tray_specs.append(
                            (item["row"], item["clue"], side, "feature_limit")
                        )
        base_revision_id = node.current_revision_id
        base_auto_revision_id = None
        base_source_clue_ids: list[str] = []
        previous = await _latest_auto_draft_for_node(db, novel_id, node)
        redo_reason = None
        use_previous = previous is not None
        if previous is not None:
            if (
                auto_draft_review_base(previous) != node.current_revision_id
                and force_redo_reason is None
            ):
                raise ConflictError("待审草图基于旧正式地图，请先审核旧草图或明确重做")
            previous_batch_id = _marker_batch_id(previous.context_fingerprint)
            prior_batch = (
                await db.get(MapAutoDraftBatchRecord, previous_batch_id)
                if previous_batch_id
                else None
            )
            prior_ref = (
                _batch_revision_ref(prior_batch, previous.id) if prior_batch else None
            )
            base_source_clue_ids = list((prior_ref or {}).get("source_clue_ids", []))
            previous_hierarchy = (
                (prior_batch.plan_json or {}).get("hierarchy", {}) if prior_batch else {}
            )
            current_hierarchy_scope = {str(item) for item in selected_entities} | (
                {str(entity_id)} if entity_id.int else set()
            )
            previous_hierarchy_scope = {
                key: value
                for key, value in previous_hierarchy.items()
                if key in current_hierarchy_scope
            }
            current_hierarchy_for_scope = {
                key: value
                for key, value in hierarchy_snapshot.items()
                if key in current_hierarchy_scope
            }
            if force_redo_reason is not None:
                redo_reason = force_redo_reason
            elif prior_batch and prior_batch.method_fingerprint != _method_fingerprint():
                redo_reason = "method_or_kernel_changed"
            elif not await _prior_source_clues_current(
                db,
                novel_id,
                base_source_clue_ids,
                through_scene_index=request.through_scene_index,
            ):
                redo_reason = "clue_superseded"
            elif previous_hierarchy_scope != current_hierarchy_for_scope:
                redo_reason = "hierarchy_parent_changed"
            elif prior_batch and (
                any(
                    problem.get("code") == "unplaced"
                    for problem in previous.problems or []
                )
                or any(
                    str(item.get("node_id")) == str(node.id)
                    and item.get("reason") == "placement_failed"
                    for item in prior_batch.tray_items or []
                )
            ):
                redo_reason = "incremental_placement_failed"
            use_previous = redo_reason is None
            base_auto_revision_id = previous.id if use_previous else None
        if previous is not None and not use_previous:
            base_source_clue_ids = []
        source_ids = sorted(
            {
                *base_source_clue_ids,
                *(str(item) for item in clue_ids_by_node.get(node.id, set())),
            }
        )
        shards.append(
            {
                "node_id": str(node.id),
                "entity_id": str(entity_id) if entity_id.int else None,
                "feature_entity_ids": [str(item) for item in selected_entities],
                "clue_ids": sorted(
                    str(item) for item in clue_ids_by_node.get(node.id, set())
                ),
                "source_clue_ids": source_ids,
                "base_revision_id": str(base_revision_id) if base_revision_id else None,
                "base_auto_revision_id": str(base_auto_revision_id)
                if base_auto_revision_id
                else None,
                "task_id": str(uuid.uuid4()),
                "redo_reason": redo_reason,
                "previous_revision_id": str(previous.id) if previous else None,
                "has_tray": False,
            }
        )

    default_node_id = uuid.UUID(shards[0]["node_id"]) if shards else None
    tray_by_id: dict[uuid.UUID, dict] = {}
    tray_reason_priority = {
        "source_stale": 100,
        "endpoint_stale": 90,
        "ambiguous_source_quote": 80,
        "pending_verification": 75,
        "unresolved_endpoint": 70,
        "endpoint_not_location": 60,
        "hierarchy_conflict": 50,
        "feature_limit": 40,
        "relation_limit": 30,
        "non_event_modality": 20,
        "placement_failed": 10,
    }
    for row, clue, side, reason in tray_specs:
        endpoint = clue.subject if side == "subject" else clue.target
        if endpoint is None:
            continue
        target_node_id = None
        item = valid_by_row.get(row.id)
        if endpoint.entity_id is not None and item is not None:
            entity = item["endpoints"].get(str(endpoint.entity_id))
            target_node = nodes.get(entity.id) if entity is not None else None
            target_node_id = target_node.id if target_node else None
        node_id = target_node_id or default_node_id
        if node_id is None:
            continue
        tray = _new_tray_item(batch_id, node_id, row, endpoint, side, reason)
        tray["quote"] = clue.quote
        current = tray_by_id.get(tray["item_id"])
        if (
            current is None
            or tray_reason_priority[reason] > tray_reason_priority[current["reason"]]
        ):
            tray_by_id[tray["item_id"]] = tray

    tray_payloads = [
        MapAutoDraftTrayItem.model_validate(item).model_dump(mode="json")
        for item in tray_by_id.values()
    ]

    tray_node_ids = {str(item["node_id"]) for item in tray_payloads}
    for shard in shards:
        shard["has_tray"] = shard["node_id"] in tray_node_ids

    plan = {
        # Keep the full requested set in the frozen plan for idempotency and
        # tray provenance. Only currently valid rows become candidate sources.
        "clue_ids": [str(row.id) for row in clue_rows],
        "valid_clue_ids": [str(item["row"].id) for item in valid],
        "dependency_fingerprint": await _build_dependency_fingerprint(
            db, novel_id, valid
        ),
        "shards": shards,
        "hierarchy": hierarchy_snapshot,
        "redo_reason": next(
            (item["redo_reason"] for item in shards if item["redo_reason"]), None
        ),
        "cursor_phase": "shards",
    }
    conflicts_json = [item.model_dump(mode="json") for item in conflicts]
    for tray in tray_payloads:
        tray["fingerprint"] = _digest(
            {
                "batch_fingerprint": input_fingerprint,
                "item": {
                    key: value for key, value in tray.items() if key != "fingerprint"
                },
            }
        )
    return plan, tray_payloads, conflicts_json


async def _latest_auto_draft_for_node(
    db: AsyncSession, novel_id: str, node: MapAtlasNode
) -> MapAtlasRevision | None:
    return await db.scalar(
        select(MapAtlasRevision)
        .where(
            MapAtlasRevision.novel_id == parse_uuid(novel_id, "novel_id"),
            MapAtlasRevision.node_id == node.id,
            MapAtlasRevision.status == "candidate",
            MapAtlasRevision.context_fingerprint.like(f"{_AUTO_DRAFT_CONTEXT_PREFIX}%"),
        )
        .order_by(MapAtlasRevision.created_at.desc(), MapAtlasRevision.id.desc())
        .limit(1)
    )


def _batch_revision_ref(
    batch: MapAutoDraftBatchRecord | None, revision_id: uuid.UUID
) -> dict | None:
    if batch is None:
        return None
    return next(
        (
            item
            for item in batch.result_refs or []
            if str(item.get("revision_id")) == str(revision_id)
        ),
        None,
    )


async def _prior_source_clues_current(
    db: AsyncSession,
    novel_id: str,
    clue_ids: list[str],
    *,
    through_scene_index: int,
) -> bool:
    if not clue_ids:
        return True
    parsed = {parse_uuid(item, "clue_id") for item in clue_ids}
    rows = (
        await db.scalars(
            select(MapSpatialClueRecord).where(
                MapSpatialClueRecord.novel_id == parse_uuid(novel_id, "novel_id"),
                MapSpatialClueRecord.id.in_(parsed),
            )
        )
    ).all()
    if {row.id for row in rows} != parsed:
        return False
    if any(
        row.status not in {"pending_review", "adopted"}
        or row.scene_index > through_scene_index
        for row in rows
    ):
        return False
    valid, invalid = await _validated_clue_inputs(
        db,
        novel_id,
        list(rows),
        through_scene_index=through_scene_index,
    )
    return not invalid and len(valid) == len(rows)


async def _lock_project_for_map_write(db: AsyncSession, novel_id: str) -> None:
    from sqlalchemy.exc import DBAPIError

    try:
        async with db.begin_nested():
            await require_active_project_exclusive(db, novel_id, nowait=True)
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) == "55P03":
            raise ConflictError("作品正在更新，请稍后继续自动草图") from exc
        raise


async def _load_revision(
    db: AsyncSession, novel_id: str, node_id: uuid.UUID, revision_id: uuid.UUID | None
) -> MapAtlasRevision | None:
    if revision_id is None:
        return None
    row = await db.scalar(
        select(MapAtlasRevision).where(
            MapAtlasRevision.novel_id == parse_uuid(novel_id, "novel_id"),
            MapAtlasRevision.node_id == node_id,
            MapAtlasRevision.id == revision_id,
        )
    )
    if row is None:
        raise ConflictError("草图基线已不存在，请重新生成")
    return row


async def _resolve_merged_entity(
    db: AsyncSession, novel_id: str, entity_id: uuid.UUID
) -> CoreEntity | None:
    seen: set[uuid.UUID] = set()
    current_id = entity_id
    while current_id not in seen:
        seen.add(current_id)
        entity = await db.scalar(
            select(CoreEntity).where(
                CoreEntity.novel_id == parse_uuid(novel_id, "novel_id"),
                CoreEntity.id == current_id,
            )
        )
        if entity is None:
            return None
        if entity.status != "merged":
            return (
                entity if entity.status in {"canonical", "candidate", "draft"} else None
            )
        redirect = (entity.content_json or {}).get("merged_into")
        if not redirect:
            return None
        try:
            current_id = parse_uuid(str(redirect), "merged_entity_id")
        except (ValueError, TypeError):
            return None
    return None


async def _project_candidate_entities(
    db: AsyncSession, novel_id: str, document: MapDocument
) -> tuple[MapDocument, list[str]]:
    projected = document.model_copy(deep=True)
    warnings: list[str] = []
    for feature in projected.features:
        if feature.entity_id is None:
            continue
        current = await _resolve_merged_entity(db, novel_id, feature.entity_id)
        if current is None:
            feature.note = (
                f"{feature.note}\n地点候选已拒绝或删除；此图元仅保留文字，需重新映射。"
            )[-1000:]
            feature.entity_id = None
            feature.points = []
            feature.locked = False
            warnings.append("部分地点已失效，已降为文字并待重新映射")
        elif current.id != feature.entity_id:
            feature.entity_id = current.id
            warnings.append("部分地点已融合，草图绑定跟随融合目标")
        if current is not None and current.status != "canonical":
            feature.note = (
                f"{feature.note}\n地点尚未采用；正式地图中仅保留文字标签，需重新映射或采用地点后再放置。"
            )[-1000:]
            warnings.append("部分地点尚未采用，地图草图保留文字标签并待核")
    return projected, list(dict.fromkeys(warnings))


async def prepare_auto_draft_adoption(
    db: AsyncSession,
    novel_id: str,
    node: MapAtlasNode,
    revision: MapAtlasRevision,
    change_keys: list[str] | None,
    *,
    source_validator,
) -> tuple[MapDocument, list[str], list[str], MapDocument]:
    """Revalidate and narrow an auto draft before the normal saved-map gate."""
    from modules.world.map_structure_review import (
        apply_revision_changes,
        document_items,
    )

    batch_id = _marker_batch_id(revision.context_fingerprint)
    if batch_id is None:
        raise ValidationError("候选版本不是自动草图")
    batch = await db.scalar(
        select(MapAutoDraftBatchRecord)
        .where(
            MapAutoDraftBatchRecord.novel_id == parse_uuid(novel_id, "novel_id"),
            MapAutoDraftBatchRecord.id == batch_id,
        )
        .with_for_update()
    )
    if batch is None or batch.status != "completed":
        raise ConflictError("自动草图批次未完成或已经失效，请重新生成")
    ref = _batch_revision_ref(batch, revision.id)
    if ref is None or ref.get("status") != "candidate":
        raise ConflictError("自动草图候选已经結束，请刷新后再操作")
    if auto_draft_review_base(revision) != node.current_revision_id:
        raise ConflictError("候选基于旧地图，请重新生成或手动比较")
    clue_ids = {parse_uuid(item, "clue_id") for item in ref.get("source_clue_ids", [])}
    clue_rows = (
        (
            await db.scalars(
                select(MapSpatialClueRecord).where(
                    MapSpatialClueRecord.novel_id == parse_uuid(novel_id, "novel_id"),
                    MapSpatialClueRecord.id.in_(clue_ids),
                )
            )
        ).all()
        if clue_ids
        else []
    )
    if {row.id for row in clue_rows} != clue_ids:
        raise ConflictError("自动草图来源线索已缺失，请重新映射")
    valid, invalid = await _validated_clue_inputs(
        db,
        novel_id,
        list(clue_rows),
        through_scene_index=batch.through_scene_index,
    )
    if invalid or len(valid) != len(clue_rows):
        raise ConflictError("自动草图来源、端点或复核已变化，请重新映射")

    baseline_row = await _load_revision(
        db, novel_id, revision.node_id, auto_draft_review_base(revision)
    )
    baseline = (
        MapDocument.model_validate(baseline_row.document)
        if baseline_row is not None
        else MapDocument()
    )
    baseline_items = document_items(baseline)
    original_candidate = MapDocument.model_validate(revision.document)
    original_entity_ids = {
        feature.id: feature.entity_id for feature in original_candidate.features
    }
    candidate, _projection_warnings = await _project_candidate_entities(
        db, novel_id, original_candidate
    )
    stale_feature_ids: set[str] = set()
    for feature in candidate.features:
        if original_entity_ids.get(feature.id) is not None and feature.entity_id is None:
            stale_feature_ids.add(feature.id)
            feature.points = []
            feature.locked = False
            feature.note = (
                f"{feature.note}\n地点已失效，待核；正式地图仅保留文字标签，需重新映射。"
            )[-1000:]
        if feature.entity_id is None:
            continue
        entity = await _resolve_merged_entity(db, novel_id, feature.entity_id)
        if entity is None or entity.status != "canonical":
            stale_feature_ids.add(feature.id)
            feature.entity_id = None
            feature.points = []
            feature.locked = False
            feature.note = (
                f"{feature.note}\n地点尚未采用或已失效，待核；正式地图仅保留文字标签，需重新映射。"
            )[-1000:]
        else:
            feature.entity_id = entity.id

    # The auto builder may use working text to make an author-facing preview.
    # Only additions with canonical manuscript citations can enter a saved map.
    retained_features = []
    for feature in candidate.features:
        if f"feature:{feature.id}" not in baseline_items and (
            not feature.sources or set(feature.depends_on) & stale_feature_ids
        ):
            continue
        retained_features.append(feature)
    candidate.features = retained_features
    feature_ids = {item.id for item in candidate.features}
    candidate.constraints = [
        item
        for item in candidate.constraints
        if not ({item.subject, item.target, *item.via} & stale_feature_ids)
        and (
            f"constraint:{item.id}" in baseline_items
            or (
                bool(item.sources)
                and item.subject in feature_ids
                and item.target in feature_ids
            )
        )
    ]
    candidate.journeys = [
        item
        for item in candidate.journeys
        if item.origin not in stale_feature_ids
        and item.destination not in stale_feature_ids
        and (
            f"journey:{item.id}" in baseline_items
            or (
                bool(item.sources)
                and item.origin in feature_ids
                and item.destination in feature_ids
            )
        )
    ]
    candidate.annotation_bindings = [
        item for item in candidate.annotation_bindings if item.feature_id in feature_ids
    ]
    candidate = MapDocument.model_validate(candidate.model_dump(mode="json"))

    prepared, applied, expanded = apply_revision_changes(baseline, candidate, change_keys)
    items = document_items(prepared)
    for key in applied:
        item = items.get(key)
        if item is None or not key.startswith(("feature:", "constraint:", "journey:")):
            continue
        for source in item.sources:
            await source_validator(db, novel_id, source)
    return prepared, applied, expanded, candidate


async def update_auto_draft_review_ref(
    db: AsyncSession,
    novel_id: str,
    revision: MapAtlasRevision,
    *,
    status: str,
    replacement: MapAtlasRevision | None = None,
) -> None:
    if status not in {"saved", "rejected"}:
        raise ValidationError("自动草图审核状态无效")
    batch_id = _marker_batch_id(revision.context_fingerprint)
    if batch_id is None:
        return
    batch = await db.scalar(
        select(MapAutoDraftBatchRecord)
        .where(
            MapAutoDraftBatchRecord.novel_id == parse_uuid(novel_id, "novel_id"),
            MapAutoDraftBatchRecord.id == batch_id,
        )
        .with_for_update()
    )
    if batch is None:
        return
    refs = [dict(item) for item in batch.result_refs or []]
    target = next(
        (item for item in refs if str(item.get("revision_id")) == str(revision.id)),
        None,
    )
    if target is None:
        return
    target["status"] = status
    if replacement is not None:
        refs.append(
            MapAutoDraftRevisionRef(
                node_id=replacement.node_id,
                revision_id=replacement.id,
                base_revision_id=replacement.base_revision_id,
                status="candidate",
                feature_count=len(
                    MapDocument.model_validate(replacement.document).features
                ),
                source_clue_ids=[
                    parse_uuid(item, "clue_id")
                    for item in target.get("source_clue_ids", [])
                ],
            ).model_dump(mode="json")
        )
    batch.result_refs = refs
    await db.flush()


async def invalidate_auto_drafts_for_clue(
    db: AsyncSession,
    novel_id: str,
    clue_id: str,
    *,
    reason: str,
) -> int:
    """Mark every durable candidate depending on an ended clue as stale."""
    clue_key = str(parse_uuid(clue_id, "clue_id"))
    batches = (
        await db.scalars(
            select(MapAutoDraftBatchRecord)
            .where(
                MapAutoDraftBatchRecord.novel_id == parse_uuid(novel_id, "novel_id"),
                MapAutoDraftBatchRecord.status.in_(["running", "completed"]),
            )
            .with_for_update()
        )
    ).all()
    changed = 0
    for batch in batches:
        references = [
            source_id
            for ref in batch.result_refs or []
            for source_id in ref.get("source_clue_ids", [])
        ]
        plan = batch.plan_json or {}
        planned = [
            *plan.get("clue_ids", []),
            *plan.get("valid_clue_ids", []),
        ]
        tray_clues = [str(item.get("clue_id")) for item in batch.tray_items or []]
        if clue_key not in {*references, *planned, *tray_clues}:
            continue
        batch.status = "stale"
        batch.stale_reason = reason[:2000]
        changed += 1
    if changed:
        await db.flush()
    return changed


def _spatial_relation(clue: MapSpatialClue) -> tuple[str, str, str] | None:
    if clue.kind == "contains" and clue.target is not None:
        # World-style “subject contains target” becomes map-style
        # “target is inside subject”.
        return "inside", "target", "subject"
    if clue.kind == "bearing" and clue.relation in _SPATIAL_RELATIONS:
        return clue.relation, "subject", "target"
    if clue.kind == "adjacency":
        return "adjacent", "subject", "target"
    if clue.kind == "connection" and clue.relation in _SPATIAL_RELATIONS:
        return clue.relation, "subject", "target"
    return None


def _tray_dicts_for_node(
    batch: MapAutoDraftBatchRecord, node_id: uuid.UUID
) -> list[dict]:
    return [
        item
        for item in batch.tray_items or []
        if str(item.get("node_id")) == str(node_id) and not item.get("placed_feature_id")
    ]


def _tray_preview_fingerprint(
    batch: MapAutoDraftBatchRecord,
    revision: MapAtlasRevision,
    tray: dict,
    request: MapAutoDraftTrayPlacementPreviewRequest,
    feature_id: str,
    document: MapDocument,
) -> str:
    return _digest(
        {
            "batch": batch.input_fingerprint,
            "revision": str(revision.id),
            "geometry": revision.geometry_hash,
            "item": tray,
            "base_revision_id": str(request.base_revision_id)
            if request.base_revision_id
            else None,
            "space_id": request.space_id,
            "point": request.point.model_dump(mode="json"),
            "feature_id": feature_id,
            "new_geometry_hash": geometry_hash(document),
        }
    )


def _append_tray_item(
    batch: MapAutoDraftBatchRecord,
    shard: dict,
    clue_row: MapSpatialClueRecord,
    clue: MapSpatialClue,
    side: str,
    reason: str,
) -> None:
    endpoint = clue.subject if side == "subject" else clue.target
    if endpoint is None:
        return
    node_id = uuid.UUID(shard["node_id"])
    item = _new_tray_item(batch.id, node_id, clue_row, endpoint, side, reason)
    item["quote"] = clue.quote
    item["fingerprint"] = _digest(
        {
            "batch_fingerprint": batch.input_fingerprint,
            "item": {key: value for key, value in item.items() if key != "fingerprint"},
        }
    )
    item = MapAutoDraftTrayItem.model_validate(item).model_dump(mode="json")
    items = list(batch.tray_items or [])
    if not any(str(prior.get("item_id")) == str(item["item_id"]) for prior in items):
        items.append(item)
        batch.tray_items = items


async def _auto_draft_document(
    db: AsyncSession,
    novel_id: str,
    batch: MapAutoDraftBatchRecord,
    shard: dict,
    node: MapAtlasNode,
    clue_inputs: dict[uuid.UUID, dict],
) -> tuple[MapDocument, list[dict], list[str], str | None]:
    saved_base = await _load_revision(
        db,
        novel_id,
        node.id,
        uuid.UUID(shard["base_revision_id"]) if shard["base_revision_id"] else None,
    )
    incremental_base = await _load_revision(
        db,
        novel_id,
        node.id,
        uuid.UUID(shard["base_auto_revision_id"])
        if shard.get("base_auto_revision_id")
        else None,
    )
    if incremental_base is not None and incremental_base.status != "candidate":
        raise ConflictError("待审自动草图已结束，请重新生成")
    baseline_row = incremental_base or saved_base
    base = (
        MapDocument.model_validate(baseline_row.document)
        if baseline_row is not None
        else MapDocument()
    )
    base, warnings = await _project_candidate_entities(db, novel_id, base)
    payload = base.model_dump(mode="json")
    payload["schema_version"] = 2
    if not payload.get("spaces"):
        payload["spaces"] = [{"id": "main", "label": "主空间"}]
    document = MapDocument.model_validate(payload)
    original_features = {feature.id: feature.locked for feature in document.features}
    by_entity = {
        str(feature.entity_id): feature
        for feature in document.features
        if feature.entity_id is not None
    }
    selected_entities = [
        uuid.UUID(value) for value in shard.get("feature_entity_ids", [])
    ]
    row_clues = [
        clue_inputs[uuid.UUID(clue_id)]
        for clue_id in shard.get("clue_ids", [])
        if uuid.UUID(clue_id) in clue_inputs
    ]
    feature_sources: dict[uuid.UUID, list[MapSource]] = {}
    feature_modalities: dict[uuid.UUID, set[str]] = {}
    feature_effective: dict[uuid.UUID, list] = {}
    source_by_clue: dict[uuid.UUID, MapSource | None] = {}
    for item in row_clues:
        row = item["row"]
        clue = item["clue"]
        source_by_clue[row.id] = item["source"]
        if clue.modality != "event_observed":
            continue
        for endpoint in (clue.subject, clue.target):
            entity_id = (
                _endpoint_entity_id(endpoint, item["endpoints"]) if endpoint else None
            )
            if entity_id is None:
                continue
            feature_modalities.setdefault(entity_id, set()).add(str(clue.modality))
            feature_effective.setdefault(entity_id, []).append(clue.attributes.effective)
            source = item["source"]
            if source is not None:
                sources = feature_sources.setdefault(entity_id, [])
                if _map_source_key(source) not in {
                    _map_source_key(value) for value in sources
                }:
                    sources.append(source)

    for entity_id in selected_entities:
        entity = await _resolve_merged_entity(db, novel_id, entity_id)
        if entity is None or entity.entity_type.casefold() != "location":
            continue
        if entity.id not in feature_modalities:
            # Statement, inference, prophecy, and other non-event observations
            # remain review material in the tray; layout never assigns them a
            # coordinate.
            continue
        existing = by_entity.get(str(entity.id))
        if existing is not None:
            prior_sources = {_map_source_key(item) for item in existing.sources}
            for source in feature_sources.get(entity.id, []):
                if (
                    len(existing.sources) < 8
                    and _map_source_key(source) not in prior_sources
                ):
                    existing.sources.append(source)
                    prior_sources.add(_map_source_key(source))
            continue
        if len(document.features) >= AUTO_DRAFT_FEATURE_LIMIT:
            for item in row_clues:
                if any(
                    _endpoint_entity_id(endpoint, item["endpoints"]) == entity.id
                    for endpoint in (item["clue"].subject, item["clue"].target)
                    if endpoint is not None
                ):
                    side = (
                        "subject"
                        if _endpoint_entity_id(item["clue"].subject, item["endpoints"])
                        == entity.id
                        else "target"
                    )
                    _append_tray_item(
                        batch, shard, item["row"], item["clue"], side, "feature_limit"
                    )
            continue
        modalities = feature_modalities.get(entity.id, set())
        modality = next(iter(modalities)) if len(modalities) == 1 else "unclear"
        feature = MapFeature(
            id=_feature_id(entity.id),
            kind="location",
            label=entity.name[:200],
            space_id="main",
            entity_id=entity.id,
            points=[],
            sources=feature_sources.get(entity.id, [])[:8],
            note="候选地点，仅供作者审核；不会自动写入正式地图",
            modality=modality,
            effective=next(
                (
                    value
                    for value in feature_effective.get(entity.id, [])
                    if value is not None
                ),
                None,
            ),
        )
        document.features.append(feature)
        by_entity[str(entity.id)] = feature

    feature_key_by_entity = {
        str(feature.entity_id): feature.id
        for feature in document.features
        if feature.entity_id is not None
    }
    constraints = {item.id: item for item in document.constraints}
    journeys = {item.id: item for item in document.journeys}
    for item in row_clues:
        row, clue = item["row"], item["clue"]
        if clue.modality != "event_observed":
            continue
        source = source_by_clue.get(row.id)
        if clue.kind == "journey" and clue.target is not None:
            left = _endpoint_entity_id(clue.subject, item["endpoints"])
            right = _endpoint_entity_id(clue.target, item["endpoints"])
            attrs = clue.attributes
            if (
                left is not None
                and right is not None
                and source is not None
                and attrs.transport_label
                and str(left) in feature_key_by_entity
                and str(right) in feature_key_by_entity
            ):
                if len(journeys) >= 400:
                    _append_tray_item(
                        batch, shard, row, clue, "subject", "relation_limit"
                    )
                    _append_tray_item(batch, shard, row, clue, "target", "relation_limit")
                    continue
                journeys.setdefault(
                    _constraint_id(row.id),
                    SpatialJourney(
                        id=_constraint_id(row.id),
                        origin=feature_key_by_entity[str(left)],
                        destination=feature_key_by_entity[str(right)],
                        transport_label=attrs.transport_label,
                        duration=attrs.duration,
                        distance=attrs.distance,
                        access_conditions=[
                            {"label": value} for value in attrs.access_conditions
                        ],
                        modality=clue.modality,
                        effective=attrs.effective,
                        sources=[source],
                    ),
                )
            continue
        relation = _spatial_relation(clue)
        if relation is None or clue.target is None:
            continue
        relation_name, subject_side, target_side = relation
        subject_endpoint = clue.subject if subject_side == "subject" else clue.target
        target_endpoint = clue.target if target_side == "target" else clue.subject
        subject_entity_id = (
            _endpoint_entity_id(subject_endpoint, item["endpoints"])
            if subject_endpoint is not None
            else None
        )
        target_entity_id = (
            _endpoint_entity_id(target_endpoint, item["endpoints"])
            if target_endpoint is not None
            else None
        )
        if (
            subject_entity_id is None
            or target_entity_id is None
            or subject_entity_id == target_entity_id
            or str(subject_entity_id) not in feature_key_by_entity
            or str(target_entity_id) not in feature_key_by_entity
        ):
            continue
        constraint_id = _constraint_id(row.id)
        if constraint_id not in constraints and len(constraints) >= 400:
            _append_tray_item(batch, shard, row, clue, "subject", "relation_limit")
            _append_tray_item(batch, shard, row, clue, "target", "relation_limit")
            continue
        constraints.setdefault(
            constraint_id,
            SpatialConstraint(
                id=constraint_id,
                subject=feature_key_by_entity[str(subject_entity_id)],
                relation=relation_name,
                target=feature_key_by_entity[str(target_entity_id)],
                sources=[source] if source is not None else [],
                modality=clue.modality,
                effective=clue.attributes.effective,
            ),
        )
    document.constraints = list(constraints.values())
    document.journeys = list(journeys.values())

    for feature in document.features:
        if feature.id in original_features:
            feature.locked = True
    laid_out = layout(document)
    document = laid_out.document
    for feature in document.features:
        if feature.id in original_features:
            feature.locked = original_features[feature.id]

    placed_ids = {feature.id for feature in document.features if feature.points}
    for item in row_clues:
        clue = item["clue"]
        for side, endpoint in (("subject", clue.subject), ("target", clue.target)):
            entity_id = (
                _endpoint_entity_id(endpoint, item["endpoints"]) if endpoint else None
            )
            feature_id = feature_key_by_entity.get(str(entity_id)) if entity_id else None
            if feature_id and feature_id not in placed_ids:
                _append_tray_item(
                    batch,
                    shard,
                    item["row"],
                    clue,
                    side,
                    "placement_failed",
                )

    problems = [problem.model_dump(mode="json") for problem in laid_out.problems]
    conflict_ids = {str(item["child_entity_id"]) for item in batch.conflicts or []}
    shard_entities = {str(item) for item in selected_entities}
    affected_conflicts = conflict_ids & shard_entities
    if affected_conflicts:
        feature_ids = [
            _feature_id(uuid.UUID(entity_id)) for entity_id in sorted(affected_conflicts)
        ]
        problems.append(
            MapProblem(
                code="hierarchy_conflict",
                message="层级来源冲突，已按较高优先级保留并待作者核对",
                feature_ids=feature_ids,
            ).model_dump(mode="json")
        )
    return document, problems, warnings, shard.get("redo_reason")


async def _mark_old_revision_superseded(
    db: AsyncSession, novel_id: str, previous: MapAtlasRevision
) -> None:
    if previous.status != "candidate":
        return
    previous.status = "superseded"
    old_batch_id = _marker_batch_id(previous.context_fingerprint)
    if old_batch_id is None:
        return
    old_batch = await db.scalar(
        select(MapAutoDraftBatchRecord)
        .where(
            MapAutoDraftBatchRecord.novel_id == parse_uuid(novel_id, "novel_id"),
            MapAutoDraftBatchRecord.id == old_batch_id,
        )
        .with_for_update()
    )
    if old_batch is None:
        return
    refs = [dict(item) for item in old_batch.result_refs or []]
    for ref in refs:
        if str(ref.get("revision_id")) == str(previous.id):
            ref["status"] = "superseded"
    old_batch.result_refs = refs


async def _process_batch(
    db: AsyncSession,
    novel_id: str,
    batch: MapAutoDraftBatchRecord,
    *,
    chunk_limit: int = AUTO_DRAFT_CHUNKS_PER_CALL,
) -> MapAutoDraftBuildResult:
    if batch.status != "running":
        return _response(batch)
    if batch.method_fingerprint != _method_fingerprint():
        batch.status = "stale"
        batch.stale_reason = "自动草图方法版本已变化，请重新生成"
        await db.flush()
        return _response(batch)

    plan = batch.plan_json or {}
    required_ids = {uuid.UUID(item) for item in plan.get("valid_clue_ids", [])}
    for shard in plan.get("shards", []):
        required_ids.update(uuid.UUID(item) for item in shard.get("source_clue_ids", []))
    rows = (
        (
            await db.scalars(
                select(MapSpatialClueRecord).where(
                    MapSpatialClueRecord.novel_id == parse_uuid(novel_id, "novel_id"),
                    MapSpatialClueRecord.id.in_(required_ids),
                )
            )
        ).all()
        if required_ids
        else []
    )
    rows_by_id = {row.id: row for row in rows}
    if set(rows_by_id) != required_ids:
        batch.status = "stale"
        batch.stale_reason = "空间线索记录已变化或缺失，请重新生成"
        await db.flush()
        return _response(batch)
    valid, invalid = await _validated_clue_inputs(
        db,
        novel_id,
        list(rows_by_id.values()),
        through_scene_index=batch.through_scene_index,
    )
    valid_by_id = {item["row"].id: item for item in valid}
    current_run_ids = {uuid.UUID(item) for item in plan.get("valid_clue_ids", [])}
    if any(rows_by_id[item].run_id != batch.run_id for item in current_run_ids):
        batch.status = "stale"
        batch.stale_reason = "空间线索不属于草图对应的阅读运行，请重新生成"
        await db.flush()
        return _response(batch)
    if invalid or set(valid_by_id) != required_ids:
        batch.status = "stale"
        batch.stale_reason = "草图依赖的原文、端点或类型已变化，请重新映射"
        await db.flush()
        return _response(batch)
    if plan.get("dependency_fingerprint") != await _build_dependency_fingerprint(
        db, novel_id, [valid_by_id[item] for item in sorted(current_run_ids, key=str)]
    ):
        batch.status = "stale"
        batch.stale_reason = "草图依赖的地点身份或层级已变化，请重新生成"
        await db.flush()
        return _response(batch)
    start = batch.cursor
    stop = min(start + max(1, chunk_limit), len(plan.get("shards", [])))
    for index in range(start, stop):
        shard = plan["shards"][index]
        node_id = uuid.UUID(shard["node_id"])
        node = await db.scalar(
            select(MapAtlasNode)
            .where(
                MapAtlasNode.novel_id == parse_uuid(novel_id, "novel_id"),
                MapAtlasNode.id == node_id,
            )
            .with_for_update()
        )
        if node is None or (
            str(node.current_revision_id) if node.current_revision_id else None
        ) != shard.get("base_revision_id"):
            batch.status = "stale"
            batch.stale_reason = "地图正式版本已变化，请刷新基线后重新生成"
            break
        existing_candidate = await _latest_auto_draft_for_node(db, novel_id, node)
        if existing_candidate is not None and (
            str(existing_candidate.id) != shard.get("base_auto_revision_id")
            and str(existing_candidate.id) != shard.get("previous_revision_id")
        ):
            batch.status = "stale"
            batch.stale_reason = "节点已有更新的自动草图，请刷新后继续"
            break
        shard_clues = {
            uuid.UUID(item): valid_by_id[uuid.UUID(item)]
            for item in shard.get("clue_ids", [])
            if uuid.UUID(item) in valid_by_id
        }
        document, problems, warnings, _redo_reason = await _auto_draft_document(
            db,
            novel_id,
            batch,
            shard,
            node,
            shard_clues,
        )
        baseline_id = (
            uuid.UUID(shard["base_auto_revision_id"])
            if shard.get("base_auto_revision_id")
            else (
                uuid.UUID(shard["base_revision_id"])
                if shard.get("base_revision_id")
                else None
            )
        )
        baseline = await _load_revision(db, novel_id, node_id, baseline_id)
        baseline_doc = (
            MapDocument.model_validate(baseline.document)
            if baseline is not None
            else MapDocument()
        )
        baseline_projected, _ = await _project_candidate_entities(
            db, novel_id, baseline_doc
        )
        if (
            document.model_dump(mode="json") == baseline_projected.model_dump(mode="json")
            and not _tray_dicts_for_node(batch, node_id)
            and not shard.get("has_tray")
        ):
            batch.cursor = index + 1
            await db.flush()
            continue

        for candidate in (
            await db.scalars(
                select(MapAtlasRevision)
                .where(
                    MapAtlasRevision.novel_id == parse_uuid(novel_id, "novel_id"),
                    MapAtlasRevision.node_id == node.id,
                    MapAtlasRevision.status == "candidate",
                    MapAtlasRevision.context_fingerprint.like(
                        f"{_AUTO_DRAFT_CONTEXT_PREFIX}%"
                    ),
                )
                .with_for_update()
            )
        ).all():
            await _mark_old_revision_superseded(db, novel_id, candidate)

        from modules.world.services.common import current_writing_chapter_index

        revision = MapAtlasRevision(
            novel_id=node.novel_id,
            node_id=node.id,
            base_revision_id=baseline_id,
            status="candidate",
            document=document.model_dump(mode="json"),
            geometry_hash=geometry_hash(document),
            problems=problems,
            confirmation_id=None,
            context_fingerprint=_batch_marker(batch.id, index),
            task_id=uuid.UUID(shard["task_id"]),
            writing_chapter_index=await current_writing_chapter_index(db, novel_id),
            change_summary={
                "auto_draft_review_base_revision_id": str(node.current_revision_id)
                if node.current_revision_id
                else None,
            },
        )
        db.add(revision)
        await db.flush()
        batch.result_refs = [
            *list(batch.result_refs or []),
            MapAutoDraftRevisionRef(
                node_id=node.id,
                revision_id=revision.id,
                base_revision_id=baseline_id,
                status="candidate",
                feature_count=len(document.features),
                source_clue_ids=[
                    uuid.UUID(item) for item in shard.get("source_clue_ids", [])
                ],
            ).model_dump(mode="json"),
        ]
        batch.cursor = index + 1
        await db.flush()
    if batch.status == "running" and batch.cursor >= len(plan.get("shards", [])):
        batch.status = "completed"
    await db.flush()
    return _response(batch)


async def build_map_auto_drafts(
    db: AsyncSession,
    novel_id: str,
    request: MapAutoDraftBuildRequest | dict,
    *,
    _redo_reason: str | None = None,
) -> MapAutoDraftBuildResult:
    """Build one aggregate, deterministic candidate set after a reading batch."""
    await _lock_project_for_map_write(db, novel_id)
    request = MapAutoDraftBuildRequest.model_validate(request)
    scene = await _scene_contract(
        db,
        novel_id,
        str(request.through_scene_id),
        request.through_scene_index,
    )
    clue_rows = await _load_build_rows(db, novel_id, request)
    row_fingerprints = [
        {"id": str(row.id), "fingerprint": row.fingerprint} for row in clue_rows
    ]
    input_fingerprint = _digest(
        {
            "run_id": request.run_id,
            "build_key": request.build_key,
            "through_scene_id": str(scene.id),
            "through_scene_index": scene.scene_index,
            "clue_ids": [str(row.id) for row in clue_rows],
            "rows": row_fingerprints,
            "method_fingerprint": _method_fingerprint(),
        }
    )
    existing = await db.scalar(
        select(MapAutoDraftBatchRecord)
        .where(
            MapAutoDraftBatchRecord.novel_id == parse_uuid(novel_id, "novel_id"),
            MapAutoDraftBatchRecord.run_id == request.run_id,
            MapAutoDraftBatchRecord.build_key == request.build_key,
            MapAutoDraftBatchRecord.through_scene_id == str(scene.id),
        )
        .with_for_update()
    )
    if existing is not None:
        if existing.input_fingerprint != input_fingerprint:
            raise ConflictError("同一草图幂等键绑定了不同输入，请使用新的 build_key")
        if existing.status == "running":
            return await _process_batch(db, novel_id, existing)
        return _response(existing)

    batch_id = uuid.uuid4()
    plan, tray_items, conflicts = await _make_plan(
        db,
        novel_id,
        request,
        batch_id,
        clue_rows,
        input_fingerprint,
        force_redo_reason=_redo_reason,
    )
    batch = MapAutoDraftBatchRecord(
        id=batch_id,
        novel_id=parse_uuid(novel_id, "novel_id"),
        run_id=request.run_id,
        build_key=request.build_key,
        through_scene_id=str(scene.id),
        through_scene_index=scene.scene_index,
        input_fingerprint=input_fingerprint,
        method_fingerprint=_method_fingerprint(),
        status="running",
        cursor=0,
        plan_json=plan,
        result_refs=[],
        tray_items=tray_items,
        conflicts=conflicts,
    )
    db.add(batch)
    await db.flush()
    if not plan.get("shards"):
        batch.status = "completed"
        return _response(batch)
    return await _process_batch(db, novel_id, batch)


async def resume_map_auto_drafts(
    db: AsyncSession,
    novel_id: str,
    batch_id: str,
    request: MapAutoDraftResumeRequest | dict,
) -> MapAutoDraftBuildResult:
    await _lock_project_for_map_write(db, novel_id)
    request = MapAutoDraftResumeRequest.model_validate(request)
    batch = await db.scalar(
        select(MapAutoDraftBatchRecord)
        .where(
            MapAutoDraftBatchRecord.novel_id == parse_uuid(novel_id, "novel_id"),
            MapAutoDraftBatchRecord.id == parse_uuid(batch_id, "batch_id"),
        )
        .with_for_update()
    )
    if batch is None:
        raise NotFoundError("自动草图批次不存在")
    if batch.input_fingerprint != request.expected_fingerprint:
        raise ConflictError("草图批次已经变化，请刷新后再继续")
    return await _process_batch(db, novel_id, batch)


async def list_map_auto_drafts(
    db: AsyncSession,
    novel_id: str,
    *,
    node_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> MapAutoDraftListResponse:
    await require_active_project(db, novel_id)
    if not 1 <= limit <= 200 or offset < 0:
        raise ValidationError("自动草图列表范围无效")
    nid = parse_uuid(novel_id, "novel_id")
    batches = list(
        (
            await db.scalars(
                select(MapAutoDraftBatchRecord)
                .where(MapAutoDraftBatchRecord.novel_id == nid)
                .order_by(
                    MapAutoDraftBatchRecord.created_at.desc(), MapAutoDraftBatchRecord.id
                )
                .limit(201)
            )
        ).all()
    )
    batches_truncated = len(batches) > 200
    batches = batches[:200]
    batches_by_id = {batch.id: batch for batch in batches}
    conditions = [
        MapAtlasRevision.novel_id == nid,
        MapAtlasRevision.status.in_(["candidate", "superseded"]),
        MapAtlasRevision.context_fingerprint.like(f"{_AUTO_DRAFT_CONTEXT_PREFIX}%"),
    ]
    if node_id:
        conditions.append(MapAtlasRevision.node_id == parse_uuid(node_id, "node_id"))
    total_count = await db.scalar(
        select(func.count()).select_from(MapAtlasRevision).where(*conditions)
    )
    rows = (
        await db.execute(
            select(MapAtlasRevision, MapAtlasNode)
            .join(
                MapAtlasNode,
                (MapAtlasNode.id == MapAtlasRevision.node_id)
                & (MapAtlasNode.novel_id == MapAtlasRevision.novel_id),
            )
            .where(*conditions)
            .order_by(MapAtlasRevision.created_at.desc(), MapAtlasRevision.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    items: list[MapAutoDraftListItem] = []
    for revision, node in rows:
        batch_id = _marker_batch_id(revision.context_fingerprint)
        batch = batches_by_id.get(batch_id)
        if batch is None:
            batch = await db.scalar(
                select(MapAutoDraftBatchRecord).where(
                    MapAutoDraftBatchRecord.novel_id == nid,
                    MapAutoDraftBatchRecord.id == batch_id,
                )
            )
            if batch is not None:
                batches_by_id[batch.id] = batch
        ref = _batch_revision_ref(batch, revision.id)
        if batch is None or ref is None:
            continue
        document, warnings = await _project_candidate_entities(
            db, novel_id, MapDocument.model_validate(revision.document)
        )
        source_clue_ids = [str(item) for item in ref.get("source_clue_ids", [])]
        tray_clue_ids = [
            str(item.get("clue_id"))
            for item in batch.tray_items or []
            if str(item.get("node_id")) == str(node.id)
        ]
        dependency_stale = False
        dependency_ids = {
            parse_uuid(item, "clue_id") for item in {*source_clue_ids, *tray_clue_ids}
        }
        if dependency_ids and batch.status != "stale":
            dependency_rows = (
                await db.scalars(
                    select(MapSpatialClueRecord).where(
                        MapSpatialClueRecord.novel_id == parse_uuid(novel_id, "novel_id"),
                        MapSpatialClueRecord.id.in_(dependency_ids),
                    )
                )
            ).all()
            if {row.id for row in dependency_rows} != dependency_ids:
                dependency_stale = True
            else:
                _valid, invalid = await _validated_clue_inputs(
                    db,
                    novel_id,
                    list(dependency_rows),
                    through_scene_index=batch.through_scene_index,
                )
                dependency_stale = bool(invalid) or len(_valid) != len(dependency_rows)
        if dependency_stale:
            warnings.append("草图依赖的来源或线索已变化，请重新映射")
        pending = [
            MapAutoDraftTrayItem.model_validate(item)
            for item in _tray_dicts_for_node(batch, node.id)
        ]
        if batch.status == "running":
            warnings.append("自动草图分片尚未完成；继续后才能审核采用")
        if batch.status == "stale":
            warnings.append(batch.stale_reason or "草图依赖已变化，请重新映射")
        items.append(
            MapAutoDraftListItem(
                batch_id=batch.id,
                batch_status=batch.status,
                node_id=node.id,
                node_title=node.title,
                node=MapAtlasService._node_dict(node, [], []),
                revision_id=revision.id,
                base_revision_id=revision.base_revision_id,
                review_base_revision_id=auto_draft_review_base(revision),
                status=revision.status,
                fingerprint=batch.input_fingerprint,
                source_clue_ids=[uuid.UUID(item) for item in source_clue_ids],
                document=document,
                pending_tray=pending,
                conflicts=[
                    MapAutoDraftHierarchyConflict.model_validate(item)
                    for item in batch.conflicts or []
                    if any(
                        str(item.get("child_entity_id")) == str(feature.entity_id)
                        for feature in document.features
                    )
                ],
                redo_reason=(batch.plan_json or {}).get("redo_reason"),
                stale=batch.status == "stale" or dependency_stale,
                warnings=list(dict.fromkeys(warnings)),
            )
        )
    return MapAutoDraftListResponse(
        items=items,
        total_count=total_count,
        truncated=offset + len(items) < total_count,
        batches_truncated=batches_truncated,
        batches=[
            MapAutoDraftBatchProgress(
                batch_id=batch.id,
                fingerprint=batch.input_fingerprint,
                status=batch.status,
                cursor=batch.cursor,
                total_chunks=len((batch.plan_json or {}).get("shards", [])),
                completed_chunks=batch.cursor,
            )
            for batch in batches
        ],
    )


async def redo_map_auto_drafts(
    db: AsyncSession,
    novel_id: str,
    batch_id: str,
    request: MapAutoDraftRedoRequest | dict,
) -> MapAutoDraftBuildResult:
    await _lock_project_for_map_write(db, novel_id)
    request = MapAutoDraftRedoRequest.model_validate(request)
    batch = await db.scalar(
        select(MapAutoDraftBatchRecord).where(
            MapAutoDraftBatchRecord.novel_id == parse_uuid(novel_id, "novel_id"),
            MapAutoDraftBatchRecord.id == parse_uuid(batch_id, "batch_id"),
        )
    )
    if batch is None:
        raise NotFoundError("自动草图批次不存在")
    if batch.input_fingerprint != request.expected_fingerprint:
        raise ConflictError("草图批次已经变化，请刷新后重做")
    redo_suffix = f":redo:{uuid.uuid4().hex[:12]}"
    redo_key = f"{batch.build_key[: 120 - len(redo_suffix)]}{redo_suffix}"
    source_clue_ids = sorted(
        {
            clue_id
            for ref in (batch.result_refs or [])
            for clue_id in ref.get("source_clue_ids", [])
        }
        | {str(item) for item in (batch.plan_json or {}).get("clue_ids", [])}
    )
    return await build_map_auto_drafts(
        db,
        novel_id,
        MapAutoDraftBuildRequest(
            run_id=batch.run_id,
            build_key=redo_key,
            through_scene_id=uuid.UUID(batch.through_scene_id),
            through_scene_index=batch.through_scene_index,
            clue_ids=[uuid.UUID(item) for item in source_clue_ids],
        ),
        _redo_reason="author_requested",
    )


async def _tray_item_context(
    db: AsyncSession,
    novel_id: str,
    batch_id: str,
    node_id: str,
    revision_id: str,
    item_id: str,
    expected_fingerprint: str,
) -> tuple[MapAutoDraftBatchRecord, MapAtlasNode, MapAtlasRevision, dict, dict, dict]:
    batch = await db.scalar(
        select(MapAutoDraftBatchRecord)
        .where(
            MapAutoDraftBatchRecord.novel_id == parse_uuid(novel_id, "novel_id"),
            MapAutoDraftBatchRecord.id == parse_uuid(batch_id, "batch_id"),
        )
        .with_for_update()
    )
    if batch is None:
        raise NotFoundError("自动草图批次不存在")
    if batch.status != "completed":
        raise ConflictError("请先完成全部草图分片后再放置托盘地点")
    tray = next(
        (
            item
            for item in batch.tray_items or []
            if str(item.get("item_id")) == str(item_id)
        ),
        None,
    )
    if tray is None or str(tray.get("node_id")) != str(node_id):
        raise NotFoundError("待放置托盘项目不存在")
    if tray.get("fingerprint") != expected_fingerprint:
        raise ConflictError("待放置项目已经变化，请刷新后重试")
    node = await db.scalar(
        select(MapAtlasNode)
        .where(
            MapAtlasNode.novel_id == parse_uuid(novel_id, "novel_id"),
            MapAtlasNode.id == parse_uuid(node_id, "node_id"),
        )
        .with_for_update()
    )
    if node is None:
        raise NotFoundError("地图节点不存在")
    revision = await db.scalar(
        select(MapAtlasRevision)
        .where(
            MapAtlasRevision.novel_id == parse_uuid(novel_id, "novel_id"),
            MapAtlasRevision.node_id == node.id,
            MapAtlasRevision.id == parse_uuid(revision_id, "revision_id"),
        )
        .with_for_update()
    )
    if revision is None:
        raise NotFoundError("自动草图版本不存在")
    if (
        revision.status
        not in (
            {"candidate", "superseded"}
            if tray.get("placed_feature_id")
            else {"candidate"}
        )
        or _marker_batch_id(revision.context_fingerprint) != batch.id
        or node.current_revision_id != auto_draft_review_base(revision)
    ):
        raise ConflictError("自动草图或正式基线已经变化，请重新比较")
    return batch, node, revision, tray, batch.plan_json or {}, batch.result_refs or []


async def _placement_document(
    db: AsyncSession,
    novel_id: str,
    batch: MapAutoDraftBatchRecord,
    node: MapAtlasNode,
    revision: MapAtlasRevision,
    tray: dict,
    request: MapAutoDraftTrayPlacementPreviewRequest,
) -> tuple[MapDocument, str, list[str]]:
    document = MapDocument.model_validate(revision.document).model_copy(deep=True)
    endpoint = MapSpatialClueEndpoint.model_validate(tray["endpoint"])
    clue_row = await db.scalar(
        select(MapSpatialClueRecord).where(
            MapSpatialClueRecord.novel_id == parse_uuid(novel_id, "novel_id"),
            MapSpatialClueRecord.id == parse_uuid(tray["clue_id"], "clue_id"),
        )
    )
    if clue_row is None or clue_row.status not in {"pending_review", "adopted"}:
        raise ConflictError("线索已拒绝、合并或失效，请重新映射")
    clue = MapSpatialClue.model_validate(clue_row.clue_payload)
    binding = MapSpatialClueSourceBinding.model_validate(clue_row.source_binding)
    resolved_endpoints = await _revalidate_stored_clue(
        db,
        novel_id,
        clue_row,
        clue,
        allow_identity_transitions=True,
    )
    resolved_sources = await _resolve_binding(
        db,
        novel_id,
        clue_row.scene_id,
        clue_row.scene_index,
        binding,
    )
    _matching_source_hash(clue, resolved_sources)
    canonical_source, _source_issue = await _unique_canonical_source(
        db, novel_id, clue_row, clue, resolved_sources
    )
    entity = (
        resolved_endpoints.get(str(endpoint.entity_id))
        if endpoint.entity_id is not None
        else None
    )
    if entity is not None and entity.entity_type.casefold() != "location":
        entity = None
    if request.space_id not in {space.id for space in document.spaces}:
        raise ValidationError("请选择当前草图中的空间")
    feature_id = (
        _feature_id(entity.id)
        if entity is not None
        else f"t_{uuid.UUID(str(tray['item_id'])).hex}"
    )
    by_entity = {
        item.entity_id: item for item in document.features if item.entity_id is not None
    }
    feature = by_entity.get(entity.id) if entity is not None else None
    if feature is None:
        feature = next(
            (item for item in document.features if item.id == feature_id), None
        )
    if feature is None:
        if len(document.features) >= AUTO_DRAFT_FEATURE_LIMIT:
            raise ConflictError("该分片已达到 200 个图元上限，请选择其他分片")
        label = (
            entity.name
            if entity is not None
            else endpoint.surface
            or (
                clue.subject.surface
                if tray["endpoint_side"] == "subject"
                else clue.target.surface
            )
            or "待核地点"
        )
        feature = MapFeature(
            id=feature_id,
            kind="location",
            label=label[:200],
            space_id=request.space_id,
            entity_id=entity.id if entity is not None else None,
            points=[request.point],
            locked=True,
            sources=[canonical_source] if canonical_source is not None else [],
            note="作者手动放置；地点身份仍按 World 门禁审核",
            modality=clue.modality,
            effective=clue.attributes.effective,
        )
        document.features.append(feature)
    else:
        feature.points = [request.point]
        feature.space_id = request.space_id
        feature.locked = True
        if canonical_source is not None and all(
            _map_source_key(item) != _map_source_key(canonical_source)
            for item in feature.sources
        ):
            if len(feature.sources) < 8:
                feature.sources.append(canonical_source)
    warnings = []
    overlaps = [
        other.id
        for other in document.features
        if other.id != feature.id
        and other.space_id == request.space_id
        and other.points
        and (other.points[0].x, other.points[0].y) == (request.point.x, request.point.y)
    ]
    if overlaps:
        warnings.append("放置点与现有图元重合，请在预览中核对")
    return document, feature.id, warnings


async def preview_map_auto_draft_tray_placement(
    db: AsyncSession,
    novel_id: str,
    batch_id: str,
    node_id: str,
    revision_id: str,
    item_id: str,
    request: MapAutoDraftTrayPlacementPreviewRequest | dict,
) -> MapAutoDraftTrayPlacementPreview:
    await require_active_project(db, novel_id)
    request = MapAutoDraftTrayPlacementPreviewRequest.model_validate(request)
    batch, node, revision, tray, _plan, _refs = await _tray_item_context(
        db,
        novel_id,
        batch_id,
        node_id,
        revision_id,
        item_id,
        request.expected_fingerprint,
    )
    if request.base_revision_id != node.current_revision_id:
        raise ConflictError("地图正式版本已变化，请刷新后再预览")
    document, feature_id, warnings = await _placement_document(
        db, novel_id, batch, node, revision, tray, request
    )
    return MapAutoDraftTrayPlacementPreview(
        batch_id=batch.id,
        node_id=node.id,
        candidate_revision_id=revision.id,
        base_revision_id=node.current_revision_id,
        item_id=uuid.UUID(str(tray["item_id"])),
        preview_fingerprint=_tray_preview_fingerprint(
            batch, revision, tray, request, feature_id, document
        ),
        feature_id=feature_id,
        old_feature_count=len(MapDocument.model_validate(revision.document).features),
        new_feature_count=len(document.features),
        remaining_tray_count=sum(
            1
            for item in batch.tray_items or []
            if str(item.get("node_id")) == str(node.id)
            and not item.get("placed_feature_id")
            and str(item.get("item_id")) != str(tray["item_id"])
        ),
        impacts=[
            "仅更新自动草图候选，不改正式地图版本",
            "作者选定的坐标会锁定，不会被后续增量布局移动",
            "候选地点仍需单独通过 World 采用门禁",
        ],
        warnings=warnings,
    )


async def place_map_auto_draft_tray_item(
    db: AsyncSession,
    novel_id: str,
    batch_id: str,
    node_id: str,
    revision_id: str,
    item_id: str,
    request: MapAutoDraftTrayPlacementRequest | dict,
) -> MapAutoDraftTrayPlacementResponse:
    await _lock_project_for_map_write(db, novel_id)
    request = MapAutoDraftTrayPlacementRequest.model_validate(request)
    batch, node, revision, tray, _plan, refs = await _tray_item_context(
        db,
        novel_id,
        batch_id,
        node_id,
        revision_id,
        item_id,
        request.expected_fingerprint,
    )
    if request.base_revision_id != node.current_revision_id:
        raise ConflictError("地图正式版本已变化，请刷新后再放置")
    if tray.get("placed_feature_id"):
        latest_ref = next(
            (
                item
                for item in reversed(refs)
                if str(item.get("node_id")) == str(node.id)
                and item.get("status") == "candidate"
            ),
            None,
        )
        if latest_ref is None:
            raise ConflictError("托盘项目已放置，但后续版本已结束")
        latest = await _load_revision(
            db, novel_id, node.id, uuid.UUID(latest_ref["revision_id"])
        )
        document = MapDocument.model_validate(latest.document)
        feature = next(
            (item for item in document.features if item.id == tray["placed_feature_id"]),
            None,
        )
        if (
            feature is None
            or feature.points != [request.point]
            or feature.space_id != request.space_id
        ):
            raise ConflictError("该托盘项目已经用其他位置放置")
        return MapAutoDraftTrayPlacementResponse(
            batch_id=batch.id,
            node_id=node.id,
            revision_id=latest.id,
            previous_revision_id=revision.id,
            placed_feature_id=feature.id,
            geometry_hash=latest.geometry_hash,
            remaining_tray_count=sum(
                1
                for item in batch.tray_items or []
                if str(item.get("node_id")) == str(node.id)
                and not item.get("placed_feature_id")
            ),
            status="candidate",
        )
    document, feature_id, _warnings = await _placement_document(
        db, novel_id, batch, node, revision, tray, request
    )
    preview_fingerprint = _tray_preview_fingerprint(
        batch, revision, tray, request, feature_id, document
    )
    if preview_fingerprint != request.preview_fingerprint:
        raise ConflictError("托盘放置内容与预览不一致，请重新预览后确认")
    candidate_marker = revision.context_fingerprint or _batch_marker(batch.id, 0)
    shard_index = int(candidate_marker.rsplit(":", 1)[-1])
    previous_ref = _batch_revision_ref(batch, revision.id)
    source_clue_ids = list((previous_ref or {}).get("source_clue_ids", []))
    source_clue_ids = sorted({*source_clue_ids, str(tray["clue_id"])})
    await _mark_old_revision_superseded(db, novel_id, revision)
    from modules.world.services.common import current_writing_chapter_index

    new_revision = MapAtlasRevision(
        novel_id=node.novel_id,
        node_id=node.id,
        base_revision_id=revision.id,
        status="candidate",
        document=document.model_dump(mode="json"),
        geometry_hash=geometry_hash(document),
        problems=[problem.model_dump(mode="json") for problem in diagnose(document)],
        confirmation_id=None,
        context_fingerprint=_batch_marker(batch.id, shard_index),
        task_id=uuid.uuid4(),
        writing_chapter_index=await current_writing_chapter_index(db, novel_id),
        change_summary={
            "auto_draft_review_base_revision_id": str(node.current_revision_id)
            if node.current_revision_id
            else None,
        },
    )
    db.add(new_revision)
    await db.flush()
    updated_refs = list(batch.result_refs or [])
    updated_refs.append(
        MapAutoDraftRevisionRef(
            node_id=node.id,
            revision_id=new_revision.id,
            base_revision_id=revision.id,
            status="candidate",
            feature_count=len(document.features),
            source_clue_ids=[uuid.UUID(value) for value in source_clue_ids],
        ).model_dump(mode="json")
    )
    batch.result_refs = updated_refs
    updated_tray = []
    for item in batch.tray_items or []:
        copied = dict(item)
        if str(copied.get("item_id")) == str(tray["item_id"]):
            copied["placed_feature_id"] = feature_id
        updated_tray.append(copied)
    batch.tray_items = updated_tray
    await db.flush()
    return MapAutoDraftTrayPlacementResponse(
        batch_id=batch.id,
        node_id=node.id,
        revision_id=new_revision.id,
        previous_revision_id=revision.id,
        placed_feature_id=feature_id,
        geometry_hash=new_revision.geometry_hash,
        remaining_tray_count=sum(
            1
            for item in batch.tray_items
            if str(item.get("node_id")) == str(node.id)
            and not item.get("placed_feature_id")
        ),
        status="candidate",
    )


__all__ = [
    "build_map_auto_drafts",
    "list_map_auto_drafts",
    "place_map_auto_draft_tray_item",
    "preview_map_auto_draft_tray_placement",
    "redo_map_auto_drafts",
    "resume_map_auto_drafts",
]
