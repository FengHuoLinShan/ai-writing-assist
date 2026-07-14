"""Deterministic Scene timeline and spatial continuity read projections."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ValidationError
from modules.world.map_repositories import (
    MapFactRepository,
    MapObservationRepository,
    MapPathNodeRepository,
    MapPathRepository,
)
from modules.world.map_schemas import (
    MAP_DYNAMIC_TRACKS,
    TRANSPORT_PATH_TYPES,
    WATER_PATH_TYPES,
    MapContinuityIssue,
    MapDynamicConflict,
    MapDynamicDeltaRead,
    MapDynamicStateAtResponse,
    MapDynamicStateItem,
    MapDynamicTimelineResponse,
    MapDynamicTimelineScene,
    MapFactResponse,
    MapObservationResponse,
)
from modules.world.services.common import parse_uuid
from modules.world.services.map.map_context import MapContext
from modules.world.services.map.map_dynamic_projection import normalize_dynamic_value

_MAX_PROJECTION_FACTS = 20000
_MAX_CANDIDATES = 500
_GLOBAL_PROJECTION_DYNAMIC_TYPES = frozenset(
    {"route", "route_state", "route-state", "path_state", "path-state"}
)


@dataclass
class _StateRecord:
    target_entity_id: str | None
    target_entity_type: str | None
    target_name: str | None
    dynamic_type: str
    track: str
    dimension_key: str
    value: dict[str, Any]
    signature: str
    spatial_anchor: dict[str, Any]
    source_fact_ids: list[str]
    scene_index: int
    source_chapter_index: int | None


@dataclass
class _Projection:
    deltas: list[MapDynamicDeltaRead]
    conflicts: list[MapDynamicConflict]
    states: list[MapDynamicStateItem]
    active_conflicts: list[MapDynamicConflict]


class MapTimelineService:
    """Build read-only dynamic projections without creating derived rows."""

    def __init__(
        self,
        *,
        context: MapContext | None = None,
        fact_repo: MapFactRepository | None = None,
        observation_repo: MapObservationRepository | None = None,
        path_repo: MapPathRepository | None = None,
        path_node_repo: MapPathNodeRepository | None = None,
    ) -> None:
        self._ctx = context or MapContext()
        self._fact_repo = fact_repo or MapFactRepository()
        self._observation_repo = observation_repo or MapObservationRepository()
        self._path_repo = path_repo or MapPathRepository()
        self._path_node_repo = path_node_repo or MapPathNodeRepository()

    async def get_timeline(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        map_id: str,
        from_scene_index: int | None = None,
        to_scene_index: int | None = None,
        focus_entity_id: str | None = None,
        tracks: set[str] | None = None,
        include_candidates: bool = False,
        skip: int = 0,
        limit: int = 100,
    ) -> MapDynamicTimelineResponse:
        config = await self._ctx.require_map(db, novel_id, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        focus_id = await self._validated_focus(
            db,
            novel_id,
            focus_entity_id,
        )
        selected_tracks = self._validated_tracks(tracks)
        from_scene_index, to_scene_index = await self._resolve_range(
            db,
            nid,
            mid,
            focus_id,
            from_scene_index,
            to_scene_index,
        )
        if from_scene_index is None or to_scene_index is None:
            paths = await self._path_repo.get_by_map(db, nid, mid, status="all")
            return MapDynamicTimelineResponse(
                map_id=map_id,
                projection_token=self._projection_token(map_id, [], paths),
                from_scene_index=None,
                to_scene_index=None,
                skip=skip,
                limit=limit,
            )

        facts = await self._fact_repo.list_for_projection(
            db,
            nid,
            map_id=mid,
            to_scene_index=to_scene_index,
            focus_entity_id=focus_id,
            context_dynamic_types=_GLOBAL_PROJECTION_DYNAMIC_TYPES,
            limit=_MAX_PROJECTION_FACTS + 1,
        )
        if len(facts) > _MAX_PROJECTION_FACTS:
            raise ValidationError(
                "时间切片需要投影的事实过多，请缩小 Scene 范围",
                code="map_timeline_projection_limit",
                status_code=422,
            )
        projection = self._project_facts(facts)
        untyped_facts = [
            response
            for response in (MapFactResponse.model_validate(item) for item in facts)
            if response.scene_index is not None
            and from_scene_index <= response.scene_index <= to_scene_index
            and response.normalized_value is None
            and "world" in selected_tracks
            and self._visible_for_focus(response.target_entity_id, focus_id)
        ]
        all_deltas = [
            item
            for item in projection.deltas
            if item.track in selected_tracks
            and self._visible_for_focus(item.target_entity_id, focus_id)
        ]
        deltas = [
            item
            for item in all_deltas
            if from_scene_index <= item.scene_index <= to_scene_index
        ]
        conflicts = [
            item
            for item in projection.conflicts
            if from_scene_index <= item.scene_index <= to_scene_index
            and self._track_for_type(item.dynamic_type) in selected_tracks
            and self._visible_for_focus(item.target_entity_id, focus_id)
        ]

        candidates: list[MapObservationResponse] = []
        candidate_rows: list[Any] = []
        if include_candidates:
            candidate_rows = await self._observation_repo.list_timeline_candidates(
                db,
                nid,
                map_id=mid,
                from_scene_index=from_scene_index,
                to_scene_index=to_scene_index,
                focus_entity_id=focus_id,
                limit=_MAX_CANDIDATES + 1,
            )
            if len(candidate_rows) > _MAX_CANDIDATES:
                raise ValidationError(
                    "待处理地图动态过多，请缩小 Scene 范围",
                    code="map_timeline_candidate_limit",
                    status_code=422,
                )
            candidates = [
                response
                for response in (
                    MapObservationResponse.model_validate(item)
                    for item in candidate_rows
                )
                if self._track_for_type(
                    response.normalized_value.type
                    if response.normalized_value is not None
                    else response.dynamic_type
                )
                in selected_tracks
            ]

        paths = await self._path_repo.get_by_map(db, nid, mid, status="all")
        path_nodes = await self._path_node_repo.get_by_paths(
            db,
            nid,
            mid,
            [path.id for path in paths],
        )
        continuity_deltas = [
            item
            for item in projection.deltas
            if item.dynamic_type == "route_state"
            or (
                item.track in selected_tracks
                and self._visible_for_focus(item.target_entity_id, focus_id)
            )
        ]
        continuity_conflicts = [
            item
            for item in projection.conflicts
            if item.dynamic_type == "route_state"
            or (
                self._track_for_type(item.dynamic_type) in selected_tracks
                and self._visible_for_focus(item.target_entity_id, focus_id)
            )
        ]
        issues = self._continuity_issues(
            config,
            continuity_deltas,
            continuity_conflicts,
            paths,
            path_nodes,
        )
        issues = [
            item
            for item in issues
            if from_scene_index <= item.to_scene_index <= to_scene_index
        ]

        undated = await self._fact_repo.list_undated_for_projection(
            db,
            nid,
            map_id=mid,
            focus_entity_id=focus_id,
            limit=100,
        )
        undated_responses = [
            response
            for response in (MapFactResponse.model_validate(item) for item in undated)
            if self._track_for_type(
                response.normalized_value.type
                if response.normalized_value is not None
                else response.dynamic_type
            )
            in selected_tracks
        ]
        scenes = self._scene_summaries(deltas, candidates, conflicts, issues)
        total = len(deltas)
        page = deltas[skip : skip + limit]
        return MapDynamicTimelineResponse(
            map_id=map_id,
            projection_token=self._projection_token(
                map_id,
                facts,
                paths,
            ),
            from_scene_index=from_scene_index,
            to_scene_index=to_scene_index,
            scenes=scenes,
            deltas=page,
            candidates=candidates,
            conflicts=conflicts,
            continuity_issues=issues,
            untyped_facts=untyped_facts,
            undated_facts=undated_responses,
            total=total,
            skip=skip,
            limit=limit,
            has_more=skip + len(page) < total,
        )

    async def get_state_at(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        map_id: str,
        scene_index: int,
        focus_entity_id: str | None = None,
        tracks: set[str] | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> MapDynamicStateAtResponse:
        await self._ctx.require_map(db, novel_id, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        focus_id = await self._validated_focus(db, novel_id, focus_entity_id)
        selected_tracks = self._validated_tracks(tracks)
        facts = await self._fact_repo.list_for_projection(
            db,
            nid,
            map_id=mid,
            to_scene_index=scene_index,
            focus_entity_id=focus_id,
            context_dynamic_types=_GLOBAL_PROJECTION_DYNAMIC_TYPES,
            limit=_MAX_PROJECTION_FACTS + 1,
        )
        if len(facts) > _MAX_PROJECTION_FACTS:
            raise ValidationError(
                "时间切片需要投影的事实过多，请使用更精确的实体焦点",
                code="map_timeline_projection_limit",
                status_code=422,
            )
        projection = self._project_facts(facts)
        items = [
            item
            for item in projection.states
            if item.track in selected_tracks
            and self._visible_for_focus(item.target_entity_id, focus_id)
        ]
        conflicts = [
            item
            for item in projection.active_conflicts
            if self._track_for_type(item.dynamic_type) in selected_tracks
            and self._visible_for_focus(item.target_entity_id, focus_id)
        ]
        total = len(items)
        page = items[skip : skip + limit]
        paths = await self._path_repo.get_by_map(db, nid, mid, status="all")
        return MapDynamicStateAtResponse(
            map_id=map_id,
            projection_token=self._projection_token(map_id, facts, paths),
            scene_index=scene_index,
            items=page,
            conflicts=conflicts,
            total=total,
            skip=skip,
            limit=limit,
            has_more=skip + len(page) < total,
        )

    async def _validated_focus(
        self,
        db: AsyncSession,
        novel_id: str,
        focus_entity_id: str | None,
    ) -> uuid.UUID | None:
        if not focus_entity_id:
            return None
        await self._ctx.require_entity(db, novel_id, focus_entity_id)
        return parse_uuid(focus_entity_id, "focus_entity_id")

    @staticmethod
    def _visible_for_focus(
        target_entity_id: str | None,
        focus_entity_id: uuid.UUID | None,
    ) -> bool:
        """Expose the focused entity plus target-less global context only."""
        return (
            focus_entity_id is None
            or target_entity_id is None
            or target_entity_id == str(focus_entity_id)
        )

    def _validated_tracks(self, tracks: set[str] | None) -> set[str]:
        selected = tracks or set(MAP_DYNAMIC_TRACKS)
        invalid = selected - set(MAP_DYNAMIC_TRACKS)
        if invalid:
            raise ValidationError(
                f"未知动态轨道: {', '.join(sorted(invalid))}",
                code="invalid_map_dynamic_track",
                status_code=422,
            )
        return selected

    async def _resolve_range(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
        focus_entity_id: uuid.UUID | None,
        from_scene_index: int | None,
        to_scene_index: int | None,
    ) -> tuple[int | None, int | None]:
        if from_scene_index is not None and to_scene_index is not None:
            if from_scene_index > to_scene_index:
                raise ValidationError(
                    "from_scene_index 不能大于 to_scene_index",
                    code="invalid_map_timeline_range",
                    status_code=422,
                )
            if to_scene_index - from_scene_index >= 500:
                raise ValidationError(
                    "单次时间轴最多跨越 500 个 Scene",
                    code="map_timeline_range_limit",
                    status_code=422,
                )
            return from_scene_index, to_scene_index

        indices = await self._fact_repo.latest_scene_indices(
            db,
            novel_id,
            map_id=map_id,
            focus_entity_id=focus_entity_id,
            limit=50,
        )
        if not indices:
            if from_scene_index is None and to_scene_index is None:
                return None, None
            boundary = (
                from_scene_index
                if from_scene_index is not None
                else to_scene_index
            )
            return boundary, boundary
        latest = max(indices)
        if from_scene_index is not None:
            resolved_to = latest
            if resolved_to < from_scene_index:
                resolved_to = from_scene_index
            if resolved_to - from_scene_index >= 500:
                resolved_to = from_scene_index + 499
            return from_scene_index, resolved_to
        if to_scene_index is not None:
            return max(0, to_scene_index - 499), to_scene_index
        latest = max(indices)
        return max(min(indices), latest - 499), latest

    def _project_facts(self, facts: list[Any]) -> _Projection:
        grouped: dict[tuple[str, str], list[tuple[Any, dict[str, Any], str, str]]] = (
            defaultdict(list)
        )
        for fact in facts:
            normalized = normalize_dynamic_value(
                fact.dynamic_type,
                fact.value_json,
                fact.spatial_anchor,
            )
            if normalized.value is None or normalized.dimension_key is None:
                continue
            target_key = self._target_key(fact, normalized.value)
            signature = self._state_signature(
                normalized.value,
                fact.spatial_anchor or {},
            )
            grouped[(target_key, normalized.dimension_key)].append(
                (fact, normalized.value, normalized.dimension_key, signature)
            )

        deltas: list[MapDynamicDeltaRead] = []
        conflicts: list[MapDynamicConflict] = []
        states: dict[tuple[str, str], _StateRecord] = {}
        active_conflicts: dict[tuple[str, str], MapDynamicConflict] = {}
        for key in sorted(grouped):
            by_scene: dict[int, list[tuple[Any, dict[str, Any], str, str]]] = defaultdict(
                list
            )
            for entry in grouped[key]:
                fact = entry[0]
                if fact.scene_index is not None:
                    by_scene[int(fact.scene_index)].append(entry)
            previous: _StateRecord | None = None
            for scene_index in sorted(by_scene):
                entries = sorted(
                    by_scene[scene_index],
                    key=lambda item: (
                        item[0].source_chapter_index is None,
                        item[0].source_chapter_index or 0,
                        item[0].created_at,
                        str(item[0].id),
                    ),
                )
                by_signature: dict[
                    str, list[tuple[Any, dict[str, Any], str, str]]
                ] = defaultdict(list)
                for entry in entries:
                    by_signature[entry[3]].append(entry)
                representative = entries[0]
                fact = representative[0]
                dimension_key = representative[2]
                if len(by_signature) > 1:
                    conflict = MapDynamicConflict(
                        conflict_id=self._stable_id(
                            "conflict",
                            dimension_key,
                            str(scene_index),
                            *(str(item[0].id) for item in entries),
                        ),
                        target_entity_id=(
                            str(fact.target_entity_id)
                            if fact.target_entity_id
                            else None
                        ),
                        target_entity_type=fact.target_entity_type,
                        target_name=fact.target_name,
                        dynamic_type=representative[1]["type"],
                        dimension_key=dimension_key,
                        scene_index=scene_index,
                        source_fact_ids=[str(item[0].id) for item in entries],
                        values=[items[0][1] for items in by_signature.values()],
                        spatial_anchors=[
                            dict(items[0][0].spatial_anchor or {})
                            for items in by_signature.values()
                        ],
                    )
                    conflicts.append(conflict)
                    active_conflicts[key] = conflict
                    states.pop(key, None)
                    previous = None
                    continue

                matching = next(iter(by_signature.values()))
                current_fact = matching[0][0]
                current_value = matching[0][1]
                current_signature = matching[0][3]
                current = _StateRecord(
                    target_entity_id=(
                        str(current_fact.target_entity_id)
                        if current_fact.target_entity_id
                        else None
                    ),
                    target_entity_type=current_fact.target_entity_type,
                    target_name=current_fact.target_name,
                    dynamic_type=current_value["type"],
                    track=self._track_for_type(current_value["type"]),
                    dimension_key=dimension_key,
                    value=current_value,
                    signature=current_signature,
                    spatial_anchor=dict(current_fact.spatial_anchor or {}),
                    source_fact_ids=[str(item[0].id) for item in matching],
                    scene_index=scene_index,
                    source_chapter_index=current_fact.source_chapter_index,
                )
                active_conflicts.pop(key, None)
                states[key] = current
                if previous is None or previous.signature != current.signature:
                    delta_source_ids = list(
                        dict.fromkeys(
                            [
                                *(previous.source_fact_ids if previous else []),
                                *current.source_fact_ids,
                            ]
                        )
                    )
                    deltas.append(
                        MapDynamicDeltaRead(
                            delta_id=self._stable_id(
                                "delta",
                                dimension_key,
                                str(scene_index),
                                *delta_source_ids,
                            ),
                            target_entity_id=current.target_entity_id,
                            target_entity_type=current.target_entity_type,
                            target_name=current.target_name,
                            dynamic_type=current.dynamic_type,
                            track=current.track,
                            dimension_key=current.dimension_key,
                            scene_index=current.scene_index,
                            before_scene_index=(
                                previous.scene_index if previous else None
                            ),
                            source_chapter_index=current.source_chapter_index,
                            change_kind="initial" if previous is None else "change",
                            before=previous.value if previous else None,
                            after=current.value,
                            spatial_anchor_before=(
                                previous.spatial_anchor if previous else None
                            ),
                            spatial_anchor_after=current.spatial_anchor,
                            source_fact_ids=delta_source_ids,
                        )
                    )
                previous = current

        state_items = [
            MapDynamicStateItem(
                target_entity_id=item.target_entity_id,
                target_entity_type=item.target_entity_type,
                target_name=item.target_name,
                dynamic_type=item.dynamic_type,
                track=item.track,
                dimension_key=item.dimension_key,
                normalized_value=item.value,
                spatial_anchor=item.spatial_anchor,
                source_fact_ids=item.source_fact_ids,
                scene_index=item.scene_index,
            )
            for _, item in sorted(
                states.items(),
                key=lambda pair: (
                    pair[1].target_name or "",
                    pair[1].target_entity_id or "",
                    pair[1].dimension_key,
                ),
            )
        ]
        deltas.sort(
            key=lambda item: (item.scene_index, item.dimension_key, item.delta_id)
        )
        conflicts.sort(
            key=lambda item: (item.scene_index, item.dimension_key, item.conflict_id)
        )
        return _Projection(
            deltas=deltas,
            conflicts=conflicts,
            states=state_items,
            active_conflicts=list(active_conflicts.values()),
        )

    def _continuity_issues(
        self,
        config: Any,
        deltas: list[MapDynamicDeltaRead],
        conflicts: list[MapDynamicConflict],
        paths: list[Any],
        path_nodes: list[Any],
    ) -> list[MapContinuityIssue]:
        issues: list[MapContinuityIssue] = []
        for conflict in conflicts:
            if conflict.dynamic_type != "location":
                continue
            issues.append(
                self._issue(
                    issue_type="same_scene_conflict",
                    severity="danger",
                    target_entity_id=conflict.target_entity_id,
                    target_name=conflict.target_name,
                    from_scene_index=conflict.scene_index,
                    to_scene_index=conflict.scene_index,
                    source_fact_ids=conflict.source_fact_ids,
                    message="同一 Scene 存在互相矛盾的位置事实。",
                )
            )

        paths_by_id = {str(path.id): path for path in paths}
        nodes_by_path: dict[str, list[Any]] = defaultdict(list)
        for node in path_nodes:
            nodes_by_path[str(node.path_id)].append(node)
        location_deltas = [item for item in deltas if item.dynamic_type == "location"]
        route_deltas = [item for item in deltas if item.dynamic_type == "route_state"]
        for delta in location_deltas:
            if delta.change_kind != "change" or delta.before is None:
                continue
            before_anchor = dict(delta.spatial_anchor_before or {})
            after_anchor = dict(delta.spatial_anchor_after or {})
            revision_mismatch = False
            for anchor in (before_anchor, after_anchor):
                path_id = anchor.get("path_id")
                revision = anchor.get("path_revision")
                current_path = paths_by_id.get(str(path_id)) if path_id else None
                if revision is not None and (
                    current_path is None
                    or current_path.status != "active"
                    or current_path.content_revision != revision
                ):
                    revision_mismatch = True
                    issues.append(
                        self._issue_from_delta(
                            delta,
                            issue_type="path_revision_mismatch",
                            severity="warning",
                            path_ids=[str(path_id)] if path_id else [],
                            message="事实保存的线路版本与当前地图不一致，需重新确认。",
                        )
                    )

            if revision_mismatch:
                continue

            before_value = self._dynamic_payload(delta.before)
            after_value = self._dynamic_payload(delta.after)
            before_location = self._location_id(before_value, before_anchor)
            after_location = self._location_id(after_value, after_anchor)
            before_point = self._anchor_point(before_anchor)
            after_point = self._anchor_point(after_anchor)
            distance = (
                self._axial_distance(before_point, after_point)
                if before_point is not None and after_point is not None
                else None
            )
            if not self._has_anchor(before_value, before_anchor) or not self._has_anchor(
                after_value, after_anchor
            ):
                issues.append(
                    self._issue_from_delta(
                        delta,
                        issue_type="missing_anchor",
                        severity="warning",
                        distance_hex=distance,
                        message="移动事实缺少可确认的起点或终点锚点。",
                    )
                )
                continue
            mode = str(after_value.get("movement_mode") or "unknown")
            if mode in {"flight", "teleport"}:
                continue
            if before_location is None or after_location is None:
                issues.append(
                    self._issue_from_delta(
                        delta,
                        issue_type="route_unknown",
                        severity="info",
                        distance_hex=distance,
                        message="位置可定位，但未绑定到完整线路端点，无法判断可达性。",
                    )
                )
                continue

            category = "water" if mode == "water" else "transport"
            matching_paths = [
                path
                for path in paths
                if path.status == "active"
                and self._path_category(path.path_type) == category
                and path.start_location_entity_id is not None
                and path.end_location_entity_id is not None
            ]
            conflict_path_ids = self._active_route_conflict_ids(
                conflicts,
                route_deltas,
                delta.scene_index,
            )
            matching_path_ids = {str(path.id) for path in matching_paths}
            if conflict_path_ids & matching_path_ids:
                issues.append(
                    self._issue_from_delta(
                        delta,
                        issue_type="route_unknown",
                        severity="warning",
                        path_ids=sorted(conflict_path_ids & matching_path_ids),
                        distance_hex=distance,
                        message="该 Scene 的线路状态互相矛盾，无法判断可达性。",
                    )
                )
                continue
            all_graph = self._path_graph(matching_paths, nodes_by_path, blocked=set())
            route_states = self._route_states_at(route_deltas, delta.scene_index)
            blocked_ids = {
                path_id for path_id, state in route_states.items() if state == "blocked"
            }
            open_graph = self._path_graph(
                matching_paths,
                nodes_by_path,
                blocked=blocked_ids,
            )
            endpoints = set(all_graph)
            if before_location not in endpoints or after_location not in endpoints:
                issues.append(
                    self._issue_from_delta(
                        delta,
                        issue_type="route_unknown",
                        severity="info",
                        distance_hex=distance,
                        message="移动端点没有完整接入当前线路图。",
                    )
                )
                continue
            open_route = self._find_route(open_graph, before_location, after_location)
            if open_route is not None:
                continue
            any_route = self._find_route(all_graph, before_location, after_location)
            if any_route is not None:
                blocking = [path_id for path_id in any_route if path_id in blocked_ids]
                issues.append(
                    self._issue_from_delta(
                        delta,
                        issue_type="blocked_route",
                        severity="danger",
                        path_ids=blocking,
                        distance_hex=distance,
                        message="起终点原有线路已在该 Scene 被阻断。",
                    )
                )
                continue
            issues.append(
                self._issue_from_delta(
                    delta,
                    issue_type="no_route",
                    severity="warning",
                    distance_hex=distance,
                    message="起终点都已接入线路图，但不存在连通路径。",
                )
            )
        return self._dedupe_issues(issues)

    def _issue_from_delta(
        self,
        delta: MapDynamicDeltaRead,
        *,
        issue_type: str,
        severity: str,
        message: str,
        path_ids: list[str] | None = None,
        distance_hex: float | None = None,
    ) -> MapContinuityIssue:
        previous_scene = delta.before_scene_index
        if previous_scene is None:
            previous_scene = max(0, delta.scene_index - 1)
        return self._issue(
            issue_type=issue_type,
            severity=severity,
            target_entity_id=delta.target_entity_id,
            target_name=delta.target_name,
            from_scene_index=previous_scene,
            to_scene_index=delta.scene_index,
            source_fact_ids=delta.source_fact_ids,
            path_ids=path_ids or [],
            distance_hex=distance_hex,
            message=message,
            spatial_anchor=delta.spatial_anchor_after or {},
        )

    def _issue(
        self,
        *,
        issue_type: str,
        severity: str,
        target_entity_id: str | None,
        target_name: str | None,
        from_scene_index: int,
        to_scene_index: int,
        source_fact_ids: list[str],
        message: str,
        path_ids: list[str] | None = None,
        distance_hex: float | None = None,
        spatial_anchor: dict[str, Any] | None = None,
    ) -> MapContinuityIssue:
        issue_key = self._stable_id(
            "continuity",
            issue_type,
            target_entity_id or target_name or "unknown",
            str(from_scene_index),
            str(to_scene_index),
            *source_fact_ids,
            *(path_ids or []),
        )
        related_ids = [target_entity_id] if target_entity_id else []
        suggested_observation = {
            "target_entity_id": target_entity_id,
            "target_entity_type": None,
            "target_name": target_name,
            "dynamic_type": "movement_explanation",
            "time_anchor": {
                "from_scene_index": from_scene_index,
                "to_scene_index": to_scene_index,
            },
            "spatial_anchor": spatial_anchor or {},
            "value_json": {
                "schema_version": 1,
                "type": "semantic",
                "relation_type": "movement_explanation",
                "related_entity_ids": related_ids,
                "summary": "",
            },
            "confidence": 1.0,
            "review_state": "candidate",
            "source_ref": {
                "source": "map_continuity",
                "issue_key": issue_key,
                "source_fact_ids": source_fact_ids,
            },
            "evidence_text": "",
            "scene_id": None,
            "scene_index": to_scene_index,
            "source_chapter_index": None,
        }
        return MapContinuityIssue(
            issue_key=issue_key,
            issue_type=issue_type,
            severity=severity,
            target_entity_id=target_entity_id,
            target_name=target_name,
            from_scene_index=from_scene_index,
            to_scene_index=to_scene_index,
            source_fact_ids=source_fact_ids,
            path_ids=path_ids or [],
            distance_hex=distance_hex,
            message=message,
            suggested_observation=suggested_observation,
        )

    @staticmethod
    def _scene_summaries(
        deltas: list[MapDynamicDeltaRead],
        candidates: list[MapObservationResponse],
        conflicts: list[MapDynamicConflict],
        issues: list[MapContinuityIssue],
    ) -> list[MapDynamicTimelineScene]:
        counts: dict[int, dict[str, int]] = defaultdict(
            lambda: {
                "delta_count": 0,
                "candidate_count": 0,
                "conflict_count": 0,
                "continuity_issue_count": 0,
            }
        )
        for item in deltas:
            counts[item.scene_index]["delta_count"] += 1
        for item in candidates:
            if item.scene_index is not None:
                counts[item.scene_index]["candidate_count"] += 1
        for item in conflicts:
            counts[item.scene_index]["conflict_count"] += 1
        for item in issues:
            counts[item.to_scene_index]["continuity_issue_count"] += 1
        return [
            MapDynamicTimelineScene(scene_index=scene_index, **counts[scene_index])
            for scene_index in sorted(counts)
        ]

    @staticmethod
    def _track_for_type(dynamic_type: str) -> str:
        return {
            "location": "journey",
            "movement": "journey",
            "position_change": "journey",
            "boundary": "territory",
            "territory": "territory",
            "crisis": "crisis",
            "resource": "resource",
            "status": "status",
        }.get(str(dynamic_type), "world")

    @staticmethod
    def _target_key(fact: Any, value: dict[str, Any]) -> str:
        if fact.target_entity_id:
            return f"entity:{fact.target_entity_id}"
        if value["type"] in {
            "route_state",
            "boundary",
            "resource",
            "terrain",
            "crisis",
        }:
            return f"stable:{value['type']}"
        if value["type"] == "semantic" and value.get("related_entity_ids"):
            return "stable:semantic"
        return f"fact:{fact.id}"

    @staticmethod
    def _state_signature(value: dict[str, Any], anchor: dict[str, Any]) -> str:
        signature: dict[str, Any] = {"value": value}
        if value["type"] == "location":
            signature["anchor"] = {
                key: anchor.get(key)
                for key in (
                    "map_id",
                    "path_id",
                    "location_entity_id",
                    "hex_q",
                    "hex_r",
                    "representative_q",
                    "representative_r",
                )
                if anchor.get(key) is not None
            }
        return json.dumps(
            signature,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _stable_id(*parts: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, "|".join(parts)))

    @staticmethod
    def _projection_token(map_id: str, facts: list[Any], paths: list[Any]) -> str:
        payload = {
            "map_id": map_id,
            "facts": [
                {
                    "id": str(item.id),
                    "updated_at": str(item.updated_at or item.created_at),
                    "status": item.fact_status,
                    "value": item.value_json,
                    "anchor": item.spatial_anchor,
                }
                for item in facts
            ],
            "paths": [
                {
                    "id": str(item.id),
                    "updated_at": str(item.updated_at or item.created_at),
                    "status": item.status,
                    "content_revision": item.content_revision,
                }
                for item in paths
            ],
        }
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _location_id(value: dict[str, Any], anchor: dict[str, Any]) -> str | None:
        raw = value.get("location_entity_id") or anchor.get("location_entity_id")
        return str(raw) if raw else None

    @staticmethod
    def _has_anchor(value: dict[str, Any], anchor: dict[str, Any]) -> bool:
        return any(
            raw is not None
            for raw in (
                value.get("location_entity_id"),
                value.get("path_id"),
                anchor.get("location_entity_id"),
                anchor.get("path_id"),
                anchor.get("hex_q"),
                anchor.get("representative_q"),
            )
        )

    @staticmethod
    def _anchor_point(anchor: dict[str, Any]) -> tuple[float, float] | None:
        if anchor.get("hex_q") is not None and anchor.get("hex_r") is not None:
            return float(anchor["hex_q"]), float(anchor["hex_r"])
        if (
            anchor.get("representative_q") is not None
            and anchor.get("representative_r") is not None
        ):
            return float(anchor["representative_q"]), float(anchor["representative_r"])
        return None

    @staticmethod
    def _axial_distance(
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> float:
        dq = end[0] - start[0]
        dr = end[1] - start[1]
        return max(abs(dq), abs(dr), abs(dq + dr))

    @staticmethod
    def _path_category(path_type: str) -> str | None:
        if path_type in TRANSPORT_PATH_TYPES:
            return "transport"
        if path_type in WATER_PATH_TYPES:
            return "water"
        return None

    def _path_graph(
        self,
        paths: list[Any],
        nodes_by_path: dict[str, list[Any]],
        *,
        blocked: set[str],
    ) -> dict[str, list[tuple[str, str, float]]]:
        graph: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
        for path in paths:
            path_id = str(path.id)
            if path_id in blocked:
                continue
            start = str(path.start_location_entity_id)
            end = str(path.end_location_entity_id)
            weight = self._path_length(nodes_by_path.get(path_id, []))
            graph[start].append((end, path_id, weight))
            graph[end].append((start, path_id, weight))
        return graph

    @staticmethod
    def _path_length(nodes: list[Any]) -> float:
        if len(nodes) < 2:
            return 1.0
        total = 0.0
        for start, end in zip(nodes, nodes[1:]):
            dq = float(end.q) - float(start.q)
            dr = float(end.r) - float(start.r)
            total += max(abs(dq), abs(dr), abs(dq + dr))
        return max(total, 1.0)

    @staticmethod
    def _find_route(
        graph: dict[str, list[tuple[str, str, float]]],
        start: str,
        end: str,
    ) -> list[str] | None:
        if start == end:
            return []
        pending: deque[tuple[str, list[str]]] = deque([(start, [])])
        visited = {start}
        while pending:
            node, route = pending.popleft()
            for neighbor, path_id, _weight in graph.get(node, []):
                if neighbor in visited:
                    continue
                next_route = [*route, path_id]
                if neighbor == end:
                    return next_route
                visited.add(neighbor)
                pending.append((neighbor, next_route))
        return None

    @staticmethod
    def _route_states_at(
        route_deltas: list[MapDynamicDeltaRead],
        scene_index: int,
    ) -> dict[str, str]:
        result: dict[str, str] = {}
        for delta in route_deltas:
            if delta.scene_index > scene_index:
                break
            payload = MapTimelineService._dynamic_payload(delta.after)
            path_id = payload["path_id"]
            result[str(path_id)] = str(payload["state"])
        return result

    @staticmethod
    def _active_route_conflict_ids(
        conflicts: list[MapDynamicConflict],
        route_deltas: list[MapDynamicDeltaRead],
        scene_index: int,
    ) -> set[str]:
        latest_delta_scene: dict[str, int] = {}
        for delta in route_deltas:
            if delta.scene_index > scene_index:
                break
            payload = MapTimelineService._dynamic_payload(delta.after)
            latest_delta_scene[str(payload["path_id"])] = delta.scene_index
        result: set[str] = set()
        for conflict in conflicts:
            if conflict.dynamic_type != "route_state":
                continue
            if conflict.scene_index > scene_index:
                continue
            path_id = conflict.dimension_key.removeprefix("route:")
            if latest_delta_scene.get(path_id, -1) <= conflict.scene_index:
                result.add(path_id)
        return result

    @staticmethod
    def _dynamic_payload(value: Any) -> dict[str, Any]:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        return dict(value or {})

    @staticmethod
    def _dedupe_issues(items: list[MapContinuityIssue]) -> list[MapContinuityIssue]:
        by_key = {item.issue_key: item for item in items}
        order = {"danger": 0, "warning": 1, "info": 2}
        return sorted(
            by_key.values(),
            key=lambda item: (
                item.to_scene_index,
                order[item.severity],
                item.issue_key,
            ),
        )
