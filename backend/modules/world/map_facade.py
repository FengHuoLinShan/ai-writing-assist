"""World map facade.

跨模块调用地图动态能力时只从这里进入；具体编排仍由 world/map 拥有。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.contracts import (
    ConfirmedMapFactContract,
    ConfirmedMapFactReplayContract,
    MapObservationCandidateBatchResult,
    MapObservationCandidateInput,
)
from modules.world.services.map_service import MapDynamicFactService
from shared.utils import parse_uuid

_map_dynamic_facts = MapDynamicFactService()


async def get_confirmed_map_facts_through_scene(
    db: AsyncSession,
    novel_id: str,
    scene_index: int,
) -> ConfirmedMapFactReplayContract:
    """Read confirmed facts after revalidating current outline Scene order."""
    from modules.outline.facade import get_scenes_by_novel
    from modules.world.map_repositories import MapFactRepository

    facts, undated_count = await MapFactRepository().list_project_through_scene(
        db,
        parse_uuid(novel_id, "novel_id"),
        to_scene_index=scene_index,
    )
    if len(facts) > 20000:
        raise ValueError("confirmed map fact replay exceeds 20000 rows")
    active_scenes = await get_scenes_by_novel(
        db,
        novel_id,
        status_filter=["canonical", "draft"],
    )
    current_scene_index = {
        str(scene["id"]): int(scene["scene_index"])
        for scene in active_scenes
    }
    replayable: list[tuple[Any, int]] = []
    for item in facts:
        current_index = current_scene_index.get(str(item.scene_id))
        if current_index is None:
            continue
        if current_index <= scene_index:
            replayable.append((item, current_index))
    replayable.sort(
        key=lambda pair: (
            pair[1],
            pair[0].source_chapter_index is None,
            pair[0].source_chapter_index or 0,
            pair[0].created_at,
            str(pair[0].id),
        )
    )
    return ConfirmedMapFactReplayContract(
        facts=[
            ConfirmedMapFactContract(
                id=str(item.id),
                scene_id=str(item.scene_id),
                scene_index=current_index,
                dynamic_type=item.dynamic_type,
                target_entity_id=(
                    str(item.target_entity_id) if item.target_entity_id else None
                ),
                target_name=item.target_name,
                map_id=str(item.map_id) if item.map_id else None,
                value_json=dict(item.value_json or {}),
                spatial_anchor=dict(item.spatial_anchor or {}),
                time_anchor=dict(item.time_anchor or {}),
                evidence_text=item.evidence_text,
            )
            for item, current_index in replayable
        ],
        undated_count=undated_count,
    )


async def create_map_observation_candidates(
    db: AsyncSession,
    novel_id: str,
    *,
    candidates: list[MapObservationCandidateInput],
) -> MapObservationCandidateBatchResult:
    """Persist a fail-closed batch of typed, workflow-owned map candidates."""
    return await _map_dynamic_facts.create_observation_candidates(
        db,
        novel_id,
        candidates=candidates,
    )


async def create_map_observation_from_delta_event(
    db: AsyncSession,
    novel_id: str,
    *,
    event: dict[str, Any],
    scene_index: int,
    context_snapshot_id: str | None = None,
    delta_log_id: str | None = None,
) -> dict[str, Any]:
    """将通用 delta_event 归一为地图观察候选。"""
    observation = await _map_dynamic_facts.create_observation_from_delta_event(
        db,
        novel_id,
        event=event,
        scene_index=scene_index,
        context_snapshot_id=context_snapshot_id,
        delta_log_id=delta_log_id,
    )
    return observation.model_dump()


async def summarize_scene_map_for_writing(
    db: AsyncSession,
    novel_id: str,
    scene_id: str,
    *,
    include_candidates: bool = False,
) -> dict[str, Any]:
    """Return a Scene map summary for writing conflict checks.

    V1 checks default to canonical map context. include_candidates lets writing
    conflict checks opt into candidate/conflicted map observation evidence.
    """
    from modules.world.services.map.map_scene_summary import MapSceneSummaryService

    summary = await MapSceneSummaryService().summarize(
        db,
        novel_id,
        scene_id,
        include_candidates=include_candidates,
    )
    return summary.model_dump()


async def count_deep_import_map_observations_by_workflow(
    db: AsyncSession,
    novel_id: str,
    workflow_id: str,
) -> int:
    """Count unconfirmed map observations for cleanup reporting only."""
    return await _map_dynamic_facts.count_deep_import_observations_by_workflow(
        db,
        novel_id,
        workflow_id,
    )


async def rollback_deep_import_map_observations_by_workflow(
    db: AsyncSession,
    novel_id: str,
    workflow_id: str,
) -> int:
    """Move workflow-owned pending observations to history and retain provenance."""
    return await _map_dynamic_facts.rollback_deep_import_observations_by_workflow(
        db,
        novel_id,
        workflow_id,
    )
