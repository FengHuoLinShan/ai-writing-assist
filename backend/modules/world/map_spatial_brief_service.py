"""Build a bounded, source-checked brief from adopted map revisions."""

from __future__ import annotations

import hashlib
import json
import unicodedata

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import and_, select

from core.container import get
from core.errors import ConflictError, NotFoundError, ValidationError
from core.service_keys import PROJECT_REQUIRE_ACTIVE
from infrastructure.stable_hash import stable_hash
from modules.evidence import facade as evidence_facade
from modules.evidence.contracts import VisibilityContextContract
from modules.world.map_spatial_brief_schemas import (
    MapSpatialBriefItem,
    MapSpatialBriefRequest,
    MapSpatialBriefResponse,
)
from modules.writing.contracts import SourceRangeRefContract

_ACTIVE_SCENES = frozenset({"candidate", "draft", "canonical"})
_SCENE_PRESENCE_KEYS = (
    "present_character_ids",
    "present_entity_ids",
    "present_item_ids",
    "present_object_ids",
)
_ROUTE_RELATIONS = frozenset(
    {
        "adjacent",
        "connects",
        "passes_through",
        "entrance_to",
        "north",
        "south",
        "east",
        "west",
        "northeast",
        "northwest",
        "southeast",
        "southwest",
        "faces",
    }
)
_CONNECTION_RELATIONS = frozenset(
    {"adjacent", "connects", "passes_through", "entrance_to"}
)
_MAX_NODES = 200
_MAX_TYPES = 32


def _story_scene_port():
    from core.container import get
    from core.service_keys import STORY_SCENE_SOURCE

    return get(STORY_SCENE_SOURCE)


def _as_dict(value) -> dict:
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="python")
    if hasattr(value, "__dataclass_fields__"):
        from dataclasses import asdict

        return asdict(value)
    return {}


def _exact_match(query: str, label: str) -> bool:
    query_key = unicodedata.normalize("NFKC", query).casefold()
    label_key = unicodedata.normalize("NFKC", label).strip().casefold()
    return bool(label_key and label_key in query_key)


def _within_cutoff(item, *, scenes: list[dict], scene_index: int | None) -> bool:
    if item.effective is None:
        return True
    if scene_index is None:
        return False
    from modules.world.map_spatial_anchors import resolve_validity

    resolution = resolve_validity(item.effective, scenes)
    return bool(
        resolution.valid
        and (
            resolution.start_scene_index is None
            or resolution.start_scene_index <= scene_index
        )
        and (
            resolution.end_scene_index is None
            or scene_index <= resolution.end_scene_index
        )
    )


def _safe_json(value: dict) -> tuple[str, bool]:
    """Keep the brief valid JSON while clipping excess advisory detail."""
    payload = json.loads(json.dumps(value, ensure_ascii=False, default=str))
    clipped = False

    def encode() -> str:
        return (
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
        )

    def clip_strings(item, limit: int):
        if isinstance(item, dict):
            return {key: clip_strings(value, limit) for key, value in item.items()}
        if isinstance(item, list):
            return [clip_strings(value, limit) for value in item]
        if isinstance(item, str) and len(item) > limit:
            return item[:limit] + "…"
        return item

    encoded = encode()
    while len(encoded) > 3000:
        lists = [item for item in payload.values() if isinstance(item, list) and item]
        if lists:
            max(lists, key=len).pop()
            clipped = True
            encoded = encode()
            continue
        payload = clip_strings(payload, 60)
        clipped = True
        encoded = encode()
        if len(encoded) > 3000:
            break
    if len(encoded) > 3000:
        return "{}", True
    return encoded, clipped


class MapSpatialBriefService:
    async def read(
        self, db, request: MapSpatialBriefRequest | dict
    ) -> MapSpatialBriefResponse:
        from modules.world.map_atlas_models import MapAtlasNode, MapAtlasRevision
        from modules.world.map_structure_geometry import (
            _path_is_calculable,
            constraint_is_calculable,
        )
        from modules.world.map_structure_schemas import MapDocument
        from modules.world.map_structure_service import (
            MapStructureService,
            _document_type_references,
            _spatial_item_type_pairs,
            resolve_spatial_vocabulary_references,
        )
        from shared.utils import parse_uuid

        data = (
            request
            if isinstance(request, MapSpatialBriefRequest)
            else MapSpatialBriefRequest.model_validate(request)
        )
        await get(PROJECT_REQUIRE_ACTIVE)(db, data.novel_id)
        if data.reveal_mode == "character" and not data.viewpoint_character_id:
            raise ValidationError("角色视角空间简报必须指定视角人物")

        scene = None
        scene_index = None
        cutoff_chapter = data.chapter_index
        presence_ids: set[str] = set()
        scene_location_ids: set[str] = set()
        state_facts: list[dict] = []
        temporal_scenes: list[dict] = []
        if data.scene_id:
            raw_scene = await _story_scene_port().get_scene_contract(
                db, data.novel_id, data.scene_id
            )
            if raw_scene is None:
                return MapSpatialBriefResponse()
            scene = _as_dict(raw_scene)
            if (
                str(scene.get("novel_id")) != str(data.novel_id)
                or str(scene.get("id")) != str(data.scene_id)
                or scene.get("status") not in _ACTIVE_SCENES
            ):
                return MapSpatialBriefResponse(scene_id=data.scene_id)
            scene_index = scene.get("scene_index")
            if isinstance(scene_index, bool) or not isinstance(scene_index, int):
                return MapSpatialBriefResponse(scene_id=data.scene_id)
            metadata = scene.get("structure_meta")
            metadata = metadata if isinstance(metadata, dict) else {}
            for key in _SCENE_PRESENCE_KEYS:
                values = metadata.get(key)
                if isinstance(values, list):
                    presence_ids.update(str(value) for value in values if value)
            for key in ("location_id", "location_entity_id"):
                value = metadata.get(key)
                if value:
                    scene_location_ids.add(str(value))

            presence = await _story_scene_port().project_scene_presence(
                db, data.novel_id, through_scene_index=scene_index
            )
            for entry in getattr(presence, "nodes", []) or []:
                if (
                    getattr(entry, "presence_kind", None) == "confirmed_in_scene"
                    and getattr(entry, "scene_index", None) == scene_index
                    and getattr(entry, "character_id", None)
                ):
                    presence_ids.add(str(entry.character_id))

            temporal_scenes = await _story_scene_port().read_temporal_anchor_scenes(
                db, data.novel_id
            )
            view = await _story_scene_port().get_scene_state_view(
                db,
                data.novel_id,
                data.scene_id,
                viewpoint={"kind": "author"},
                include_dimensions=["locations"],
            )
            state_view = _as_dict(view)
            scene_chapters = [
                int(value)
                for value in scene.get("chapter_ids") or []
                if str(value).isdigit() and int(value) > 0
            ]
            actual_cutoff = max(scene_chapters, default=None)
            if state_view.get("status") != "degraded":
                chapter = state_view.get("chapter_index")
                if isinstance(chapter, int) and chapter > 0:
                    actual_cutoff = min(
                        chapter,
                        actual_cutoff if actual_cutoff is not None else chapter,
                    )
            if actual_cutoff is None:
                return MapSpatialBriefResponse(
                    scene_id=data.scene_id,
                    scene_index=scene_index,
                )
            if data.chapter_index is not None and data.chapter_index < actual_cutoff:
                # Numeric chapter IDs do not identify a stable Scene anchor.
                # Do not guess which map Scene revision was visible at an
                # earlier chapter boundary.
                return MapSpatialBriefResponse(
                    scene_id=data.scene_id,
                    scene_index=scene_index,
                    chapter_index=data.chapter_index,
                )
            cutoff_chapter = actual_cutoff
            for dimension in state_view.get("dimensions") or []:
                if (
                    not isinstance(dimension, dict)
                    or dimension.get("dimension") != "locations"
                ):
                    continue
                if dimension.get("status") != "ok":
                    continue
                state_facts = [
                    _as_dict(fact)
                    for fact in dimension.get("facts") or []
                    if isinstance(fact, dict) or hasattr(fact, "model_dump")
                ]
                break

        visibility_mode = "character" if data.reveal_mode == "character" else "reader"
        visibility = VisibilityContextContract(
            mode=visibility_mode,
            cutoff_chapter=cutoff_chapter,
            cutoff_scene_id=data.scene_id,
            character_id=(
                data.viewpoint_character_id if visibility_mode == "character" else None
            ),
        )
        excluded_nodes = set()
        excluded_revisions = set()
        excluded_entities = set()
        excluded_pages = set()
        excluded_source_ids = set()
        excluded_types = set()
        excluded_type_revisions = set()
        for item in data.excluded_ids:
            value = str(item)
            parts = value.split(":")
            kind = parts[0]
            target_id = parts[1] if len(parts) > 1 else value
            if kind in {"map_spatial", "map_spatial_node", "map_atlas_node"}:
                excluded_nodes.add(target_id)
            elif kind == "map_atlas_revision":
                excluded_revisions.add(target_id)
            elif kind in {"world_entity", "world_object", "core_entity", "entity"}:
                excluded_entities.add(target_id)
            elif kind in {"world_bible_page", "world_bible"}:
                excluded_pages.add(target_id)
            elif kind in {"writing_draft", "writing_chapter", "source_range"}:
                excluded_source_ids.add(target_id)
            elif kind in {
                "project_vocabulary",
                "project_vocabulary_term",
                "world_vocabulary",
                "vocabulary_term",
            }:
                excluded_types.add(target_id)
            elif kind == "project_vocabulary_revision":
                excluded_type_revisions.add(target_id)
            else:
                excluded_nodes.add(value)
        scene_location_ids.difference_update(excluded_entities)
        checked_sources: dict[str, bool] = {}
        checked_targets: dict[str, bool] = {}

        def range_is_excluded(ref: dict) -> bool:
            if not isinstance(ref, dict):
                return True
            return any(
                str(ref.get(key) or "") in excluded_source_ids
                for key in ("draft_id", "chapter_index", "range_hash")
            )

        async def knowledge_visible(target_type: str, target_id: str) -> bool:
            if target_type == "world_entity" and target_id in excluded_entities:
                return False
            from modules.world.contracts import KnowledgeVisibilityRequest
            from modules.world.facade import check_knowledge_visibility

            decisions = await check_knowledge_visibility(
                db,
                data.novel_id,
                [
                    KnowledgeVisibilityRequest(
                        target_type=target_type,
                        target_id=target_id,
                        character_id=(
                            data.viewpoint_character_id
                            if visibility_mode == "character"
                            else None
                        ),
                        cutoff_chapter=cutoff_chapter,
                        cutoff_scene_id=data.scene_id,
                        apply_reader_reveal=True,
                    )
                ],
            )
            return bool(decisions and decisions[0].visible)

        async def target_visible(
            target_type: str, target_id: str, evidence_type: str
        ) -> bool:
            cache_key = f"{target_type}:{target_id}"
            if cache_key in checked_targets:
                return checked_targets[cache_key]
            if not await knowledge_visible(target_type, target_id):
                checked_targets[cache_key] = False
                return False
            inspected = await evidence_facade.inspect_novel_target(
                db,
                novel_id=data.novel_id,
                target_ref={"target_type": evidence_type, "target_id": target_id},
                content_mode="canonical",
                visibility=visibility,
            )
            visible = bool(inspected.get("visible") and inspected.get("item"))
            checked_targets[cache_key] = visible
            return visible

        async def source_is_current_and_visible(ref) -> bool:
            cache_key = ref.model_dump_json()
            if cache_key in checked_sources:
                return checked_sources[cache_key]
            source_exclusions = {
                "entity": excluded_entities,
                "world_bible_page": excluded_pages,
                "source_range": excluded_source_ids,
            }[ref.kind]
            if str(ref.id) in source_exclusions or (
                ref.kind == "source_range" and range_is_excluded(ref.source_ref or {})
            ):
                checked_sources[cache_key] = False
                return False
            try:
                await MapStructureService().source(db, data.novel_id, ref)
            except (ConflictError, NotFoundError, ValidationError, TypeError, ValueError):
                checked_sources[cache_key] = False
                return False
            if ref.kind == "source_range":
                try:
                    result = await evidence_facade.read_novel_evidence(
                        db,
                        novel_id=data.novel_id,
                        source_ref=SourceRangeRefContract(**ref.source_ref),
                        visibility=visibility,
                        before=0,
                        after=0,
                    )
                except (
                    ConflictError,
                    NotFoundError,
                    ValidationError,
                    TypeError,
                    ValueError,
                ):
                    checked_sources[cache_key] = False
                    return False
                decision = result.get("visibility_decision")
                visible = (
                    bool(result.get("text"))
                    and isinstance(decision, dict)
                    and (decision.get("visible") is True)
                )
                checked_sources[cache_key] = visible
                return visible
            check_type = "world_entity" if ref.kind == "entity" else "world_bible_page"
            if ref.kind == "world_bible_page":
                visible = await self._page_source_visible(
                    db,
                    data,
                    ref,
                    visibility_mode=visibility_mode,
                    cutoff_chapter=cutoff_chapter,
                    knowledge_visible=await knowledge_visible(check_type, str(ref.id)),
                )
            else:
                visible = await target_visible(check_type, str(ref.id), check_type)
            checked_sources[cache_key] = visible
            return visible

        async def all_sources_visible(refs) -> bool:
            for ref in refs:
                if not await source_is_current_and_visible(ref):
                    return False
            return True

        async def scene_ranges_are_visible(refs: list[dict]) -> bool:
            if (
                not refs
                or scene_index is None
                or not data.scene_id
                or any(range_is_excluded(ref) for ref in refs)
            ):
                return False
            try:
                await _story_scene_port().validate_scene_source_ranges(
                    db,
                    data.novel_id,
                    data.scene_id,
                    scene_index,
                    refs,
                    content_mode="canonical",
                )
            except (
                ConflictError,
                NotFoundError,
                ValidationError,
                TypeError,
                ValueError,
            ):
                return False
            for raw_ref in refs:
                try:
                    source_ref = SourceRangeRefContract(**raw_ref)
                    result = await evidence_facade.read_novel_evidence(
                        db,
                        novel_id=data.novel_id,
                        source_ref=source_ref,
                        visibility=visibility,
                        before=0,
                        after=0,
                    )
                except (
                    ConflictError,
                    NotFoundError,
                    ValidationError,
                    TypeError,
                    ValueError,
                ):
                    return False
                decision = result.get("visibility_decision")
                if (
                    not result.get("text")
                    or not isinstance(decision, dict)
                    or decision.get("visible") is not True
                ):
                    return False
            return True

        node_query = (
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
                MapAtlasRevision.status == "saved",
            )
            .order_by(MapAtlasNode.sort_order, MapAtlasNode.id)
            .limit(_MAX_NODES + 1)
        )
        rows = list((await db.execute(node_query)).all())
        omitted_count = max(0, len(rows) - _MAX_NODES)
        rows = rows[:_MAX_NODES]
        excluded_node_ids = {value for value in excluded_nodes}
        node_rows = [
            (node, revision)
            for node, revision in rows
            if str(node.id) not in excluded_node_ids
            and str(revision.id) not in excluded_revisions
        ]
        omitted_count += len(rows) - len(node_rows)
        if cutoff_chapter is None:
            return MapSpatialBriefResponse(
                scene_id=data.scene_id,
                scene_index=scene_index,
                unknowns=["尚未选择 Scene 或截止章节，空间资料未核对；请选择范围后重试。"]
                if node_rows
                else [],
            )
        documents = []
        type_refs = {}
        for node, revision in node_rows:
            try:
                document = MapDocument.model_validate(revision.document)
                refs = _document_type_references(document)
                for pair, kind in refs.items():
                    prior = type_refs.setdefault(pair, kind)
                    if prior != kind:
                        raise ValidationError("空间类型引用种类不一致")
            except (ValidationError, PydanticValidationError, TypeError, ValueError):
                omitted_count += 1
                continue
            documents.append((node, revision, document))
        try:
            resolved_types = await resolve_spatial_vocabulary_references(
                db, data.novel_id, type_refs
            )
        except (NotFoundError, ValidationError):
            # A stale vocabulary pin makes only its map item unavailable.
            resolved_types = {}
            omitted_count += 1

        resolved_types = {
            key: value
            for key, value in resolved_types.items()
            if str(key[0]) not in excluded_types
            and str(key[1]) not in excluded_type_revisions
        }

        traits = {
            key: value["traits"]
            for key, value in resolved_types.items()
            if value.get("status") == "active"
        }
        type_text: dict[tuple, dict] = {}
        for key, value in resolved_types.items():
            type_text[key] = {
                "name": str(value.get("name") or ""),
                "description": str(value.get("description") or ""),
                "status": str(value.get("status") or ""),
            }

        by_node_id = {
            str(node.id): (node, revision, document)
            for node, revision, document in documents
        }
        ancestor_titles: dict[str, list[dict]] = {}
        for node, _revision, _document in documents:
            ancestors = []
            current_id = str(node.parent_id) if node.parent_id else None
            seen = {str(node.id)}
            for _ in range(20):
                if not current_id or current_id in seen:
                    break
                seen.add(current_id)
                parent = by_node_id.get(current_id)
                if parent is None:
                    break
                parent_node = parent[0]
                if parent_node.location_entity_id and not await target_visible(
                    "world_entity", str(parent_node.location_entity_id), "world_entity"
                ):
                    break
                ancestors.append(
                    {
                        "title": str(parent_node.title)[:200],
                        "level": str(parent_node.level),
                    }
                )
                current_id = str(parent_node.parent_id) if parent_node.parent_id else None
            ancestor_titles[str(node.id)] = list(reversed(ancestors))

        items: list[MapSpatialBriefItem] = []
        for node, revision, document in documents:
            if str(node.id) in excluded_node_ids:
                continue
            if node.location_entity_id and not await target_visible(
                "world_entity", str(node.location_entity_id), "world_entity"
            ):
                omitted_count += 1
                continue
            features = {feature.id: feature for feature in document.features}
            spaces = {space.id: space for space in document.spaces}
            feature_text: dict[str, dict] = {}
            from modules.world.map_structure_service import canonical_map_feature_ids

            canonical_features = await canonical_map_feature_ids(
                db, data.novel_id, document
            )
            valid_features = set()
            included_source_hashes: set[str] = set()
            for feature in document.features:
                if (
                    feature.id not in canonical_features
                    or feature.modality != "event_observed"
                    or not feature.sources
                    and revision.task_id is not None
                    or feature.type_ref is not None
                    and (feature.type_ref, feature.type_revision_id) not in resolved_types
                    or feature.space_id in spaces
                    and spaces[feature.space_id].type_ref is not None
                    and (
                        spaces[feature.space_id].type_ref,
                        spaces[feature.space_id].type_revision_id,
                    )
                    not in resolved_types
                    or feature.reader_from_chapter is not None
                    and (
                        cutoff_chapter is None
                        or feature.reader_from_chapter > cutoff_chapter
                    )
                    or not _within_cutoff(
                        feature, scenes=temporal_scenes, scene_index=scene_index
                    )
                    or feature.entity_id
                    and not await target_visible(
                        "world_entity", str(feature.entity_id), "world_entity"
                    )
                ):
                    omitted_count += 1
                    continue
                if not await all_sources_visible(feature.sources):
                    omitted_count += 1
                    continue
                included_source_hashes.update(ref.source_hash for ref in feature.sources)
                valid_features.add(feature.id)
                pair = (feature.type_ref, feature.type_revision_id)
                type_info = type_text.get(pair) if feature.type_ref is not None else None
                feature_text[feature.id] = {
                    "label": feature.label,
                    "kind": feature.kind,
                    "note": feature.note[:400] if feature.note else "",
                    "space": next(
                        (
                            space.label
                            for space in document.spaces
                            if space.id == feature.space_id
                        ),
                        "",
                    ),
                    "entity_id": str(feature.entity_id) if feature.entity_id else None,
                    "type": type_info,
                }

            location_features = {
                feature_id
                for feature_id in valid_features
                if scene_location_ids.intersection(
                    {
                        feature_id,
                        str(features[feature_id].entity_id or ""),
                    }
                )
            }
            node_is_location = bool(
                node.location_entity_id
                and str(node.location_entity_id) in scene_location_ids
                and await target_visible(
                    "world_entity", str(node.location_entity_id), "world_entity"
                )
            )
            query_features = {
                feature_id
                for feature_id in valid_features
                if data.query_text
                and _exact_match(data.query_text, features[feature_id].label)
            }
            focus_features = location_features | query_features
            moving_positions: dict[str, tuple[int, dict]] = {}
            ambiguous_position_ids: set[str] = set()
            for feature_id in valid_features:
                feature = features[feature_id]
                pair = (feature.type_ref, feature.type_revision_id)
                resolved = (
                    resolved_types.get(pair) if feature.type_ref is not None else None
                )
                if (
                    feature.entity_id is None
                    or str(feature.entity_id) not in presence_ids
                    or resolved is None
                    or resolved.get("status") != "active"
                    or "movable" not in resolved["traits"].other
                ):
                    continue
                for fact in state_facts:
                    occurred_at = fact.get("occurred_at")
                    if (
                        str(fact.get("subject_id") or "") != str(feature.entity_id)
                        or fact.get("field") not in {"location", "location_id"}
                        or fact.get("layer") != "fact"
                        or fact.get("confidence") != "confirmed"
                        or not isinstance(occurred_at, dict)
                        or isinstance(occurred_at.get("scene_index"), bool)
                        or not isinstance(occurred_at.get("scene_index"), int)
                        or occurred_at["scene_index"] > scene_index
                    ):
                        continue
                    provenance = (fact.get("source") or {}).get("provenance") or {}
                    refs = provenance.get("source_refs") or []
                    if provenance.get("status") != "exact" or not refs:
                        continue
                    if not await scene_ranges_are_visible(refs):
                        omitted_count += 1
                        continue
                    value = fact.get("value")
                    value = value if isinstance(value, dict) else {}
                    location_id = str(value.get("location_id") or "")
                    location_label = None
                    if location_id:
                        if not await target_visible(
                            "world_entity", location_id, "world_entity"
                        ):
                            omitted_count += 1
                            continue
                        location_label = next(
                            (
                                feature_text[location_feature]["label"]
                                for location_feature in valid_features
                                if location_id
                                in {
                                    location_feature,
                                    str(features[location_feature].entity_id or ""),
                                }
                            ),
                            None,
                        )
                    location_label = (
                        location_label or str(value.get("text_state") or "").strip()
                    )
                    if not location_label:
                        continue
                    position = {
                        "object": feature_text[feature_id]["label"],
                        "location": location_label[:300],
                        "occurred_at": fact["occurred_at"],
                    }
                    entity_id = str(feature.entity_id)
                    scene_time = occurred_at["scene_index"]
                    previous = moving_positions.get(entity_id)
                    if previous is None or scene_time > previous[0]:
                        moving_positions[entity_id] = (scene_time, position)
                        ambiguous_position_ids.discard(entity_id)
                    elif scene_time == previous[0] and position != previous[1]:
                        ambiguous_position_ids.add(entity_id)

            positions_for_node = [
                position
                for entity_id, (_scene_time, position) in sorted(moving_positions.items())
                if entity_id not in ambiguous_position_ids
            ]

            if not (focus_features or node_is_location or moving_positions):
                continue

            current_labels = [feature_text[key] for key in sorted(location_features)]
            if node_is_location and not current_labels:
                current_labels = [{"label": str(node.title), "kind": str(node.level)}]

            related_edges = []
            used_type_pairs = set()
            for constraint in document.constraints:
                endpoint_ids = {constraint.subject, constraint.target, *constraint.via}
                if (
                    constraint.modality != "event_observed"
                    or not _within_cutoff(
                        constraint, scenes=temporal_scenes, scene_index=scene_index
                    )
                    or not endpoint_ids.issubset(valid_features)
                    or not endpoint_ids.intersection(focus_features)
                    or constraint.relation not in _ROUTE_RELATIONS
                    or (
                        not constraint.sources
                        and (
                            constraint.generated_by_task_id is not None
                            or revision.task_id is not None
                        )
                    )
                ):
                    continue
                if constraint.sources and not await all_sources_visible(
                    constraint.sources
                ):
                    omitted_count += 1
                    continue
                included_source_hashes.update(
                    ref.source_hash for ref in constraint.sources
                )
                pair = (constraint.type_ref, constraint.type_revision_id)
                if constraint.type_ref is not None and pair not in resolved_types:
                    continue
                computable = constraint_is_calculable(constraint, type_traits=traits)
                path_computable = _path_is_calculable(constraint, traits)
                used_type_pairs.update(
                    candidate
                    for candidate in _spatial_item_type_pairs(constraint)
                    if candidate[0]
                )
                edge = {
                    "relation": constraint.relation,
                    "from": feature_text[constraint.subject]["label"],
                    "to": feature_text[constraint.target]["label"],
                    "via": [feature_text[key]["label"] for key in constraint.via],
                    "type": type_text.get(pair) if constraint.type_ref else None,
                    "path_label": constraint.path_label,
                }
                if constraint.relation in _CONNECTION_RELATIONS:
                    edge["traversable"] = bool(computable and path_computable)
                related_edges.append(edge)

            journeys = []
            for journey in document.journeys:
                endpoints = {journey.origin, journey.destination}
                if (
                    journey.modality != "event_observed"
                    or any(
                        pair not in resolved_types
                        for pair in _spatial_item_type_pairs(journey)
                        if pair[0] is not None
                    )
                    or not _within_cutoff(
                        journey, scenes=temporal_scenes, scene_index=scene_index
                    )
                    or not endpoints.issubset(valid_features)
                    or not endpoints.intersection(focus_features)
                ):
                    continue
                if not await all_sources_visible(journey.sources):
                    omitted_count += 1
                    continue
                included_source_hashes.update(ref.source_hash for ref in journey.sources)
                type_pairs = _spatial_item_type_pairs(journey)
                used_type_pairs.update(
                    candidate for candidate in type_pairs if candidate[0]
                )
                journeys.append(
                    {
                        "from": feature_text[journey.origin]["label"],
                        "to": feature_text[journey.destination]["label"],
                        "transport": journey.transport_label,
                        "duration": journey.duration.model_dump(mode="json")
                        if journey.duration
                        else None,
                        "distance": journey.distance.model_dump(mode="json")
                        if journey.distance
                        else None,
                        "access_conditions": [
                            {
                                "label": condition.label,
                                "type": type_text.get(
                                    (condition.type_ref, condition.type_revision_id)
                                )
                                if condition.type_ref
                                else None,
                            }
                            for condition in journey.access_conditions
                        ],
                        "types": [
                            type_text[pair] for pair in type_pairs if pair in type_text
                        ],
                    }
                )

            payload = {
                "当前地点": current_labels,
                "上级地点": ancestor_titles.get(str(node.id), [])
                if location_features or node_is_location
                else [],
                "邻接与通路": related_edges,
                "行程与通行条件": journeys,
                "移动对象最后位置": positions_for_node,
                "空间类型": [
                    {
                        "label": space.label,
                        "type": type_text.get((space.type_ref, space.type_revision_id)),
                    }
                    for space in document.spaces
                    if space.id in {features[key].space_id for key in focus_features}
                ],
                "项目类型": [
                    type_text[key]
                    for key in sorted(used_type_pairs, key=str)
                    if key in type_text
                ][:_MAX_TYPES],
            }
            encoded, clipped = _safe_json(payload)
            if clipped:
                omitted_count += 1
            if not encoded or encoded == "{}":
                continue
            selected_hashes = sorted(included_source_hashes)
            revision_hash = stable_hash(
                {
                    "node_id": str(node.id),
                    "title": str(node.title),
                    "revision_id": str(revision.id),
                    "document": revision.document,
                }
            )
            content_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
            items.append(
                MapSpatialBriefItem(
                    node_id=str(node.id),
                    revision_id=str(revision.id),
                    title=str(node.title)[:200],
                    content=encoded,
                    content_hash=content_hash,
                    revision_hash=revision_hash,
                    geometry_hash=str(revision.geometry_hash or ""),
                    source_hashes=selected_hashes[:64],
                )
            )

        if len(items) > data.limit:
            omitted_count += len(items) - data.limit
            items = items[: data.limit]

        # No explicit Scene location and no exact query match means no map placeholder.
        return MapSpatialBriefResponse(
            scene_id=data.scene_id,
            scene_index=int(scene_index) if isinstance(scene_index, int) else None,
            chapter_index=cutoff_chapter,
            items=items,
            omitted_count=omitted_count,
        )

    @staticmethod
    async def _page_source_visible(
        db,
        data: MapSpatialBriefRequest,
        ref,
        *,
        visibility_mode: str,
        cutoff_chapter: int | None,
        knowledge_visible: bool,
    ) -> bool:
        # World Bible pages have no direct reader/character projection. For
        # author-safe/full prompts, only a quote present in the safe projection
        # may support a map claim.
        if (
            not knowledge_visible
            or visibility_mode != "reader"
            or data.reveal_mode in {"reader", "character"}
        ):
            return False
        from modules.world.facade import get_world_bible_projection_candidates

        resolution = await get_world_bible_projection_candidates(
            db,
            data.novel_id,
            [{"target_type": "world_bible_page", "target_id": str(ref.id)}],
            projection_type="context_brief",
            reveal_mode="author_safe",
        )
        item = next(
            (
                value
                for value in resolution.items
                if str(value.target.get("target_id") or "") == str(ref.id)
            ),
            None,
        )
        if item is None or getattr(item, "warnings", None):
            return False
        return not ref.quote or ref.quote in str(item.content or "")


async def read_map_spatial_brief(
    db, request: MapSpatialBriefRequest | dict
) -> MapSpatialBriefResponse:
    return await MapSpatialBriefService().read(db, request)
