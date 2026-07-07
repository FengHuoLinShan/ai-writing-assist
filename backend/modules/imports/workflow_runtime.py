"""Runtime interface for Deep Import phase runners."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.workflow_schemas import DeepImportProgress, DeepImportStep

ProgressCallback = Callable[[DeepImportProgress, float], Awaitable[None]]
SceneProgressCallback = Callable[..., Awaitable[None]]


class DeepImportWorkflowRuntime(Protocol):
    """Explicit phase-runner runtime surface.

    The concrete runtime is `DeepImportWorkflow`. The private method names are
    preserved for compatibility with existing monkeypatch-based tests while
    phase runner constructors stop accepting an untyped owner object.
    """

    def _start_phase(
        self,
        progress: DeepImportProgress,
        phase: str,
        *,
        item: dict[str, Any] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None: ...

    def _finish_phase(
        self,
        progress: DeepImportProgress,
        phase: str,
        *,
        status: str,
        details: dict[str, Any] | None = None,
        error_kind: str | None = None,
        error_message: str | None = None,
    ) -> None: ...

    def _emit_progress(
        self,
        progress: DeepImportProgress,
        value: float,
        on_progress: ProgressCallback | None,
    ) -> Awaitable[None]: ...

    def _mark_step_completed(
        self,
        progress: DeepImportProgress,
        step: DeepImportStep,
    ) -> None: ...

    def _diagnostic_samples(self, diagnostics: Any) -> Any: ...

    def _update_phase1_batch_counts(
        self,
        progress: DeepImportProgress,
        phase0_result: Any,
        phase1a_result: Any | None = None,
        phase1b_result: Any | None = None,
        *,
        commit_started: bool = False,
        commit_completed: bool = False,
    ) -> None: ...

    def _run_phase0_plan(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
    ) -> Awaitable[Any]: ...

    def _run_phase1a_scene_slicing(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        phase0_result: Any,
        *,
        on_batch_progress: Callable[[int, int, str], Awaitable[None]] | None,
    ) -> Awaitable[Any]: ...

    def _run_phase1b_enrichment(
        self,
        db: AsyncSession,
        novel_id: str,
        candidates: Any,
        *,
        start_chapter: int,
        end_chapter: int,
        chapters: Any,
        on_batch_progress: Callable[[int, int, str], Awaitable[None]] | None,
    ) -> Awaitable[Any]: ...

    def _commit_fused_scenes(
        self,
        db: AsyncSession,
        novel_id: str,
        candidates: Any,
        *,
        workflow_id: str,
    ) -> Awaitable[Any]: ...

    def _extract_entities_by_scene(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        workflow_id: str | None,
        on_scene_progress: SceneProgressCallback | None,
        existing_checkpoints: dict[str, Any] | None,
        start_chapter: int | None,
        end_chapter: int | None,
    ) -> Awaitable[dict[str, Any]]: ...

    def _merge_checkpoints(
        self,
        progress: DeepImportProgress,
        phase_result: dict[str, Any],
    ) -> None: ...

    def _merge_audit_summary(
        self,
        progress: DeepImportProgress,
        phase_result: dict[str, Any],
    ) -> None: ...

    def _merge_snapshot_health_summary(
        self,
        progress: DeepImportProgress,
        phase_result: dict[str, Any],
    ) -> None: ...

    def _refresh_snapshot_health_summary(
        self,
        db: AsyncSession,
        novel_id: str,
        workflow_id: str | None,
        progress: DeepImportProgress,
    ) -> Awaitable[None]: ...

    def _rollback_after_phase_failure(
        self,
        db: AsyncSession,
        phase: str,
        exc: Exception,
    ) -> Awaitable[None]: ...

    def _is_llm_health_required(self) -> bool: ...

    def _check_llm_health(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> Awaitable[Any]: ...

    def _fail_preflight(
        self,
        progress: DeepImportProgress,
        health: Any,
        on_progress: ProgressCallback | None,
    ) -> Awaitable[DeepImportProgress]: ...

    def _scene_chapter_coverage(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
    ) -> Awaitable[dict[str, Any]]: ...

    def _analyze_structure(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        *,
        workflow_id: str | None,
        context_mode: str,
        include_pending_objects: bool,
    ) -> Awaitable[dict[str, Any]]: ...

    def _phase3_timeout_seconds(self) -> float: ...

    def _count_world_objects(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> Awaitable[int]: ...
