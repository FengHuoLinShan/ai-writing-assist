"""Map Scene summary assembly for the writing view."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError
from modules.world.map_models import MapLocationBinding, MapMarker
from modules.world.map_repositories import (
    MapConfigRepository,
    MapFactRepository,
    MapLocationBindingRepository,
    MapMarkerRepository,
    MapObservationRepository,
    MapTerritoryRepository,
)
from modules.world.map_schemas import (
    MapOpenTarget,
    MapSceneSummaryItem,
    MapSceneSummaryResponse,
    MapSceneSummaryWarning,
)
from modules.world.repositories import CoreEntityRepository
from modules.world.services.common import parse_uuid

SceneLookup = Callable[[AsyncSession, str, str], Awaitable[object | None]]
SUMMARY_DYNAMIC_TYPES: tuple[str, ...] = (
    "crisis",
    "crisis_spread",
    "risk",
    "conflict",
)


async def _default_scene_lookup(
    db: AsyncSession,
    novel_id: str,
    scene_id: str,
) -> object | None:
    from modules.outline.facade import get_scene_contract

    return await get_scene_contract(db, novel_id, scene_id)


class MapSceneSummaryService:
    """Build a compact map summary for one Scene."""

    def __init__(
        self,
        *,
        marker_repo: MapMarkerRepository | None = None,
        binding_repo: MapLocationBindingRepository | None = None,
        territory_repo: MapTerritoryRepository | None = None,
        observation_repo: MapObservationRepository | None = None,
        fact_repo: MapFactRepository | None = None,
        map_repo: MapConfigRepository | None = None,
        entity_repo: CoreEntityRepository | None = None,
        scene_lookup: SceneLookup | None = None,
    ) -> None:
        self._marker_repo = marker_repo or MapMarkerRepository()
        self._binding_repo = binding_repo or MapLocationBindingRepository()
        self._territory_repo = territory_repo or MapTerritoryRepository()
        self._observation_repo = observation_repo or MapObservationRepository()
        self._fact_repo = fact_repo or MapFactRepository()
        self._map_repo = map_repo or MapConfigRepository()
        self._entity_repo = entity_repo or CoreEntityRepository()
        self._scene_lookup = scene_lookup or _default_scene_lookup

    async def summarize(
        self,
        db: AsyncSession,
        novel_id: str,
        scene_id: str,
        *,
        include_candidates: bool = False,
    ) -> MapSceneSummaryResponse:
        scene = await self._scene_lookup(db, novel_id, scene_id)
        if scene is None:
            raise NotFoundError(f"Scene {scene_id} not found", code="scene_not_found")

        nid = parse_uuid(novel_id, "novel_id")
        sid = parse_uuid(scene_id, "scene_id")
        scene_index = getattr(scene, "scene_index", None)
        markers = await self._marker_repo.get_by_scene(
            db, nid, scene_id=sid, scene_index=scene_index
        )
        marker_entities = await self._load_entities_by_id(
            db, nid, [m.entity_id for m in markers]
        )
        marker_statuses = {
            entity_id: getattr(entity, "status", None)
            for entity_id, entity in marker_entities.items()
        }
        markers = [m for m in markers if marker_statuses.get(m.entity_id) == "canonical"]
        # A marker explicitly anchored to this Scene is the strongest static
        # signal. Confirmed Scene facts outrank broad marker ranges, otherwise
        # one long-lived character marker can mask the Scene's real map.
        selected_map_id = self._select_explicit_map_id(markers, sid)
        if selected_map_id is None:
            selected_map_id = await self._fact_repo.find_map_for_scene(
                db,
                nid,
                sid,
            )
        if selected_map_id is None and include_candidates:
            selected_map_id = await self._observation_repo.find_map_for_scene(
                db,
                nid,
                sid,
            )
        if selected_map_id is None:
            selected_map_id = self._select_map_id(markers)
        selected_from_project_fallback = False
        if selected_map_id is None:
            fallback_map = await self._map_repo.first_by_novel(db, nid)
            selected_map_id = fallback_map.id if fallback_map is not None else None
            selected_from_project_fallback = selected_map_id is not None
        entity_names = {
            marker.entity_id: getattr(marker_entities[marker.entity_id], "name", "")
            for marker in markers
            if marker.entity_id in marker_entities
        }
        warnings: list[MapSceneSummaryWarning] = []

        if selected_map_id is None:
            warnings.append(
                MapSceneSummaryWarning(
                    code="scene_without_map_context",
                    message="当前 Scene 暂无地图上下文",
                )
            )
            return MapSceneSummaryResponse(
                scene_id=str(sid),
                primary_location=None,
                characters=[],
                events=[],
                factions=[],
                warnings=warnings[:2],
                open_target=MapOpenTarget(
                    mode="recent",
                    scene_id=str(sid),
                    fallback_reason="scene_without_map",
                    fallback_message="当前 Scene 暂无地图上下文，已回退到最近地图",
                ),
            )

        map_markers = [m for m in markers if m.map_id == selected_map_id]
        primary_location = await self._primary_location(
            db,
            nid,
            selected_map_id,
            map_markers,
            scene_id=sid,
            include_candidates=include_candidates,
        )
        if selected_from_project_fallback and primary_location is None:
            warnings.append(
                MapSceneSummaryWarning(
                    code="scene_without_map_context",
                    message="当前 Scene 暂无地图上下文",
                )
            )
            return MapSceneSummaryResponse(
                scene_id=str(sid),
                primary_location=None,
                characters=[],
                events=[],
                factions=[],
                warnings=warnings[:2],
                open_target=MapOpenTarget(
                    mode="recent",
                    scene_id=str(sid),
                    fallback_reason="scene_without_map",
                    fallback_message="当前 Scene 暂无地图上下文，已回退到最近地图",
                ),
            )
        if primary_location is None:
            warnings.append(
                MapSceneSummaryWarning(
                    code="scene_without_location",
                    message="当前 Scene 暂无主地点",
                )
            )

        characters = self._marker_items(map_markers, entity_names, "character", limit=5)
        events = self._marker_items(map_markers, entity_names, "event", limit=3)
        factions = await self._faction_items(db, nid, selected_map_id, map_markers)
        crises, risks = await self._dynamic_scene_items(
            db,
            nid,
            selected_map_id,
            sid,
            include_candidates=include_candidates,
        )
        warnings.extend(
            await self._cross_map_warnings(
                db, nid, map_markers, scene_index, entity_names
            )
        )

        return MapSceneSummaryResponse(
            scene_id=str(sid),
            primary_location=primary_location,
            characters=characters,
            events=events,
            factions=factions[:3],
            crises=crises[:3],
            risks=risks[:3],
            warnings=warnings[:2],
            open_target=MapOpenTarget(
                mode="map",
                map_id=str(selected_map_id),
                scene_id=str(sid),
            ),
        )

    def _select_explicit_map_id(
        self,
        markers: list[MapMarker],
        scene_id: uuid.UUID,
    ) -> uuid.UUID | None:
        explicit = [
            m
            for m in markers
            if m.start_scene_id == scene_id or m.end_scene_id == scene_id
        ]
        return explicit[0].map_id if explicit else None

    def _select_map_id(self, markers: list[MapMarker]) -> uuid.UUID | None:
        return markers[0].map_id if markers else None

    async def _load_entities_by_id(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        entity_ids: list[Any],
    ) -> dict[uuid.UUID, Any]:
        ids = list({entity_id for entity_id in entity_ids if entity_id is not None})
        if not ids:
            return {}
        entities = await self._entity_repo.get_by_ids(db, novel_id, ids)
        return {e.id: e for e in entities}

    def _marker_items(
        self,
        markers: list[MapMarker],
        entity_names: dict[uuid.UUID, str],
        marker_type: str,
        *,
        limit: int,
    ) -> list[MapSceneSummaryItem]:
        items: list[MapSceneSummaryItem] = []
        seen: set[uuid.UUID] = set()
        for marker in markers:
            if marker.marker_type != marker_type or marker.entity_id in seen:
                continue
            seen.add(marker.entity_id)
            items.append(
                MapSceneSummaryItem(
                    entity_id=str(marker.entity_id),
                    name=entity_names.get(marker.entity_id) or marker.label or "未命名",
                    map_id=str(marker.map_id),
                    hex_q=marker.hex_q,
                    hex_r=marker.hex_r,
                )
            )
            if len(items) >= limit:
                break
        return items

    async def _primary_location(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
        markers: list[MapMarker],
        *,
        scene_id: uuid.UUID | None = None,
        include_candidates: bool = False,
    ) -> MapSceneSummaryItem | None:
        allowed_statuses = (
            ["canonical", "draft", "candidate"] if include_candidates else ["canonical"]
        )
        scene_anchors: list[tuple[uuid.UUID, str | None, str | None]] = []
        has_scene_location_context = False
        if scene_id is not None:
            facts = await self._fact_repo.list_for_scene_summary(
                db,
                novel_id,
                map_id=map_id,
                scene_id=scene_id,
                dynamic_types={"location", "status"},
                fact_status="confirmed",
                limit=20,
            )
            has_scene_location_context = bool(facts)
            for fact in facts:
                anchor = fact.spatial_anchor or {}
                location_id = anchor.get("location_entity_id")
                if location_id:
                    scene_anchors.append(
                        (uuid.UUID(str(location_id)), fact.evidence_text, None)
                    )
            if include_candidates:
                observations = await self._observation_repo.list_for_scene_summary(
                    db,
                    novel_id,
                    map_id=map_id,
                    scene_id=scene_id,
                    dynamic_types={"location", "status"},
                    limit=20,
                )
                has_scene_location_context = bool(
                    has_scene_location_context or observations
                )
                for observation in observations:
                    anchor = observation.spatial_anchor or {}
                    location_id = anchor.get("location_entity_id")
                    if location_id:
                        scene_anchors.append(
                            (
                                uuid.UUID(str(location_id)),
                                observation.evidence_text,
                                observation.review_state,
                            )
                        )

        if scene_anchors:
            anchor_bindings = await self._binding_repo.get_by_map_for_entity_statuses(
                db,
                novel_id,
                map_id,
                statuses=allowed_statuses,
            )
            anchor_entities = await self._entity_repo.get_by_ids(
                db,
                novel_id,
                [location_id for location_id, _, _ in scene_anchors],
            )
            anchor_names = {entity.id: entity.name for entity in anchor_entities}
            anchor_statuses = {entity.id: entity.status for entity in anchor_entities}
            bindings_by_location: dict[uuid.UUID, list[MapLocationBinding]] = {}
            for binding in anchor_bindings:
                bindings_by_location.setdefault(binding.location_entity_id, []).append(
                    binding
                )
            for location_id, evidence_text, review_state in scene_anchors:
                if anchor_statuses.get(location_id) not in allowed_statuses:
                    continue
                candidates = bindings_by_location.get(location_id, [])
                if not candidates:
                    continue
                candidates.sort(key=lambda binding: not binding.is_center)
                binding = candidates[0]
                depends_on_candidate = anchor_statuses.get(location_id) in {
                    "draft",
                    "candidate",
                }
                return MapSceneSummaryItem(
                    entity_id=str(location_id),
                    name=anchor_names.get(location_id) or "未命名地点",
                    map_id=str(binding.map_id),
                    hex_q=binding.hex_q,
                    hex_r=binding.hex_r,
                    depends_on_candidate=depends_on_candidate,
                    candidate_review_state=(
                        review_state or anchor_statuses.get(location_id)
                        if depends_on_candidate
                        else None
                    ),
                    evidence_excerpt=evidence_text,
                )

        # An explicit Scene context with only coordinates deliberately means
        # that the precise canonical location is unknown. Do not replace that
        # boundary with an unrelated first center from the selected map.
        if has_scene_location_context and not markers:
            return None

        marker_hexes = list(
            dict.fromkeys((marker.hex_q, marker.hex_r) for marker in markers)
        )
        if marker_hexes:
            bindings = await self._binding_repo.get_by_hexes_for_entity_statuses(
                db,
                novel_id,
                map_id,
                marker_hexes,
                statuses=allowed_statuses,
            )
        else:
            bindings = await self._binding_repo.get_centers(db, novel_id, map_id)
        by_hex: dict[tuple[int, int], list[MapLocationBinding]] = {}
        for binding in bindings:
            by_hex.setdefault((binding.hex_q, binding.hex_r), []).append(binding)
        location_ids: list[uuid.UUID] = [b.location_entity_id for b in bindings]
        entities = await self._entity_repo.get_by_ids(db, novel_id, location_ids)
        names = {e.id: e.name for e in entities}
        statuses = {e.id: e.status for e in entities}

        def build_item(binding: MapLocationBinding) -> MapSceneSummaryItem:
            status = statuses.get(binding.location_entity_id)
            depends_on_candidate = status in {"draft", "candidate"}
            return MapSceneSummaryItem(
                entity_id=str(binding.location_entity_id),
                name=names.get(binding.location_entity_id) or "未命名地点",
                map_id=str(binding.map_id),
                hex_q=binding.hex_q,
                hex_r=binding.hex_r,
                depends_on_candidate=depends_on_candidate,
                candidate_review_state=status if depends_on_candidate else None,
            )

        if not marker_hexes:
            for binding in bindings:
                if statuses.get(binding.location_entity_id) not in allowed_statuses:
                    continue
                return build_item(binding)
            return None

        for marker in markers:
            candidates = [
                binding
                for binding in by_hex.get((marker.hex_q, marker.hex_r), [])
                if statuses.get(binding.location_entity_id) in allowed_statuses
            ]
            if not candidates:
                continue
            candidates.sort(key=lambda b: not b.is_center)
            return build_item(candidates[0])
        return None

    async def _faction_items(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
        markers: list[MapMarker],
    ) -> list[MapSceneSummaryItem]:
        seen: set[uuid.UUID] = set()
        marker_hexes = list(
            dict.fromkeys((marker.hex_q, marker.hex_r) for marker in markers)
        )
        territory_rows = await self._territory_repo.get_by_hexes(
            db, novel_id, map_id, marker_hexes
        )
        entity_ids = [t.faction_entity_id for t in territory_rows]
        entities = await self._entity_repo.get_by_ids(db, novel_id, entity_ids)
        statuses = {e.id: e.status for e in entities}
        names = {e.id: e.name for e in entities}

        items: list[MapSceneSummaryItem] = []
        for territory in territory_rows:
            if statuses.get(territory.faction_entity_id) != "canonical":
                continue
            if territory.faction_entity_id in seen:
                continue
            seen.add(territory.faction_entity_id)
            items.append(
                MapSceneSummaryItem(
                    entity_id=str(territory.faction_entity_id),
                    name=names.get(territory.faction_entity_id) or "未命名势力",
                    map_id=str(territory.map_id),
                    hex_q=territory.hex_q,
                    hex_r=territory.hex_r,
                )
            )
        return items

    async def _dynamic_scene_items(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
        scene_id: uuid.UUID,
        *,
        include_candidates: bool,
    ) -> tuple[list[MapSceneSummaryItem], list[MapSceneSummaryWarning]]:
        facts = await self._fact_repo.list_for_scene_summary(
            db,
            novel_id,
            map_id=map_id,
            scene_id=scene_id,
            dynamic_types=SUMMARY_DYNAMIC_TYPES,
            fact_status="confirmed",
            limit=80,
        )
        observations = []
        if include_candidates:
            observations = await self._observation_repo.list_for_scene_summary(
                db,
                novel_id,
                map_id=map_id,
                scene_id=scene_id,
                dynamic_types=SUMMARY_DYNAMIC_TYPES,
                limit=80,
            )
        crises: list[MapSceneSummaryItem] = []
        risks: list[MapSceneSummaryWarning] = []
        confirmed_fact_keys: set[tuple[str, str | None, int | None, int | None]] = set()
        for fact in facts:
            if fact.dynamic_type not in {
                "crisis",
                "crisis_spread",
                "risk",
                "conflict",
            }:
                continue
            confirmed_fact_keys.add(self._dynamic_summary_key(fact))
            anchor = fact.spatial_anchor or {}
            title = fact.target_name or fact.target_entity_type or "地图风险"
            open_target = {
                "kind": "map_object",
                "map_id": str(fact.map_id or map_id),
                "scene_id": str(scene_id),
                "observation_id": (
                    str(fact.observation_id) if fact.observation_id else None
                ),
                "focus_entity_id": (
                    str(fact.target_entity_id) if fact.target_entity_id else None
                ),
            }
            crises.append(
                MapSceneSummaryItem(
                    entity_id=str(fact.target_entity_id or fact.id),
                    name=title,
                    map_id=str(fact.map_id or map_id),
                    hex_q=anchor.get("hex_q"),
                    hex_r=anchor.get("hex_r"),
                    evidence_excerpt=fact.evidence_text,
                    open_target=open_target,
                )
            )
            risks.append(
                MapSceneSummaryWarning(
                    level="warning",
                    code="map_dynamic_risk",
                    message=f"{title}：{self._status_label(fact.fact_status)}",
                    evidence_excerpt=fact.evidence_text,
                    open_target=open_target,
                )
            )
        for observation in observations:
            is_candidate_dependent = observation.review_state in {
                "candidate",
                "conflicted",
            }
            if is_candidate_dependent and not include_candidates:
                continue
            if observation.dynamic_type not in {
                "crisis",
                "crisis_spread",
                "risk",
                "conflict",
            }:
                continue
            if self._dynamic_summary_key(observation) in confirmed_fact_keys:
                continue
            anchor = observation.spatial_anchor or {}
            title = (
                observation.target_name or observation.target_entity_type or "地图风险"
            )
            open_target = {
                "kind": "map_object",
                "map_id": str(observation.map_id or map_id),
                "scene_id": str(scene_id),
                "observation_id": str(observation.id),
                "focus_entity_id": (
                    str(observation.target_entity_id)
                    if observation.target_entity_id
                    else None
                ),
            }
            crises.append(
                MapSceneSummaryItem(
                    entity_id=str(observation.target_entity_id or observation.id),
                    name=title,
                    map_id=str(observation.map_id or map_id),
                    hex_q=anchor.get("hex_q"),
                    hex_r=anchor.get("hex_r"),
                    depends_on_candidate=is_candidate_dependent,
                    candidate_review_state=(
                        observation.review_state if is_candidate_dependent else None
                    ),
                    evidence_excerpt=observation.evidence_text,
                    open_target=open_target,
                )
            )
            risks.append(
                MapSceneSummaryWarning(
                    level="warning",
                    code="map_dynamic_risk",
                    message=f"{title}：{self._status_label(observation.review_state)}",
                    depends_on_candidate=is_candidate_dependent,
                    candidate_review_state=(
                        observation.review_state if is_candidate_dependent else None
                    ),
                    evidence_excerpt=observation.evidence_text,
                    open_target=open_target,
                )
            )
        return crises, risks

    def _dynamic_summary_key(
        self,
        item: Any,
    ) -> tuple[str, str | None, int | None, int | None]:
        anchor = getattr(item, "spatial_anchor", None) or {}
        target_entity_id = getattr(item, "target_entity_id", None)
        target = (
            str(target_entity_id)
            if target_entity_id
            else getattr(
                item,
                "target_name",
                None,
            )
        )
        return (
            getattr(item, "dynamic_type"),
            target,
            anchor.get("hex_q"),
            anchor.get("hex_r"),
        )

    def _status_label(self, status: str | None) -> str:
        return {
            "candidate": "待处理",
            "confirmed": "已采用",
            "ignored": "已忽略",
            "conflicted": "待处理",
        }.get(status or "", "待判断")

    async def _cross_map_warnings(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        markers: list[MapMarker],
        scene_index: int | None,
        entity_names: dict[uuid.UUID, str],
    ) -> list[MapSceneSummaryWarning]:
        if scene_index is None:
            return []
        character_markers = [m for m in markers if m.marker_type == "character"]
        previous = await self._marker_repo.get_latest_before_scene_for_entities(
            db,
            novel_id,
            entity_ids=[m.entity_id for m in character_markers],
            scene_index=scene_index,
        )
        warnings: list[MapSceneSummaryWarning] = []
        for marker in character_markers:
            prev = previous.get(marker.entity_id)
            if prev is None or prev.map_id == marker.map_id:
                continue
            name = entity_names.get(marker.entity_id) or marker.label or "角色"
            warnings.append(
                MapSceneSummaryWarning(
                    code="character_cross_map",
                    message=f"{name}上一场在其他地图，需确认移动合理性",
                )
            )
        return warnings
