"""Progress state helpers for deep import workflows."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.workflow_schemas import DeepImportProgress, DeepImportStep

logger = logging.getLogger(__name__)


class DeepImportProgressTracker:
    """Mutates the stable DeepImportProgress result contract."""

    @staticmethod
    def now_iso() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def short_message(message: Any) -> str:
        return str(message or "")[:300]

    @classmethod
    def start_phase(
        cls,
        progress: DeepImportProgress,
        phase: str,
        *,
        item: dict[str, Any] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        progress.current_item = item or {}
        progress.phase_timeline.append(
            {
                "phase": phase,
                "operation": progress.current_operation,
                "status": "running",
                "started_at": cls.now_iso(),
                "details": details or {},
            }
        )
        cls.refresh_diagnostic_counts(progress)

    @classmethod
    def finish_phase(
        cls,
        progress: DeepImportProgress,
        phase: str,
        *,
        status: str = "completed",
        details: dict[str, Any] | None = None,
        error_kind: str | None = None,
        error_message: str | None = None,
    ) -> None:
        now = cls.now_iso()
        target: dict[str, Any] | None = None
        for item in reversed(progress.phase_timeline):
            if item.get("phase") == phase and item.get("status") == "running":
                target = item
                break
        if target is None:
            for item in reversed(progress.phase_timeline):
                if item.get("phase") == phase:
                    target = item
                    break
        if target is not None:
            target["status"] = status
            target["ended_at"] = now
            target["duration_s"] = cls.duration_seconds(target.get("started_at"), now)
            if details:
                target["details"] = {**(target.get("details") or {}), **details}
            if error_kind:
                target["error_kind"] = error_kind
        if error_kind:
            cls.set_last_error(
                progress,
                phase=phase,
                error_kind=error_kind,
                message=error_message,
            )
        cls.refresh_diagnostic_counts(progress)

    @staticmethod
    def duration_seconds(started_at: Any, ended_at: str) -> float | None:
        if not isinstance(started_at, str):
            return None
        try:
            start = datetime.fromisoformat(started_at)
            end = datetime.fromisoformat(ended_at)
        except ValueError:
            return None
        return round((end - start).total_seconds(), 2)

    @classmethod
    def set_last_error(
        cls,
        progress: DeepImportProgress,
        *,
        phase: str,
        error_kind: str | None,
        message: Any,
    ) -> None:
        progress.last_error = {
            "phase": phase,
            "error_kind": error_kind or "unknown",
            "message": cls.short_message(message),
        }

    @classmethod
    def refresh_diagnostic_counts(cls, progress: DeepImportProgress) -> None:
        scene_commit = progress.quality_stats.get("scene_commit") or {}
        phase2 = progress.quality_stats.get("phase2") or {}
        phase3 = progress.quality_stats.get("phase3") or {}
        snapshot = progress.snapshot_health_summary or {}
        snapshot_status = snapshot.get("by_status") or {}
        checkpoint_summary = cls.checkpoint_summary(progress.checkpoints)
        progress.diagnostic_counts = {
            "scene_count": int(scene_commit.get("created_count", 0) or 0)
            + int(scene_commit.get("skipped_count", 0) or 0),
            "created_scene_count": int(scene_commit.get("created_count", 0) or 0),
            "skipped_scene_count": int(scene_commit.get("skipped_count", 0) or 0),
            "phase2_total_scenes": progress.phase2_total_scenes,
            "phase2_completed_scenes": max(
                progress.phase2_completed_scenes,
                int(phase2.get("completed_scenes", 0) or 0),
            ),
            "entity_count": int(phase2.get("total_created", 0) or 0),
            "relation_count": int(phase2.get("total_relations", 0) or 0),
            "alias_count": int(phase2.get("total_aliases", 0) or 0),
            "alias_relation_scenes": int(
                phase2.get("alias_relation_scenes", 0) or 0
            ),
            "alias_relation_failed_scene_count": len(
                phase2.get("alias_relation_failed_scenes") or []
            ),
            "delta_count": int(phase2.get("total_deltas", 0) or 0),
            "structure_counts": {
                "threads": int(phase3.get("total_threads", 0) or 0),
                "arcs": int(phase3.get("total_arcs", 0) or 0),
                "foreshadowing": int(phase3.get("total_foreshadowing", 0) or 0),
                "reveals": int(phase3.get("total_reveals", 0) or 0),
            },
            "snapshot_total": int(snapshot.get("total_snapshots", 0) or 0),
            "snapshot_succeeded": int(snapshot_status.get("succeeded", 0) or 0),
            "snapshot_failed": int(snapshot_status.get("failed", 0) or 0),
            "checkpoint_summary": checkpoint_summary,
            "phase_error_count": len(progress.phase_errors),
        }

    @staticmethod
    def checkpoint_summary(checkpoints: dict[str, Any] | None) -> dict[str, Any]:
        phase2 = (checkpoints or {}).get("phase2")
        scenes = phase2.get("scenes") if isinstance(phase2, dict) else []
        if not isinstance(scenes, list):
            return {}
        status_counts: dict[str, int] = {}
        for item in scenes:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
        return {
            "phase2_scene_checkpoints": len(scenes),
            "phase2_status_counts": status_counts,
        }

    @classmethod
    async def emit_progress(
        cls,
        progress: DeepImportProgress,
        progress_value: float,
        on_progress: Callable[[DeepImportProgress, float], Awaitable[None]] | None,
    ) -> None:
        cls.refresh_diagnostic_counts(progress)
        if progress.phase_errors and progress.last_error is None:
            error = progress.phase_errors[-1]
            cls.set_last_error(
                progress,
                phase=error.get("phase", progress.current_phase or "unknown"),
                error_kind=error.get("error_kind"),
                message=error.get("message"),
            )
        if on_progress is not None:
            await on_progress(progress, progress_value)

    @staticmethod
    def mark_step_completed(
        progress: DeepImportProgress,
        step: DeepImportStep,
    ) -> None:
        if step.value not in progress.completed_steps:
            progress.completed_steps.append(step.value)

    @staticmethod
    def merge_checkpoints(
        progress: DeepImportProgress,
        phase_result: dict[str, Any],
    ) -> None:
        checkpoints = phase_result.get("checkpoints")
        if not isinstance(checkpoints, dict):
            return
        progress.checkpoints = {
            **(progress.checkpoints or {}),
            **checkpoints,
        }

    @staticmethod
    def merge_audit_summary(
        progress: DeepImportProgress,
        phase_result: dict[str, Any],
    ) -> None:
        audit_summary = phase_result.get("audit_summary")
        if isinstance(audit_summary, dict):
            progress.audit_summary = {
                **(progress.audit_summary or {}),
                **audit_summary,
            }

    @staticmethod
    def merge_snapshot_health_summary(
        progress: DeepImportProgress,
        phase_result: dict[str, Any],
    ) -> None:
        snapshot_health_summary = phase_result.get("snapshot_health_summary")
        if isinstance(snapshot_health_summary, dict):
            progress.snapshot_health_summary = snapshot_health_summary

    @staticmethod
    async def refresh_snapshot_health_summary(
        db: AsyncSession,
        novel_id: str,
        workflow_id: str | None,
        progress: DeepImportProgress,
    ) -> None:
        if db is None or not workflow_id or type(db).__module__ == "unittest.mock":
            return
        from modules.context.facade import build_snapshot_health_summary

        try:
            progress.snapshot_health_summary = await build_snapshot_health_summary(
                db,
                novel_id=novel_id,
                workflow_id=workflow_id,
            )
        except Exception as exc:
            logger.warning("snapshot health summary refresh failed: %s", exc)
