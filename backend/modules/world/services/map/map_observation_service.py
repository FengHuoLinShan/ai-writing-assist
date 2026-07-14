from __future__ import annotations

import uuid
from datetime import UTC, datetime
from math import sqrt
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, DomainError, NotFoundError, ValidationError
from modules.outline.facade import get_scene_contract
from modules.world.map_models import MapObservation
from modules.world.map_repositories import MapPathNodeRepository, MapPathRepository
from modules.world.map_schemas import (
    MapFactResponse,
    MapObservationBatchReviewRequest,
    MapObservationBatchReviewResponse,
    MapObservationCreate,
    MapObservationListResponse,
    MapObservationResponse,
    MapObservationReviewUpdate,
    MapSpatialAnchor,
)
from modules.world.services.common import parse_uuid
from modules.world.services.map.map_dynamic_lifecycle import MapDynamicLifecycle
from modules.world.services.map.map_dynamic_projection import (
    canonical_dynamic_type,
    normalize_dynamic_value,
    validate_versioned_dynamic_value,
)


class MapObservationService:
    """Delegated dynamic-map service."""

    def __init__(self, owner: MapDynamicLifecycle) -> None:
        self.owner = owner
        self._path_repo = MapPathRepository()
        self._path_node_repo = MapPathNodeRepository()

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
            items=[MapObservationResponse.model_validate(item) for item in items],
            total=total,
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
        return MapObservationResponse.model_validate(observation)

    async def update_observation_review(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        map_id: str,
        observation_id: str,
        data: MapObservationReviewUpdate,
    ) -> MapObservationResponse:
        owner = self.owner
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        await owner._ctx.require_map(db, novel_id, map_id)
        oid = parse_uuid(observation_id, "observation_id")
        observation = await owner._observation_repo.get(db, oid)
        owner._assert_observation_in_novel(observation, observation_id, nid)
        assert observation is not None
        owner._assert_observation_in_map(observation, observation_id, mid)
        update_values = data.model_dump(exclude_unset=True)
        if data.target_entity_id:
            await owner._ctx.require_entity(db, novel_id, data.target_entity_id)
        if "spatial_anchor" in update_values:
            config = await owner._ctx.require_map(db, novel_id, map_id)
            update_values["spatial_anchor"] = await self._validated_anchor(
                db, novel_id, config, data.spatial_anchor
            )
        config = await owner._ctx.require_map(db, novel_id, map_id)
        combined_dynamic_type = update_values.get(
            "dynamic_type", observation.dynamic_type
        )
        combined_value = update_values.get("value_json", observation.value_json)
        combined_anchor = update_values.get(
            "spatial_anchor", observation.spatial_anchor
        )
        update_values["value_json"] = await self._validated_dynamic_value(
            db,
            novel_id,
            config,
            combined_dynamic_type,
            combined_value,
            combined_anchor,
        )
        if "scene_id" in update_values or "scene_index" in update_values:
            raw_scene_id = update_values.get("scene_id")
            if raw_scene_id is None and "scene_id" not in update_values:
                raw_scene_id = str(observation.scene_id) if observation.scene_id else None
            raw_scene_index = update_values.get(
                "scene_index", observation.scene_index
            )
            update_values["scene_id"] = await self._validated_scene(
                db,
                novel_id,
                str(raw_scene_id) if raw_scene_id else None,
                raw_scene_index,
            )
        updated = await owner._observation_repo.update(db, observation, update_values)
        assert updated is not None
        return MapObservationResponse.model_validate(updated)

    async def ignore_observation(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        map_id: str,
        observation_id: str,
    ) -> MapObservationResponse:
        owner = self.owner
        return await owner.update_observation_review(
            db,
            novel_id,
            map_id=map_id,
            observation_id=observation_id,
            data=MapObservationReviewUpdate(review_state="ignored"),
        )

    async def confirm_observation(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        map_id: str,
        observation_id: str,
    ) -> MapFactResponse:
        owner = self.owner
        await owner._ctx.require_map(db, novel_id, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        oid = parse_uuid(observation_id, "observation_id")

        observation = await owner._observation_repo.get(db, oid)
        owner._assert_observation_in_novel(observation, observation_id, nid)
        assert observation is not None
        owner._assert_observation_in_map(observation, observation_id, mid)

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

        existing = await owner._fact_repo.get_by_observation(db, oid)
        if existing is not None:
            await owner._observation_repo.update_review_state(
                db,
                observation,
                "confirmed",
            )
            from modules.world.services.worldbuilding.synopsis_invalidation import (
                mark_synopsis_source_changed,
            )

            await mark_synopsis_source_changed(
                db,
                novel_id,
                source_type="map_fact",
                source_id=str(existing.id),
            )
            return MapFactResponse.model_validate(existing)

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
            parse_uuid(observation_id, "observation_id")
            for observation_id in data.observation_ids
        ]
        observations_by_id = {
            observation.id: observation
            for observation in await owner._observation_repo.get_many(
                db,
                observation_ids,
            )
        }
        observations = []
        for observation_id, oid in zip(data.observation_ids, observation_ids):
            observation = observations_by_id.get(oid)
            owner._assert_observation_in_novel(observation, observation_id, nid)
            assert observation is not None
            owner._assert_observation_in_map(observation, observation_id, mid)
            observations.append(observation)

        updated_observations = []
        facts = []
        created_fact_count = 0
        if data.action == "confirm":
            config = await owner._ctx.require_map(db, novel_id, map_id)
            for observation in observations:
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

            updated = await owner._observation_repo.update_review_states(
                db,
                [observation.id for observation in observations],
                "confirmed",
            )
            updated_by_id = {observation.id: observation for observation in updated}
            for observation in observations:
                fact = fact_by_observation.get(observation.id)
                if fact is not None:
                    facts.append(MapFactResponse.model_validate(fact))
                updated_observation = updated_by_id.get(observation.id)
                if updated_observation is not None:
                    updated_observations.append(
                        MapObservationResponse.model_validate(updated_observation)
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
            updated = await owner._observation_repo.update_review_states(
                db,
                [observation.id for observation in observations],
                next_state,
            )
            updated_by_id = {observation.id: observation for observation in updated}
            for observation in observations:
                updated_observation = updated_by_id.get(observation.id)
                assert updated_observation is not None
                updated_observations.append(
                    MapObservationResponse.model_validate(updated_observation)
                )

        return MapObservationBatchReviewResponse(
            action=data.action,
            requested_count=len(data.observation_ids),
            updated_count=len(updated_observations),
            created_fact_count=created_fact_count,
            observations=updated_observations,
            facts=facts,
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
        return MapObservationResponse.model_validate(observation)
