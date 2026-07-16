from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ValidationError
from modules.world.contracts import (
    MapObservationCandidateBatchResult,
    MapObservationCandidateInput,
)
from modules.world.map_repositories import (
    MapConfigRepository,
    MapFactRepository,
    MapLocationBindingRepository,
    MapMarkerRepository,
    MapObservationRepository,
    MapPathNodeRepository,
    MapPathRepository,
    MapTerritoryRepository,
)
from modules.world.map_schemas import (
    MapBatchActionRequest,
    MapBatchActionResponse,
    MapDashboardResponse,
    MapDynamicStateAtResponse,
    MapDynamicTimelineResponse,
    MapFactListResponse,
    MapFactResponse,
    MapFactStatusUpdate,
    MapObservationAssignmentRequest,
    MapObservationAuthorUpdate,
    MapObservationBatchReviewRequest,
    MapObservationBatchReviewResponse,
    MapObservationCreate,
    MapObservationListResponse,
    MapObservationResponse,
    MapObservationRevisionRequest,
    MapOpenTarget,
    MapPlaybackResponse,
)
from modules.world.repositories import CoreEntityRepository
from modules.world.services.common import parse_uuid
from modules.world.services.map.map_context import MapContext
from modules.world.services.map.map_dashboard_service import MapDashboardMixin
from modules.world.services.map.map_dynamic_helpers import MapDynamicHelperMixin
from modules.world.services.map.map_fact_service import MapFactMixin
from modules.world.services.map.map_observation_service import MapObservationMixin
from modules.world.services.map.map_open_target_service import MapOpenTargetMixin
from modules.world.services.map.map_playback_service import MapPlaybackMixin
from modules.world.services.map.map_timeline_service import MapTimelineService


class MapDynamicFactService(
    MapObservationMixin,
    MapFactMixin,
    MapDashboardMixin,
    MapPlaybackMixin,
    MapOpenTargetMixin,
    MapDynamicHelperMixin,
):
    """Deep dynamic-map lifecycle with one stable facade surface."""

    def __init__(
        self,
        observation_repo: MapObservationRepository | None = None,
        fact_repo: MapFactRepository | None = None,
        context: MapContext | None = None,
        entity_repo: CoreEntityRepository | None = None,
        map_repo: MapConfigRepository | None = None,
        binding_repo: MapLocationBindingRepository | None = None,
        marker_repo: MapMarkerRepository | None = None,
        territory_repo: MapTerritoryRepository | None = None,
        path_repo: MapPathRepository | None = None,
        path_node_repo: MapPathNodeRepository | None = None,
    ) -> None:
        self._observation_repo = observation_repo or MapObservationRepository()
        self._fact_repo = fact_repo or MapFactRepository()
        self._ctx = context or MapContext()
        self._entity_repo = entity_repo or CoreEntityRepository()
        self._map_repo = map_repo or MapConfigRepository()
        self._binding_repo = binding_repo or MapLocationBindingRepository()
        self._marker_repo = marker_repo or MapMarkerRepository()
        self._territory_repo = territory_repo or MapTerritoryRepository()
        self._path_repo = path_repo or MapPathRepository()
        self._path_node_repo = path_node_repo or MapPathNodeRepository()

    @property
    def _timeline(self) -> MapTimelineService:
        return MapTimelineService(
            context=self._ctx,
            fact_repo=self._fact_repo,
            observation_repo=self._observation_repo,
            path_repo=self._path_repo,
        )

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
        return await MapObservationMixin.list_observations(
            self,
            db,
            novel_id,
            map_id=map_id,
            review_state=review_state,
            skip=skip,
            limit=limit,
        )

    async def list_project_observation_inbox(
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
        return await MapObservationMixin.list_project_inbox(
            self,
            db,
            novel_id,
            dynamic_type=dynamic_type,
            scene_id=scene_id,
            source=source,
            confidence=confidence,
            eligibility=eligibility,
            skip=skip,
            limit=limit,
        )

    async def count_deep_import_observations_by_workflow(
        self,
        db: AsyncSession,
        novel_id: str,
        workflow_id: str,
    ) -> int:
        return await MapObservationMixin.count_deep_import_observations_by_workflow(
            self,
            db,
            novel_id,
            workflow_id,
        )

    async def rollback_deep_import_observations_by_workflow(
        self,
        db: AsyncSession,
        novel_id: str,
        workflow_id: str,
    ) -> int:
        return await MapObservationMixin.rollback_deep_import_observations_by_workflow(
            self,
            db,
            novel_id,
            workflow_id,
        )

    async def create_observation(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        map_id: str,
        data: MapObservationCreate,
    ) -> MapObservationResponse:
        return await MapObservationMixin.create_observation(
            self,
            db,
            novel_id,
            map_id=map_id,
            data=data,
        )

    async def update_observation_review(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        map_id: str,
        observation_id: str,
        data: MapObservationAuthorUpdate,
    ) -> MapObservationResponse:
        return await MapObservationMixin.update_observation_review(
            self,
            db,
            novel_id,
            map_id=map_id,
            observation_id=observation_id,
            data=data,
        )

    async def update_project_observation(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        observation_id: str,
        data: MapObservationAuthorUpdate,
    ) -> MapObservationResponse:
        return await MapObservationMixin.update_project_observation(
            self,
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
        return await MapObservationMixin.assign_project_observation(
            self,
            db,
            novel_id,
            observation_id=observation_id,
            data=data,
        )

    async def ignore_project_observation(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        observation_id: str,
        data: MapObservationRevisionRequest,
    ) -> MapObservationResponse:
        return await MapObservationMixin.ignore_project_observation(
            self,
            db,
            novel_id,
            observation_id=observation_id,
            data=data,
        )

    async def ignore_observation(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        map_id: str,
        observation_id: str,
        data: MapObservationRevisionRequest,
    ) -> MapObservationResponse:
        return await MapObservationMixin.ignore_observation(
            self,
            db,
            novel_id,
            map_id=map_id,
            observation_id=observation_id,
            data=data,
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
        return await MapObservationMixin.confirm_observation(
            self,
            db,
            novel_id,
            map_id=map_id,
            observation_id=observation_id,
            data=data,
        )

    async def batch_review_observations(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        map_id: str,
        data: MapObservationBatchReviewRequest,
    ) -> MapObservationBatchReviewResponse:
        return await MapObservationMixin.batch_review_observations(
            self,
            db,
            novel_id,
            map_id=map_id,
            data=data,
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
        return await MapObservationMixin.create_observation_from_delta_event(
            self,
            db,
            novel_id,
            event=event,
            scene_index=scene_index,
            context_snapshot_id=context_snapshot_id,
            delta_log_id=delta_log_id,
        )

    async def create_observation_candidates(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        candidates: list[MapObservationCandidateInput],
    ) -> MapObservationCandidateBatchResult:
        return await MapObservationMixin.create_observation_candidates(
            self,
            db,
            novel_id,
            candidates=candidates,
        )

    async def list_facts(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        map_id: str | None = None,
        fact_status: str | None = "confirmed",
        skip: int = 0,
        limit: int = 100,
    ) -> MapFactListResponse:
        return await MapFactMixin.list_facts(
            self,
            db,
            novel_id,
            map_id=map_id,
            fact_status=fact_status,
            skip=skip,
            limit=limit,
        )

    async def update_fact_status(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        map_id: str,
        fact_id: str,
        data: MapFactStatusUpdate,
    ) -> MapFactResponse:
        return await MapFactMixin.update_fact_status(
            self,
            db,
            novel_id,
            map_id=map_id,
            fact_id=fact_id,
            data=data,
        )

    async def get_open_target(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        scene_id: str | None = None,
        focus_entity_id: str | None = None,
    ) -> MapOpenTarget:
        return await MapOpenTargetMixin.get_open_target(
            self,
            db,
            novel_id,
            scene_id=scene_id,
            focus_entity_id=focus_entity_id,
        )

    async def run_batch_action(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        map_id: str,
        data: MapBatchActionRequest,
    ) -> MapBatchActionResponse:
        await self._ctx.require_map(db, novel_id, map_id)
        if data.action in {
            "confirm_observations",
            "ignore_observations",
            "mark_conflicted",
        }:
            action_map = {
                "confirm_observations": "confirm",
                "ignore_observations": "ignore",
                "mark_conflicted": "conflict",
            }
            batch = await self.batch_review_observations(
                db,
                novel_id,
                map_id=map_id,
                data=MapObservationBatchReviewRequest(
                    items=data.observation_items,
                    action=action_map[data.action],
                ),
            )
            return MapBatchActionResponse(
                action=data.action,
                requested_count=batch.requested_count,
                updated_count=batch.updated_count,
                created_fact_count=batch.created_fact_count,
                observations=batch.observations,
                facts=batch.facts,
            )

        if data.action == "update_fact_status":
            next_status = data.patch.get("fact_status")
            if next_status not in {"confirmed", "rolled_back", "deprecated"}:
                raise ValidationError(
                    "patch.fact_status must be confirmed, rolled_back, or deprecated",
                    code="invalid_fact_status",
                    status_code=422,
                )
            await self._ctx.require_map(db, novel_id, map_id)
            nid = parse_uuid(novel_id, "novel_id")
            mid = parse_uuid(map_id, "map_id")
            fact_ids = [parse_uuid(fact_id, "fact_id") for fact_id in data.fact_ids]
            existing = await self._fact_repo.get_many(db, fact_ids)
            existing_by_id = {fact.id: fact for fact in existing}
            for raw_fact_id, fact_id in zip(data.fact_ids, fact_ids):
                self._assert_fact_access(
                    existing_by_id.get(fact_id),
                    raw_fact_id,
                    nid,
                    mid,
                )
            updated = await self._fact_repo.update_statuses(db, fact_ids, next_status)
            updated_by_id = {fact.id: fact for fact in updated}
            facts = [
                MapFactResponse.model_validate(updated_by_id[fact_id])
                for fact_id in fact_ids
                if fact_id in updated_by_id
            ]
            return MapBatchActionResponse(
                action=data.action,
                requested_count=len(data.fact_ids),
                updated_count=len(facts),
                facts=facts,
            )

        visibility = data.patch.get("layer_visibility") or {}
        return MapBatchActionResponse(
            action=data.action,
            requested_count=0,
            updated_count=0,
            layer_visibility=visibility,
        )

    async def get_dashboard(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        map_id: str,
        scene_id: str | None = None,
        focus_entity_id: str | None = None,
        focus_item_id: str | None = None,
    ) -> MapDashboardResponse:
        return await MapDashboardMixin.get_dashboard(
            self,
            db,
            novel_id,
            map_id=map_id,
            scene_id=scene_id,
            focus_entity_id=focus_entity_id,
            focus_item_id=focus_item_id,
        )

    async def get_playback(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        map_id: str,
        scene_id: str | None = None,
        focus_entity_id: str | None = None,
        include_candidates: bool = True,
    ) -> MapPlaybackResponse:
        return await MapPlaybackMixin.get_playback(
            self,
            db,
            novel_id,
            map_id=map_id,
            scene_id=scene_id,
            focus_entity_id=focus_entity_id,
            include_candidates=include_candidates,
        )

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
        return await self._timeline.get_timeline(
            db,
            novel_id,
            map_id=map_id,
            from_scene_index=from_scene_index,
            to_scene_index=to_scene_index,
            focus_entity_id=focus_entity_id,
            tracks=tracks,
            include_candidates=include_candidates,
            skip=skip,
            limit=limit,
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
        return await self._timeline.get_state_at(
            db,
            novel_id,
            map_id=map_id,
            scene_index=scene_index,
            focus_entity_id=focus_entity_id,
            tracks=tracks,
            skip=skip,
            limit=limit,
        )
