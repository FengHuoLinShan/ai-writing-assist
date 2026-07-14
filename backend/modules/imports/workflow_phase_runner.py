"""Shared request interfaces for deep import phase runners."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.workflow_schemas import DeepImportProgress, DeepImportStep

ProgressCallback = Callable[[DeepImportProgress, float], Awaitable[None]]


@dataclass(frozen=True, kw_only=True)
class DeepImportPhaseRequest:
    db: AsyncSession
    novel_id: str
    start_chapter: int
    end_chapter: int
    progress: DeepImportProgress
    workflow_id: str | None = None
    on_progress: ProgressCallback | None = None


@dataclass(frozen=True, kw_only=True)
class SceneFullPipelineRequest(DeepImportPhaseRequest):
    stop_after: DeepImportStep | None = None
    replace_existing: bool = False
    prepared_phase0_result: Any | None = None
    project_profile: dict[str, Any] | None = None
    before_scene_commit: Callable[[], Awaitable[None]] | None = None
    require_provider_no_transaction: bool = False


@dataclass(frozen=True, kw_only=True)
class EntityFullPipelineRequest(DeepImportPhaseRequest):
    total_scenes: int


@dataclass(frozen=True, kw_only=True)
class StructureFullPipelineRequest(DeepImportPhaseRequest):
    total_scenes: int
    context_mode: str = "working"
    include_pending_objects: bool = True


@dataclass(frozen=True, kw_only=True)
class EntityStageRequest(DeepImportPhaseRequest):
    pass


@dataclass(frozen=True, kw_only=True)
class StructureStageRequest(DeepImportPhaseRequest):
    context_mode: str = "working"
    include_pending_objects: bool = True


FullPipelineRequestT = TypeVar("FullPipelineRequestT", contravariant=True)
FullPipelineResultT = TypeVar("FullPipelineResultT", covariant=True)
StageRequestT = TypeVar("StageRequestT", contravariant=True)


class FullPipelinePhaseRunner(
    Protocol[FullPipelineRequestT, FullPipelineResultT],
):
    async def run_full_pipeline(
        self,
        request: FullPipelineRequestT,
    ) -> FullPipelineResultT: ...


class StageOnlyPhaseRunner(Protocol[StageRequestT]):
    async def run_stage(self, request: StageRequestT) -> DeepImportProgress: ...


__all__ = [
    "DeepImportPhaseRequest",
    "EntityFullPipelineRequest",
    "EntityStageRequest",
    "FullPipelinePhaseRunner",
    "ProgressCallback",
    "SceneFullPipelineRequest",
    "StageOnlyPhaseRunner",
    "StructureFullPipelineRequest",
    "StructureStageRequest",
]
