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
        title = self._display_title(item)
        object_type = self._display_object_type(item)
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
            object_type=object_type,
            type_label=self._object_type_label(object_type or item.dynamic_type),
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
        title = self._display_title(item)
        object_type = self._display_object_type(item)
        return MapDashboardQueueItem(
            item_id=str(item.id),
            item_kind="fact",
            title=title,
            target_entity_id=(
                str(item.target_entity_id) if item.target_entity_id else None
            ),
            object_type=object_type,
            type_label=self._object_type_label(object_type or item.dynamic_type),
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

    def _filter_queue_for_item(
        self,
        queue: list[MapDashboardQueueItem],
        focus_item_id: str,
    ) -> list[MapDashboardQueueItem]:
        focus = next((item for item in queue if item.item_id == focus_item_id), None)
        if focus is None:
            return queue
        object_key = self._dynamic_object_key(focus)
        return [item for item in queue if self._dynamic_object_key(item) == object_key]

    @staticmethod
    def _dynamic_object_key(item: MapDashboardQueueItem) -> str:
        if item.target_entity_id:
            return f"entity:{item.target_entity_id}"
        return "|".join([item.title, item.object_type or item.dynamic_type or "unknown"])

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
            title=self._display_title(item),
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
        field_label = self._change_field_label(field)
        if not self._is_blank_change_value(old_value) and not self._is_blank_change_value(
            new_value
        ):
            return (
                f"{field_label}：{self._format_change_value(old_value)} → "
                f"{self._format_change_value(new_value)}"
            )
        if not self._is_blank_change_value(new_value):
            return f"{field_label}：{self._format_change_value(new_value)}"
        if item.evidence_text:
            return item.evidence_text
        return "状态变化待确认"

    @staticmethod
    def _is_blank_change_value(value: Any) -> bool:
        return value is None or value == ""

    def _format_change_value(self, value: Any) -> str:
        if isinstance(value, dict | list):
            return self._format_structured_change_value(value)
        return str(value)

    def _format_structured_change_value(self, value: Any) -> str:
        if isinstance(value, list):
            items = [
                self._format_structured_change_value(item)
                for item in value[:3]
                if not self._is_blank_change_value(item)
            ]
            suffix = f"等 {len(value)} 项" if len(value) > 3 else ""
            return "；".join([*items, suffix]) if suffix else "；".join(items)
        if not isinstance(value, dict):
            return str(value)
        name = self._first_text(
            value,
            "name",
            "title",
            "target_name",
            "entity_name",
            "object_name",
            "source_name",
        )
        value_type = self._first_text(
            value,
            "entity_type",
            "target_entity_type",
            "object_type",
            "type",
            "relation_type",
        )
        summary = self._first_text(
            value,
            "summary",
            "description",
            "public_info",
            "evidence_text",
        )
        if name:
            label = name
            if value_type:
                label = f"{label}（{value_type}）"
            return f"{label}：{summary}" if summary else label
        if value_type:
            return f"{value_type}：{summary}" if summary else value_type
        scalar_pairs = [
            f"{key}：{raw}"
            for key, raw in value.items()
            if raw is not None and not isinstance(raw, dict | list)
        ][:3]
        return "；".join(scalar_pairs) if scalar_pairs else "结构化候选"

    def _display_title(self, item: Any) -> str:
        value = item.value_json or {}
        structured_title = None
        for key in ("new", "old"):
            structured_title = self._structured_value_name(value.get(key))
            if structured_title:
                break
        field_title = None
        if structured_title is None and self._uses_delta_value_as_title(item):
            field_title = self._field_value_title(value.get("field"))
        scalar_title = None
        if structured_title is None and self._uses_delta_value_as_title(item):
            for key in ("new", "old"):
                scalar_title = self._scalar_value_title(value.get(key))
                if scalar_title:
                    break
        if item.target_name:
            target_name = str(item.target_name).strip()
            if target_name and not self._is_generic_dynamic_name(
                target_name,
                item.dynamic_type,
            ):
                return target_name
        if structured_title:
            return structured_title
        if field_title:
            return field_title
        if scalar_title:
            return scalar_title
        return item.target_entity_type or self._object_type_label(item.dynamic_type)

    def _structured_value_name(self, value: Any) -> str | None:
        if isinstance(value, dict):
            return self._first_text(
                value,
                "name",
                "title",
                "target_name",
                "entity_name",
                "object_name",
                "source_name",
            )
        if isinstance(value, list):
            for item in value:
                name = self._structured_value_name(item)
                if name:
                    return name
        return None

    def _scalar_value_title(self, value: Any) -> str | None:
        if isinstance(value, str):
            text = value.strip()
            return text or None
        if isinstance(value, list):
            for item in value:
                text = self._scalar_value_title(item)
                if text:
                    return text
        return None

    def _field_value_title(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        text = value.strip()
        if not text:
            return None
        normalized = self._normalize_dynamic_type(text)
        if (
            text.startswith(("entities", "relations", "aliases"))
            or normalized
            in {
                "name",
                "title",
                "summary",
                "description",
                "entity_created",
                "entity_updated",
                "relation_created",
                "relation_updated",
                "alias_created",
                "alias_updated",
                "entity",
                "status",
            }
            or "_" in normalized
        ):
            return None
        return text

    def _display_object_type(self, item: Any) -> str | None:
        if item.target_entity_type:
            return str(item.target_entity_type)
        value = item.value_json or {}
        for key in ("new", "old"):
            value_type = self._structured_value_type(value.get(key))
            if value_type:
                return value_type
        return self._delta_candidate_object_type(item)

    def _structured_value_type(self, value: Any) -> str | None:
        if isinstance(value, dict):
            return self._first_text(
                value,
                "entity_type",
                "target_entity_type",
                "object_type",
                "type",
            )
        if isinstance(value, list):
            for item in value:
                value_type = self._structured_value_type(item)
                if value_type:
                    return value_type
        return None

    def _is_generic_dynamic_name(self, target_name: str, dynamic_type: str) -> bool:
        normalized_target = self._normalize_dynamic_type(target_name)
        normalized_dynamic = self._normalize_dynamic_type(dynamic_type)
        return normalized_target in {
            normalized_dynamic,
            "entity_created",
            "entity_updated",
            "relation_created",
            "relation_updated",
            "alias_created",
            "alias_updated",
            "delta_event",
            "change",
        }

    def _uses_delta_value_as_title(self, item: Any) -> bool:
        dynamic_type = self._normalize_dynamic_type(item.dynamic_type)
        value = item.value_json or {}
        field = str(value.get("field") or "").strip()
        category = self._normalize_dynamic_type(value.get("category"))
        candidate_types = {
            "entity_created",
            "entity_updated",
            "relation_created",
            "relation_updated",
            "alias_created",
            "alias_updated",
        }
        return (
            dynamic_type in candidate_types
            or category in candidate_types
            or field.startswith(("entities", "relations", "aliases"))
        )

    def _delta_candidate_object_type(self, item: Any) -> str | None:
        dynamic_type = self._normalize_dynamic_type(item.dynamic_type)
        value = item.value_json or {}
        field = str(value.get("field") or "").strip()
        category = self._normalize_dynamic_type(value.get("category"))
        if (
            dynamic_type in {"entity_created", "entity_updated"}
            or category in {"entity_created", "entity_updated"}
            or field.startswith("entities")
        ):
            return "entity_candidate"
        if (
            dynamic_type in {"relation_created", "relation_updated"}
            or category in {"relation_created", "relation_updated"}
            or field.startswith("relations")
        ):
            return "relation_candidate"
        if (
            dynamic_type in {"alias_created", "alias_updated"}
            or category in {"alias_created", "alias_updated"}
            or field.startswith("aliases")
        ):
            return "alias_candidate"
        return None

    @staticmethod
    def _first_text(value: dict[str, Any], *keys: str) -> str | None:
        for key in keys:
            raw = value.get(key)
            if raw is None:
                continue
            text = str(raw).strip()
            if text:
                return text
        return None

    @staticmethod
    def _change_field_label(field: Any) -> str:
        text = str(field or "").strip()
        if text.startswith("entities[") or text in {"entities", "entity"}:
            return "对象候选"
        if text.startswith("relations[") or text in {"relations", "relation"}:
            return "关系候选"
        if text.startswith("aliases[") or text in {"aliases", "alias"}:
            return "别名候选"
        if text.startswith("deltas[") or text in {"delta", "delta_event"}:
            return "世界动态"
        return text or "状态变化"

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
        return f"{source} · {self._change_summary(item)}"

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
            "concept": "概念",
            "faction": "势力",
            "person": "人物",
            "entity_candidate": "对象候选",
            "relation_candidate": "关系候选",
            "alias_candidate": "别名候选",
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
