"""Guarded real-LLM acceptance for deep import real samples.

This is intentionally outside the normal test path. It reads the real novel file,
imports every chapter, then executes the same deep_import task path used by the
worker. Enable it only for explicit quality runs:

    RUN_DEEP_IMPORT_5_REAL_LLM=1 pytest \
        modules/imports/tests/test_deep_import_real_llm.py -q

    RUN_DEEP_IMPORT_60_REAL_LLM=1 pytest \
        modules/imports/tests/test_deep_import_real_llm.py -q
"""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from infrastructure.tasks.models import AsyncTask
from modules.imports.orchestrator import DeepImportOrchestrator
from modules.imports.parsers import parse_txt
from modules.imports.services import ImportService
from modules.outline.models import (
    ForeshadowingPlan,
    OutlineArc,
    PlotThread,
    RevealPlan,
    Scene,
)
from modules.project.models import Project
from modules.world.models import CoreEntity

DEFAULT_5_CHAPTER_FILE_PATH = Path(
    "/Users/tywww/Desktop/项目/wirting skill/诡秘之主_第一部 小丑_前5章.txt"
)
DEFAULT_60_CHAPTER_FILE_PATH = Path(
    "/Users/tywww/Desktop/项目/wirting skill/诡秘之主_第一部 小丑_前60章.txt"
)
BACKEND_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LOG_DIR = BACKEND_ROOT / ".test-logs" / "deep_import_real_llm"
OFFICIAL_API_RECOMMENDATION = "推荐使用官方api以保障稳定性与质量"


def _real_llm_enabled() -> bool:
    return (
        os.getenv("RUN_DEEP_IMPORT_5_REAL_LLM") == "1"
        or os.getenv("RUN_DEEP_IMPORT_60_REAL_LLM") == "1"
        or os.getenv("RUN_DEEP_IMPORT_213_REAL_LLM") == "1"
    )


def _expected_chapter_count() -> int:
    configured = os.getenv("DEEP_IMPORT_EXPECTED_CHAPTERS")
    if configured:
        return int(configured)
    if os.getenv("RUN_DEEP_IMPORT_60_REAL_LLM") == "1" or os.getenv(
        "RUN_DEEP_IMPORT_213_REAL_LLM"
    ) == "1":
        return 60
    return 5


def _real_file_path() -> Path:
    configured = os.getenv("DEEP_IMPORT_REAL_FILE")
    if configured:
        return Path(configured).expanduser()
    if _expected_chapter_count() == 60:
        return DEFAULT_60_CHAPTER_FILE_PATH
    return DEFAULT_5_CHAPTER_FILE_PATH


REAL_FILE_PATH = _real_file_path()
EXPECTED_CHAPTER_COUNT = _expected_chapter_count()

real_llm_required = pytest.mark.skipif(
    not _real_llm_enabled(),
    reason=(
        "真实 LLM 深度导入默认跳过；设置 RUN_DEEP_IMPORT_5_REAL_LLM=1 "
        "或 RUN_DEEP_IMPORT_60_REAL_LLM=1 才运行"
    ),
)


def _llm_config_log_payload() -> dict[str, Any]:
    settings = get_settings()
    return {
        "llm_base_url": settings.llm_base_url,
        "llm_model": settings.llm_model,
        "llm_timeout": settings.llm_timeout,
        "llm_retry_max_attempts": settings.llm_retry_max_attempts,
        "llm_retry_base_delay": settings.llm_retry_base_delay,
        "llm_retry_max_delay": settings.llm_retry_max_delay,
        "llm_health_required": settings.llm_health_required,
    }


def _chapter_title(chapter: dict[str, Any]) -> str:
    return str(chapter.get("title") or "")


def _expected_phase_shape() -> dict[str, Any]:
    from modules.imports.scene_fusion import build_phase1b_windows
    from modules.imports.scene_prefetch import build_phase0_prefetch_batches

    phase0_batches = build_phase0_prefetch_batches(1, EXPECTED_CHAPTER_COUNT)
    phase1b_windows = build_phase1b_windows(
        start_chapter=1,
        end_chapter=EXPECTED_CHAPTER_COUNT,
    )
    return {
        "phase0_total_batches": len(phase0_batches),
        "phase1a_total_batches": len(phase0_batches),
        "phase1b_total_windows": len(phase1b_windows),
        "phase0_batches": [batch.model_dump(mode="json") for batch in phase0_batches],
        "phase1b_windows": [
            window.model_dump(mode="json") for window in phase1b_windows
        ],
    }


class PersistentAcceptanceLogger:
    """Append-only JSONL progress log that survives Ctrl-C and pytest teardown."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.started_at = time.monotonic()
        self.latest_path = self.path.parent / "latest.json"
        self.latest_payload: dict[str, Any] = {
            "log_path": str(self.path),
            "started_at": datetime.now(UTC).isoformat(),
            "status": "running",
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._write_latest()

    @classmethod
    def from_env(cls) -> PersistentAcceptanceLogger:
        configured = (
            os.getenv("DEEP_IMPORT_LOG_PATH")
            or os.getenv("DEEP_IMPORT_5_LOG_PATH")
            or os.getenv("DEEP_IMPORT_60_LOG_PATH")
            or os.getenv("DEEP_IMPORT_213_LOG_PATH")
        )
        if configured:
            path = Path(configured).expanduser()
            if not path.is_absolute():
                path = BACKEND_ROOT / path
        else:
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            path = DEFAULT_LOG_DIR / (
                f"deep_import_{EXPECTED_CHAPTER_COUNT}_{stamp}.jsonl"
            )
        return cls(path)

    def write(self, event: str, **payload: Any) -> None:
        record = {
            "ts": datetime.now(UTC).isoformat(),
            "elapsed_s": round(time.monotonic() - self.started_at, 2),
            "event": event,
            **payload,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            handle.flush()
        self._update_latest(event, record)

    def set_context(self, **payload: Any) -> None:
        self.latest_payload.update({k: v for k, v in payload.items() if v is not None})
        self._write_latest()

    def _update_latest(self, event: str, record: dict[str, Any]) -> None:
        if event == "exception":
            status = (
                "interrupted"
                if record.get("error_type") == "KeyboardInterrupt"
                else "failed"
            )
        elif event == "acceptance_checks" and record.get("issues"):
            status = "failed"
        elif event == "final_summary":
            status = "complete" if not record.get("issues") else "failed"
        else:
            status = self.latest_payload.get("status", "running")
        self.latest_payload.update(
            {
                "status": status,
                "last_event": event,
                "last_phase": record.get("current_phase")
                or record.get("phase")
                or self.latest_payload.get("last_phase"),
                "last_elapsed_s": record.get("elapsed_s"),
                "updated_at": record.get("ts"),
            }
        )
        for key in ("project_id", "task_id", "quality_status", "last_error"):
            if record.get(key) is not None:
                self.latest_payload[key] = record[key]
        self._write_latest()

    def _write_latest(self) -> None:
        self.latest_path.write_text(
            json.dumps(self.latest_payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )


async def _count_by_novel(
    db: AsyncSession,
    model: type,
    novel_id: str,
) -> int:
    result = await db.execute(
        select(func.count(model.id)).where(model.novel_id == uuid.UUID(novel_id))
    )
    return int(result.scalar() or 0)


async def _group_count_by_novel(
    db: AsyncSession,
    model: type,
    novel_id: str,
    column,
) -> dict[str, int]:
    result = await db.execute(
        select(column, func.count(model.id))
        .where(model.novel_id == uuid.UUID(novel_id))
        .group_by(column)
    )
    return {str(key or "unknown"): int(count or 0) for key, count in result.all()}


def _progress_log_payload(progress, progress_value: float) -> dict[str, Any]:
    return {
        "progress": round(progress_value, 4),
        "phase": progress.phase,
        "current_step": progress.current_step.value if progress.current_step else None,
        "current_phase": progress.current_phase,
        "current_operation": progress.current_operation,
        "current_round": progress.current_round,
        "current_chapter_range": progress.current_chapter_range,
        "current_chapter": progress.current_chapter,
        "current_scene_candidate_id": progress.current_scene_candidate_id,
        "current_window": progress.current_window,
        "phase1_completed_batches": progress.phase1_completed_batches,
        "phase1_total_batches": progress.phase1_total_batches,
        "phase2_completed_scenes": progress.phase2_completed_scenes,
        "phase2_total_scenes": progress.phase2_total_scenes,
        "completed_steps": progress.completed_steps,
        "current_item": progress.current_item,
        "phase_timeline": progress.phase_timeline,
        "diagnostic_counts": progress.diagnostic_counts,
        "last_error": progress.last_error,
        "quality_status": progress.quality_status,
        "degraded": progress.degraded,
        "degraded_reason": progress.degraded_reason,
        "phase1a_fallback": progress.phase1a_fallback,
        "message": progress.message,
        "quality_stats": progress.quality_stats,
        "phase_errors": progress.phase_errors[-5:],
        "checkpoint_summary": _checkpoint_summary(progress.checkpoints),
    }


def _checkpoint_summary(checkpoints: dict[str, Any] | None) -> dict[str, Any]:
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


def _result_log_payload(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "phase": result.get("phase"),
        "current_step": result.get("current_step"),
        "completed_steps": result.get("completed_steps"),
        "current_phase": result.get("current_phase"),
        "current_operation": result.get("current_operation"),
        "quality_status": result.get("quality_status"),
        "degraded": result.get("degraded"),
        "degraded_reason": result.get("degraded_reason"),
        "phase1a_fallback": result.get("phase1a_fallback"),
        "current_item": result.get("current_item"),
        "phase_timeline": result.get("phase_timeline"),
        "diagnostic_counts": result.get("diagnostic_counts"),
        "last_error": result.get("last_error"),
        "message": result.get("message"),
        "quality_stats": result.get("quality_stats"),
        "phase_errors": result.get("phase_errors"),
        "snapshot_health_summary": result.get("snapshot_health_summary"),
        "audit_summary": result.get("audit_summary"),
        "checkpoint_summary": _checkpoint_summary(result.get("checkpoints")),
    }


def _phase_event_name(status: str) -> str:
    if status == "running":
        return "phase_started"
    if status == "failed":
        return "phase_failed"
    return "phase_completed"


def _record_acceptance_check(
    checks: list[dict[str, Any]],
    issues: list[str],
    *,
    name: str,
    ok: bool,
    expected: Any,
    actual: Any,
    message: str,
) -> None:
    checks.append(
        {
            "name": name,
            "status": "passed" if ok else "failed",
            "expected": expected,
            "actual": actual,
            "message": message,
        }
    )
    if not ok:
        issues.append(message)


async def _count_acceptance_outputs(
    db: AsyncSession,
    project_id: uuid.UUID,
) -> dict[str, Any]:
    novel_id = str(project_id)
    scene_count = await _count_by_novel(db, Scene, novel_id)
    entity_count = await _count_by_novel(db, CoreEntity, novel_id)
    structure_counts = {
        "threads": await _count_by_novel(db, PlotThread, novel_id),
        "arcs": await _count_by_novel(db, OutlineArc, novel_id),
        "foreshadowing": await _count_by_novel(db, ForeshadowingPlan, novel_id),
        "reveals": await _count_by_novel(db, RevealPlan, novel_id),
    }
    needs_review_result = await db.execute(
        select(func.count(Scene.id)).where(
            Scene.novel_id == project_id,
            Scene.structure_meta["needs_review"].as_boolean().is_(True),
        )
    )
    return {
        "scene_count": scene_count,
        "entity_count": entity_count,
        "structure_counts": structure_counts,
        "entity_type_counts": await _group_count_by_novel(
            db,
            CoreEntity,
            novel_id,
            CoreEntity.entity_type,
        ),
        "scene_status_counts": await _group_count_by_novel(
            db,
            Scene,
            novel_id,
            Scene.status,
        ),
        "structure_status_counts": {
            "threads": await _group_count_by_novel(
                db,
                PlotThread,
                novel_id,
                PlotThread.status,
            ),
            "arcs": await _group_count_by_novel(
                db,
                OutlineArc,
                novel_id,
                OutlineArc.status,
            ),
            "foreshadowing": await _group_count_by_novel(
                db,
                ForeshadowingPlan,
                novel_id,
                ForeshadowingPlan.status,
            ),
            "reveals": await _group_count_by_novel(
                db,
                RevealPlan,
                novel_id,
                RevealPlan.status,
            ),
        },
        "needs_review_scene_count": int(needs_review_result.scalar() or 0),
    }


@pytest.mark.asyncio
@pytest.mark.real_llm
@real_llm_required
async def test_deep_import_real_llm_acceptance(
    db_session: AsyncSession,
) -> None:
    log = PersistentAcceptanceLogger.from_env()
    expected_phase_shape = _expected_phase_shape()
    log.write(
        "test_started",
        log_path=str(log.path),
        file_path=str(REAL_FILE_PATH),
        expected_chapter_count=EXPECTED_CHAPTER_COUNT,
        expected_phase_shape=expected_phase_shape,
        llm_config=_llm_config_log_payload(),
    )
    assert REAL_FILE_PATH.exists(), f"真实文件不存在: {REAL_FILE_PATH}"
    file_bytes = REAL_FILE_PATH.read_bytes()
    chapters = parse_txt(file_bytes)
    assert len(chapters) == EXPECTED_CHAPTER_COUNT
    if EXPECTED_CHAPTER_COUNT == 5:
        assert _chapter_title(chapters[0]) == "第一章 绯红"
        assert _chapter_title(chapters[-1]) == "第五章 仪式"
    assert all(chapter.get("content") for chapter in chapters)
    log.write(
        "file_parsed",
        chapter_count=len(chapters),
        bytes=len(file_bytes),
        first_title=_chapter_title(chapters[0]) if chapters else None,
        last_title=_chapter_title(chapters[-1]) if chapters else None,
        nonempty_content_count=sum(1 for chapter in chapters if chapter.get("content")),
    )

    project_id = uuid.uuid4()
    db_session.add(
        Project(
            id=project_id,
            title=f"诡秘之主 第一部 前{EXPECTED_CHAPTER_COUNT}章深度导入验收",
            genre="西方奇幻",
            tone="维多利亚风格、黑暗",
            language="zh",
            target_length="novel",
            current_stage="writing",
        )
    )
    await db_session.flush()

    import_result = await ImportService().upload_and_import(
        db_session,
        str(project_id),
        REAL_FILE_PATH.name,
        file_bytes,
    )
    log.write(
        "chapters_imported",
        project_id=str(project_id),
        total_chapters=import_result.total_chapters,
        imported_chapters=import_result.imported_chapters,
    )
    assert import_result.total_chapters == EXPECTED_CHAPTER_COUNT
    assert import_result.imported_chapters == EXPECTED_CHAPTER_COUNT

    task = AsyncTask(
        id=uuid.uuid4(),
        task_type="deep_import",
        status="pending",
        meta={
            "novel_id": str(project_id),
            "start_chapter": 1,
            "end_chapter": EXPECTED_CHAPTER_COUNT,
            "context_mode": "working",
            "include_pending_objects": True,
        },
        progress=0.0,
    )
    db_session.add(task)
    await db_session.flush()
    log.set_context(project_id=str(project_id), task_id=str(task.id))
    log.write(
        "task_created",
        task_id=str(task.id),
        project_id=str(project_id),
        meta=task.meta,
    )

    emitted_phase_events: set[tuple[str, str]] = set()

    async def _observe_progress(progress, progress_value: float, _task) -> None:
        payload = _progress_log_payload(progress, progress_value)
        log.write(
            "progress",
            task_id=str(_task.id),
            project_id=str(project_id),
            **payload,
        )
        for item in progress.phase_timeline:
            phase_name = str(item.get("phase") or "")
            status = str(item.get("status") or "unknown")
            key = (phase_name, status)
            if not phase_name or key in emitted_phase_events:
                continue
            emitted_phase_events.add(key)
            log.write(
                _phase_event_name(status),
                task_id=str(_task.id),
                project_id=str(project_id),
                **item,
            )
        log.write(
            "diagnostic_snapshot",
            task_id=str(_task.id),
            project_id=str(project_id),
            current_phase=progress.current_phase,
            current_item=progress.current_item,
            diagnostic_counts=progress.diagnostic_counts,
            last_error=progress.last_error,
            phase_errors=progress.phase_errors[-5:],
            checkpoint_summary=_checkpoint_summary(progress.checkpoints),
            snapshot_health_summary=progress.snapshot_health_summary,
        )

    orchestrator = DeepImportOrchestrator(progress_observer=_observe_progress)

    try:
        result = await orchestrator.run_task(db_session, task)
    except BaseException as exc:
        log.write(
            "exception",
            error_type=exc.__class__.__name__,
            error_message=str(exc),
            project_id=str(project_id),
            task_id=str(task.id),
        )
        try:
            log.write(
                "interrupted_counts",
                **await _count_acceptance_outputs(db_session, project_id),
            )
        except Exception as count_exc:
            log.write(
                "interrupted_count_failed",
                error_type=count_exc.__class__.__name__,
                error_message=str(count_exc),
            )
        raise

    log.write("result", **_result_log_payload(result))
    output_counts = await _count_acceptance_outputs(db_session, project_id)
    log.write("output_counts", **output_counts)

    quality_stats = result.get("quality_stats") or {}
    assert {"phase0", "phase1a", "phase1b"}.issubset(quality_stats)
    for phase in ("phase0", "phase1a", "phase1b"):
        assert "final_422_rate" in quality_stats[phase]
        assert "timeout" in quality_stats[phase] or phase == "phase1b"
        assert "schema_error" in quality_stats[phase] or phase == "phase1b"

    acceptance_issues: list[str] = []
    acceptance_rule_results: list[dict[str, Any]] = []
    if EXPECTED_CHAPTER_COUNT == 5:
        expected_phase_checks = {
            "phase0_total_batches": (
                quality_stats["phase0"].get("total_batches"),
                expected_phase_shape["phase0_total_batches"],
            ),
            "phase1a_total_batches": (
                quality_stats["phase1a"].get("total_batches"),
                expected_phase_shape["phase1a_total_batches"],
            ),
            "phase1b_total_windows": (
                quality_stats["phase1b"].get("total_windows"),
                expected_phase_shape["phase1b_total_windows"],
            ),
        }
        for check_name, (actual, expected) in expected_phase_checks.items():
            _record_acceptance_check(
                acceptance_rule_results,
                acceptance_issues,
                name=check_name,
                ok=actual == expected,
                expected=expected,
                actual=actual,
                message=f"{check_name} expected {expected}, got {actual}",
            )

    if result["phase"] == "failed":
        _record_acceptance_check(
            acceptance_rule_results,
            acceptance_issues,
            name="failed_phase_allowed",
            ok=result.get("current_phase") in {"phase0_prefetch", "phase1a_reinforce"},
            expected=["phase0_prefetch", "phase1a_reinforce"],
            actual=result.get("current_phase"),
            message=f"unexpected failed phase: {result.get('current_phase')}",
        )
        _record_acceptance_check(
            acceptance_rule_results,
            acceptance_issues,
            name="failed_reason_is_422_threshold",
            ok="422_rate_exceeded" in (result.get("degraded_reason") or ""),
            expected="degraded_reason contains 422_rate_exceeded",
            actual=result.get("degraded_reason"),
            message=(
                "failed without 422 threshold reason: "
                f"{result.get('degraded_reason')}"
            ),
        )
        _record_acceptance_check(
            acceptance_rule_results,
            acceptance_issues,
            name="official_api_recommendation_present",
            ok=OFFICIAL_API_RECOMMENDATION in (result.get("message") or ""),
            expected=OFFICIAL_API_RECOMMENDATION,
            actual=result.get("message"),
            message="failed task missed official API recommendation",
        )
        log.write(
            "acceptance_checks",
            checks=acceptance_rule_results,
            issues=acceptance_issues,
        )
        log.write(
            "final_summary",
            project_id=str(project_id),
            task_id=str(task.id),
            issues=acceptance_issues,
            output_counts=output_counts,
            result=_result_log_payload(result),
        )
        if acceptance_issues:
            pytest.fail("\n".join(acceptance_issues))
        return

    _record_acceptance_check(
        acceptance_rule_results,
        acceptance_issues,
        name="task_phase_done",
        ok=result["phase"] == "done",
        expected="done",
        actual=result["phase"],
        message=f"task phase expected done, got {result['phase']}",
    )
    completed_steps = result.get("completed_steps") or []
    _record_acceptance_check(
        acceptance_rule_results,
        acceptance_issues,
        name="completed_steps_start",
        ok=completed_steps[:2] == ["scene_segmentation", "entity_extraction"],
        expected=["scene_segmentation", "entity_extraction"],
        actual=completed_steps[:2],
        message=f"completed steps start mismatch: {completed_steps[:2]}",
    )
    if "structure_analysis" not in completed_steps:
        structure_errors = [
            error
            for error in (result.get("phase_errors") or [])
            if error.get("phase") == "structure_analysis"
        ]
        assert result.get("quality_status") == "partial"
        assert any(error.get("error_kind") == "timeout" for error in structure_errors)

    scene_count = output_counts["scene_count"]
    entity_count = output_counts["entity_count"]
    structure_counts = output_counts["structure_counts"]
    checkpoint_summary = _checkpoint_summary(result.get("checkpoints"))
    phase_errors = result.get("phase_errors") or []

    _record_acceptance_check(
        acceptance_rule_results,
        acceptance_issues,
        name="scene_count_positive",
        ok=scene_count > 0,
        expected="> 0",
        actual=scene_count,
        message=f"scene_count expected > 0, got {scene_count}",
    )
    if EXPECTED_CHAPTER_COUNT == 7 and scene_count < 9:
        _record_acceptance_check(
            acceptance_rule_results,
            acceptance_issues,
            name="scene_count_1_7_threshold",
            ok=scene_count >= 9,
            expected=">= 9",
            actual=scene_count,
            message=(
                "scene_count expected >= 9 for 1-7 chapter acceptance, "
                f"got {scene_count}"
            ),
        )
    entity_has_diagnostics = bool(
        phase_errors or checkpoint_summary.get("phase2_scene_checkpoints")
    )
    _record_acceptance_check(
        acceptance_rule_results,
        acceptance_issues,
        name="entity_count_or_diagnostics",
        ok=entity_count > 0 or entity_has_diagnostics,
        expected="entity_count > 0 or phase diagnostics present",
        actual={
            "entity_count": entity_count,
            "has_phase_errors": bool(phase_errors),
            "phase2_scene_checkpoints": checkpoint_summary.get(
                "phase2_scene_checkpoints",
                0,
            ),
        },
        message=(
            "entity_count expected > 0, got 0 without phase_errors or "
            "phase2 checkpoints"
        ),
    )
    if EXPECTED_CHAPTER_COUNT == 7 and entity_count < 18:
        _record_acceptance_check(
            acceptance_rule_results,
            acceptance_issues,
            name="entity_count_1_7_threshold",
            ok=entity_count >= 18,
            expected=">= 18",
            actual=entity_count,
            message=(
                "entity_count expected >= 18 for 1-7 chapter acceptance, "
                f"got {entity_count}"
            ),
        )
    _record_acceptance_check(
        acceptance_rule_results,
        acceptance_issues,
        name="structure_any_output",
        ok=any(count > 0 for count in structure_counts.values()),
        expected="at least one structure count > 0",
        actual=structure_counts,
        message=f"at least one structure output expected, got {structure_counts}",
    )
    if EXPECTED_CHAPTER_COUNT == 7 and sum(structure_counts.values()) < 8:
        _record_acceptance_check(
            acceptance_rule_results,
            acceptance_issues,
            name="structure_count_1_7_total",
            ok=sum(structure_counts.values()) >= 8,
            expected="sum >= 8",
            actual=structure_counts,
            message=(
                "structure outputs expected >= 8 for 1-7 chapter acceptance, "
                f"got {structure_counts}"
            ),
        )
    if EXPECTED_CHAPTER_COUNT == 7:
        for structure_name, count in structure_counts.items():
            if count < 4:
                _record_acceptance_check(
                    acceptance_rule_results,
                    acceptance_issues,
                    name=f"{structure_name}_1_7_threshold",
                    ok=count >= 4,
                    expected=">= 4",
                    actual=count,
                    message=(
                        f"{structure_name} expected >= 4 for 1-7 chapter "
                        f"acceptance, got {count}"
                    ),
                )
    if EXPECTED_CHAPTER_COUNT == 5:
        _record_acceptance_check(
            acceptance_rule_results,
            acceptance_issues,
            name="phase2_checkpoint_present_5_chapter",
            ok=bool(checkpoint_summary.get("phase2_scene_checkpoints")),
            expected="phase2_scene_checkpoints > 0",
            actual=checkpoint_summary,
            message="phase2 expected at least one scene checkpoint, got 0",
        )
    _record_acceptance_check(
        acceptance_rule_results,
        acceptance_issues,
        name="snapshot_or_audit_present",
        ok=bool(result.get("snapshot_health_summary") or result.get("audit_summary")),
        expected="snapshot_health_summary or audit_summary present",
        actual={
            "has_snapshot_health_summary": bool(result.get("snapshot_health_summary")),
            "has_audit_summary": bool(result.get("audit_summary")),
        },
        message="snapshot_health_summary or audit_summary is required",
    )

    zero_output_quality_ok = not (
        scene_count <= 0 or entity_count <= 0
    ) or result.get("quality_status") in {"partial", "failed"}
    _record_acceptance_check(
        acceptance_rule_results,
        acceptance_issues,
        name="zero_output_quality_status",
        ok=zero_output_quality_ok,
        expected="partial/failed when Scene or entity output is 0",
        actual=result.get("quality_status"),
        message=(
            "quality_status should be partial/failed when Scene or entity output is 0; "
            f"got {result.get('quality_status')}"
        ),
    )

    assert output_counts["needs_review_scene_count"] >= 0
    log.write(
        "acceptance_checks",
        checks=acceptance_rule_results,
        issues=acceptance_issues,
    )
    log.write(
        "final_summary",
        project_id=str(project_id),
        task_id=str(task.id),
        issues=acceptance_issues,
        output_counts=output_counts,
        result=_result_log_payload(result),
    )
    if acceptance_issues:
        pytest.fail("\n".join(acceptance_issues))
