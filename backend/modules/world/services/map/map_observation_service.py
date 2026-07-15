from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from math import sqrt
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, DomainError, NotFoundError, ValidationError
from modules.outline.facade import get_scene_contract
from modules.world.contracts import (
    MapObservationCandidateBatchResult,
    MapObservationCandidateInput,
    MapObservationCandidateResult,
)
from modules.world.map_models import MapObservation
from modules.world.map_repositories import MapPathNodeRepository, MapPathRepository
from modules.world.map_schemas import (
    MapFactResponse,
    MapObservationAssignmentRequest,
    MapObservationAuthorUpdate,
    MapObservationBatchReviewRequest,
    MapObservationBatchReviewResponse,
    MapObservationCreate,
    MapObservationEligibility,
    MapObservationListResponse,
    MapObservationResponse,
    MapObservationReviewUpdate,
    MapObservationRevisionRequest,
    MapSpatialAnchor,
    validate_map_observation_payload,
)
from modules.world.services.common import parse_uuid
from modules.world.services.map.map_dynamic_lifecycle import MapDynamicLifecycle
from modules.world.services.map.map_dynamic_projection import (
    canonical_dynamic_type,
    equivalent_dynamic_types,
    normalize_dynamic_value,
    validate_versioned_dynamic_value,
)


class MapObservationService:
    """Delegated dynamic-map service."""

    def __init__(self, owner: MapDynamicLifecycle) -> None:
        self.owner = owner
        self._path_repo = MapPathRepository()
        self._path_node_repo = MapPathNodeRepository()

    _MISSING_LABELS = {
        "map": "未选择地图",
        "canonical_value": "动态字段尚未解析完整",
        "target_entity": "未选择目标对象",
        "target_entity_type": "目标对象类型不正确",
        "target_entity_canonical": "目标对象尚未采用",
        "location": "未匹配地点或空间位置",
        "location_canonical": "地点尚未采用",
        "path": "未匹配地图线路",
        "controller": "未选择控制势力",
        "controller_canonical": "控制势力尚未采用",
        "boundary_hexes": "需要绘制明确势力范围",
        "scene": "缺少来源 Scene",
        "chapter": "缺少来源章节",
    }

    @staticmethod
    def _same_revision(actual: datetime | None, expected: datetime) -> bool:
        if actual is None:
            return False
        if actual.tzinfo is None:
            actual = actual.replace(tzinfo=UTC)
        if expected.tzinfo is None:
            expected = expected.replace(tzinfo=UTC)
        return actual.astimezone(UTC) == expected.astimezone(UTC)

    @staticmethod
    def _is_initial_state(observation: MapObservation) -> bool:
        source_ref = observation.source_ref or {}
        source = str(source_ref.get("source") or "").lower()
        if "deep_import" in source or source_ref.get("auto_ingested") is True:
            return False
        return (observation.time_anchor or {}).get("kind") == "initial_state"

    @staticmethod
    def _proposal_type(observation: MapObservation) -> str | None:
        value = observation.value_json or {}
        if value.get("payload_kind") == "proposal":
            return value.get("proposal_type")
        source_ref = observation.source_ref or {}
        value = source_ref.get("proposal_type")
        return value if isinstance(value, str) else None

    async def _eligibility(
        self,
        db: AsyncSession,
        novel_id: str,
        observation: MapObservation,
    ) -> MapObservationEligibility:
        missing: list[str] = []
        conflict_reason: str | None = None
        config = None
        if observation.map_id is None:
            missing.append("map")
        else:
            try:
                config = await self.owner._ctx.require_map(
                    db,
                    novel_id,
                    str(observation.map_id),
                )
            except DomainError as exc:
                conflict_reason = exc.code

        normalized = normalize_dynamic_value(
            observation.dynamic_type,
            observation.value_json,
            observation.spatial_anchor,
        )
        if normalized.state != "typed" or normalized.value is None:
            missing.append("canonical_value")
        else:
            value = normalized.value
            target = None
            if observation.target_entity_id is None:
                if value["type"] in {"location", "boundary"}:
                    missing.append("target_entity")
            else:
                try:
                    target = await self.owner._ctx.require_entity(
                        db,
                        novel_id,
                        str(observation.target_entity_id),
                    )
                except DomainError as exc:
                    conflict_reason = conflict_reason or exc.code
                if target is not None and target.status != "canonical":
                    missing.append("target_entity_canonical")

            if value["type"] == "location":
                proposal_type = self._proposal_type(observation)
                expected_types = {
                    "character_location": {"character"},
                    "event_location": {"event"},
                }.get(proposal_type, {"character", "event"})
                if target is not None and target.entity_type not in expected_types:
                    missing.append("target_entity_type")
                anchor = observation.spatial_anchor or {}
                location_id = value.get("location_entity_id") or anchor.get(
                    "location_entity_id"
                )
                has_hex = (
                    anchor.get("hex_q") is not None and anchor.get("hex_r") is not None
                )
                if location_id:
                    try:
                        location = await self.owner._ctx.require_entity(
                            db,
                            novel_id,
                            str(location_id),
                            allowed_types={"location"},
                        )
                        if location.status != "canonical":
                            missing.append("location_canonical")
                    except DomainError as exc:
                        conflict_reason = conflict_reason or exc.code
                path_is_sufficient = proposal_type != "event_location" and value.get(
                    "path_id"
                )
                if not location_id and not path_is_sufficient and not has_hex:
                    missing.append("location")

            if value["type"] == "route_state" and not value.get("path_id"):
                missing.append("path")

            if value["type"] == "boundary":
                controller = None
                try:
                    controller = await self.owner._ctx.require_entity(
                        db,
                        novel_id,
                        value["controller_entity_id"],
                        allowed_types={"organization", "faction"},
                    )
                except DomainError as exc:
                    conflict_reason = conflict_reason or exc.code
                    missing.append("controller")
                if controller is not None and controller.status != "canonical":
                    missing.append("controller_canonical")
                if not value.get("hexes"):
                    missing.append("boundary_hexes")

            if config is not None:
                try:
                    await self._validated_dynamic_value(
                        db,
                        novel_id,
                        config,
                        observation.dynamic_type,
                        observation.value_json,
                        observation.spatial_anchor,
                    )
                    await self._validated_anchor(
                        db,
                        novel_id,
                        config,
                        observation.spatial_anchor,
                    )
                except DomainError as exc:
                    conflict_reason = conflict_reason or exc.code

        if not self._is_initial_state(observation):
            if observation.scene_id is None:
                missing.append("scene")
            if observation.source_chapter_index is None:
                missing.append("chapter")

        unique_missing = list(dict.fromkeys(missing))
        return MapObservationEligibility(
            can_confirm=(
                observation.review_state in {"candidate", "conflicted"}
                and not unique_missing
                and conflict_reason is None
            ),
            missing_items=unique_missing,
            missing_item_labels=[self._MISSING_LABELS[item] for item in unique_missing],
            conflict_reason=conflict_reason,
        )

    async def _response(
        self,
        db: AsyncSession,
        novel_id: str,
        observation: MapObservation,
    ) -> MapObservationResponse:
        response = MapObservationResponse.model_validate(observation)
        response.eligibility = await self._eligibility(db, novel_id, observation)
        return response

    async def _raise_revision_conflict(
        self,
        db: AsyncSession,
        novel_id: str,
        observation_id: uuid.UUID,
    ) -> None:
        latest = await self.owner._observation_repo.get(db, observation_id)
        context: dict[str, Any] = {}
        if latest is not None and latest.novel_id == parse_uuid(novel_id, "novel_id"):
            context["latest"] = (await self._response(db, novel_id, latest)).model_dump(
                mode="json"
            )
        raise ConflictError(
            "地图待处理项已被其他操作更新，请核对最新内容后重试",
            code="map_observation_revision_conflict",
            context=context,
        )

    async def _validated_dynamic_value(
        self,
        db: AsyncSession,
        novel_id: str,
        config: Any,
        dynamic_type: str,
        value_json: dict[str, Any] | None,
        spatial_anchor: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Validate typed references without rewriting legacy JSON."""
        value = dict(value_json or {})
        try:
            validate_versioned_dynamic_value(dynamic_type, value)
        except ValueError as exc:
            raise ValidationError(
                "地图动态值不符合 schema_version=1 契约",
                code="invalid_map_dynamic_value",
                status_code=422,
                context={"reason": str(exc)},
            ) from exc

        anchor = dict(spatial_anchor or {})
        normalized = normalize_dynamic_value(dynamic_type, value, anchor)
        payload = normalized.value
        if payload is None:
            canonical_type = canonical_dynamic_type(dynamic_type)
            if canonical_type == "location" and value.get("location_entity_id"):
                location = await self.owner._ctx.require_entity(
                    db,
                    novel_id,
                    str(value["location_entity_id"]),
                )
                if location.entity_type != "location":
                    raise ValidationError(
                        "location 动态只能引用地点实体",
                        code="invalid_map_dynamic_location",
                        status_code=422,
                    )
            raw_entity_ids = []
            if canonical_type in {"boundary", "resource"} and value.get(
                "controller_entity_id"
            ):
                raw_entity_ids.append(str(value["controller_entity_id"]))
            if canonical_type == "semantic" and isinstance(
                value.get("related_entity_ids"), list
            ):
                raw_entity_ids.extend(str(item) for item in value["related_entity_ids"])
            if raw_entity_ids:
                await self.owner._ctx.require_entities(
                    db,
                    novel_id,
                    raw_entity_ids,
                )
            raw_path_id = value.get("path_id")
            if canonical_type in {"location", "route_state"} and raw_path_id:
                path = await self._path_repo.get_in_map(
                    db,
                    config.novel_id,
                    config.id,
                    parse_uuid(str(raw_path_id), "path_id"),
                )
                if path is None:
                    raise NotFoundError(
                        "地图线路不存在",
                        code="map_path_not_found",
                    )
                if path.status != "active":
                    raise ConflictError(
                        "已归档线路不能用于新的地图动态",
                        code="map_path_archived",
                    )
            return value

        if payload["type"] == "location":
            for key in ("location_entity_id", "path_id"):
                if payload.get(key) and anchor.get(key) and payload[key] != anchor[key]:
                    raise ValidationError(
                        f"{key} 与空间锚点不一致",
                        code="map_dynamic_anchor_conflict",
                        status_code=422,
                    )

        entity_ids: list[str] = []
        value_type = payload["type"]
        if value_type == "location" and payload.get("location_entity_id"):
            location = await self.owner._ctx.require_entity(
                db,
                novel_id,
                payload["location_entity_id"],
            )
            if location.entity_type != "location":
                raise ValidationError(
                    "location 动态只能引用地点实体",
                    code="invalid_map_dynamic_location",
                    status_code=422,
                )
        for key in ("controller_entity_id",):
            if payload.get(key):
                entity_ids.append(payload[key])
        entity_ids.extend(payload.get("related_entity_ids") or [])
        if entity_ids:
            await self.owner._ctx.require_entities(db, novel_id, entity_ids)

        path_id = payload.get("path_id")
        if path_id:
            path = await self._path_repo.get_in_map(
                db,
                config.novel_id,
                config.id,
                parse_uuid(path_id, "path_id"),
            )
            if path is None:
                raise NotFoundError("地图线路不存在", code="map_path_not_found")
            if path.status != "active":
                raise ConflictError(
                    "已归档线路不能用于新的地图动态",
                    code="map_path_archived",
                )

        for item in payload.get("hexes") or []:
            if item["hex_q"] >= config.grid_width or item["hex_r"] >= config.grid_height:
                raise ConflictError(
                    "地图动态范围超出地图边界",
                    code="map_hex_out_of_bounds",
                )
        # Versioned payloads are owned by this contract, so persist the
        # validator's deterministic representation (UUID coercion plus sorted,
        # de-duplicated hex/entity sets).  Legacy payloads stay byte-shape
        # compatible and are normalized only in read projections.
        return payload if normalized.state == "typed" else value

    async def _validated_scene(
        self,
        db: AsyncSession,
        novel_id: str,
        scene_id: str | None,
        scene_index: int | None,
    ) -> uuid.UUID | None:
        if scene_id is None:
            return None
        scene = await get_scene_contract(db, novel_id, scene_id)
        if scene is None:
            raise NotFoundError("Scene 不存在", code="scene_not_found")
        if scene_index is not None and scene.scene_index != scene_index:
            raise ValidationError(
                "scene_index 与 scene_id 对应的 Scene 不一致",
                code="map_dynamic_scene_index_mismatch",
                status_code=422,
            )
        return parse_uuid(scene_id, "scene_id")

    async def _validated_anchor(
        self,
        db: AsyncSession,
        novel_id: str,
        config: Any,
        spatial_anchor: Any,
        *,
        require_active_path: bool = True,
    ) -> dict[str, Any]:
        payload = self.owner._spatial_anchor_payload(spatial_anchor)
        path_id = payload.get("path_id")
        if path_id:
            payload.setdefault("map_id", str(config.id))
        if payload.get("map_id") and payload["map_id"] != str(config.id):
            raise NotFoundError(
                "spatial anchor 不属于当前地图",
                code="map_path_not_found",
            )
        location_entity_id = payload.get("location_entity_id")
        if location_entity_id:
            location = await self.owner._ctx.require_entity(
                db,
                novel_id,
                location_entity_id,
            )
            if location.entity_type != "location":
                raise ValidationError(
                    "spatial anchor 只能引用地点实体",
                    code="invalid_map_spatial_anchor_location",
                )
        coordinate_pairs = (
            ("hex_q", "hex_r"),
            ("representative_q", "representative_r"),
        )
        for q_key, r_key in coordinate_pairs:
            if q_key not in payload:
                continue
            if (
                payload[q_key] >= config.grid_width
                or payload[r_key] >= config.grid_height
            ):
                raise ConflictError(
                    "spatial anchor 超出地图边界",
                    code="map_hex_out_of_bounds",
                )
        if path_id:
            path = await self._path_repo.get_in_map(
                db,
                config.novel_id,
                config.id,
                parse_uuid(path_id, "path_id"),
            )
            if path is None:
                raise NotFoundError("地图线路不存在", code="map_path_not_found")
            if require_active_path and path.status != "active":
                raise ConflictError(
                    "已归档线路不能用于新的待处理观察",
                    code="map_path_archived",
                )
        return self.owner._spatial_anchor_payload(
            MapSpatialAnchor.model_validate(payload)
        )

    async def _fact_anchor_snapshot(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: uuid.UUID,
        spatial_anchor: Any,
        *,
        dynamic_type: str,
        value_json: dict[str, Any] | None,
    ) -> dict[str, Any]:
        config = await self.owner._ctx.require_map(db, novel_id, str(map_id))
        payload = await self._validated_anchor(
            db,
            novel_id,
            config,
            spatial_anchor,
            require_active_path=True,
        )
        normalized = normalize_dynamic_value(
            dynamic_type,
            value_json,
            payload,
        )
        typed_value_path_id = None
        if (
            normalized.state == "typed"
            and normalized.value is not None
            and normalized.value["type"] == "location"
        ):
            typed_value_path_id = normalized.value.get("path_id")
        path_id = payload.get("path_id") or typed_value_path_id
        if not path_id:
            return payload
        payload["map_id"] = str(map_id)
        payload["path_id"] = str(path_id)
        nid = parse_uuid(novel_id, "novel_id")
        path = await self._path_repo.get_in_map(
            db,
            nid,
            map_id,
            parse_uuid(path_id, "path_id"),
        )
        if path is None:
            raise NotFoundError("地图线路不存在", code="map_path_not_found")
        if path.status != "active":
            raise ConflictError(
                "引用已归档线路的 Observation 不能确认",
                code="map_path_archived",
            )
        nodes = await self._path_node_repo.get_by_paths(db, nid, map_id, [path.id])
        representative = None
        if payload.get("hex_q") is not None:
            representative = (payload["hex_q"], payload["hex_r"])
        elif nodes:
            representative = self._path_midpoint(nodes)
        payload.update(
            {
                "map_id": str(map_id),
                "path_id": str(path.id),
                "path_revision": path.content_revision,
                "path_name": path.name,
            }
        )
        if representative is not None:
            payload["representative_q"], payload["representative_r"] = representative
        return self.owner._spatial_anchor_payload(
            MapSpatialAnchor.model_validate(payload)
        )

    @staticmethod
    def _path_midpoint(nodes: list[Any]) -> tuple[float, float]:
        if len(nodes) == 1:
            return nodes[0].q, nodes[0].r
        segments: list[tuple[Any, Any, float]] = []
        total = 0.0
        for start, end in zip(nodes, nodes[1:]):
            dq = end.q - start.q
            dr = end.r - start.r
            length = sqrt(max(0.0, dq * dq + dr * dr + dq * dr))
            segments.append((start, end, length))
            total += length
        if total == 0:
            return nodes[0].q, nodes[0].r
        target = total / 2
        traversed = 0.0
        for start, end, length in segments:
            if traversed + length >= target:
                ratio = (target - traversed) / length if length else 0
                return (
                    start.q + (end.q - start.q) * ratio,
                    start.r + (end.r - start.r) * ratio,
                )
            traversed += length
        return nodes[-1].q, nodes[-1].r

    async def count_deep_import_observations_by_workflow(
        self,
        db: AsyncSession,
        novel_id: str,
        workflow_id: str,
    ) -> int:
        """Count workflow-owned pending observations for cleanup reporting."""
        nid = parse_uuid(novel_id, "novel_id")
        result = await db.execute(
            select(MapObservation).where(
                MapObservation.novel_id == nid,
                MapObservation.review_state.in_(["candidate", "conflicted"]),
            )
        )
        return sum(
            1
            for observation in result.scalars().all()
            if (observation.source_ref or {}).get("workflow_id") == workflow_id
            and (observation.source_ref or {}).get("auto_ingested") is True
        )

    async def rollback_deep_import_observations_by_workflow(
        self,
        db: AsyncSession,
        novel_id: str,
        workflow_id: str,
    ) -> int:
        """Archive only untouched pending observations owned by one workflow."""
        nid = parse_uuid(novel_id, "novel_id")
        result = await db.execute(
            select(MapObservation)
            .where(
                MapObservation.novel_id == nid,
                MapObservation.review_state.in_(["candidate", "conflicted"]),
            )
            .with_for_update()
        )
        rolled_back_at = datetime.now(UTC).isoformat()
        count = 0
        for observation in result.scalars().all():
            source_ref = dict(observation.source_ref or {})
            if (
                source_ref.get("workflow_id") != workflow_id
                or source_ref.get("auto_ingested") is not True
                or source_ref.get("user_edited") is True
            ):
                continue
            source_ref.update(
                {
                    "rolled_back": True,
                    "rolled_back_at": rolled_back_at,
                    "rollback_reason": "workflow_abandoned",
                }
            )
            observation.source_ref = source_ref
            observation.review_state = "ignored"
            db.add(observation)
            count += 1
        await db.flush()
        return count

    async def list_observations(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        map_id: str | None = None,
        review_state: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> MapObservationListResponse:
        owner = self.owner
        mid = None
        if map_id:
            await owner._ctx.require_map(db, novel_id, map_id)
            mid = parse_uuid(map_id, "map_id")
        nid = parse_uuid(novel_id, "novel_id")
        items, total = await owner._observation_repo.list(
            db,
            nid,
            map_id=mid,
            review_state=review_state,
            skip=skip,
            limit=limit,
        )
        return MapObservationListResponse(
            items=[await self._response(db, novel_id, item) for item in items],
            total=total,
            has_more=skip + len(items) < total,
        )

    async def list_project_inbox(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        dynamic_type: str | None = None,
        scene_id: str | None = None,
        source: str | None = None,
        confidence: str | None = None,
        eligibility: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> MapObservationListResponse:
        nid = parse_uuid(novel_id, "novel_id")
        scene_uuid = None
        if scene_id:
            await self._validated_scene(db, novel_id, scene_id, None)
            scene_uuid = parse_uuid(scene_id, "scene_id")
        advanced_filters = any((source, confidence, eligibility))
        items, total = await self.owner._observation_repo.list_project_inbox(
            db,
            nid,
            dynamic_types=(
                equivalent_dynamic_types(dynamic_type) if dynamic_type else None
            ),
            scene_id=scene_uuid,
            skip=0 if advanced_filters else skip,
            limit=None if advanced_filters else limit,
        )
        responses = [await self._response(db, novel_id, item) for item in items]
        if advanced_filters:
            responses = [
                item
                for item in responses
                if (not source or item.source == source)
                and (
                    not confidence
                    or (confidence == "low" and item.confidence < 0.6)
                    or (confidence == "high" and item.confidence >= 0.6)
                )
                and (
                    not eligibility
                    or (eligibility == "ready" and item.eligibility.can_confirm)
                    or (eligibility == "missing" and not item.eligibility.can_confirm)
                )
            ]
            total = len(responses)
            responses = responses[skip : skip + limit]
        return MapObservationListResponse(
            items=responses,
            total=total,
            has_more=skip + len(responses) < total,
        )

    async def create_observation(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        map_id: str,
        data: MapObservationCreate,
    ) -> MapObservationResponse:
        owner = self.owner
        config = await owner._ctx.require_map(db, novel_id, map_id)
        if data.target_entity_id:
            await owner._ctx.require_entity(db, novel_id, data.target_entity_id)
        spatial_anchor = await self._validated_anchor(
            db, novel_id, config, data.spatial_anchor
        )
        value_json = await self._validated_dynamic_value(
            db,
            novel_id,
            config,
            data.dynamic_type,
            data.value_json,
            spatial_anchor,
        )
        scene_uuid = await self._validated_scene(
            db,
            novel_id,
            data.scene_id,
            data.scene_index,
        )

        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        values = owner._observation_values(data, map_id=mid)
        values["spatial_anchor"] = spatial_anchor
        values["value_json"] = value_json
        values["scene_id"] = scene_uuid
        observation = await owner._observation_repo.create(db, nid, values)
        return await self._response(db, novel_id, observation)

    async def _author_update(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        observation_id: str,
        data: MapObservationAuthorUpdate,
        required_map_id: str | None = None,
    ) -> MapObservationResponse:
        owner = self.owner
        nid = parse_uuid(novel_id, "novel_id")
        oid = parse_uuid(observation_id, "observation_id")
        observation = await owner._observation_repo.get(db, oid)
        owner._assert_observation_in_novel(observation, observation_id, nid)
        assert observation is not None
        if required_map_id is not None:
            mid = parse_uuid(required_map_id, "map_id")
            await owner._ctx.require_map(db, novel_id, required_map_id)
            owner._assert_observation_in_map(observation, observation_id, mid)

        update_values = data.model_dump(
            exclude_unset=True,
            exclude={"expected_updated_at"},
        )
        immutable_proposal_type = (observation.source_ref or {}).get("proposal_type")
        next_value_json = update_values.get("value_json")
        if (
            isinstance(immutable_proposal_type, str)
            and isinstance(next_value_json, dict)
            and next_value_json.get("payload_kind") == "proposal"
            and next_value_json.get("proposal_type") != immutable_proposal_type
        ):
            raise ValidationError(
                "导入候选的 proposal 类型属于来源身份，不能原地修改",
                code="map_observation_proposal_type_immutable",
                status_code=422,
                context={"proposal_type": immutable_proposal_type},
            )
        effective_target_entity_id = update_values.get(
            "target_entity_id",
            observation.target_entity_id,
        )
        if effective_target_entity_id:
            target = await owner._ctx.require_entity(
                db,
                novel_id,
                str(effective_target_entity_id),
            )
            if target.status != "canonical":
                raise ValidationError(
                    "目标对象尚未采用",
                    code="unadopted_map_entity",
                    status_code=422,
                )
            update_values["target_entity_id"] = target.id
            update_values["target_entity_type"] = target.entity_type
            update_values["target_name"] = target.name

        config = None
        if observation.map_id is not None:
            config = await owner._ctx.require_map(
                db,
                novel_id,
                str(observation.map_id),
            )
        if "spatial_anchor" in update_values:
            if config is None:
                raise ValidationError(
                    "请先分配地图，再选择空间位置",
                    code="map_assignment_required",
                    status_code=422,
                )
            update_values["spatial_anchor"] = await self._validated_anchor(
                db,
                novel_id,
                config,
                data.spatial_anchor,
            )
        if "value_json" in update_values:
            value_json = update_values["value_json"]
            try:
                validate_map_observation_payload(
                    observation.dynamic_type,
                    value_json,
                    require_explicit_schema=True,
                )
            except (PydanticValidationError, ValueError) as exc:
                raise ValidationError(
                    "地图待处理项不符合 proposal/canonical 契约",
                    code="invalid_map_observation_payload",
                    status_code=422,
                    context={"reason": str(exc)},
                ) from exc
            if config is None and value_json.get("payload_kind") != "proposal":
                raise ValidationError(
                    "canonical 地图动态必须先分配地图",
                    code="map_assignment_required",
                    status_code=422,
                )
            if config is not None:
                update_values["value_json"] = await self._validated_dynamic_value(
                    db,
                    novel_id,
                    config,
                    observation.dynamic_type,
                    value_json,
                    update_values.get(
                        "spatial_anchor",
                        observation.spatial_anchor,
                    ),
                )
        source_ref = dict(observation.source_ref or {})
        proposal_type = self._proposal_type(observation)
        next_value = update_values.get("value_json") or {}
        if proposal_type and next_value.get("payload_kind") != "proposal":
            source_ref["proposal_type"] = proposal_type
        source_ref.update(
            {
                "user_edited": True,
                "author_updated_at": datetime.now(UTC).isoformat(),
            }
        )
        update_values["source_ref"] = source_ref
        updated = await owner._observation_repo.compare_and_update(
            db,
            nid,
            oid,
            expected_updated_at=data.expected_updated_at,
            values=update_values,
        )
        if updated is None:
            await self._raise_revision_conflict(db, novel_id, oid)
        assert updated is not None
        return await self._response(db, novel_id, updated)

    async def update_observation_review(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        map_id: str,
        observation_id: str,
        data: MapObservationAuthorUpdate,
    ) -> MapObservationResponse:
        return await self._author_update(
            db,
            novel_id,
            observation_id=observation_id,
            data=data,
            required_map_id=map_id,
        )

    async def update_project_observation(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        observation_id: str,
        data: MapObservationAuthorUpdate,
    ) -> MapObservationResponse:
        return await self._author_update(
            db,
            novel_id,
            observation_id=observation_id,
            data=data,
        )

    async def assign_project_observation(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        observation_id: str,
        data: MapObservationAssignmentRequest,
    ) -> MapObservationResponse:
        owner = self.owner
        nid = parse_uuid(novel_id, "novel_id")
        oid = parse_uuid(observation_id, "observation_id")
        observation = await owner._observation_repo.get(db, oid)
        owner._assert_observation_in_novel(observation, observation_id, nid)
        assert observation is not None
        next_map_id = None
        if data.map_id:
            config = await owner._ctx.require_map(db, novel_id, data.map_id)
            next_map_id = config.id
        source_ref = dict(observation.source_ref or {})
        history = list(source_ref.get("assignment_history") or [])
        history.append(
            {
                "from_map_id": str(observation.map_id) if observation.map_id else None,
                "to_map_id": str(next_map_id) if next_map_id else None,
                "assigned_at": datetime.now(UTC).isoformat(),
            }
        )
        source_ref["assignment_history"] = history[-20:]
        updated = await owner._observation_repo.compare_and_update(
            db,
            nid,
            oid,
            expected_updated_at=data.expected_updated_at,
            values={"map_id": next_map_id, "source_ref": source_ref},
        )
        if updated is None:
            await self._raise_revision_conflict(db, novel_id, oid)
        assert updated is not None
        return await self._response(db, novel_id, updated)

    async def ignore_observation(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        map_id: str,
        observation_id: str,
        data: MapObservationRevisionRequest,
    ) -> MapObservationResponse:
        return await self._author_update(
            db,
            novel_id,
            observation_id=observation_id,
            required_map_id=map_id,
            data=MapObservationReviewUpdate(
                expected_updated_at=data.expected_updated_at,
                review_state="ignored",
            ),
        )

    async def ignore_project_observation(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        observation_id: str,
        data: MapObservationRevisionRequest,
    ) -> MapObservationResponse:
        return await self._author_update(
            db,
            novel_id,
            observation_id=observation_id,
            data=MapObservationReviewUpdate(
                expected_updated_at=data.expected_updated_at,
                review_state="ignored",
            ),
        )

    async def confirm_observation(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        map_id: str,
        observation_id: str,
        data: MapObservationRevisionRequest,
    ) -> MapFactResponse:
        owner = self.owner
        await owner._ctx.require_map(db, novel_id, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        oid = parse_uuid(observation_id, "observation_id")

        observation = await owner._observation_repo.get_in_novel_for_update(
            db,
            nid,
            oid,
        )
        owner._assert_observation_in_novel(observation, observation_id, nid)
        assert observation is not None
        owner._assert_observation_in_map(observation, observation_id, mid)

        existing = await owner._fact_repo.get_by_observation(db, oid)
        if existing is not None:
            return MapFactResponse.model_validate(existing)
        if observation.review_state not in {
            "candidate",
            "conflicted",
        } or not self._same_revision(
            observation.updated_at,
            data.expected_updated_at,
        ):
            await self._raise_revision_conflict(db, novel_id, oid)

        response = await self._response(db, novel_id, observation)
        if not response.eligibility.can_confirm:
            raise ValidationError(
                "地图待处理项仍有缺失或冲突，暂不能采用",
                code="map_observation_not_eligible",
                status_code=422,
                context={"eligibility": response.eligibility.model_dump(mode="json")},
            )

        config = await owner._ctx.require_map(db, novel_id, map_id)
        await self._validated_dynamic_value(
            db,
            novel_id,
            config,
            observation.dynamic_type,
            observation.value_json,
            observation.spatial_anchor,
        )
        await self._validated_scene(
            db,
            novel_id,
            str(observation.scene_id) if observation.scene_id else None,
            observation.scene_index,
        )

        fact_anchor = await self._fact_anchor_snapshot(
            db,
            novel_id,
            observation.map_id or mid,
            observation.spatial_anchor,
            dynamic_type=observation.dynamic_type,
            value_json=observation.value_json,
        )
        fact = await owner._fact_repo.create(
            db,
            nid,
            {
                "observation_id": oid,
                "map_id": observation.map_id or mid,
                "target_entity_id": observation.target_entity_id,
                "target_entity_type": observation.target_entity_type,
                "target_name": observation.target_name,
                "dynamic_type": observation.dynamic_type,
                "time_anchor": observation.time_anchor or {},
                "spatial_anchor": fact_anchor,
                "value_json": observation.value_json or {},
                "confidence": observation.confidence,
                "fact_status": "confirmed",
                "source_ref": observation.source_ref or {},
                "evidence_text": observation.evidence_text,
                "scene_id": observation.scene_id,
                "scene_index": observation.scene_index,
                "source_chapter_index": observation.source_chapter_index,
            },
        )
        await owner._observation_repo.update_review_state(db, observation, "confirmed")
        from modules.world.services.worldbuilding.synopsis_invalidation import (
            mark_synopsis_source_changed,
        )

        await mark_synopsis_source_changed(
            db,
            novel_id,
            source_type="map_fact",
            source_id=str(fact.id),
        )
        return MapFactResponse.model_validate(fact)

    async def batch_review_observations(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        map_id: str,
        data: MapObservationBatchReviewRequest,
    ) -> MapObservationBatchReviewResponse:
        owner = self.owner
        await owner._ctx.require_map(db, novel_id, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        observation_ids = [
            parse_uuid(item.observation_id, "observation_id") for item in data.items
        ]
        locked = await owner._observation_repo.get_many_in_novel_for_update(
            db,
            nid,
            observation_ids,
        )
        locked_by_id = {observation.id: observation for observation in locked}
        request_by_id = {
            parse_uuid(item.observation_id, "observation_id"): item for item in data.items
        }
        observations: list[MapObservation] = []
        for oid in sorted(observation_ids, key=str):
            request_item = request_by_id[oid]
            observation = locked_by_id.get(oid)
            owner._assert_observation_in_novel(
                observation,
                request_item.observation_id,
                nid,
            )
            assert observation is not None
            owner._assert_observation_in_map(
                observation,
                request_item.observation_id,
                mid,
            )
            if observation.review_state not in {
                "candidate",
                "conflicted",
            } or not self._same_revision(
                observation.updated_at,
                request_item.expected_updated_at,
            ):
                await self._raise_revision_conflict(db, novel_id, oid)
            observations.append(observation)

        updated_observations: list[MapObservationResponse] = []
        facts: list[MapFactResponse] = []
        created_fact_count = 0
        if data.action == "confirm":
            config = await owner._ctx.require_map(db, novel_id, map_id)
            for observation in observations:
                response = await self._response(db, novel_id, observation)
                if not response.eligibility.can_confirm:
                    raise ValidationError(
                        "批量采用包含仍有缺失或冲突的地图待处理项",
                        code="map_observation_not_eligible",
                        status_code=422,
                        context={
                            "observation_id": str(observation.id),
                            "eligibility": response.eligibility.model_dump(mode="json"),
                        },
                    )
                await self._validated_dynamic_value(
                    db,
                    novel_id,
                    config,
                    observation.dynamic_type,
                    observation.value_json,
                    observation.spatial_anchor,
                )
                await self._validated_scene(
                    db,
                    novel_id,
                    str(observation.scene_id) if observation.scene_id else None,
                    observation.scene_index,
                )
            existing_facts = await owner._fact_repo.get_by_observations(
                db,
                [observation.id for observation in observations],
            )
            fact_by_observation = {fact.observation_id: fact for fact in existing_facts}
            missing_observations = []
            seen_missing: set[Any] = set()
            for observation in observations:
                if observation.id in fact_by_observation:
                    continue
                if observation.id in seen_missing:
                    continue
                seen_missing.add(observation.id)
                missing_observations.append(observation)

            fact_anchors = {
                observation.id: await self._fact_anchor_snapshot(
                    db,
                    novel_id,
                    observation.map_id or mid,
                    observation.spatial_anchor,
                    dynamic_type=observation.dynamic_type,
                    value_json=observation.value_json,
                )
                for observation in missing_observations
            }
            created_facts = await owner._fact_repo.create_many(
                db,
                nid,
                [
                    {
                        "observation_id": observation.id,
                        "map_id": observation.map_id or mid,
                        "target_entity_id": observation.target_entity_id,
                        "target_entity_type": observation.target_entity_type,
                        "target_name": observation.target_name,
                        "dynamic_type": observation.dynamic_type,
                        "time_anchor": observation.time_anchor or {},
                        "spatial_anchor": fact_anchors[observation.id],
                        "value_json": observation.value_json or {},
                        "confidence": observation.confidence,
                        "fact_status": "confirmed",
                        "source_ref": observation.source_ref or {},
                        "evidence_text": observation.evidence_text,
                        "scene_id": observation.scene_id,
                        "scene_index": observation.scene_index,
                        "source_chapter_index": observation.source_chapter_index,
                    }
                    for observation in missing_observations
                ],
            )
            created_fact_count = len(created_facts)
            fact_by_observation.update(
                {fact.observation_id: fact for fact in created_facts}
            )

            for observation in observations:
                observation.review_state = "confirmed"
                db.add(observation)
                fact = fact_by_observation.get(observation.id)
                if fact is not None:
                    facts.append(MapFactResponse.model_validate(fact))
            await db.flush()
            for observation in observations:
                updated_observations.append(
                    await self._response(db, novel_id, observation)
                )
            if facts:
                from modules.world.services.worldbuilding.synopsis_invalidation import (
                    mark_synopsis_source_changed,
                )

                await mark_synopsis_source_changed(
                    db,
                    novel_id,
                    source_type="map_fact_batch",
                    source_id=map_id,
                )
        else:
            next_state = "ignored" if data.action == "ignore" else "conflicted"
            for observation in observations:
                observation.review_state = next_state
                db.add(observation)
            await db.flush()
            for observation in observations:
                updated_observations.append(
                    await self._response(db, novel_id, observation)
                )

        return MapObservationBatchReviewResponse(
            action=data.action,
            requested_count=len(data.items),
            updated_count=len(updated_observations),
            created_fact_count=created_fact_count,
            observations=updated_observations,
            facts=facts,
        )

    @staticmethod
    def _candidate_identity(
        novel_id: str,
        candidate: MapObservationCandidateInput,
    ) -> uuid.UUID:
        identity = "|".join(
            (
                str(novel_id),
                candidate.workflow_id,
                candidate.scene_id,
                candidate.source_item_key,
                candidate.proposal.proposal_type,
            )
        )
        return uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"ai-writing-assist:map-observation:v1:{identity}",
        )

    @staticmethod
    def _candidate_payload_hash(candidate: MapObservationCandidateInput) -> str:
        payload = candidate.model_dump(
            mode="json",
            exclude={"task_id", "authorization"},
        )
        payload["authorization_fingerprint"] = (
            candidate.authorization.snapshot_fingerprint
        )
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    async def create_observation_candidates(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        candidates: list[MapObservationCandidateInput],
    ) -> MapObservationCandidateBatchResult:
        """Create import-owned proposal observations as one fail-closed batch."""
        if not candidates:
            return MapObservationCandidateBatchResult()

        owner = self.owner
        nid = parse_uuid(novel_id, "novel_id")
        prepared: dict[
            uuid.UUID,
            tuple[MapObservationCandidateInput, str, dict[str, Any]],
        ] = {}
        dynamic_types = {
            "character_location": "location",
            "event_location": "location",
            "route_state": "route_state",
            "boundary": "boundary",
        }
        expected_entity_types = {
            "character_location": {"character"},
            "event_location": {"event"},
            "boundary": {"organization", "faction"},
        }

        for candidate in candidates:
            authorization_scope = candidate.authorization.scope
            if authorization_scope.novel_id != str(nid):
                raise ValidationError(
                    "地图候选授权项目与当前项目不一致",
                    code="map_observation_candidate_authorization_scope_invalid",
                    status_code=422,
                )
            if not (
                authorization_scope.start_chapter
                <= candidate.source_chapter_index
                <= authorization_scope.end_chapter
            ):
                raise ValidationError(
                    "地图候选章节不在导入授权范围内",
                    code="map_observation_candidate_authorization_scope_invalid",
                    status_code=422,
                    context={
                        "source_chapter_index": candidate.source_chapter_index,
                        "start_chapter": authorization_scope.start_chapter,
                        "end_chapter": authorization_scope.end_chapter,
                    },
                )
            scene = await get_scene_contract(db, novel_id, candidate.scene_id)
            if scene is None:
                raise NotFoundError(
                    "地图候选来源 Scene 不存在",
                    code="map_observation_candidate_scene_not_found",
                    context={"scene_id": candidate.scene_id},
                )
            if scene.scene_index != candidate.scene_index:
                raise ValidationError(
                    "地图候选 Scene 序号与当前项目不一致",
                    code="map_observation_candidate_scene_mismatch",
                    status_code=422,
                    context={
                        "scene_id": candidate.scene_id,
                        "expected_scene_index": scene.scene_index,
                        "received_scene_index": candidate.scene_index,
                    },
                )

            proposal_type = candidate.proposal.proposal_type
            target_uuid = None
            target_type = None
            target_name = candidate.target_name
            if candidate.target_entity_id:
                target = await owner._ctx.require_entity(
                    db,
                    novel_id,
                    candidate.target_entity_id,
                )
                allowed_types = expected_entity_types.get(proposal_type)
                if allowed_types and target.entity_type not in allowed_types:
                    raise ValidationError(
                        "地图候选目标对象类型不正确",
                        code="map_observation_candidate_target_type_invalid",
                        status_code=422,
                        context={
                            "proposal_type": proposal_type,
                            "entity_type": target.entity_type,
                        },
                    )
                target_uuid = target.id
                target_type = target.entity_type
                target_name = target.name
            elif (
                proposal_type in {"character_location", "event_location"}
                and not target_name
            ):
                raise ValidationError(
                    "人物/事件地点候选必须提供目标名称或目标对象",
                    code="map_observation_candidate_target_required",
                    status_code=422,
                )
            elif proposal_type == "boundary" and not target_name:
                target_name = candidate.proposal.controller_name

            observation_id = self._candidate_identity(str(nid), candidate)
            payload_hash = self._candidate_payload_hash(candidate)
            source_ref = {
                "source": "deep_import_typed_map_proposal",
                "identity_version": 1,
                "workflow_id": candidate.workflow_id,
                "task_id": candidate.task_id,
                "source_item_key": candidate.source_item_key,
                "proposal_type": proposal_type,
                "scene_source_fingerprint": candidate.scene_source_fingerprint,
                "context_snapshot_id": candidate.context_snapshot_id,
                "evidence_anchor": candidate.evidence_anchor,
                "original_payload_hash": payload_hash,
                "adoption_policy": candidate.authorization.adoption_policy,
                "authorization_confirmed": True,
                "authorized_at": candidate.authorization.authorized_at.isoformat(),
                "authorization_scope": candidate.authorization.scope.model_dump(
                    mode="json"
                ),
                "authorization_snapshot_fingerprint": (
                    candidate.authorization.snapshot_fingerprint
                ),
                "auto_ingested": True,
            }
            values = {
                "id": observation_id,
                "map_id": None,
                "target_entity_id": target_uuid,
                "target_entity_type": target_type,
                "target_name": target_name,
                "dynamic_type": dynamic_types[proposal_type],
                "time_anchor": {
                    "kind": "scene",
                    "scene_id": candidate.scene_id,
                    "scene_index": candidate.scene_index,
                    "source_chapter_index": candidate.source_chapter_index,
                },
                "spatial_anchor": {},
                "value_json": candidate.proposal.model_dump(
                    mode="json", exclude_none=True
                ),
                "confidence": candidate.confidence,
                "review_state": "candidate",
                "source_ref": source_ref,
                "evidence_text": candidate.evidence_text,
                "scene_id": parse_uuid(candidate.scene_id, "scene_id"),
                "scene_index": candidate.scene_index,
                "source_chapter_index": candidate.source_chapter_index,
            }
            previous = prepared.get(observation_id)
            if previous and previous[1] != payload_hash:
                raise ConflictError(
                    "同一地图候选身份包含不同来源内容",
                    code="map_observation_candidate_payload_conflict",
                    context={"observation_id": str(observation_id)},
                )
            prepared[observation_id] = (candidate, payload_hash, values)

        await owner._observation_repo.lock_candidate_identities(
            db,
            nid,
            list(prepared),
        )
        existing_rows = await owner._observation_repo.get_many_in_novel_for_update(
            db,
            nid,
            list(prepared),
        )
        existing = {item.id: item for item in existing_rows}
        results: list[MapObservationCandidateResult] = []
        for observation_id in sorted(prepared, key=str):
            candidate, payload_hash, values = prepared[observation_id]
            current = existing.get(observation_id)
            if current is not None:
                current_hash = (current.source_ref or {}).get("original_payload_hash")
                if current_hash != payload_hash:
                    raise ConflictError(
                        "地图候选来源已变化，已停止重试写入",
                        code="map_observation_candidate_payload_conflict",
                        context={
                            "observation_id": str(observation_id),
                            "existing_payload_hash": current_hash,
                            "received_payload_hash": payload_hash,
                        },
                    )

        created_ids: set[uuid.UUID] = set()
        for observation_id in sorted(prepared, key=str):
            candidate, payload_hash, values = prepared[observation_id]
            if observation_id not in existing:
                await owner._observation_repo.create(db, nid, values)
                created_ids.add(observation_id)
            results.append(
                MapObservationCandidateResult(
                    observation_id=str(observation_id),
                    action="created" if observation_id in created_ids else "reused",
                    proposal_type=candidate.proposal.proposal_type,
                    payload_hash=payload_hash,
                )
            )
        return MapObservationCandidateBatchResult(
            created_count=len(created_ids),
            reused_count=len(results) - len(created_ids),
            items=results,
        )

    async def create_observation_from_delta_event(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        event: dict[str, Any],
        scene_index: int,
        context_snapshot_id: str | None = None,
        delta_log_id: str | None = None,
    ) -> MapObservationResponse:
        """将 deep import 的通用 delta_event 接入地图候选流。

        该方法宽容处理不完整 LLM 输出：缺失地图、实体或空间锚点时仍保留候选
        观察，但不会写入可疑跨 novel_id 的实体引用。
        """
        owner = self.owner

        nid = parse_uuid(novel_id, "novel_id")
        meta = event.get("meta") or {}
        map_uuid = await owner._safe_map_uuid(db, novel_id, meta.get("map_id"))
        target_uuid = await owner._safe_entity_uuid(
            db, nid, meta.get("target_entity_id") or meta.get("entity_id")
        )
        dynamic_type = owner._normalize_dynamic_type(
            meta.get("dynamic_type")
            or meta.get("map_dynamic_type")
            or event.get("category")
            or "delta_event"
        )
        confidence = owner._clamp_confidence(meta.get("confidence", 0.5))
        source_ref = {
            "source": "deep_import_delta_event",
            "delta_log_id": delta_log_id,
            "context_snapshot_id": context_snapshot_id,
            **(meta.get("source_ref") or {}),
        }
        raw_anchor = meta.get("spatial_anchor") or {}
        invalid_anchor: dict[str, Any] | None = None
        try:
            spatial_anchor = MapSpatialAnchor.model_validate(raw_anchor).model_dump(
                mode="json", exclude_none=True
            )
        except PydanticValidationError:
            spatial_anchor = {}
            invalid_anchor = {
                "reason": "schema_validation_failed",
                "path_candidate": str(
                    raw_anchor.get("path_id") if isinstance(raw_anchor, dict) else ""
                )[:255],
            }
        anchor_declared_map = isinstance(raw_anchor, dict) and bool(
            raw_anchor.get("map_id")
        )
        if map_uuid is not None and (
            spatial_anchor.get("path_id") or anchor_declared_map
        ):
            spatial_anchor["map_id"] = str(map_uuid)
        else:
            spatial_anchor.pop("map_id", None)
        if spatial_anchor.get("path_id"):
            path = (
                await self._path_repo.get_in_map(
                    db,
                    nid,
                    map_uuid,
                    parse_uuid(spatial_anchor["path_id"], "path_id"),
                )
                if map_uuid is not None
                else None
            )
            if path is None or path.status != "active":
                invalid_anchor = {
                    "reason": "invalid_path_reference",
                    "path_candidate": str(spatial_anchor.get("path_id"))[:255],
                }
                for field in (
                    "path_id",
                    "path_revision",
                    "path_name",
                    "representative_q",
                    "representative_r",
                ):
                    spatial_anchor.pop(field, None)
        location_entity_id = spatial_anchor.get("location_entity_id")
        if location_entity_id:
            try:
                location = await owner._ctx.require_entity(
                    db,
                    novel_id,
                    location_entity_id,
                )
            except NotFoundError:
                location = None
            if location is None or location.entity_type != "location":
                invalid_anchor = {
                    "reason": "invalid_location_reference",
                    "location_candidate": str(location_entity_id)[:255],
                }
                spatial_anchor.pop("location_entity_id", None)
        if map_uuid is not None:
            config = await owner._map_repo.get_in_novel(
                db, nid, map_uuid, status="active"
            )
            if config is not None:
                for q_key, r_key in (
                    ("hex_q", "hex_r"),
                    ("representative_q", "representative_r"),
                ):
                    if q_key not in spatial_anchor:
                        continue
                    if (
                        spatial_anchor[q_key] >= config.grid_width
                        or spatial_anchor[r_key] >= config.grid_height
                    ):
                        invalid_anchor = {"reason": "coordinates_out_of_bounds"}
                        spatial_anchor.pop(q_key, None)
                        spatial_anchor.pop(r_key, None)
        if invalid_anchor is not None:
            source_ref["invalid_spatial_anchor"] = invalid_anchor
        value_json = {
            "category": event.get("category"),
            "field": event.get("field"),
            "old": event.get("old"),
            "new": event.get("new"),
        }
        typed_candidate = meta.get("map_value") or meta.get("normalized_value")
        if isinstance(typed_candidate, dict) and "schema_version" in typed_candidate:
            config = (
                await owner._map_repo.get_in_novel(
                    db,
                    nid,
                    map_uuid,
                    status="active",
                )
                if map_uuid is not None
                else None
            )
            try:
                if config is None:
                    raise ValidationError(
                        "类型化地图动态需要有效地图",
                        code="typed_map_dynamic_requires_map",
                    )
                value_json = await self._validated_dynamic_value(
                    db,
                    novel_id,
                    config,
                    dynamic_type,
                    typed_candidate,
                    spatial_anchor,
                )
            except (DomainError, ValueError) as exc:
                source_ref["invalid_map_value"] = {
                    "reason": getattr(exc, "code", "schema_validation_failed"),
                }
        scene_uuid = None
        raw_scene_id = meta.get("scene_id")
        if raw_scene_id:
            try:
                scene_uuid = await self._validated_scene(
                    db,
                    novel_id,
                    str(raw_scene_id),
                    scene_index,
                )
            except DomainError as exc:
                source_ref["invalid_scene_anchor"] = {
                    "reason": exc.code,
                    "scene_candidate": str(raw_scene_id)[:255],
                }
        values = {
            "map_id": map_uuid,
            "target_entity_id": target_uuid,
            "target_entity_type": meta.get("target_entity_type")
            or meta.get("entity_type"),
            "target_name": meta.get("target_name")
            or meta.get("entity_name")
            or meta.get("object_name"),
            "dynamic_type": dynamic_type,
            "time_anchor": {
                "scene_index": scene_index,
                **(meta.get("time_anchor") or {}),
            },
            "spatial_anchor": spatial_anchor,
            "value_json": value_json,
            "confidence": confidence,
            "review_state": "candidate",
            "source_ref": source_ref,
            "evidence_text": meta.get("evidence_text")
            or meta.get("quote")
            or meta.get("source_text"),
            "scene_id": scene_uuid,
            "scene_index": scene_index,
            "source_chapter_index": meta.get("source_chapter_index"),
        }
        observation = await owner._observation_repo.create(db, nid, values)
        return await self._response(db, novel_id, observation)
