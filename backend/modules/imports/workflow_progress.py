"""Progress state helpers for deep import workflows."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.redaction import redact_diagnostic
from modules.imports.service_progress_limits import trim_progress_diagnostics
from modules.imports.service_progress_logs import record_progress_event
from modules.imports.workflow_schemas import DeepImportProgress, DeepImportStep

logger = logging.getLogger(__name__)


class DeepImportProgressTracker:
    """Mutates the stable DeepImportProgress result contract."""

    @staticmethod
    def now_iso() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def short_message(message: Any) -> str:
        return redact_diagnostic(message or "", limit=300)

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
        record_progress_event(
            progress,
            "phase_started",
            phase=phase,
            status="running",
            message=f"{phase} started",
            details={
                "operation": progress.current_operation,
                "item": item or {},
                "details": details or {},
            },
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
        event_level = (
            "error"
            if status == "failed"
            else ("warning" if status == "degraded" else "info")
        )
        record_progress_event(
            progress,
            "phase_finished",
            phase=phase,
            status=status,
            level=event_level,
            message=error_message or f"{phase} {status}",
            details={
                "error_kind": error_kind,
                "details": details or {},
            },
        )
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
        trim_progress_diagnostics(progress)
        scene_commit = progress.quality_stats.get("scene_commit") or {}
        phase2 = progress.quality_stats.get("phase2") or {}
        phase3 = progress.quality_stats.get("phase3") or {}
        scene_dedup = (
            (scene_commit.get("dedup") or {}) if isinstance(scene_commit, dict) else {}
        )
        phase2_dedup = phase2.get("phase2_dedup_counts") or {}
        structure_dedup = phase3.get("structure_dedup") or {}
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
            "phase2b_total_scenes": progress.phase2b_total_scenes,
            "phase2b_completed_scenes": max(
                progress.phase2b_completed_scenes,
                int(phase2.get("alias_relation_scenes", 0) or 0),
            ),
            "entity_count": int(phase2.get("total_created", 0) or 0),
            "relation_count": int(phase2.get("total_relations", 0) or 0),
            "alias_count": int(phase2.get("total_aliases", 0) or 0),
            "alias_relation_scenes": int(phase2.get("alias_relation_scenes", 0) or 0),
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
            "phase_artifact_summary": cls.phase_artifact_summary(
                progress.phase_artifacts
            ),
            "phase_error_count": len(progress.phase_errors),
            "dedup_summary": {
                "scene_same_workflow_collapsed": int(
                    scene_dedup.get("same_workflow_collapsed", 0) or 0
                ),
                "entity_auto_merged": int(phase2_dedup.get("auto_merged", 0) or 0),
                "entity_review_suggested": int(
                    phase2_dedup.get("review_suggested", 0) or 0
                ),
                "relation_merged": int(phase2_dedup.get("relation_merged", 0) or 0),
                "structure_suggestions_recorded": int(
                    structure_dedup.get("suggestions_recorded", 0) or 0
                ),
                "structure_auto_applied": int(
                    structure_dedup.get("auto_applied", 0) or 0
                ),
                "structure_skipped_external_asset": int(
                    structure_dedup.get("skipped_external_asset", 0) or 0
                ),
            },
        }

    @classmethod
    def checkpoint_summary(cls, checkpoints: dict[str, Any] | None) -> dict[str, Any]:
        phase2 = (checkpoints or {}).get("phase2")
        scenes = phase2.get("scenes") if isinstance(phase2, dict) else []
        phase2b = (checkpoints or {}).get("phase2b")
        alias_scenes = phase2b.get("scenes") if isinstance(phase2b, dict) else []
        phase2_status_counts = cls._checkpoint_status_counts(
            scenes if isinstance(scenes, list) else []
        )
        phase2b_status_counts = cls._checkpoint_status_counts(
            alias_scenes if isinstance(alias_scenes, list) else []
        )
        return {
            "phase2_scene_checkpoints": len(scenes) if isinstance(scenes, list) else 0,
            "phase2_status_counts": phase2_status_counts,
            "phase2b_scene_checkpoints": len(alias_scenes)
            if isinstance(alias_scenes, list)
            else 0,
            "phase2b_status_counts": phase2b_status_counts,
        }

    @staticmethod
    def _checkpoint_status_counts(items: list[dict[str, Any]]) -> dict[str, int]:
        status_counts: dict[str, int] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
        return status_counts

    @staticmethod
    def phase_artifact_summary(artifacts: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(artifacts, dict):
            return {}
        summary: dict[str, Any] = {}
        for phase, artifact in artifacts.items():
            if not isinstance(artifact, dict):
                continue
            coverage = artifact.get("coverage") or {}
            repair = artifact.get("repair") or {}
            counts = artifact.get("counts") or {}
            summary[str(phase)] = {
                "status": artifact.get("status"),
                "quality_status": artifact.get("quality_status"),
                "coverage_complete": coverage.get("coverage_complete"),
                "missing_chapters": coverage.get("missing_chapters") or [],
                "repair_attempts": repair.get("attempts", 0),
                "repair_failed_units": repair.get("failed_units", 0),
                "counts": counts,
            }
        return summary

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
            **_redact_checkpoint_strings(checkpoints),
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
                **_redact_checkpoint_strings(audit_summary),
            }

    @staticmethod
    def merge_snapshot_health_summary(
        progress: DeepImportProgress,
        phase_result: dict[str, Any],
    ) -> None:
        snapshot_health_summary = phase_result.get("snapshot_health_summary")
        if isinstance(snapshot_health_summary, dict):
            progress.snapshot_health_summary = _redact_checkpoint_strings(
                snapshot_health_summary
            )

    @staticmethod
    async def refresh_snapshot_health_summary(
        db: AsyncSession,
        novel_id: str,
        workflow_id: str | None,
        progress: DeepImportProgress,
    ) -> None:
        if db is None or not workflow_id:
            return
        from modules.evidence.facade import build_snapshot_health_summary

        try:
            progress.snapshot_health_summary = _redact_checkpoint_strings(
                await build_snapshot_health_summary(
                    db,
                    novel_id=novel_id,
                    workflow_id=workflow_id,
                )
            )
        except Exception as exc:
            logger.warning(
                "snapshot health summary refresh failed: %s",
                redact_diagnostic(exc, limit=300),
            )


def _redact_checkpoint_strings(value: Any, *, depth: int = 0) -> Any:
    """Redact credentials in resumable state without changing checkpoint shape."""
    if depth > 12:
        return "<truncated>"
    if isinstance(value, dict):
        return {
            str(key): _redact_checkpoint_strings(item, depth=depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _redact_checkpoint_strings(item, depth=depth + 1) for item in value
        ]
    if isinstance(value, tuple):
        return [
            _redact_checkpoint_strings(item, depth=depth + 1) for item in value
        ]
    if isinstance(value, str):
        return redact_diagnostic(value)
    return value
