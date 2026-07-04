from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ValidationError
from modules.world.map_repositories import (
    MapConfigRepository,
    MapFactRepository,
    MapLocationBindingRepository,
    MapMarkerRepository,
    MapObservationRepository,
    MapTerritoryRepository,
)
from modules.world.map_schemas import (
    MapBatchActionRequest,
    MapBatchActionResponse,
    MapDashboardResponse,
    MapFactListResponse,
    MapFactResponse,
    MapFactStatusUpdate,
    MapObservationBatchReviewRequest,
    MapObservationBatchReviewResponse,
    MapObservationCreate,
    MapObservationListResponse,
    MapObservationResponse,
    MapObservationReviewUpdate,
    MapOpenTarget,
    MapPlaybackResponse,
)
from modules.world.repositories import CoreEntityRepository
from modules.world.services.helpers import parse_uuid
from modules.world.services.map_context import MapContext
from modules.world.services.map_dashboard_service import MapDashboardService
from modules.world.services.map_dynamic_helpers import MapDynamicHelperMixin
from modules.world.services.map_fact_service import MapFactService
from modules.world.services.map_observation_service import MapObservationService
from modules.world.services.map_open_target_service import MapOpenTargetService
from modules.world.services.map_playback_service import MapPlaybackService


class MapDynamicFactService(MapDynamicHelperMixin):
    """Compatibility facade for dynamic map facts and observations."""

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
    ) -> None:
        self._observation_repo = observation_repo or MapObservationRepository()
        self._fact_repo = fact_repo or MapFactRepository()
        self._ctx = context or MapContext()
        self._entity_repo = entity_repo or CoreEntityRepository()
        self._map_repo = map_repo or MapConfigRepository()
        self._binding_repo = binding_repo or MapLocationBindingRepository()
        self._marker_repo = marker_repo or MapMarkerRepository()
        self._territory_repo = territory_repo or MapTerritoryRepository()

    @property
    def _observations(self) -> MapObservationService:
        return MapObservationService(self)

    @property
    def _facts(self) -> MapFactService:
        return MapFactService(self)

    @property
    def _dashboard(self) -> MapDashboardService:
        return MapDashboardService(self)

    @property
    def _playback(self) -> MapPlaybackService:
        return MapPlaybackService(self)

    @property
    def _open_targets(self) -> MapOpenTargetService:
        return MapOpenTargetService(self)

    async def _map_id_for_entity_focus(
        self,
        db: AsyncSession,
        novel_id: Any,
        entity_id: Any,
        entity_type: str,
    ) -> str | None:
        return await self._open_targets._map_id_for_entity_focus(
            db,
            novel_id,
            entity_id,
            entity_type,
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
        return await self._observations.list_observations(
                db,
                novel_id,
                map_id=map_id,
                review_state=review_state,
                skip=skip,
                limit=limit,
            )

    async def create_observation(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        map_id: str,
        data: MapObservationCreate,
    ) -> MapObservationResponse:
        return await self._observations.create_observation(
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
        data: MapObservationReviewUpdate,
    ) -> MapObservationResponse:
        return await self._observations.update_observation_review(
                db,
                novel_id,
                map_id=map_id,
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
    ) -> MapObservationResponse:
        return await self._observations.ignore_observation(
                db,
                novel_id,
                map_id=map_id,
                observation_id=observation_id,
            )

    async def confirm_observation(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        map_id: str,
        observation_id: str,
    ) -> MapFactResponse:
        return await self._observations.confirm_observation(
                db,
                novel_id,
                map_id=map_id,
                observation_id=observation_id,
            )

    async def batch_review_observations(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        map_id: str,
        data: MapObservationBatchReviewRequest,
    ) -> MapObservationBatchReviewResponse:
        return await self._observations.batch_review_observations(
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
        return await self._observations.create_observation_from_delta_event(
                db,
                novel_id,
                event=event,
                scene_index=scene_index,
                context_snapshot_id=context_snapshot_id,
                delta_log_id=delta_log_id,
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
        return await self._facts.list_facts(
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
        return await self._facts.update_fact_status(
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
        return await self._open_targets.get_open_target(
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
                    observation_ids=data.observation_ids,
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
        return await self._dashboard.get_dashboard(
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
        return await self._playback.get_playback(
                db,
                novel_id,
                map_id=map_id,
                scene_id=scene_id,
                focus_entity_id=focus_entity_id,
                include_candidates=include_candidates,
            )
