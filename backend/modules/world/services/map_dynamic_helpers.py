from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.map_schemas import (
    MapDashboardBatchGroup,
    MapDashboardInspector,
    MapDashboardQueueItem,
    MapObservationCreate,
    MapPlaybackEvent,
    MapPlaybackTrack,
)
from modules.world.services.helpers import parse_uuid

logger = logging.getLogger(__name__)


class MapDynamicHelperMixin:
    """Private dynamic-map helper methods kept as a compatibility mixin."""

    def _queue_item_from_observation(self, item: Any) -> MapDashboardQueueItem:
        title = item.target_name or item.target_entity_type or item.dynamic_type
        status_label = self._status_label(item.review_state)
        risk_level = self._risk_level(
            dynamic_type=item.dynamic_type,
            status=item.review_state,
            confidence=item.confidence,
        )
        return MapDashboardQueueItem(
            item_id=str(item.id),
            item_kind="observation",
            title=title,
            target_entity_id=(
                str(item.target_entity_id) if item.target_entity_id else None
            ),
            object_type=item.target_entity_type,
            type_label=self._object_type_label(
                item.target_entity_type or item.dynamic_type
            ),
            dynamic_type=item.dynamic_type,
            time_label=self._time_label(item),
            status_label=status_label,
            source_summary=self._source_summary(item),
            location_label=self._location_label(item),
            spatial_anchor_label=self._spatial_anchor_label(item),
            debug_ref={
                "kind": "observation",
                "id": str(item.id),
                "scene_id": str(item.scene_id) if item.scene_id else None,
            },
            priority=self._priority_score(
                dynamic_type=item.dynamic_type,
                status=item.review_state,
                confidence=item.confidence,
                scene_index=item.scene_index,
            ),
            risk_level=risk_level,
            confidence=item.confidence,
            review_state=item.review_state,
        )

    def _queue_item_from_fact(self, item: Any) -> MapDashboardQueueItem:
        title = item.target_name or item.target_entity_type or item.dynamic_type
        return MapDashboardQueueItem(
            item_id=str(item.id),
            item_kind="fact",
            title=title,
            target_entity_id=(
                str(item.target_entity_id) if item.target_entity_id else None
            ),
            object_type=item.target_entity_type,
            type_label=self._object_type_label(
                item.target_entity_type or item.dynamic_type
            ),
            dynamic_type=item.dynamic_type,
            time_label=self._time_label(item),
            status_label=self._status_label(item.fact_status),
            source_summary=self._source_summary(item),
            location_label=self._location_label(item),
            spatial_anchor_label=self._spatial_anchor_label(item),
            debug_ref={
                "kind": "fact",
                "id": str(item.id),
                "scene_id": str(item.scene_id) if item.scene_id else None,
            },
            priority=self._priority_score(
                dynamic_type=item.dynamic_type,
                status=item.fact_status,
                confidence=item.confidence,
                scene_index=item.scene_index,
            ),
            risk_level=self._risk_level(
                dynamic_type=item.dynamic_type,
                status=item.fact_status,
                confidence=item.confidence,
            ),
            confidence=item.confidence,
            fact_status=item.fact_status,
        )

    def _build_dashboard_inspector(
        self,
        queue: list[MapDashboardQueueItem],
        *,
        focus_entity_id: str | None,
    ) -> MapDashboardInspector:
        primary = queue[0] if queue else None
        candidates = [
            item
            for item in queue
            if item.item_kind == "observation" and item.review_state == "candidate"
        ]
        facts = [item for item in queue if item.item_kind == "fact"]
        conflicts = [
            item
            for item in queue
            if item.risk_level == "danger" or item.review_state == "conflicted"
        ]
        evidence = []
        for item in queue:
            if item.source_summary and item.source_summary not in evidence:
                evidence.append(item.source_summary)
            if len(evidence) >= 5:
                break
        available_actions = []
        if candidates:
            available_actions.extend(["confirm", "ignore", "conflict"])
        if facts:
            available_actions.extend(["rollback", "deprecated"])
        return MapDashboardInspector(
            title=primary.title if primary else "暂无世界动态",
            status_label=primary.status_label if primary else "等待地图事实",
            summary=(
                "右侧检查器汇总候选映射、正式事实、冲突风险和来源证据。"
                if queue
                else "暂无可检查的地图事实。"
            ),
            focus_entity_id=focus_entity_id,
            object_type=primary.object_type if primary else None,
            type_label=primary.type_label if primary else None,
            object_name=primary.title if primary else None,
            location_label=primary.location_label if primary else None,
            spatial_anchor_label=primary.spatial_anchor_label if primary else None,
            debug_ref=primary.debug_ref if primary else {},
            timeline=sorted(queue, key=lambda item: (item.time_label, item.title))[:12],
            available_actions=available_actions,
            map_facts=facts[:5],
            ai_candidates=candidates[:5],
            conflicts=conflicts[:5],
            source_evidence=evidence,
            related_dynamics=queue[:8],
        )

    def _build_first_visual_layer(
        self,
        queue: list[MapDashboardQueueItem],
        *,
        scene_id: str | None,
        risk_summary: list[str],
    ) -> dict[str, Any]:
        crisis = next((item for item in queue if item.dynamic_type == "crisis"), None)
        characters = [
            item.title
            for item in queue
            if item.object_type == "character"
        ][:5]
        scene_events = [
            item.title
            for item in queue
            if scene_id and item.time_label.startswith("Scene")
        ][:5]
        return {
            "current_storyline": self._storyline_label(queue, scene_id=scene_id),
            "main_crisis": crisis.title if crisis else "暂无主线危机",
            "main_characters": characters,
            "current_scene_events": scene_events,
            "top_risks": risk_summary[:3],
        }

    def _build_batch_groups(
        self,
        queue: list[MapDashboardQueueItem],
    ) -> list[MapDashboardBatchGroup]:
        groups: dict[str, dict[str, Any]] = {}
        for item in queue:
            key = item.object_type or item.dynamic_type or "unknown"
            group = groups.setdefault(
                key,
                {
                    "count": 0,
                    "candidate_count": 0,
                    "confirmed_count": 0,
                    "first_joined_label": item.time_label,
                },
            )
            group["count"] += 1
            if item.item_kind == "observation" and item.review_state == "candidate":
                group["candidate_count"] += 1
            if item.item_kind == "fact":
                group["confirmed_count"] += 1
        result = []
        for key, group in groups.items():
            result.append(
                MapDashboardBatchGroup(
                    group_key=key,
                    group_label=self._object_type_label(key),
                    count=group["count"],
                    candidate_count=group["candidate_count"],
                    confirmed_count=group["confirmed_count"],
                    first_joined_label=group["first_joined_label"],
                )
            )
        return sorted(result, key=lambda item: (-item.count, item.group_label))[:12]

    def _build_risk_summary(self, queue: list[MapDashboardQueueItem]) -> list[str]:
        risks = []
        for item in queue:
            if item.risk_level in {"warning", "danger"}:
                risks.append(f"{item.title}：{item.status_label}")
            if len(risks) >= 5:
                break
        return risks

    def _filter_queue_for_focus(
        self,
        queue: list[MapDashboardQueueItem],
        focus_entity_id: str,
    ) -> list[MapDashboardQueueItem]:
        return [
            item
            for item in queue
            if item.target_entity_id == focus_entity_id
        ]

    def _filter_queue_for_scene(
        self,
        queue: list[MapDashboardQueueItem],
        scene_id: str,
    ) -> list[MapDashboardQueueItem]:
        return [
            item
            for item in queue
            if item.debug_ref.get("scene_id") == scene_id
        ]

    def _storyline_label(
        self,
        queue: list[MapDashboardQueueItem],
        *,
        scene_id: str | None,
    ) -> str:
        if scene_id:
            for item in queue:
                if item.time_label.startswith("Scene "):
                    return item.time_label
            return "当前 Scene 相关动态"
        if queue:
            return f"围绕 {queue[0].time_label} 的地图动态"
        return "暂无当前剧情线"

    def _playback_event_from_item(
        self,
        kind: str,
        item: Any,
    ) -> MapPlaybackEvent | None:
        status = getattr(item, "review_state", None) or getattr(item, "fact_status", None)
        if status == "ignored":
            return None
        dynamic_type = self._normalize_dynamic_type(item.dynamic_type)
        return MapPlaybackEvent(
            event_id=str(item.id),
            event_kind="observation" if kind == "observation" else "fact",
            typed_observation=dynamic_type,
            track=self._playback_track(dynamic_type),
            title=item.target_name or item.target_entity_type or dynamic_type,
            time_label=self._time_label(item),
            status_label=self._status_label(status),
            change_summary=self._change_summary(item),
            source_summary=self._source_summary(item),
            spatial_anchor=item.spatial_anchor or {},
            scene_index=item.scene_index,
            source_chapter_index=item.source_chapter_index,
            risk_level=self._risk_level(
                dynamic_type=dynamic_type,
                status=status,
                confidence=item.confidence,
            ),
            confidence=item.confidence,
        )

    def _build_playback_tracks(
        self,
        events: list[MapPlaybackEvent],
    ) -> list[MapPlaybackTrack]:
        groups: dict[str, MapPlaybackTrack] = {}
        for event in events:
            if event.track not in groups:
                groups[event.track] = MapPlaybackTrack(
                    track=event.track,
                    label=self._playback_track_label(event.track),
                    count=0,
                    first_time_label=event.time_label,
                )
            groups[event.track].count += 1
        order = ["journey", "territory", "crisis", "resource", "status", "world"]
        return sorted(groups.values(), key=lambda track: order.index(track.track))

    def _change_summary(self, item: Any) -> str:
        value = item.value_json or {}
        old_value = value.get("old")
        new_value = value.get("new")
        field = value.get("field") or value.get("category") or item.dynamic_type
        if old_value not in {None, ""} and new_value not in {None, ""}:
            return f"{field}：{old_value} → {new_value}"
        if new_value not in {None, ""}:
            return f"{field}：{new_value}"
        if item.evidence_text:
            return item.evidence_text
        return "状态变化待确认"

    def _playback_track(self, dynamic_type: str) -> str:
        if dynamic_type in {"location", "position_change", "movement"}:
            return "journey"
        if dynamic_type in {"boundary", "boundary_change", "territory"}:
            return "territory"
        if dynamic_type in {"crisis", "crisis_spread", "risk", "conflict"}:
            return "crisis"
        if dynamic_type in {"resource", "resource_control", "resource_control_change"}:
            return "resource"
        if dynamic_type in {"status", "status_change"}:
            return "status"
        return "world"

    def _playback_track_label(self, track: str) -> str:
        return {
            "journey": "人物旅程",
            "territory": "势力变化",
            "crisis": "危机推进",
            "resource": "资源控制",
            "status": "状态变化",
            "world": "世界状态",
        }.get(track, track)

    def _priority_score(
        self,
        *,
        dynamic_type: str,
        status: str,
        confidence: float | None,
        scene_index: int | None,
    ) -> int:
        score = 10
        if status == "conflicted":
            score += 100
        if status == "candidate":
            score += 70
        if dynamic_type in {"crisis", "risk", "conflict"}:
            score += 60
        if dynamic_type in {"location", "status", "boundary"}:
            score += 30
        if scene_index is not None:
            score += min(scene_index, 30)
        if confidence is not None and confidence < 0.45:
            score += 20
        return score

    def _risk_level(
        self,
        *,
        dynamic_type: str,
        status: str,
        confidence: float | None,
    ) -> str:
        if status == "conflicted" or dynamic_type in {"crisis", "risk", "conflict"}:
            return "danger"
        if status == "candidate" or (confidence is not None and confidence < 0.5):
            return "warning"
        return "info"

    def _time_label(self, item: Any) -> str:
        time_anchor = item.time_anchor or {}
        scene_index = getattr(item, "scene_index", None) or time_anchor.get("scene_index")
        if scene_index is not None:
            return f"Scene {scene_index}"
        chapter_index = getattr(item, "source_chapter_index", None) or time_anchor.get(
            "chapter_index"
        )
        if chapter_index is not None:
            return f"第 {chapter_index} 章"
        return "时间待确认"

    def _status_label(self, status: str | None) -> str:
        return {
            "candidate": "待确认",
            "confirmed": "已确认",
            "ignored": "已忽略",
            "conflicted": "有冲突",
            "rolled_back": "已回滚",
            "deprecated": "已废弃",
        }.get(status or "", "待判断")

    def _source_summary(self, item: Any) -> str:
        source_ref = item.source_ref or {}
        source = source_ref.get("source") or source_ref.get("operation") or "来源待确认"
        evidence = item.evidence_text or ""
        if evidence:
            return f"{source} · {evidence}"
        return str(source)

    def _location_label(self, item: Any) -> str | None:
        anchor = item.spatial_anchor or {}
        name = anchor.get("location_name") or anchor.get("map_name")
        return str(name) if name else None

    def _spatial_anchor_label(self, item: Any) -> str | None:
        anchor = item.spatial_anchor or {}
        q = anchor.get("hex_q")
        r = anchor.get("hex_r")
        if q is not None and r is not None:
            return f"坐标 {q},{r}"
        name = anchor.get("location_name") or anchor.get("map_name")
        return str(name) if name else None

    def _object_type_label(self, key: str) -> str:
        return {
            "character": "人物",
            "location": "地点",
            "organization": "组织",
            "event": "事件",
            "item": "物品",
            "resource": "资源",
            "crisis": "危机",
            "status": "状态",
            "boundary": "边界",
            "semantic": "语义",
        }.get(key, key)

    def _observation_values(
        self,
        data: MapObservationCreate,
        *,
        map_id: uuid.UUID | None,
    ) -> dict[str, Any]:
        return {
            "map_id": map_id,
            "target_entity_id": (
                parse_uuid(data.target_entity_id, "target_entity_id")
                if data.target_entity_id
                else None
            ),
            "target_entity_type": data.target_entity_type,
            "target_name": data.target_name,
            "dynamic_type": self._normalize_dynamic_type(data.dynamic_type),
            "time_anchor": data.time_anchor or {},
            "spatial_anchor": data.spatial_anchor or {},
            "value_json": data.value_json or {},
            "confidence": data.confidence,
            "review_state": data.review_state,
            "source_ref": data.source_ref or {},
            "evidence_text": data.evidence_text,
            "scene_id": parse_uuid(data.scene_id, "scene_id") if data.scene_id else None,
            "scene_index": data.scene_index,
            "source_chapter_index": data.source_chapter_index,
        }

    def _assert_observation_in_novel(
        self,
        observation: Any,
        observation_id: str,
        novel_id: uuid.UUID,
    ) -> None:
        if observation is None or observation.novel_id != novel_id:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"MapObservation {observation_id} not found",
            )

    def _assert_observation_in_map(
        self,
        observation: Any,
        observation_id: str,
        map_id: uuid.UUID,
    ) -> None:
        if observation.map_id is not None and observation.map_id != map_id:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"MapObservation {observation_id} not found",
            )

    def _assert_fact_access(
        self,
        fact: Any,
        fact_id: str,
        novel_id: uuid.UUID,
        map_id: uuid.UUID,
    ) -> None:
        if fact is None or fact.novel_id != novel_id or fact.map_id != map_id:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"MapFact {fact_id} not found",
            )

    def _assert_spatial_anchor_in_bounds(self, config: Any, spatial_anchor: dict) -> None:
        if "hex_q" not in spatial_anchor or "hex_r" not in spatial_anchor:
            return
        self._ctx.assert_hex_in_bounds(
            config,
            int(spatial_anchor["hex_q"]),
            int(spatial_anchor["hex_r"]),
        )

    async def _safe_map_uuid(
        self,
        db: AsyncSession,
        novel_id: str,
        raw_map_id: Any,
    ) -> uuid.UUID | None:
        if not raw_map_id:
            return None
        try:
            config = await self._ctx.require_map(db, novel_id, str(raw_map_id))
            return config.id
        except (HTTPException, TypeError, ValueError):
            logger.warning("Ignoring invalid map_id in map observation: %r", raw_map_id)
            return None

    async def _safe_entity_uuid(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        raw_entity_id: Any,
    ) -> uuid.UUID | None:
        entity_id = self._safe_uuid(raw_entity_id)
        if entity_id is None:
            return None
        entity = await self._entity_repo.get(db, entity_id)
        if entity is None or entity.novel_id != novel_id:
            logger.warning(
                "Ignoring invalid target_entity_id in map observation: %r",
                raw_entity_id,
            )
            return None
        return entity_id

    @staticmethod
    def _safe_uuid(raw_value: Any) -> uuid.UUID | None:
        if not raw_value:
            return None
        try:
            return uuid.UUID(str(raw_value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _clamp_confidence(raw_value: Any) -> float:
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            return 0.5
        return min(max(value, 0.0), 1.0)

    @staticmethod
    def _normalize_dynamic_type(raw_value: Any) -> str:
        value = str(raw_value or "delta_event").strip().lower()
        return value[:64] or "delta_event"
