from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.map_models import MapObservation
from modules.world.map_schemas import (
    MapFactResponse,
    MapObservationBatchReviewRequest,
    MapObservationBatchReviewResponse,
    MapObservationCreate,
    MapObservationListResponse,
    MapObservationResponse,
    MapObservationReviewUpdate,
)
from modules.world.services.common import parse_uuid
from modules.world.services.map.map_dynamic_lifecycle import MapDynamicLifecycle


class MapObservationService:
    """Delegated dynamic-map service."""

    def __init__(self, owner: MapDynamicLifecycle) -> None:
        self.owner = owner

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
        owner._assert_spatial_anchor_in_bounds(config, data.spatial_anchor or {})

        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        values = owner._observation_values(data, map_id=mid)
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
            owner._assert_spatial_anchor_in_bounds(config, data.spatial_anchor or {})
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

        existing = await owner._fact_repo.get_by_observation(db, oid)
        if existing is not None:
            await owner._observation_repo.update_review_state(
                db,
                observation,
                "confirmed",
            )
            return MapFactResponse.model_validate(existing)

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
                "spatial_anchor": observation.spatial_anchor or {},
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
                        "spatial_anchor": observation.spatial_anchor or {},
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
            "spatial_anchor": meta.get("spatial_anchor") or {},
            "value_json": {
                "category": event.get("category"),
                "field": event.get("field"),
                "old": event.get("old"),
                "new": event.get("new"),
            },
            "confidence": confidence,
            "review_state": "candidate",
            "source_ref": source_ref,
            "evidence_text": meta.get("evidence_text")
            or meta.get("quote")
            or meta.get("source_text"),
            "scene_id": owner._safe_uuid(meta.get("scene_id")),
            "scene_index": scene_index,
            "source_chapter_index": meta.get("source_chapter_index"),
        }
        observation = await owner._observation_repo.create(db, nid, values)
        return MapObservationResponse.model_validate(observation)
