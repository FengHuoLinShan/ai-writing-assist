"""Typed, read-only adopted-map route projection for Story world progression."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, select

from infrastructure.llm.collaboration import content_hash
from modules.evidence.contracts import VisibilityContextContract
from modules.world.entity_facade import get_hidden_guard_sources
from modules.world.map_atlas_models import MapAtlasNode, MapAtlasRevision
from modules.world.map_spatial_anchors import resolve_validity
from modules.world.map_structure_schemas import MapDocument
from modules.world.map_structure_service import (
    MapStructureService,
    _document_type_references,
    _spatial_item_type_pairs,
    read_map_node_heads,
    resolve_spatial_vocabulary_references,
)
from shared.utils import parse_uuid


class ProgressionMapRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route_ref_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    node_id: str
    revision_id: str
    kind: Literal["journey"]
    feature_key: str
    origin_id: str
    origin_kind: Literal["object", "map_node"]
    destination_id: str
    destination_kind: Literal["object", "map_node"]
    source_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


class ProgressionMapState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    novel_id: str
    scene_id: str
    scene_index: int = Field(ge=0)
    routes: list[ProgressionMapRoute] = Field(default_factory=list)
    actor_routes: dict[str, list[ProgressionMapRoute]] = Field(default_factory=dict)
    revision_fingerprints: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    coverage: Literal["available", "partial", "not_available"]
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


def _source_fingerprint(journey) -> str:
    return content_hash(
        {
            "sources": sorted(
                (str(item.kind), str(item.id), str(item.source_hash))
                for item in journey.sources
            ),
            "author_decision": (
                journey.author_decision.model_dump(mode="json")
                if journey.author_decision
                else None
            ),
            "types": [
                str(value)
                for value in (
                    journey.transport_type_ref,
                    journey.transport_type_revision_id,
                    journey.traveler_type_ref,
                    journey.traveler_type_revision_id,
                    journey.connection_type_ref,
                    journey.connection_type_revision_id,
                )
                if value is not None
            ],
        }
    )


def _active_at(
    validity, *, scene_index: int, scenes: list[dict], unknowns: list[str]
) -> bool:
    if validity is None:
        return True
    resolved = resolve_validity(validity, scenes)
    if not resolved.valid:
        unknowns.append(f"spatial_validity:{resolved.reason or 'unknown'}")
        return False
    return not (
        resolved.start_scene_index is not None
        and scene_index < resolved.start_scene_index
        or resolved.end_scene_index is not None
        and scene_index > resolved.end_scene_index
    )


async def _read_story_scene_anchors(db, novel_id: str) -> list[dict]:
    from core.container import get
    from core.service_keys import STORY_SCENE_SOURCE

    port = get(STORY_SCENE_SOURCE)
    return await port.read_temporal_anchor_scenes(db, novel_id)


async def _read_cutoff_chapter(db, novel_id: str, scene_id: str) -> int | None:
    from core.container import get
    from core.service_keys import STORY_SCENE_SOURCE

    view = await get(STORY_SCENE_SOURCE).get_scene_state_view(
        db,
        novel_id,
        scene_id,
        viewpoint={"kind": "author"},
        include_dimensions=["locations"],
    )
    if isinstance(view, dict):
        value = view
    elif hasattr(view, "model_dump"):
        value = view.model_dump(mode="json")
    elif hasattr(view, "__dataclass_fields__"):
        from dataclasses import asdict

        value = asdict(view)
    else:
        value = {}
    chapter = value.get("chapter_index")
    return (
        int(chapter)
        if value.get("status") != "degraded" and isinstance(chapter, int) and chapter > 0
        else None
    )


async def read_map_progression_state(
    db,
    *,
    novel_id: str,
    scene_id: str,
    scene_index: int,
    actor_ids: list[str],
) -> ProgressionMapState:
    """Read current saved journeys at the author cutoff and each actor's view."""
    novel_uuid = parse_uuid(novel_id, "novel_id")
    scenes = await _read_story_scene_anchors(db, novel_id)
    cutoff = next(
        (
            item
            for item in scenes
            if str(item.get("scene_id")) == scene_id
            and int(item.get("scene_index") or -1) == int(scene_index)
        ),
        None,
    )
    if cutoff is None:
        raise ValueError("地图路线读取的 Scene 截止点已变化或不可用")
    cutoff_chapter = await _read_cutoff_chapter(db, novel_id, scene_id)

    rows = (
        await db.execute(
            select(MapAtlasNode, MapAtlasRevision)
            .join(
                MapAtlasRevision,
                and_(
                    MapAtlasRevision.id == MapAtlasNode.current_revision_id,
                    MapAtlasRevision.novel_id == MapAtlasNode.novel_id,
                    MapAtlasRevision.node_id == MapAtlasNode.id,
                ),
            )
            .where(
                MapAtlasNode.novel_id == novel_uuid,
                MapAtlasNode.status == "adopted",
                MapAtlasNode.merged_into_node_id.is_(None),
                MapAtlasRevision.status == "saved",
            )
            .order_by(MapAtlasNode.id)
        )
    ).all()
    service = MapStructureService()
    unknowns: list[str] = []
    routes: list[ProgressionMapRoute] = []
    actor_routes: dict[str, list[ProgressionMapRoute]] = {
        actor_id: [] for actor_id in actor_ids
    }
    revision_fingerprints: list[str] = []
    source_checks: list[tuple[ProgressionMapRoute, object, MapDocument]] = []
    entity_ids: set[str] = set()
    map_node_ids: set[str] = set()

    for node, revision in rows:
        try:
            document = MapDocument.model_validate(revision.document)
        except Exception as exc:
            unknowns.append(f"map_document:{node.id}:{type(exc).__name__}")
            continue
        revision_fingerprints.append(
            content_hash(
                {
                    "node_id": str(node.id),
                    "revision_id": str(revision.id),
                    "geometry_hash": str(revision.geometry_hash or ""),
                    "document": document.model_dump(mode="json"),
                }
            )
        )
        features = {feature.id: feature for feature in document.features}
        for journey in document.journeys:
            if not _active_at(
                journey.effective,
                scene_index=scene_index,
                scenes=scenes,
                unknowns=unknowns,
            ):
                continue
            origin, destination = (
                features.get(journey.origin),
                features.get(journey.destination),
            )
            if origin is None or destination is None:
                unknowns.append(f"journey_endpoint_missing:{node.id}:{journey.id}")
                continue
            if not _active_at(
                origin.effective,
                scene_index=scene_index,
                scenes=scenes,
                unknowns=unknowns,
            ):
                continue
            if not _active_at(
                destination.effective,
                scene_index=scene_index,
                scenes=scenes,
                unknowns=unknowns,
            ):
                continue
            if (
                origin.modality != "event_observed"
                or destination.modality != "event_observed"
            ):
                continue
            origin_identity = str(origin.entity_id or origin.target_node_id or "")
            destination_identity = str(
                destination.entity_id or destination.target_node_id or ""
            )
            origin_kind = "object" if origin.entity_id else "map_node"
            destination_kind = "object" if destination.entity_id else "map_node"
            if not origin_identity or not destination_identity:
                unknowns.append(
                    f"journey_endpoint_identity_missing:{node.id}:{journey.id}"
                )
                continue
            if origin.entity_id:
                entity_ids.add(str(origin.entity_id))
            if destination.entity_id:
                entity_ids.add(str(destination.entity_id))
            if origin.target_node_id:
                map_node_ids.add(str(origin.target_node_id))
            if destination.target_node_id:
                map_node_ids.add(str(destination.target_node_id))
            source_fingerprint = _source_fingerprint(journey)
            route_ref_id = content_hash(
                {
                    "node_id": str(node.id),
                    "revision_id": str(revision.id),
                    "kind": "journey",
                    "feature_key": str(journey.id),
                    "source_fingerprint": source_fingerprint,
                    "origin_feature_key": str(journey.origin),
                    "destination_feature_key": str(journey.destination),
                }
            )
            route = ProgressionMapRoute(
                route_ref_id=route_ref_id,
                node_id=str(node.id),
                revision_id=str(revision.id),
                kind="journey",
                feature_key=str(journey.id),
                origin_id=origin_identity,
                origin_kind=origin_kind,
                destination_id=destination_identity,
                destination_kind=destination_kind,
                source_fingerprint=source_fingerprint,
            )
            source_checks.append((route, journey, document))

    entities, _ = await get_hidden_guard_sources(
        db,
        novel_id=novel_id,
        entity_ids=sorted(entity_ids),
        relation_ids=[],
    )
    canonical_entities = {
        str(item.entity_id) for item in entities if str(item.status) == "canonical"
    }
    map_heads = await read_map_node_heads(db, novel_id, sorted(map_node_ids))
    canonical_map_nodes = {
        node_id for node_id, head in map_heads.items() if head.get("status") == "adopted"
    }

    for route, journey, document in source_checks:
        if (
            route.origin_id not in canonical_entities | canonical_map_nodes
            or route.destination_id not in canonical_entities | canonical_map_nodes
        ):
            unknowns.append(
                f"journey_endpoint_not_canonical:{route.node_id}:{route.feature_key}"
            )
            continue
        if journey.sources:
            source_valid = True
            for source in journey.sources:
                try:
                    await service.source(db, novel_id, source)
                except Exception:
                    unknowns.append(
                        f"journey_source_changed:{route.node_id}:{route.feature_key}"
                    )
                    source_valid = False
                    break
            if not source_valid:
                continue
        elif journey.author_decision is None:
            unknowns.append(f"journey_source_missing:{route.node_id}:{route.feature_key}")
            continue

        type_refs = _document_type_references(document)
        resolved_types = await resolve_spatial_vocabulary_references(
            db, novel_id, type_refs
        )
        type_pairs = _spatial_item_type_pairs(journey)
        if any(
            type_ref is not None
            and not resolved_types.get((type_ref, revision_id), {}).get("computable")
            for type_ref, revision_id in type_pairs
        ):
            unknowns.append(
                f"journey_type_unavailable:{route.node_id}:{route.feature_key}"
            )
            continue
        routes.append(route)

        for actor_id in actor_ids:
            if not journey.sources:
                continue
            visibility = VisibilityContextContract(
                mode="character",
                cutoff_chapter=cutoff_chapter,
                cutoff_scene_id=scene_id,
                character_id=actor_id,
            )
            allowed = True
            for source in journey.sources:
                if not await service.reader_source_visible(
                    db, novel_id, source, visibility
                ):
                    allowed = False
                    break
            if allowed:
                actor_routes[actor_id].append(route)

    # Match only saved route revisions whose sources passed validation.
    route_ids = {item.route_ref_id for item in routes}
    for actor_id in actor_ids:
        actor_routes[actor_id] = [
            item for item in actor_routes[actor_id] if item.route_ref_id in route_ids
        ]
    unique_routes = {item.route_ref_id: item for item in routes}
    routes = list(unique_routes.values())
    fingerprint = content_hash(
        {
            "novel_id": novel_id,
            "scene_id": scene_id,
            "scene_index": scene_index,
            "routes": [item.model_dump(mode="json") for item in routes],
            "actor_routes": {
                actor: [item.route_ref_id for item in items]
                for actor, items in sorted(actor_routes.items())
            },
            "revisions": sorted(revision_fingerprints),
            "unknowns": sorted(set(unknowns)),
        }
    )
    if not routes:
        coverage = "not_available"
    elif unknowns:
        coverage = "partial"
    else:
        coverage = "available"
    return ProgressionMapState(
        novel_id=novel_id,
        scene_id=scene_id,
        scene_index=scene_index,
        routes=routes,
        actor_routes=actor_routes,
        revision_fingerprints=sorted(revision_fingerprints),
        unknowns=sorted(set(unknowns)),
        coverage=coverage,
        fingerprint=fingerprint,
    )
