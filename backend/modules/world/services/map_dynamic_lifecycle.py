"""Typed lifecycle dependencies for dynamic map services."""

from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.map_repositories import MapFactRepository, MapObservationRepository
from modules.world.map_schemas import MapDashboardQueueItem
from modules.world.services.map_context import MapContext


class MapDynamicLifecycle(Protocol):
    """Dependencies consumed by dynamic map read/write helpers."""

    _ctx: MapContext
    _observation_repo: MapObservationRepository
    _fact_repo: MapFactRepository

    def _assert_spatial_anchor_in_bounds(
        self,
        config: Any,
        spatial_anchor: dict[str, Any],
    ) -> None: ...

    def _assert_observation_in_novel(
        self,
        observation: Any,
        observation_id: str,
        novel_id: Any,
    ) -> None: ...

    def _assert_observation_in_map(
        self,
        observation: Any,
        observation_id: str,
        map_id: Any,
    ) -> None: ...

    def _assert_fact_access(
        self,
        fact: Any,
        fact_id: str,
        novel_id: Any,
        map_id: Any,
    ) -> None: ...

    def _observation_values(self, data: Any, *, map_id: Any) -> dict[str, Any]: ...

    async def _safe_map_uuid(
        self,
        db: AsyncSession,
        novel_id: str,
        raw_map_id: Any,
    ) -> Any: ...

    async def _safe_entity_uuid(
        self,
        db: AsyncSession,
        novel_id: Any,
        raw_entity_id: Any,
    ) -> Any: ...

    def _safe_uuid(self, value: Any) -> Any: ...

    def _normalize_dynamic_type(self, value: Any) -> str: ...

    def _clamp_confidence(self, value: Any) -> float: ...

    def _queue_item_from_observation(self, observation: Any) -> MapDashboardQueueItem: ...

    def _queue_item_from_fact(self, fact: Any) -> MapDashboardQueueItem: ...

    def _filter_queue_for_scene(
        self,
        queue: list[MapDashboardQueueItem],
        scene_id: str,
    ) -> list[MapDashboardQueueItem]: ...

    def _filter_queue_for_item(
        self,
        queue: list[MapDashboardQueueItem],
        focus_item_id: str,
    ) -> list[MapDashboardQueueItem]: ...

    def _filter_queue_for_focus(
        self,
        queue: list[MapDashboardQueueItem],
        focus_entity_id: str,
    ) -> list[MapDashboardQueueItem]: ...

    def _build_dashboard_inspector(
        self,
        queue: list[MapDashboardQueueItem],
        *,
        focus_entity_id: str | None,
    ) -> Any: ...

    def _build_risk_summary(self, queue: list[MapDashboardQueueItem]) -> Any: ...

    def _build_first_visual_layer(self, *args: Any, **kwargs: Any) -> Any: ...

    def _build_batch_groups(self, queue: list[MapDashboardQueueItem]) -> Any: ...
