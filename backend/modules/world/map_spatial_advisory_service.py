"""Deterministic, read-only advisories over adopted spatial revisions."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, is_dataclass
from typing import Any

from sqlalchemy import and_, select

from core.container import get
from core.errors import ConflictError, NotFoundError, ValidationError
from core.service_keys import PROJECT_REQUIRE_ACTIVE
from infrastructure.stable_hash import stable_hash
from modules.evidence import facade as evidence_facade
from modules.evidence.contracts import VisibilityContextContract
from modules.world.map_spatial_advisory_schemas import (
    MapSpatialAdvisoryItem,
    MapSpatialAdvisoryMapRevision,
    MapSpatialAdvisoryRequest,
    MapSpatialAdvisoryResponse,
)
from modules.writing.contracts import SourceRangeRefContract

_ACTIVE_SCENES = frozenset({"candidate", "draft", "canonical"})
_CONNECTIONS = frozenset({"adjacent", "connects", "passes_through", "entrance_to"})
_DIRECTIONS = {
    "north": "south",
    "south": "north",
    "east": "west",
    "west": "east",
    "northeast": "southwest",
    "southwest": "northeast",
    "northwest": "southeast",
    "southeast": "northwest",
}
_MAX_MAP_NODES = 200
_MAX_ADVISORIES = 100


def _as_dict(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="python")
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    return {}


def _within_cutoff(item: object, *, scenes: list[dict], scene_index: int) -> bool:
    effective = getattr(item, "effective", None)
    if effective is None:
        return True
    from modules.world.map_spatial_anchors import resolve_validity

    resolved = resolve_validity(effective, scenes)
    return bool(
        resolved.valid
        and (
            resolved.start_scene_index is None
            or resolved.start_scene_index <= scene_index
        )
        and (resolved.end_scene_index is None or scene_index <= resolved.end_scene_index)
    )


def _outside_cutoff(item: object, *, scenes: list[dict], scene_index: int) -> bool:
    effective = getattr(item, "effective", None)
    if effective is None:
        return False
    from modules.world.map_spatial_anchors import resolve_validity

    resolved = resolve_validity(effective, scenes)
    return bool(
        resolved.valid
        and resolved.end_scene_index is not None
        and resolved.end_scene_index < scene_index
    )


def _excluded_by_validity(item: object, *, scenes: list[dict], scene_index: int) -> bool:
    effective = getattr(item, "effective", None)
    if effective is None:
        return False
    from modules.world.map_spatial_anchors import resolve_validity

    resolved = resolve_validity(effective, scenes)
    return bool(
        resolved.valid
        and (
            resolved.start_scene_index is not None
            and resolved.start_scene_index > scene_index
            or resolved.end_scene_index is not None
            and resolved.end_scene_index < scene_index
        )
    )


def _source_hashes(items: list[object]) -> list[str]:
    result = {
        str(source.source_hash)
        for item in items
        for source in (getattr(item, "sources", None) or [])
    }
    for item in items:
        decision = getattr(item, "author_decision", None)
        statement_hash = getattr(decision, "statement_hash", None)
        if statement_hash:
            result.add(str(statement_hash))
    return sorted(result)[:32]


def _intervals_disjoint(left: object, right: object) -> bool:
    if getattr(left, "unit", "").casefold() != getattr(right, "unit", "").casefold():
        return False
    left_min, left_max = left.minimum, left.maximum
    right_min, right_max = right.minimum, right.maximum
    return bool(
        left_max is not None
        and right_min is not None
        and left_max < right_min
        or right_max is not None
        and left_min is not None
        and right_max < left_min
    )


def _journey_key(journey: object) -> tuple:
    mode = (
        (str(journey.transport_type_ref), str(journey.transport_type_revision_id))
        if journey.transport_type_ref
        else journey.transport_label.strip().casefold()
    )
    traveler = (
        (str(journey.traveler_type_ref), str(journey.traveler_type_revision_id))
        if journey.traveler_type_ref
        else None
    )
    conditions = tuple(
        sorted(
            (
                str(condition.type_ref) if condition.type_ref else "",
                str(condition.type_revision_id) if condition.type_revision_id else "",
                condition.label.strip().casefold(),
            )
            for condition in journey.access_conditions
        )
    )
    return journey.origin, journey.destination, mode, traveler, conditions


def _direction_conflicts(features: dict[str, object], constraints: list[object]):
    compass: dict[tuple[str, str], dict[str, object]] = defaultdict(dict)
    for constraint in constraints:
        if constraint.relation not in _DIRECTIONS:
            continue
        left = features.get(constraint.subject)
        right = features.get(constraint.target)
        if (
            left is None
            or right is None
            or not getattr(left, "entity_id", None)
            or not getattr(right, "entity_id", None)
            or getattr(left, "space_id", None) != getattr(right, "space_id", None)
        ):
            continue
        compass[(constraint.subject, constraint.target)][constraint.relation] = constraint
    result = []
    seen: set[frozenset[str]] = set()
    for (left_id, right_id), directions in compass.items():
        pair_key = frozenset((left_id, right_id))
        if pair_key in seen:
            continue
        for direction in _DIRECTIONS:
            if direction not in directions:
                continue
            reverse = compass.get((right_id, left_id), {})
            opposing = directions.get(_DIRECTIONS[direction]) or reverse.get(direction)
            if opposing is not None:
                seen.add(pair_key)
                result.append((left_id, right_id, directions[direction], opposing))
                break
    return result


class MapSpatialAdvisoryService:
    async def read(
        self, db, request: MapSpatialAdvisoryRequest | dict
    ) -> MapSpatialAdvisoryResponse:
        from core.service_keys import STORY_SCENE_SOURCE
        from modules.world.contracts import KnowledgeVisibilityRequest
        from modules.world.facade import check_knowledge_visibility
        from modules.world.map_atlas_models import MapAtlasNode, MapAtlasRevision
        from modules.world.map_merge_lineage import (
            EXCLUDED_MERGE_UNKNOWN,
            excluded_merge_targets,
        )
        from modules.world.map_structure_geometry import (
            _path_is_calculable,
            constraint_is_calculable,
        )
        from modules.world.map_structure_schemas import MapDocument
        from modules.world.map_structure_service import (
            MapStructureService,
            _document_type_references,
            resolve_spatial_vocabulary_references,
        )
        from shared.utils import parse_uuid

        data = (
            request
            if isinstance(request, MapSpatialAdvisoryRequest)
            else MapSpatialAdvisoryRequest.model_validate(request)
        )
        await get(PROJECT_REQUIRE_ACTIVE)(db, data.novel_id)
        if data.reveal_mode == "character" and not data.viewpoint_character_id:
            raise ValidationError("角色视角空间提醒必须指定视角人物")
        excluded = {
            part
            for value in data.excluded_ids
            for part in (str(value).split(":")[1:] or [str(value)])
        }
        story_port = get(STORY_SCENE_SOURCE)
        scene = await story_port.get_scene_contract(db, data.novel_id, data.scene_id)
        scene_data = _as_dict(scene)
        if (
            not scene_data
            or str(scene_data.get("novel_id")) != str(data.novel_id)
            or str(scene_data.get("id")) != str(data.scene_id)
            or scene_data.get("status") not in _ACTIVE_SCENES
        ):
            return MapSpatialAdvisoryResponse(scene_id=data.scene_id)
        scene_index = scene_data.get("scene_index")
        if (
            isinstance(scene_index, bool)
            or not isinstance(scene_index, int)
            or scene_index < 0
        ):
            return MapSpatialAdvisoryResponse(scene_id=data.scene_id)
        metadata = scene_data.get("structure_meta") or {}
        scene_locations = {
            str(metadata[key])
            for key in ("location_id", "location_entity_id")
            if metadata.get(key)
        }
        scene_locations.update(
            location
            for transition in data.transitions
            for location in (transition.from_location_id, transition.to_location_id)
        )
        scene_locations.difference_update(excluded)
        if not scene_locations:
            return MapSpatialAdvisoryResponse(
                scene_id=data.scene_id,
                scene_index=scene_index,
                unknowns=[
                    "本场没有显式地点身份，无法核对地图；未根据名称或坐标猜测地点。"
                ],
            )
        temporal_scenes = await story_port.read_temporal_anchor_scenes(db, data.novel_id)
        temporal_scenes = [
            _as_dict(item)
            for item in temporal_scenes
            if isinstance(item, dict) or hasattr(item, "model_dump") or is_dataclass(item)
        ]
        scene_chapters = [
            int(value)
            for value in scene_data.get("chapter_ids") or []
            if str(value).isdigit() and int(value) > 0
        ]
        cutoff_chapter = max(scene_chapters, default=None)
        state_view = await story_port.get_scene_state_view(
            db,
            data.novel_id,
            data.scene_id,
            viewpoint={"kind": "author"},
            include_dimensions=["locations"],
        )
        state_view = _as_dict(state_view)
        if state_view.get("status") != "degraded":
            chapter = state_view.get("chapter_index")
            if isinstance(chapter, int) and chapter > 0:
                cutoff_chapter = min(
                    chapter,
                    cutoff_chapter if cutoff_chapter is not None else chapter,
                )

        rows = list(
            (
                await db.execute(
                    select(MapAtlasNode, MapAtlasRevision)
                    .join(
                        MapAtlasRevision,
                        and_(
                            MapAtlasRevision.id == MapAtlasNode.current_revision_id,
                            MapAtlasRevision.node_id == MapAtlasNode.id,
                            MapAtlasRevision.novel_id == MapAtlasNode.novel_id,
                        ),
                    )
                    .where(
                        MapAtlasNode.novel_id == parse_uuid(data.novel_id, "novel_id"),
                        MapAtlasNode.status == "adopted",
                        MapAtlasNode.merged_into_node_id.is_(None),
                        MapAtlasRevision.status == "saved",
                    )
                    .order_by(MapAtlasNode.sort_order, MapAtlasNode.id)
                    .limit(_MAX_MAP_NODES + 1)
                )
            ).all()
        )
        if cutoff_chapter is None:
            return MapSpatialAdvisoryResponse(
                scene_id=data.scene_id,
                scene_index=scene_index,
                unknowns=["本场没有可核对的截止章节，空间资料未核对。"] if rows else [],
            )
        docs: list[tuple[object, object, MapDocument]] = []
        type_refs: dict[tuple, str] = {}
        omitted = max(0, len(rows) - _MAX_MAP_NODES)
        excluded_merges = await excluded_merge_targets(
            db,
            data.novel_id,
            [node.id for node, _ in rows[:_MAX_MAP_NODES]],
            excluded_nodes=excluded,
            excluded_revisions=excluded,
        )
        for node, revision in rows[:_MAX_MAP_NODES]:
            if str(node.id) in excluded_merges:
                omitted += 1
                continue
            if str(node.id) in excluded or str(revision.id) in excluded:
                continue
            try:
                document = MapDocument.model_validate(revision.document)
                if not any(
                    str(feature.entity_id or "") in scene_locations
                    for feature in document.features
                ):
                    continue
                for pair, kind in _document_type_references(document).items():
                    prior = type_refs.setdefault(pair, kind)
                    if prior != kind:
                        raise ValidationError("同一项目类型不能被当作不同空间类型使用")
            except (ValidationError, TypeError, ValueError):
                omitted += 1
                continue
            docs.append((node, revision, document))
        try:
            resolved_types = await resolve_spatial_vocabulary_references(
                db, data.novel_id, type_refs
            )
        except (NotFoundError, ValidationError):
            resolved_types = {}
            omitted += len(docs)
            docs = []

        def type_is_active(ref, revision_id) -> bool:
            if ref is None:
                return True
            if str(ref) in excluded or str(revision_id) in excluded:
                return False
            value = resolved_types.get((ref, revision_id))
            return bool(value and value.get("status") == "active")

        source_checks: dict[tuple, bool] = {}

        async def sources_current(item, *, revision_has_task: bool) -> bool:
            decision = getattr(item, "author_decision", None)
            key = (
                revision_has_task,
                decision.model_dump_json() if decision is not None else None,
                tuple(source.model_dump_json() for source in item.sources),
            )
            if key not in source_checks:
                source_checks[key] = await check_sources(
                    item, revision_has_task=revision_has_task
                )
            return source_checks[key]

        async def check_sources(item, *, revision_has_task: bool) -> bool:
            sources = list(getattr(item, "sources", None) or [])
            author_decision = getattr(item, "author_decision", None)
            if not sources and revision_has_task and author_decision is None:
                return False
            if not sources and author_decision is not None:
                if author_decision.origin == "manual":
                    return not revision_has_task
                from core.service_keys import ASSISTANT_READ_MAP_AUTHOR_DECISION
                from modules.world.map_structure_schemas import MapAuthorDecision

                verified = MapAuthorDecision.model_validate(
                    await get(ASSISTANT_READ_MAP_AUTHOR_DECISION)(
                        db,
                        data.novel_id,
                        str(author_decision.run_id),
                        message_id=str(author_decision.message_id),
                    )
                )
                return verified == author_decision
            service = MapStructureService()
            for source in sources:
                if str(source.id) in excluded or (
                    source.kind == "source_range"
                    and (source.source_ref or {}).get("content_mode") != "canonical"
                ):
                    return False
                try:
                    await service.source(db, data.novel_id, source)
                except (
                    ConflictError,
                    NotFoundError,
                    ValidationError,
                    TypeError,
                    ValueError,
                ):
                    return False
                if source.kind == "entity":
                    if not await entity_visible(str(source.id)):
                        return False
                    inspected = await evidence_facade.inspect_novel_target(
                        db,
                        novel_id=data.novel_id,
                        target_ref={
                            "target_type": "world_entity",
                            "target_id": str(source.id),
                        },
                        content_mode="canonical",
                        visibility=VisibilityContextContract(
                            mode="character"
                            if data.reveal_mode == "character"
                            else "reader",
                            character_id=data.viewpoint_character_id
                            if data.reveal_mode == "character"
                            else None,
                            cutoff_chapter=cutoff_chapter,
                            cutoff_scene_id=data.scene_id,
                        ),
                    )
                    safe_text = str(inspected.get("item") or {})
                    if source.quote and source.quote not in safe_text:
                        return False
                elif source.kind == "world_bible_page":
                    if data.reveal_mode in {"reader", "character"}:
                        return False
                    decisions = await check_knowledge_visibility(
                        db,
                        data.novel_id,
                        [
                            KnowledgeVisibilityRequest(
                                target_type="world_bible_page",
                                target_id=str(source.id),
                                apply_reader_reveal=True,
                                cutoff_chapter=cutoff_chapter,
                                cutoff_scene_id=data.scene_id,
                                character_id=data.viewpoint_character_id
                                if data.reveal_mode == "character"
                                else None,
                            )
                        ],
                    )
                    if not decisions or not decisions[0].visible:
                        return False
                    from modules.world.facade import get_world_bible_projection_candidates

                    projection = await get_world_bible_projection_candidates(
                        db,
                        data.novel_id,
                        [
                            {
                                "target_type": "world_bible_page",
                                "target_id": str(source.id),
                            }
                        ],
                        projection_type="context_brief",
                        reveal_mode="author_safe",
                    )
                    projected = next(
                        (
                            candidate
                            for candidate in projection.items
                            if str(candidate.target.get("target_id") or "")
                            == str(source.id)
                        ),
                        None,
                    )
                    if (
                        projected is None
                        or getattr(projected, "warnings", None)
                        or source.quote
                        and source.quote not in str(projected.content or "")
                    ):
                        return False
                else:
                    result = await evidence_facade.read_novel_evidence(
                        db,
                        novel_id=data.novel_id,
                        source_ref=SourceRangeRefContract(**source.source_ref),
                        visibility=VisibilityContextContract(
                            mode="character"
                            if data.reveal_mode == "character"
                            else "reader",
                            character_id=data.viewpoint_character_id
                            if data.reveal_mode == "character"
                            else None,
                            cutoff_chapter=cutoff_chapter,
                            cutoff_scene_id=data.scene_id,
                        ),
                        before=0,
                        after=0,
                    )
                    decision = result.get("visibility_decision")
                    if (
                        not result.get("text")
                        or not isinstance(decision, dict)
                        or decision.get("visible") is not True
                    ):
                        return False
            return True

        async def entity_visible(entity_id: str) -> bool:
            if entity_id in excluded:
                return False
            decisions = await check_knowledge_visibility(
                db,
                data.novel_id,
                [
                    KnowledgeVisibilityRequest(
                        target_type="world_entity",
                        target_id=entity_id,
                        apply_reader_reveal=True,
                        cutoff_chapter=cutoff_chapter,
                        cutoff_scene_id=data.scene_id,
                        character_id=data.viewpoint_character_id
                        if data.reveal_mode == "character"
                        else None,
                    )
                ],
            )
            if not (decisions and decisions[0].visible):
                return False
            inspected = await evidence_facade.inspect_novel_target(
                db,
                novel_id=data.novel_id,
                target_ref={"target_type": "world_entity", "target_id": entity_id},
                content_mode="canonical",
                visibility=VisibilityContextContract(
                    mode="character" if data.reveal_mode == "character" else "reader",
                    character_id=data.viewpoint_character_id
                    if data.reveal_mode == "character"
                    else None,
                    cutoff_chapter=cutoff_chapter,
                    cutoff_scene_id=data.scene_id,
                ),
            )
            return bool(inspected.get("visible") and inspected.get("item"))

        items: list[MapSpatialAdvisoryItem] = []
        baselines: list[MapSpatialAdvisoryMapRevision] = []
        for node, revision, document in docs:
            feature_by_id = {feature.id: feature for feature in document.features}
            unavailable_spaces = {
                space.id
                for space in document.spaces
                if not type_is_active(space.type_ref, space.type_revision_id)
            }
            valid_features = {}
            inactive_location_features = {}
            movable_entity_ids: set[str] = set()
            for feature in document.features:
                if (
                    feature.modality != "event_observed"
                    or feature.reader_from_chapter is not None
                    and (
                        cutoff_chapter is None
                        or feature.reader_from_chapter > cutoff_chapter
                    )
                    or feature.space_id in unavailable_spaces
                    or not type_is_active(feature.type_ref, feature.type_revision_id)
                    or feature.entity_id is not None
                    and not await entity_visible(str(feature.entity_id))
                    or not await sources_current(
                        feature, revision_has_task=bool(revision.task_id)
                    )
                ):
                    omitted += 1
                    continue
                pair = (feature.type_ref, feature.type_revision_id)
                resolved = resolved_types.get(pair) if feature.type_ref else None
                if feature.type_ref and resolved is None:
                    continue
                if _within_cutoff(
                    feature, scenes=temporal_scenes, scene_index=scene_index
                ):
                    valid_features[feature.id] = feature
                elif feature.entity_id is not None and _excluded_by_validity(
                    feature, scenes=temporal_scenes, scene_index=scene_index
                ):
                    inactive_location_features[str(feature.entity_id)] = feature
                    continue
                else:
                    continue
                if (
                    feature.entity_id
                    and resolved
                    and "movable" in resolved["traits"].other
                ):
                    movable_entity_ids.add(str(feature.entity_id))

            if not any(
                str(feature.entity_id or "") in scene_locations
                for feature in [
                    *valid_features.values(),
                    *inactive_location_features.values(),
                ]
            ):
                continue

            valid_constraints = []
            expired_connections = []
            for constraint in document.constraints:
                endpoints = {constraint.subject, constraint.target, *constraint.via}
                if (
                    constraint.modality != "event_observed"
                    or not endpoints.issubset(feature_by_id)
                    or not type_is_active(
                        constraint.type_ref, constraint.type_revision_id
                    )
                    or not type_is_active(
                        constraint.path_type_ref, constraint.path_type_revision_id
                    )
                    or not await sources_current(
                        constraint,
                        revision_has_task=bool(
                            revision.task_id or constraint.generated_by_task_id
                        ),
                    )
                    or not constraint_is_calculable(
                        constraint,
                        type_traits={
                            pair: value["traits"]
                            for pair, value in resolved_types.items()
                            if value.get("status") == "active"
                        },
                    )
                    or not _path_is_calculable(
                        constraint,
                        {
                            pair: value["traits"]
                            for pair, value in resolved_types.items()
                            if value.get("status") == "active"
                        },
                    )
                ):
                    omitted += 1
                    continue
                endpoints_active = endpoints.issubset(valid_features)
                if not endpoints_active:
                    continue
                endpoint_spaces = {
                    valid_features[key].space_id
                    for key in (constraint.subject, constraint.target, *constraint.via)
                }
                if len(endpoint_spaces) > 1:
                    pair = (constraint.type_ref, constraint.type_revision_id)
                    resolved = resolved_types.get(pair)
                    if (
                        constraint.relation != "connects"
                        or resolved is None
                        or "cross_space" not in resolved["traits"].connection
                    ):
                        continue
                if _within_cutoff(
                    constraint, scenes=temporal_scenes, scene_index=scene_index
                ):
                    valid_constraints.append(constraint)
                elif constraint.relation in _CONNECTIONS and _outside_cutoff(
                    constraint, scenes=temporal_scenes, scene_index=scene_index
                ):
                    expired_connections.append(constraint)

            # Contradictory active compass declarations are reported only when
            # both directions are explicit, adopted and source-current.
            for left_id, right_id, first, second in _direction_conflicts(
                valid_features, valid_constraints
            ):
                items.append(
                    MapSpatialAdvisoryItem(
                        rule_code="direction_conflict",
                        summary="地图中同一对地点存在互相矛盾的方位声明。",
                        node_id=str(node.id),
                        revision_id=str(revision.id),
                        revision_hash=str(
                            revision.geometry_hash or stable_hash(revision.document)
                        ),
                        source_hashes=_source_hashes([first, second]),
                        feature_ids=[left_id, right_id],
                        unknowns=["本提醒只比较明确的方位声明，不依据图面坐标推断方向。"],
                    )
                )

            journeys_by_key: dict[tuple, list[object]] = defaultdict(list)
            valid_journeys: list[object] = []
            for journey in document.journeys:
                if (
                    journey.modality != "event_observed"
                    or not _within_cutoff(
                        journey, scenes=temporal_scenes, scene_index=scene_index
                    )
                    or journey.origin not in valid_features
                    or journey.destination not in valid_features
                    or not await sources_current(
                        journey, revision_has_task=bool(revision.task_id)
                    )
                    or not all(
                        type_is_active(ref, rev)
                        for ref, rev in (
                            (
                                journey.transport_type_ref,
                                journey.transport_type_revision_id,
                            ),
                            (
                                journey.traveler_type_ref,
                                journey.traveler_type_revision_id,
                            ),
                            (
                                journey.connection_type_ref,
                                journey.connection_type_revision_id,
                            ),
                            *[
                                (condition.type_ref, condition.type_revision_id)
                                for condition in journey.access_conditions
                            ],
                        )
                    )
                ):
                    omitted += 1
                    continue
                if (
                    valid_features[journey.origin].space_id
                    != valid_features[journey.destination].space_id
                ):
                    connection = resolved_types.get(
                        (journey.connection_type_ref, journey.connection_type_revision_id)
                    )
                    if (
                        connection is None
                        or "cross_space" not in connection["traits"].connection
                    ):
                        continue
                valid_journeys.append(journey)
                if journey.duration:
                    journeys_by_key[_journey_key(journey)].append(journey)
            for journeys in journeys_by_key.values():
                conflict_pair = next(
                    (
                        (left, right)
                        for index, left in enumerate(journeys)
                        for right in journeys[index + 1 :]
                        if _intervals_disjoint(left.duration, right.duration)
                    ),
                    None,
                )
                if conflict_pair is None:
                    continue
                left, right = conflict_pair
                endpoints = [left.origin, left.destination]
                source_hashes = _source_hashes([left, right])
                items.append(
                    MapSpatialAdvisoryItem(
                        rule_code="journey_duration_conflict",
                        summary="同一交通方式、旅行者类别与通行条件下，行程耗时区间互不重叠。",
                        node_id=str(node.id),
                        revision_id=str(revision.id),
                        revision_hash=str(
                            revision.geometry_hash or stable_hash(revision.document)
                        ),
                        source_hashes=source_hashes,
                        feature_ids=endpoints,
                        unknowns=[
                            "不同单位、交通方式、旅行者类别或通行条件的行程不会互相比较。"
                        ],
                    )
                )

            baselines.append(
                MapSpatialAdvisoryMapRevision(
                    node_id=str(node.id),
                    revision_id=str(revision.id),
                    revision_hash=str(
                        revision.geometry_hash or stable_hash(revision.document)
                    ),
                    source_hashes=_source_hashes(
                        [*valid_features.values(), *valid_constraints, *valid_journeys]
                    ),
                )
            )
            for transition in data.transitions:
                if {
                    transition.from_location_id,
                    transition.to_location_id,
                    transition.mover_id,
                } & excluded:
                    continue
                endpoint_features = {
                    str(feature.entity_id): feature
                    for feature in valid_features.values()
                    if feature.entity_id
                }
                start = endpoint_features.get(transition.from_location_id)
                end = endpoint_features.get(transition.to_location_id)
                inactive_target = inactive_location_features.get(
                    transition.to_location_id
                )
                if inactive_target is not None and transition.to_location_id not in {
                    str(feature.entity_id)
                    for feature in valid_features.values()
                    if feature.entity_id
                }:
                    items.append(
                        MapSpatialAdvisoryItem(
                            rule_code="location_not_effective",
                            summary=(
                                "Scene 时点状态将对象置于一处尚未生效或已经失效的地点。"
                            ),
                            node_id=str(node.id),
                            revision_id=str(revision.id),
                            revision_hash=str(
                                revision.geometry_hash or stable_hash(revision.document)
                            ),
                            source_hashes=_source_hashes([inactive_target]),
                            feature_ids=[inactive_target.id],
                            unknowns=[
                                "仅在地图有效期锚点可解析时提醒；作者仍可确认地图记录不完整。"
                            ],
                        )
                    )
                if start is None or end is None:
                    continue
                if any(
                    (journey.origin, journey.destination) == (start.id, end.id)
                    for journey in valid_journeys
                ):
                    # A declared journey is route evidence, even without a drawn edge.
                    # It still does not prove timing or suitability for this traveler.
                    continue
                if start.space_id != end.space_id:
                    if transition.mover_id not in movable_entity_ids:
                        continue
                    cross_space = any(
                        constraint.relation == "connects"
                        and {constraint.subject, constraint.target} == {start.id, end.id}
                        and "cross_space"
                        in getattr(
                            resolved_types.get(
                                (constraint.type_ref, constraint.type_revision_id), {}
                            ).get("traits"),
                            "connection",
                            [],
                        )
                        for constraint in valid_constraints
                    )
                    declared_journey = any(
                        {journey.origin, journey.destination} == {start.id, end.id}
                        for journey in valid_journeys
                    )
                    if not cross_space and not declared_journey:
                        items.append(
                            MapSpatialAdvisoryItem(
                                rule_code="cross_space_connection_unknown",
                                summary="移动对象跨越两个空间，但地图没有声明连接；当前只能确认连接资料缺失。",
                                node_id=str(node.id),
                                revision_id=str(revision.id),
                                revision_hash=str(
                                    revision.geometry_hash
                                    or stable_hash(revision.document)
                                ),
                                source_hashes=_source_hashes(valid_constraints),
                                feature_ids=[start.id, end.id],
                                unknowns=[
                                    "故事内时间间隔未明确，无法判断移动是否来得及。",
                                    "没有根据几何坐标推算真实距离或移动时间。",
                                ],
                            )
                        )
                    continue
                known_route_endpoints = {
                    str(feature.entity_id)
                    for constraint in [*valid_constraints, *expired_connections]
                    if constraint.relation in _CONNECTIONS
                    for key in (constraint.subject, constraint.target, *constraint.via)
                    if (feature := valid_features.get(key)) is not None
                    and feature.entity_id is not None
                }
                route_constraints = [
                    constraint
                    for constraint in valid_constraints
                    if constraint.relation in _CONNECTIONS
                    and all(
                        valid_features[key].space_id == start.space_id
                        for key in (
                            constraint.subject,
                            constraint.target,
                            *constraint.via,
                        )
                        if key in valid_features
                    )
                ]
                route_graph: dict[str, set[str]] = defaultdict(set)
                graph_endpoints: set[str] = set()
                for constraint in route_constraints:
                    path = [constraint.subject, *constraint.via, constraint.target]
                    for left_id, right_id in zip(path, path[1:], strict=False):
                        left_entity = valid_features[left_id].entity_id
                        right_entity = valid_features[right_id].entity_id
                        if not left_entity or not right_entity:
                            continue
                        left_key, right_key = str(left_entity), str(right_entity)
                        graph_endpoints.update((left_key, right_key))
                        route_graph[left_key].add(right_key)
                        relation_type = resolved_types.get(
                            (constraint.type_ref, constraint.type_revision_id)
                        )
                        directed = bool(
                            relation_type
                            and "directed" in relation_type["traits"].connection
                        )
                        if not directed:
                            route_graph[right_key].add(left_key)

                def path_exists(source: str, target: str) -> bool:
                    queue = [source]
                    visited = {source}
                    while queue:
                        current = queue.pop()
                        if current == target:
                            return True
                        for neighbor in route_graph.get(current, ()):
                            if neighbor not in visited:
                                visited.add(neighbor)
                                queue.append(neighbor)
                    return False

                expired_match = [
                    constraint
                    for constraint in expired_connections
                    if {constraint.subject, constraint.target} == {start.id, end.id}
                ]
                has_active_connection = any(
                    constraint.relation in _CONNECTIONS
                    and {constraint.subject, constraint.target} == {start.id, end.id}
                    for constraint in valid_constraints
                )
                disconnected_known_network = (
                    transition.from_location_id in graph_endpoints
                    and transition.to_location_id in graph_endpoints
                    and not path_exists(
                        transition.from_location_id, transition.to_location_id
                    )
                )
                if (
                    (
                        disconnected_known_network
                        or expired_match
                        and not has_active_connection
                    )
                    and transition.from_location_id in known_route_endpoints
                    and transition.to_location_id in known_route_endpoints
                ):
                    items.append(
                        MapSpatialAdvisoryItem(
                            rule_code="route_no_active_connection",
                            summary=(
                                "地图记录过这两地之间的通路，但当前有效的通路网络未连通。"
                                if disconnected_known_network
                                else (
                                    "地图记录过这两地之间的通路，但该通路已过生效期，"
                                    "当前没有仍有效的连接。"
                                )
                            ),
                            node_id=str(node.id),
                            revision_id=str(revision.id),
                            revision_hash=str(
                                revision.geometry_hash or stable_hash(revision.document)
                            ),
                            source_hashes=_source_hashes(
                                expired_match or route_constraints
                            ),
                            feature_ids=[start.id, end.id],
                            unknowns=[
                                "地图只覆盖已声明的通路，未登记路线不代表现实中绝对无路。"
                            ],
                        )
                    )

        deduped: dict[tuple[str, str, tuple[str, ...]], MapSpatialAdvisoryItem] = {}
        for item in items:
            key = (item.rule_code, item.revision_id, tuple(sorted(item.feature_ids)))
            deduped.setdefault(key, item)
        ordered = list(deduped.values())
        return MapSpatialAdvisoryResponse(
            scene_id=data.scene_id,
            scene_index=scene_index,
            items=ordered[:_MAX_ADVISORIES],
            omitted_count=omitted + max(0, len(ordered) - _MAX_ADVISORIES),
            map_revisions=baselines,
            unknowns=([EXCLUDED_MERGE_UNKNOWN] if excluded_merges else [])
            + (
                ["未提供正文明确的场景间时间间隔，无法判断移动是否来得及。"]
                if data.transitions
                else []
            ),
        )


async def read_map_spatial_advisories(
    db, request: MapSpatialAdvisoryRequest | dict
) -> MapSpatialAdvisoryResponse:
    return await MapSpatialAdvisoryService().read(db, request)
