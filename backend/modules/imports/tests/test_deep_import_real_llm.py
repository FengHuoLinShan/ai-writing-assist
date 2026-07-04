"""Guarded real-LLM acceptance for deep import real samples.

This is intentionally outside the normal test path. It reads the real novel file,
imports every chapter, then executes the same deep_import task path used by the
worker. Enable it only for explicit quality runs:

    RUN_DEEP_IMPORT_5_REAL_LLM=1 pytest \
        modules/imports/tests/test_deep_import_real_llm.py -q

    RUN_DEEP_IMPORT_60_REAL_LLM=1 pytest \
        modules/imports/tests/test_deep_import_real_llm.py -q

    RUN_DEEP_IMPORT_60_SCENE_REAL_LLM=1 LLM_TIMEOUT=180 \
        PHASE01_SCENE_MAX_TOKENS=8192 pytest \
        modules/imports/tests/test_deep_import_real_llm.py -q -s

    RUN_DEEP_IMPORT_60_PHASE0_REAL_LLM=1 LLM_TIMEOUT=180 \
        PHASE01_SCENE_MAX_TOKENS=8192 pytest \
        modules/imports/tests/test_deep_import_real_llm.py -q -s

    RUN_DEEP_IMPORT_60_PHASE1A_REAL_LLM=1 LLM_TIMEOUT=180 \
        PHASE1A_SCENE_MAX_TOKENS=8192 pytest \
        modules/imports/tests/test_deep_import_real_llm.py -q -s

    RUN_DEEP_IMPORT_60_PHASE1B_REAL_LLM=1 LLM_TIMEOUT=180 \
        pytest modules/imports/tests/test_deep_import_real_llm.py -q -s

    RUN_DEEP_IMPORT_60_PHASE2A_REAL_LLM=1 LLM_TIMEOUT=180 \
        pytest modules/imports/tests/test_deep_import_real_llm.py -q -s

    RUN_DEEP_IMPORT_60_PHASE2B_REAL_LLM=1 LLM_TIMEOUT=180 \
        pytest modules/imports/tests/test_deep_import_real_llm.py -q -s

    RUN_DEEP_IMPORT_60_PHASE3_REAL_LLM=1 LLM_TIMEOUT=180 \
        pytest modules/imports/tests/test_deep_import_real_llm.py -q -s
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from infrastructure.llm.profiles import resolve_llm_profile
from infrastructure.tasks.models import AsyncTask
from modules.imports.orchestrator import DeepImportOrchestrator
from modules.imports.parsers import parse_txt
from modules.imports.scene_candidates import (
    SceneCandidate,
    SceneCandidateBatch,
    ScenePrefetchResult,
    SceneReinforcementResult,
)
from modules.imports.scene_commit import SceneCommitResult, SceneCommitter
from modules.imports.scene_entity_config import (
    phase2_batch_concurrency,
    phase2_batch_size_scenes,
    phase2_batch_tuning_group,
)
from modules.imports.scene_entity_extraction import SceneEntityExtractionService
from modules.imports.scene_fusion import FinalSceneCandidate, Phase1bFusionResult
from modules.imports.services import ImportService
from modules.imports.workflow import (
    DeepImportWorkflow,
    _Phase0SceneCandidateLLM,
    _Phase1aSceneCandidateLLM,
)
from modules.imports.workflow_entity_phase import phase2_quality_stats
from modules.imports.workflow_schemas import DeepImportProgress
from modules.imports.workflow_structure_phase import minimum_structure_category_targets
from modules.outline.models import (
    ForeshadowingPlan,
    OutlineArc,
    PlotThread,
    RevealPlan,
    Scene,
)
from modules.project.models import Project
from modules.world.models import CoreEntity, EntityRelation

DEFAULT_5_CHAPTER_FILE_PATH = Path(
    "/Users/tywww/Desktop/项目/wirting skill/诡秘之主_第一部 小丑_前5章.txt"
)
DEFAULT_60_CHAPTER_FILE_PATH = Path(
    "/Users/tywww/Desktop/项目/wirting skill/诡秘之主_第一部 小丑_前60章.txt"
)
BACKEND_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LOG_DIR = BACKEND_ROOT / ".test-logs" / "deep_import_real_llm"
OFFICIAL_API_RECOMMENDATION = "推荐使用官方api以保障稳定性与质量"


def _enabled(env_var: str) -> bool:
    return os.getenv(env_var) == "1"


def _full_real_llm_enabled() -> bool:
    return (
        _enabled("RUN_DEEP_IMPORT_5_REAL_LLM")
        or _enabled("RUN_DEEP_IMPORT_60_REAL_LLM")
        or _enabled("RUN_DEEP_IMPORT_213_REAL_LLM")
    )


def _scene_real_llm_enabled() -> bool:
    return _enabled("RUN_DEEP_IMPORT_60_SCENE_REAL_LLM")


def _phase0_real_llm_enabled() -> bool:
    return _enabled("RUN_DEEP_IMPORT_60_PHASE0_REAL_LLM")


def _phase1a_real_llm_enabled() -> bool:
    return _enabled("RUN_DEEP_IMPORT_60_PHASE1A_REAL_LLM")


def _phase1b_real_llm_enabled() -> bool:
    return _enabled("RUN_DEEP_IMPORT_60_PHASE1B_REAL_LLM")


def _phase2a_real_llm_enabled() -> bool:
    return _enabled("RUN_DEEP_IMPORT_60_PHASE2A_REAL_LLM")


def _phase2b_real_llm_enabled() -> bool:
    return _enabled("RUN_DEEP_IMPORT_60_PHASE2B_REAL_LLM")


def _phase3_real_llm_enabled() -> bool:
    return _enabled("RUN_DEEP_IMPORT_60_PHASE3_REAL_LLM")


def _expected_chapter_count() -> int:
    configured = os.getenv("DEEP_IMPORT_EXPECTED_CHAPTERS")
    if configured:
        return int(configured)
    if (
        os.getenv("RUN_DEEP_IMPORT_60_REAL_LLM") == "1"
        or os.getenv("RUN_DEEP_IMPORT_213_REAL_LLM") == "1"
        or _scene_real_llm_enabled()
        or _phase0_real_llm_enabled()
        or _phase1a_real_llm_enabled()
        or _phase1b_real_llm_enabled()
        or _phase2a_real_llm_enabled()
        or _phase2b_real_llm_enabled()
        or _phase3_real_llm_enabled()
    ):
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
    not _full_real_llm_enabled(),
    reason=(
        "真实 LLM 深度导入默认跳过；设置 RUN_DEEP_IMPORT_5_REAL_LLM=1 "
        "或 RUN_DEEP_IMPORT_60_REAL_LLM=1 才运行"
    ),
)
scene_real_llm_required = pytest.mark.skipif(
    not _scene_real_llm_enabled(),
    reason=(
        "60 章真实 LLM Scene-only 验收默认跳过；设置 "
        "RUN_DEEP_IMPORT_60_SCENE_REAL_LLM=1 才运行"
    ),
)
phase0_real_llm_required = pytest.mark.skipif(
    not _phase0_real_llm_enabled(),
    reason=(
        "60 章真实 LLM Phase0-only 验收默认跳过；设置 "
        "RUN_DEEP_IMPORT_60_PHASE0_REAL_LLM=1 才运行"
    ),
)
phase1a_real_llm_required = pytest.mark.skipif(
    not _phase1a_real_llm_enabled(),
    reason=(
        "60 章真实 LLM Phase1a-only 验收默认跳过；设置 "
        "RUN_DEEP_IMPORT_60_PHASE1A_REAL_LLM=1 才运行"
    ),
)
phase1b_real_llm_required = pytest.mark.skipif(
    not _phase1b_real_llm_enabled(),
    reason=(
        "60 章真实 LLM Phase1b-only 验收默认跳过；设置 "
        "RUN_DEEP_IMPORT_60_PHASE1B_REAL_LLM=1 才运行"
    ),
)
phase2a_real_llm_required = pytest.mark.skipif(
    not _phase2a_real_llm_enabled(),
    reason=(
        "60 章真实 LLM Phase2a-only 验收默认跳过；设置 "
        "RUN_DEEP_IMPORT_60_PHASE2A_REAL_LLM=1 才运行"
    ),
)
phase2b_real_llm_required = pytest.mark.skipif(
    not _phase2b_real_llm_enabled(),
    reason=(
        "60 章真实 LLM Phase2b-only 验收默认跳过；设置 "
        "RUN_DEEP_IMPORT_60_PHASE2B_REAL_LLM=1 才运行"
    ),
)
phase3_real_llm_required = pytest.mark.skipif(
    not _phase3_real_llm_enabled(),
    reason=(
        "60 章真实 LLM Phase3-only 验收默认跳过；设置 "
        "RUN_DEEP_IMPORT_60_PHASE3_REAL_LLM=1 才运行"
    ),
)


def _llm_config_log_payload(
    project_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    profile = resolve_llm_profile(project_settings, env_settings=settings)
    summary = profile.sanitized_summary()
    return {
        "effective_llm_profile": summary,
        "llm_base_url_host": summary["base_url_host"],
        "llm_model": profile.model,
        "llm_timeout": profile.timeout,
        "llm_max_tokens": profile.max_tokens,
        "llm_profile_sources": profile.sources,
        "llm_retry_max_attempts": settings.llm_retry_max_attempts,
        "llm_retry_base_delay": settings.llm_retry_base_delay,
        "llm_retry_max_delay": settings.llm_retry_max_delay,
        "llm_health_required": settings.llm_health_required,
    }


def _phase2_batch_runtime_payload() -> dict[str, Any]:
    return {
        "phase2_batch_tuning_group": phase2_batch_tuning_group(),
        "phase2_batch_size_scenes": phase2_batch_size_scenes(),
        "phase2_batch_concurrency": phase2_batch_concurrency(),
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
            or os.getenv("DEEP_IMPORT_60_PHASE3_LOG_PATH")
            or os.getenv("DEEP_IMPORT_PHASE3_LOG_PATH")
            or os.getenv("DEEP_IMPORT_60_PHASE2B_LOG_PATH")
            or os.getenv("DEEP_IMPORT_PHASE2B_LOG_PATH")
            or os.getenv("DEEP_IMPORT_60_PHASE2A_LOG_PATH")
            or os.getenv("DEEP_IMPORT_PHASE2A_LOG_PATH")
            or os.getenv("DEEP_IMPORT_60_PHASE1B_LOG_PATH")
            or os.getenv("DEEP_IMPORT_PHASE1B_LOG_PATH")
            or os.getenv("DEEP_IMPORT_60_PHASE1A_LOG_PATH")
            or os.getenv("DEEP_IMPORT_PHASE1A_LOG_PATH")
            or os.getenv("DEEP_IMPORT_60_PHASE0_LOG_PATH")
            or os.getenv("DEEP_IMPORT_PHASE0_LOG_PATH")
            or os.getenv("DEEP_IMPORT_5_LOG_PATH")
            or os.getenv("DEEP_IMPORT_60_SCENE_LOG_PATH")
            or os.getenv("DEEP_IMPORT_SCENE_LOG_PATH")
            or os.getenv("DEEP_IMPORT_60_LOG_PATH")
            or os.getenv("DEEP_IMPORT_213_LOG_PATH")
        )
        if configured:
            path = Path(configured).expanduser()
            if not path.is_absolute():
                path = BACKEND_ROOT / path
        else:
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            if _phase2b_real_llm_enabled():
                suffix = "phase2b_"
            elif _phase3_real_llm_enabled():
                suffix = "phase3_"
            elif _phase2a_real_llm_enabled():
                suffix = "phase2a_"
            elif _phase1b_real_llm_enabled():
                suffix = "phase1b_"
            elif _phase1a_real_llm_enabled():
                suffix = "phase1a_"
            elif _phase0_real_llm_enabled():
                suffix = "phase0_"
            elif _scene_real_llm_enabled():
                suffix = "scene_"
            else:
                suffix = ""
            path = DEFAULT_LOG_DIR / (
                f"deep_import_{EXPECTED_CHAPTER_COUNT}_{suffix}{stamp}.jsonl"
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


async def _alias_counts_by_novel(
    db: AsyncSession,
    project_id: uuid.UUID,
) -> dict[str, int]:
    result = await db.execute(
        select(CoreEntity.content_json).where(CoreEntity.novel_id == project_id)
    )
    counts = {
        "total_alias_count": 0,
        "candidate_alias_count": 0,
        "deep_import_alias_count": 0,
        "needs_review_alias_count": 0,
    }
    for content_json in result.scalars().all():
        aliases = (content_json or {}).get("aliases", [])
        if not isinstance(aliases, list):
            continue
        for alias_item in aliases:
            alias_text = (
                alias_item.get("alias")
                if isinstance(alias_item, dict)
                else str(alias_item or "")
            )
            if not str(alias_text or "").strip():
                continue
            counts["total_alias_count"] += 1
            if not isinstance(alias_item, dict):
                continue
            if alias_item.get("status") == "candidate":
                counts["candidate_alias_count"] += 1
            if alias_item.get("source") == "deep_import":
                counts["deep_import_alias_count"] += 1
            if alias_item.get("needs_review") is True:
                counts["needs_review_alias_count"] += 1
    return counts


def _progress_log_payload(progress, progress_value: float) -> dict[str, Any]:
    phase2_stats = (progress.quality_stats or {}).get("phase2") or {}
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
        "phase2b": {
            "total_aliases": phase2_stats.get("total_aliases"),
            "total_relations": phase2_stats.get("total_relations"),
            "alias_relation_scenes": phase2_stats.get("alias_relation_scenes"),
            "alias_relation_failed_scenes": phase2_stats.get(
                "alias_relation_failed_scenes",
            ),
        },
        **_phase2_diagnostics_payload(phase2_stats),
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


def _phase2_diagnostics_payload(phase2_stats: dict[str, Any]) -> dict[str, Any]:
    return {
        "phase2_batch_tuning": _phase2_batch_runtime_payload(),
        "phase2_batches": {
            "total": phase2_stats.get("phase2_batches_total"),
            "completed": phase2_stats.get("phase2_batches_completed"),
            "batch_size_scenes": phase2_stats.get("phase2_batch_size_scenes"),
            "concurrency": phase2_stats.get("phase2_batch_concurrency"),
            "failed_batches": phase2_stats.get("phase2_failed_batches"),
            "degraded_batches": phase2_stats.get("phase2_degraded_batches"),
        },
        "phase2_boundary": {
            "windows_total": phase2_stats.get("phase2_boundary_windows_total"),
            "windows_completed": phase2_stats.get(
                "phase2_boundary_windows_completed",
            ),
            "supplement_counts": phase2_stats.get(
                "phase2_boundary_supplement_counts",
            ),
        },
        "phase2_actions": phase2_stats.get("phase2_action_counts"),
        "phase2_dedup": phase2_stats.get("phase2_dedup_counts"),
        "phase2_low_confidence": phase2_stats.get("phase2_low_confidence"),
        "phase2_linked_to_existing": phase2_stats.get("phase2_linked_to_existing"),
        "phase2_ignored": phase2_stats.get("phase2_ignored"),
        "phase2_temporary_only": phase2_stats.get("phase2_temporary_only"),
    }


def _phase2_summary_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict | list):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    else:
        text = str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _backend_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else BACKEND_ROOT / path


def _configured_path(env_var: str) -> Path | None:
    configured = os.getenv(env_var)
    return _backend_path(configured) if configured else None


def _summary_or_artifact_path(
    log_path: Path,
    *,
    env_var: str,
    prefix: str,
    suffix: str,
) -> Path:
    configured = _configured_path(env_var)
    if configured is not None:
        return configured
    stamp = log_path.stem.rsplit("_", 1)[-1]
    return log_path.parent / f"{prefix}_{stamp}{suffix}"


def _latest_artifact_path(
    pattern: str,
    predicate,
) -> Path | None:
    candidates = sorted(
        DEFAULT_LOG_DIR.glob(pattern),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return next((path for path in candidates if predicate(path)), None)


def _append_summary_row(summary_path: Path, title: str, row: dict[str, Any]) -> Path:
    headers = list(row)
    if not summary_path.exists():
        summary_path.write_text(
            f"# {title}\n\n"
            + "| "
            + " | ".join(headers)
            + " |\n| "
            + " | ".join("---" for _ in headers)
            + " |\n",
            encoding="utf-8",
        )
    with summary_path.open("a", encoding="utf-8") as handle:
        handle.write(
            "| "
            + " | ".join(_phase2_summary_value(row[key]) for key in headers)
            + " |\n"
        )
    return summary_path


def _phase2_batch_tuning_summary_path(log_path: Path) -> Path:
    return _summary_or_artifact_path(
        log_path,
        env_var="PHASE2_BATCH_TUNING_SUMMARY_PATH",
        prefix="phase2_batch_tuning",
        suffix=".md",
    )


def _write_phase2_batch_tuning_summary(
    *,
    log_path: Path,
    wall_clock_s: float,
    result: dict[str, Any],
    output_counts: dict[str, Any],
    issues: list[str],
) -> Path:
    summary_path = _phase2_batch_tuning_summary_path(log_path)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    phase2_stats = (result.get("quality_stats") or {}).get("phase2") or {}
    row = {
        "group": phase2_batch_tuning_group(),
        "chapters": EXPECTED_CHAPTER_COUNT,
        "wall_clock_s": round(wall_clock_s, 2),
        "phase": result.get("phase"),
        "quality": result.get("quality_status"),
        "batch_size": phase2_stats.get("phase2_batch_size_scenes")
        or phase2_batch_size_scenes(),
        "concurrency": phase2_stats.get("phase2_batch_concurrency")
        or phase2_batch_concurrency(),
        "completed_scenes": phase2_stats.get("completed_scenes"),
        "failed_scene_count": phase2_stats.get("failed_scene_count"),
        "entities": output_counts.get("entity_count"),
        "aliases": output_counts.get("total_alias_count"),
        "relations": output_counts.get("relation_count"),
        "low_confidence": phase2_stats.get("phase2_low_confidence"),
        "boundary": phase2_stats.get("phase2_boundary_supplement_counts"),
        "actions": phase2_stats.get("phase2_action_counts"),
        "dedup": phase2_stats.get("phase2_dedup_counts"),
        "degraded": phase2_stats.get("degraded"),
        "error_kind": phase2_stats.get("error_kind"),
        "issues": "; ".join(issues),
        "log": str(log_path),
    }
    return _append_summary_row(summary_path, "Phase 2 Batch Tuning Summary", row)


def _phase01_scene_summary_path(log_path: Path) -> Path:
    return _summary_or_artifact_path(
        log_path,
        env_var="PHASE01_SCENE_REAL_LLM_SUMMARY_PATH",
        prefix="phase01_scene_real_llm",
        suffix=".md",
    )


def _write_phase01_scene_summary(
    *,
    log_path: Path,
    wall_clock_s: float,
    result: dict[str, Any],
    output_counts: dict[str, Any],
    coverage: dict[str, Any],
    issues: list[str],
) -> Path:
    summary_path = _phase01_scene_summary_path(log_path)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    quality_stats = result.get("quality_stats") or {}
    expected_chapters = coverage.get("expected_chapters") or []
    row = {
        "chapters": len(expected_chapters) or EXPECTED_CHAPTER_COUNT,
        "wall_clock_s": round(wall_clock_s, 2),
        "phase": result.get("phase"),
        "quality": result.get("quality_status"),
        "scene_count": output_counts.get("scene_count"),
        "created": (quality_stats.get("scene_commit") or {}).get("created_count"),
        "skipped": (quality_stats.get("scene_commit") or {}).get("skipped_count"),
        "covered": len(coverage.get("covered_chapters") or []),
        "missing": coverage.get("missing_chapters"),
        "phase0": quality_stats.get("phase0"),
        "phase1a": quality_stats.get("phase1a"),
        "phase1b": quality_stats.get("phase1b"),
        "issues": "; ".join(issues),
        "log": str(log_path),
    }
    return _append_summary_row(summary_path, "Phase 0/1 Scene Real LLM Summary", row)


def _phase0_summary_path(log_path: Path) -> Path:
    return _summary_or_artifact_path(
        log_path,
        env_var="PHASE0_REAL_LLM_SUMMARY_PATH",
        prefix="phase0_real_llm",
        suffix=".md",
    )


def _phase0_artifact_path(log_path: Path) -> Path:
    return _summary_or_artifact_path(
        log_path,
        env_var="PHASE0_REAL_LLM_ARTIFACT_PATH",
        prefix="phase0_real_llm",
        suffix=".artifact.json",
    )


def _write_phase0_artifact(
    *,
    log_path: Path,
    phase0_result: Any,
    coverage: dict[str, Any],
    expected_phase_shape: dict[str, Any],
    llm_config: dict[str, Any],
    project_id: str | None = None,
    task_id: str | None = None,
) -> Path:
    artifact_path = _phase0_artifact_path(log_path)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "test_mode": "phase0_only",
        "stage": "phase0_prefetch",
        "created_at": datetime.now(UTC).isoformat(),
        "source_log_path": str(log_path),
        "project_id": project_id,
        "task_id": task_id,
        "expected_chapter_count": EXPECTED_CHAPTER_COUNT,
        "expected_phase_shape": expected_phase_shape,
        "coverage": coverage,
        "llm_config": llm_config,
        "phase0_result": {
            "candidates": [
                candidate.model_dump(mode="json")
                for candidate in getattr(phase0_result, "candidates", []) or []
            ],
            "quality_stats": getattr(phase0_result, "quality_stats", {}) or {},
            "diagnostics": getattr(phase0_result, "diagnostics", []) or [],
            "blocked": bool(getattr(phase0_result, "blocked", False)),
            "block_reason": getattr(phase0_result, "block_reason", None),
        },
    }
    artifact_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return artifact_path


def _phase1a_phase0_artifact_path() -> Path | None:
    return _configured_path(
        "PHASE1A_PHASE0_ARTIFACT_PATH"
    ) or _latest_passed_phase0_artifact_path()


def _latest_passed_phase0_artifact_path() -> Path | None:
    return _latest_artifact_path(
        "phase0_real_llm_*.artifact.json",
        _is_passed_phase0_artifact,
    )


def _is_passed_phase0_artifact(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if payload.get("test_mode") != "phase0_only":
        return False
    if payload.get("stage") != "phase0_prefetch":
        return False
    if payload.get("expected_chapter_count") != EXPECTED_CHAPTER_COUNT:
        return False
    coverage = payload.get("coverage") or {}
    if coverage.get("missing_chapters"):
        return False
    if coverage.get("coverage_ratio") != 1.0:
        return False
    phase0_payload = payload.get("phase0_result") or {}
    if phase0_payload.get("blocked"):
        return False
    quality_stats = phase0_payload.get("quality_stats") or {}
    expected_phase_shape = payload.get("expected_phase_shape") or {}
    expected_batches = expected_phase_shape.get("phase0_total_batches")
    if expected_batches is not None:
        if quality_stats.get("total_batches") != expected_batches:
            return False
        if quality_stats.get("completed_batches") != expected_batches:
            return False
    if quality_stats.get("failed") != 0:
        return False
    return bool(phase0_payload.get("candidates"))


def _phase0_repair_source_artifact_path() -> Path | None:
    return _configured_path("PHASE0_REPAIR_SOURCE_ARTIFACT_PATH")


def _load_phase0_artifact(path: Path) -> ScenePrefetchResult:
    payload = json.loads(path.read_text(encoding="utf-8"))
    phase0_payload = payload.get("phase0_result") or {}
    return ScenePrefetchResult(
        candidates=[
            SceneCandidate.model_validate(candidate)
            for candidate in phase0_payload.get("candidates", [])
        ],
        quality_stats=phase0_payload.get("quality_stats") or {},
        diagnostics=phase0_payload.get("diagnostics") or [],
        blocked=bool(phase0_payload.get("blocked", False)),
        block_reason=phase0_payload.get("block_reason"),
    )


def _candidate_batch_key(
    candidate: SceneCandidate,
) -> tuple[str, str, int, tuple[int, ...]]:
    return (
        candidate.source_round,
        candidate.source_batch_id,
        candidate.source_batch_index,
        tuple(candidate.source_chapter_indices),
    )


def _phase0_repair_max_failed_batches() -> int:
    raw = os.getenv("PHASE0_REPAIR_MAX_FAILED_BATCHES")
    if raw is None or raw.strip() == "":
        return 5
    try:
        value = int(raw)
    except ValueError:
        return 5
    return value if value > 0 else 5


def _phase0_repair_concurrency() -> int:
    raw = os.getenv("PHASE0_REPAIR_CONCURRENCY")
    if raw is None or raw.strip() == "":
        return 2
    try:
        value = int(raw)
    except ValueError:
        return 2
    return value if value > 0 else 2


def _phase0_repair_attempts() -> int:
    raw = os.getenv("PHASE0_REPAIR_ATTEMPTS")
    if raw is None or raw.strip() == "":
        return 3
    try:
        value = int(raw)
    except ValueError:
        return 3
    return value if value > 0 else 3


def _phase0_repair_retry_delay_seconds() -> float:
    raw = os.getenv("PHASE0_REPAIR_RETRY_DELAY_SECONDS")
    if raw is None or raw.strip() == "":
        return 5.0
    try:
        value = float(raw)
    except ValueError:
        return 5.0
    return value if value > 0 else 5.0


async def _repair_phase0_artifact(
    *,
    db: AsyncSession,
    project_id: uuid.UUID,
    source_artifact_path: Path,
) -> tuple[ScenePrefetchResult, dict[str, Any]]:
    from modules.imports.scene_prefetch import (
        Phase0ScenePrefetcher,
        _build_quality_stats,
    )

    source_result = _load_phase0_artifact(source_artifact_path)
    current_candidates = list(source_result.candidates)
    max_failed = _phase0_repair_max_failed_batches()
    prefetcher = Phase0ScenePrefetcher(
        llm=_Phase0SceneCandidateLLM(db, str(project_id)),
        concurrency=_phase0_repair_concurrency(),
    )
    semaphore = asyncio.Semaphore(_phase0_repair_concurrency())

    async def repair(candidate: SceneCandidate) -> SceneCandidate:
        batch = SceneCandidateBatch(
            batch_id=candidate.source_batch_id,
            round_name=candidate.source_round,
            batch_index=candidate.source_batch_index,
            chapter_indices=candidate.source_chapter_indices,
        )
        async with semaphore:
            return await prefetcher._process_batch(batch)

    repair_attempts: list[dict[str, Any]] = []
    repaired_batch_ids: list[str] = []
    for attempt in range(1, _phase0_repair_attempts() + 1):
        failed_candidates = [
            candidate
            for candidate in current_candidates
            if candidate.quality == "failed"
        ]
        if not failed_candidates:
            break
        if len(failed_candidates) > max_failed:
            raise AssertionError(
                "phase0 repair source has too many failed batches: "
                f"{len(failed_candidates)} > {max_failed}"
            )
        if attempt > 1:
            await asyncio.sleep(_phase0_repair_retry_delay_seconds())
        repaired_candidates = await asyncio.gather(
            *(repair(candidate) for candidate in failed_candidates)
        )
        repaired_batch_ids.extend(
            candidate.source_batch_id for candidate in repaired_candidates
        )
        merged_by_key = {
            _candidate_batch_key(candidate): candidate
            for candidate in current_candidates
        }
        for candidate in repaired_candidates:
            merged_by_key[_candidate_batch_key(candidate)] = candidate
        current_candidates = _sorted_phase0_candidates(merged_by_key.values())
        repair_attempts.append(
            {
                "attempt": attempt,
                "input_failed_batches": [
                    candidate.source_batch_id for candidate in failed_candidates
                ],
                "output_failed_batches": [
                    candidate.source_batch_id
                    for candidate in current_candidates
                    if candidate.quality == "failed"
                ],
            }
        )
    merged_candidates = _sorted_phase0_candidates(current_candidates)
    quality_stats = _build_quality_stats(
        merged_candidates,
        total_batches=len(merged_candidates),
    )
    diagnostics = [
        candidate.diagnostics
        for candidate in merged_candidates
        if candidate.diagnostics
    ]
    result = ScenePrefetchResult(
        candidates=merged_candidates,
        quality_stats=quality_stats,
        diagnostics=diagnostics,
        blocked=source_result.blocked,
        block_reason=source_result.block_reason,
    )
    repair_summary = {
        "source_artifact_path": str(source_artifact_path),
        "repair_attempts": repair_attempts,
        "repaired_batch_count": len(repaired_batch_ids),
        "repaired_batches": repaired_batch_ids,
        "remaining_failed": quality_stats.get("failed"),
    }
    return result, repair_summary


def _sorted_phase0_candidates(
    candidates: Iterable[SceneCandidate],
) -> list[SceneCandidate]:
    return sorted(
        candidates,
        key=lambda candidate: (
            candidate.source_round,
            min(candidate.source_chapter_indices or [10**9]),
            candidate.source_batch_index,
        ),
    )


def _write_phase0_summary(
    *,
    log_path: Path,
    wall_clock_s: float,
    result: dict[str, Any],
    output_counts: dict[str, Any],
    coverage: dict[str, Any],
    expected_phase_shape: dict[str, Any],
    issues: list[str],
    llm_config: dict[str, Any] | None = None,
) -> Path:
    summary_path = _phase0_summary_path(log_path)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    quality_stats = result.get("quality_stats") or {}
    expected_chapters = coverage.get("expected_chapters") or []
    row = {
        "test_mode": "phase0_only",
        "stage": "phase0_prefetch",
        "chapters": len(expected_chapters) or EXPECTED_CHAPTER_COUNT,
        "wall_clock_s": round(wall_clock_s, 2),
        "blocked": result.get("blocked"),
        "block_reason": result.get("block_reason"),
        "expected_batches": expected_phase_shape.get("phase0_total_batches"),
        "total_batches": quality_stats.get("total_batches"),
        "completed_batches": quality_stats.get("completed_batches"),
        "failed": quality_stats.get("failed"),
        "candidate_count": result.get("candidate_count"),
        "covered": len(coverage.get("covered_chapters") or []),
        "missing": coverage.get("missing_chapters"),
        "scene_count": output_counts.get("scene_count"),
        "entity_count": output_counts.get("entity_count"),
        "provider": (llm_config or {}).get("effective_llm_profile"),
        "later_phases": result.get("later_phases"),
        "issues": "; ".join(issues),
        "log": str(log_path),
    }
    return _append_summary_row(summary_path, "Phase 0 Real LLM Summary", row)


def _phase1a_summary_path(log_path: Path) -> Path:
    return _summary_or_artifact_path(
        log_path,
        env_var="PHASE1A_REAL_LLM_SUMMARY_PATH",
        prefix="phase1a_real_llm",
        suffix=".md",
    )


def _write_phase1a_summary(
    *,
    log_path: Path,
    wall_clock_s: float,
    result: dict[str, Any],
    output_counts: dict[str, Any],
    coverage: dict[str, Any],
    expected_phase_shape: dict[str, Any],
    issues: list[str],
    llm_config: dict[str, Any] | None = None,
) -> Path:
    summary_path = _phase1a_summary_path(log_path)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    phase0_stats = result.get("phase0_quality_stats") or {}
    phase1a_stats = result.get("quality_stats") or {}
    expected_chapters = coverage.get("expected_chapters") or []
    row = {
        "test_mode": "phase1a_only",
        "stage": "phase1a_reinforce",
        "chapters": len(expected_chapters) or EXPECTED_CHAPTER_COUNT,
        "wall_clock_s": round(wall_clock_s, 2),
        "blocked": result.get("blocked"),
        "block_reason": result.get("block_reason"),
        "expected_phase0_batches": expected_phase_shape.get("phase0_total_batches"),
        "phase0_failed": phase0_stats.get("failed"),
        "expected_phase1a_batches": expected_phase_shape.get("phase1a_total_batches"),
        "phase1a_total_batches": phase1a_stats.get("total_batches"),
        "phase1a_completed_batches": phase1a_stats.get("completed_batches"),
        "phase1a_failed": phase1a_stats.get("failed"),
        "phase1a_timeout": phase1a_stats.get("timeout"),
        "phase1a_schema_error": phase1a_stats.get("schema_error"),
        "candidate_count": result.get("candidate_count"),
        "candidate_scene_count": result.get("candidate_scene_count"),
        "covered": len(coverage.get("covered_chapters") or []),
        "missing": coverage.get("missing_chapters"),
        "scene_count": output_counts.get("scene_count"),
        "entity_count": output_counts.get("entity_count"),
        "provider": (llm_config or {}).get("effective_llm_profile"),
        "later_phases": result.get("later_phases"),
        "issues": "; ".join(issues),
        "log": str(log_path),
    }
    return _append_summary_row(summary_path, "Phase 1a Real LLM Summary", row)


def _phase1a_artifact_path(log_path: Path) -> Path:
    return _summary_or_artifact_path(
        log_path,
        env_var="PHASE1A_REAL_LLM_ARTIFACT_PATH",
        prefix="phase1a_real_llm",
        suffix=".artifact.json",
    )


def _write_phase1a_artifact(
    *,
    log_path: Path,
    phase0_result: Any,
    phase1a_result: Any,
    coverage: dict[str, Any],
    expected_phase_shape: dict[str, Any],
    llm_config: dict[str, Any],
    project_id: str | None = None,
    task_id: str | None = None,
) -> Path:
    artifact_path = _phase1a_artifact_path(log_path)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "test_mode": "phase1a_only",
        "stage": "phase1a_reinforce",
        "created_at": datetime.now(UTC).isoformat(),
        "source_log_path": str(log_path),
        "project_id": project_id,
        "task_id": task_id,
        "expected_chapter_count": EXPECTED_CHAPTER_COUNT,
        "expected_phase_shape": expected_phase_shape,
        "coverage": coverage,
        "llm_config": llm_config,
        "phase0_result": {
            "quality_stats": getattr(phase0_result, "quality_stats", {}) or {},
            "candidate_count": len(getattr(phase0_result, "candidates", []) or []),
        },
        "phase1a_result": {
            "candidates": [
                candidate.model_dump(mode="json")
                for candidate in getattr(phase1a_result, "candidates", []) or []
            ],
            "quality_stats": getattr(phase1a_result, "quality_stats", {}) or {},
            "diagnostics": getattr(phase1a_result, "diagnostics", []) or [],
            "blocked": bool(getattr(phase1a_result, "blocked", False)),
            "block_reason": getattr(phase1a_result, "block_reason", None),
        },
    }
    artifact_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return artifact_path


def _phase1a_repair_source_artifact_path() -> Path | None:
    return _configured_path("PHASE1A_REPAIR_SOURCE_ARTIFACT_PATH")


def _load_phase1a_artifact(path: Path) -> SceneReinforcementResult:
    payload = json.loads(path.read_text(encoding="utf-8"))
    phase1a_payload = payload.get("phase1a_result") or {}
    return SceneReinforcementResult(
        candidates=[
            SceneCandidate.model_validate(candidate)
            for candidate in phase1a_payload.get("candidates", [])
        ],
        quality_stats=phase1a_payload.get("quality_stats") or {},
        diagnostics=phase1a_payload.get("diagnostics") or [],
        blocked=bool(phase1a_payload.get("blocked", False)),
        block_reason=phase1a_payload.get("block_reason"),
        did_merge_rounds=False,
    )


def _phase1b_phase1a_artifact_path() -> Path | None:
    return _configured_path(
        "PHASE1B_PHASE1A_ARTIFACT_PATH"
    ) or _latest_passed_phase1a_artifact_path()


def _latest_passed_phase1a_artifact_path() -> Path | None:
    return _latest_artifact_path(
        "phase1a_real_llm_*.artifact.json",
        _is_passed_phase1a_artifact,
    )


def _is_passed_phase1a_artifact(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if payload.get("test_mode") != "phase1a_only":
        return False
    if payload.get("stage") != "phase1a_reinforce":
        return False
    if payload.get("expected_chapter_count") != EXPECTED_CHAPTER_COUNT:
        return False
    coverage = payload.get("coverage") or {}
    if coverage.get("missing_chapters"):
        return False
    if coverage.get("coverage_ratio") != 1.0:
        return False
    phase1a_payload = payload.get("phase1a_result") or {}
    if phase1a_payload.get("blocked"):
        return False
    quality_stats = phase1a_payload.get("quality_stats") or {}
    expected_phase_shape = payload.get("expected_phase_shape") or {}
    expected_batches = expected_phase_shape.get("phase1a_total_batches")
    if expected_batches is not None:
        if quality_stats.get("total_batches") != expected_batches:
            return False
        if quality_stats.get("completed_batches") != expected_batches:
            return False
    for key in ("failed", "timeout", "schema_error", "degraded_fallback"):
        if quality_stats.get(key, 0) != 0:
            return False
    return bool(phase1a_payload.get("candidates"))


def _phase1b_summary_path(log_path: Path) -> Path:
    return _summary_or_artifact_path(
        log_path,
        env_var="PHASE1B_REAL_LLM_SUMMARY_PATH",
        prefix="phase1b_real_llm",
        suffix=".md",
    )


def _write_phase1b_summary(
    *,
    log_path: Path,
    wall_clock_s: float,
    result: dict[str, Any],
    output_counts: dict[str, Any],
    coverage: dict[str, Any],
    expected_phase_shape: dict[str, Any],
    issues: list[str],
    llm_config: dict[str, Any] | None = None,
) -> Path:
    summary_path = _phase1b_summary_path(log_path)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    phase1a_stats = result.get("phase1a_quality_stats") or {}
    phase1b_stats = result.get("quality_stats") or {}
    expected_chapters = coverage.get("expected_chapters") or []
    row = {
        "test_mode": "phase1b_only",
        "stage": "phase1b_fusion",
        "chapters": len(expected_chapters) or EXPECTED_CHAPTER_COUNT,
        "wall_clock_s": round(wall_clock_s, 2),
        "blocked": result.get("blocked"),
        "degraded": result.get("degraded"),
        "block_reason": result.get("block_reason"),
        "phase1a_failed": phase1a_stats.get("failed"),
        "expected_phase1b_windows": expected_phase_shape.get(
            "phase1b_total_windows"
        ),
        "phase1b_total_windows": phase1b_stats.get("total_windows"),
        "phase1b_completed_windows": phase1b_stats.get("completed_windows"),
        "phase1b_failed": phase1b_stats.get("failed"),
        "phase1b_timeout": phase1b_stats.get("timeout"),
        "phase1b_schema_error": phase1b_stats.get("schema_error"),
        "phase1b_fallback": result.get("phase1a_fallback"),
        "candidate_count": result.get("candidate_count"),
        "covered": len(coverage.get("covered_chapters") or []),
        "missing": coverage.get("missing_chapters"),
        "scene_count": output_counts.get("scene_count"),
        "entity_count": output_counts.get("entity_count"),
        "provider": (llm_config or {}).get("effective_llm_profile"),
        "later_phases": result.get("later_phases"),
        "issues": "; ".join(issues),
        "log": str(log_path),
    }
    return _append_summary_row(summary_path, "Phase 1b Real LLM Summary", row)


def _phase1b_artifact_path(log_path: Path) -> Path:
    return _summary_or_artifact_path(
        log_path,
        env_var="PHASE1B_REAL_LLM_ARTIFACT_PATH",
        prefix="phase1b_real_llm",
        suffix=".artifact.json",
    )


def _write_phase1b_artifact(
    *,
    log_path: Path,
    phase1a_artifact_path: Path,
    phase1a_result: Any,
    phase1b_result: Any,
    coverage: dict[str, Any],
    expected_phase_shape: dict[str, Any],
    llm_config: dict[str, Any],
    project_id: str | None = None,
    task_id: str | None = None,
) -> Path:
    artifact_path = _phase1b_artifact_path(log_path)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "test_mode": "phase1b_only",
        "stage": "phase1b_fusion",
        "created_at": datetime.now(UTC).isoformat(),
        "source_log_path": str(log_path),
        "source_phase1a_artifact_path": str(phase1a_artifact_path),
        "project_id": project_id,
        "task_id": task_id,
        "expected_chapter_count": EXPECTED_CHAPTER_COUNT,
        "expected_phase_shape": expected_phase_shape,
        "coverage": coverage,
        "llm_config": llm_config,
        "phase1a_result": {
            "quality_stats": getattr(phase1a_result, "quality_stats", {}) or {},
            "candidate_count": len(getattr(phase1a_result, "candidates", []) or []),
        },
        "phase1b_result": {
            "candidates": [
                candidate.model_dump(mode="json")
                for candidate in getattr(phase1b_result, "candidates", []) or []
            ],
            "quality_stats": getattr(phase1b_result, "quality_stats", {}) or {},
            "diagnostics": getattr(phase1b_result, "diagnostics", []) or [],
            "degraded": bool(getattr(phase1b_result, "degraded", False)),
            "phase1a_fallback": bool(
                getattr(phase1b_result, "phase1a_fallback", False)
            ),
            "blocked": bool(getattr(phase1b_result, "blocked", False)),
            "block_reason": getattr(phase1b_result, "block_reason", None),
        },
    }
    artifact_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return artifact_path


def _phase2a_phase1b_artifact_path() -> Path | None:
    configured = _configured_path("PHASE2A_PHASE1B_ARTIFACT_PATH")
    if configured is not None:
        return configured
    repair_source = _phase2a_repair_source_artifact_path()
    if repair_source is not None:
        payload = json.loads(repair_source.read_text(encoding="utf-8"))
        source = payload.get("source_phase1b_artifact_path")
        if source:
            return _backend_path(source)
    return _latest_passed_phase1b_artifact_path()


def _latest_passed_phase1b_artifact_path() -> Path | None:
    return _latest_artifact_path(
        "phase1b_real_llm_*.artifact.json",
        _is_passed_phase1b_artifact,
    )


def _is_passed_phase1b_artifact(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if payload.get("test_mode") != "phase1b_only":
        return False
    if payload.get("stage") != "phase1b_fusion":
        return False
    if payload.get("expected_chapter_count") != EXPECTED_CHAPTER_COUNT:
        return False
    coverage = payload.get("coverage") or {}
    if coverage.get("missing_chapters") or coverage.get("coverage_ratio") != 1.0:
        return False
    phase1b = payload.get("phase1b_result") or {}
    if phase1b.get("blocked") or phase1b.get("degraded"):
        return False
    if phase1b.get("phase1a_fallback"):
        return False
    quality_stats = phase1b.get("quality_stats") or {}
    for key in ("failed", "timeout", "schema_error"):
        if int(quality_stats.get(key, 0) or 0) != 0:
            return False
    expected_windows = (payload.get("expected_phase_shape") or {}).get(
        "phase1b_total_windows"
    )
    if expected_windows is not None:
        if quality_stats.get("total_windows") != expected_windows:
            return False
        if quality_stats.get("completed_windows") != expected_windows:
            return False
    return bool(phase1b.get("candidates"))


def _load_phase1b_artifact(path: Path) -> Phase1bFusionResult:
    payload = json.loads(path.read_text(encoding="utf-8"))
    phase1b = payload.get("phase1b_result") or {}
    return Phase1bFusionResult(
        candidates=[
            FinalSceneCandidate.model_validate(candidate)
            for candidate in phase1b.get("candidates", [])
        ],
        quality_stats=phase1b.get("quality_stats") or {},
        diagnostics=phase1b.get("diagnostics") or [],
        degraded=bool(phase1b.get("degraded", False)),
        phase1a_fallback=bool(phase1b.get("phase1a_fallback", False)),
        blocked=bool(phase1b.get("blocked", False)),
        block_reason=phase1b.get("block_reason"),
    )


def _phase2a_repair_source_artifact_path() -> Path | None:
    return _configured_path("PHASE2A_REPAIR_SOURCE_ARTIFACT_PATH")


def _phase2b_phase2a_artifact_path() -> Path | None:
    repair_source = _phase2b_repair_source_artifact_path()
    if repair_source is not None:
        payload = json.loads(repair_source.read_text(encoding="utf-8"))
        source_phase2a = payload.get("source_phase2a_artifact_path")
        if source_phase2a:
            return _backend_path(source_phase2a)
    return _configured_path(
        "PHASE2B_PHASE2A_ARTIFACT_PATH"
    ) or _latest_hydratable_phase2a_artifact_path()


def _phase2b_repair_source_artifact_path() -> Path | None:
    return _configured_path("PHASE2B_REPAIR_SOURCE_ARTIFACT_PATH")


def _latest_hydratable_phase2a_artifact_path() -> Path | None:
    return _latest_artifact_path(
        "phase2a_real_llm_*.artifact.json",
        _is_hydratable_phase2a_artifact,
    )


def _load_phase2a_artifact_payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _phase2a_summary_path(log_path: Path) -> Path:
    return _summary_or_artifact_path(
        log_path,
        env_var="PHASE2A_REAL_LLM_SUMMARY_PATH",
        prefix="phase2a_real_llm",
        suffix=".md",
    )


def _phase2b_summary_path(log_path: Path) -> Path:
    return _summary_or_artifact_path(
        log_path,
        env_var="PHASE2B_REAL_LLM_SUMMARY_PATH",
        prefix="phase2b_real_llm",
        suffix=".md",
    )


def _phase2a_artifact_path(log_path: Path) -> Path:
    return _summary_or_artifact_path(
        log_path,
        env_var="PHASE2A_REAL_LLM_ARTIFACT_PATH",
        prefix="phase2a_real_llm",
        suffix=".artifact.json",
    )


def _phase2b_artifact_path(log_path: Path) -> Path:
    return _summary_or_artifact_path(
        log_path,
        env_var="PHASE2B_REAL_LLM_ARTIFACT_PATH",
        prefix="phase2b_real_llm",
        suffix=".artifact.json",
    )


def _phase3_summary_path(log_path: Path) -> Path:
    return _summary_or_artifact_path(
        log_path,
        env_var="PHASE3_REAL_LLM_SUMMARY_PATH",
        prefix="phase3_real_llm",
        suffix=".md",
    )


def _phase3_artifact_path(log_path: Path) -> Path:
    return _summary_or_artifact_path(
        log_path,
        env_var="PHASE3_REAL_LLM_ARTIFACT_PATH",
        prefix="phase3_real_llm",
        suffix=".artifact.json",
    )


def _phase3_phase2b_artifact_path() -> Path | None:
    return _configured_path(
        "PHASE3_PHASE2B_ARTIFACT_PATH"
    ) or _latest_passed_phase2b_artifact_path()


def _latest_passed_phase2b_artifact_path() -> Path | None:
    return _latest_artifact_path(
        "phase2b_real_llm_*.artifact.json",
        _is_passed_phase2b_artifact,
    )


def _is_passed_phase2b_artifact(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if payload.get("test_mode") != "phase2b_only":
        return False
    if payload.get("stage") != "alias_relation_phase2b":
        return False
    phase2b = payload.get("phase2b_result") or {}
    total_scenes = int(phase2b.get("total_scenes", 0) or 0)
    world_snapshot = payload.get("world_snapshot") or {}
    return (
        total_scenes > 0
        and int(phase2b.get("alias_relation_scenes", 0) or 0) == total_scenes
        and not (phase2b.get("alias_relation_failed_scenes") or [])
        and phase2b.get("degraded") is False
        and phase2b.get("error_kind") is None
        and int(world_snapshot.get("entity_count", 0) or 0) > 0
    )


def _load_phase2b_artifact_payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


async def _world_snapshot_for_phase_artifact(
    db: AsyncSession,
    project_id: uuid.UUID,
) -> dict[str, Any]:
    entity_rows = (
        await db.execute(
            select(CoreEntity)
            .where(CoreEntity.novel_id == project_id)
            .order_by(CoreEntity.created_at, CoreEntity.id)
        )
    ).scalars().all()
    relation_rows = (
        await db.execute(
            select(EntityRelation)
            .where(EntityRelation.novel_id == project_id)
            .order_by(EntityRelation.created_at, EntityRelation.id)
        )
    ).scalars().all()
    entity_name_by_id = {str(entity.id): entity.name for entity in entity_rows}
    return {
        "schema_version": 1,
        "entity_count": len(entity_rows),
        "relation_count": len(relation_rows),
        "entities": [
            {
                "id": str(entity.id),
                "entity_type": entity.entity_type,
                "name": entity.name,
                "summary": entity.summary,
                "public_info": entity.public_info,
                "hidden_truth": entity.hidden_truth,
                "importance": entity.importance,
                "importance_level": entity.importance_level,
                "reveal_level": entity.reveal_level,
                "content_json": entity.content_json or {},
                "status": entity.status,
                "created_by": entity.created_by,
            }
            for entity in entity_rows
        ],
        "relations": [
            {
                "id": str(relation.id),
                "source_id": str(relation.source_id),
                "target_id": str(relation.target_id),
                "source_name": entity_name_by_id.get(str(relation.source_id)),
                "target_name": entity_name_by_id.get(str(relation.target_id)),
                "relation_type": relation.relation_type,
                "description": relation.description,
                "quote": relation.quote,
                "strength": relation.strength,
                "status": relation.status,
            }
            for relation in relation_rows
        ],
    }


async def _hydrate_world_snapshot(
    db: AsyncSession,
    project_id: uuid.UUID,
    world_snapshot: dict[str, Any],
) -> dict[str, Any]:
    from modules.world.facade import create_entity, create_relation

    id_map: dict[str, str] = {}
    created_entities = 0
    created_relations = 0
    skipped_relations = 0
    for entity in world_snapshot.get("entities") or []:
        created = await create_entity(
            db,
            str(project_id),
            {
                "entity_type": entity.get("entity_type") or "unknown",
                "name": entity.get("name") or "未命名对象",
                "summary": entity.get("summary"),
                "public_info": entity.get("public_info"),
                "hidden_truth": entity.get("hidden_truth"),
                "importance": entity.get("importance") or 0.5,
                "importance_level": entity.get("importance_level") or "normal",
                "reveal_level": entity.get("reveal_level") or "author_only",
                "content_json": entity.get("content_json") or {},
                "status": entity.get("status") or "candidate",
                "created_by": entity.get("created_by") or "ai_import",
            },
        )
        old_id = str(entity.get("id") or "")
        if old_id and created.get("id"):
            id_map[old_id] = str(created["id"])
        created_entities += 1

    for relation in world_snapshot.get("relations") or []:
        source_id = id_map.get(str(relation.get("source_id") or ""))
        target_id = id_map.get(str(relation.get("target_id") or ""))
        if not source_id or not target_id:
            skipped_relations += 1
            continue
        await create_relation(
            db,
            str(project_id),
            {
                "source_id": source_id,
                "target_id": target_id,
                "relation_type": relation.get("relation_type") or "related_to",
                "description": relation.get("description"),
                "quote": relation.get("quote"),
                "strength": relation.get("strength") or 0.5,
                "status": relation.get("status") or "candidate",
            },
        )
        created_relations += 1
    await db.flush()
    return {
        "source_entity_count": len(world_snapshot.get("entities") or []),
        "source_relation_count": len(world_snapshot.get("relations") or []),
        "created_entities": created_entities,
        "created_relations": created_relations,
        "skipped_relations": skipped_relations,
    }


def _write_phase2a_summary(
    *,
    log_path: Path,
    wall_clock_s: float,
    result: dict[str, Any],
    output_counts: dict[str, Any],
    scene_coverage: dict[str, Any],
    issues: list[str],
    llm_config: dict[str, Any],
) -> Path:
    summary_path = _phase2a_summary_path(log_path)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    phase2 = result.get("quality_stats") or {}
    scene_commit = result.get("scene_commit") or {}
    row = {
        "test_mode": "phase2a_only",
        "stage": "entity_extraction_phase2a",
        "chapters": EXPECTED_CHAPTER_COUNT,
        "wall_clock_s": round(wall_clock_s, 2),
        "scene_commit_created": scene_commit.get("created_count"),
        "scene_commit_skipped": scene_commit.get("skipped_count"),
        "covered": len(scene_coverage.get("covered_chapters") or []),
        "missing": scene_coverage.get("missing_chapters"),
        "total_scenes": phase2.get("total_scenes"),
        "completed_scenes": phase2.get("completed_scenes"),
        "failed_scene_count": phase2.get("failed_scene_count"),
        "total_created": phase2.get("total_created"),
        "total_relations": phase2.get("total_relations"),
        "total_deltas": phase2.get("total_deltas"),
        "batch_group": phase2_batch_tuning_group(),
        "batch_size": phase2.get("phase2_batch_size_scenes"),
        "batch_concurrency": phase2.get("phase2_batch_concurrency"),
        "failed_batches": phase2.get("phase2_failed_batches"),
        "degraded_batches": phase2.get("phase2_degraded_batches"),
        "degraded": phase2.get("degraded"),
        "error_kind": phase2.get("error_kind"),
        "provider": llm_config.get("effective_llm_profile"),
        "issues": "; ".join(issues),
        "log": str(log_path),
    }
    return _append_summary_row(summary_path, "Phase 2a Real LLM Summary", row)


def _write_phase2a_artifact(
    *,
    log_path: Path,
    source_phase1b_artifact_path: Path,
    phase1b_result: Phase1bFusionResult,
    scene_commit_result: SceneCommitResult,
    phase2_result: dict[str, Any],
    phase2_quality: dict[str, Any],
    output_counts: dict[str, Any],
    scene_coverage: dict[str, Any],
    expected_phase_shape: dict[str, Any],
    llm_config: dict[str, Any],
    project_id: str,
    task_id: str,
    repair_summary: dict[str, Any] | None = None,
    world_snapshot: dict[str, Any] | None = None,
) -> Path:
    artifact_path = _phase2a_artifact_path(log_path)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "test_mode": "phase2a_only",
        "stage": "entity_extraction_phase2a",
        "created_at": datetime.now(UTC).isoformat(),
        "source_log_path": str(log_path),
        "source_phase1b_artifact_path": str(source_phase1b_artifact_path),
        "project_id": project_id,
        "task_id": task_id,
        "expected_chapter_count": EXPECTED_CHAPTER_COUNT,
        "expected_phase_shape": expected_phase_shape,
        "scene_coverage": scene_coverage,
        "llm_config": llm_config,
        "phase2_batch_tuning": _phase2_batch_runtime_payload(),
        "phase1b_result": {
            "candidate_count": len(phase1b_result.candidates),
            "quality_stats": phase1b_result.quality_stats,
            "degraded": phase1b_result.degraded,
            "phase1a_fallback": phase1b_result.phase1a_fallback,
            "blocked": phase1b_result.blocked,
        },
        "scene_commit": scene_commit_result.model_dump(mode="json"),
        "phase2_result": phase2_result,
        "phase2_quality_stats": phase2_quality,
        "output_counts": output_counts,
        "world_snapshot": world_snapshot,
        "repair_summary": repair_summary,
    }
    artifact_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return artifact_path


def _write_phase2b_summary(
    *,
    log_path: Path,
    wall_clock_s: float,
    result: dict[str, Any],
    output_counts: dict[str, Any],
    scene_coverage: dict[str, Any],
    issues: list[str],
    llm_config: dict[str, Any],
) -> Path:
    summary_path = _phase2b_summary_path(log_path)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    phase2b = result.get("phase2b_result") or {}
    hydrate_summary = result.get("hydrate_summary") or {}
    row = {
        "test_mode": "phase2b_only",
        "stage": "alias_relation_phase2b",
        "chapters": EXPECTED_CHAPTER_COUNT,
        "wall_clock_s": round(wall_clock_s, 2),
        "hydrated_entities": hydrate_summary.get("created_entities"),
        "hydrated_relations": hydrate_summary.get("created_relations"),
        "covered": len(scene_coverage.get("covered_chapters") or []),
        "missing": scene_coverage.get("missing_chapters"),
        "total_scenes": phase2b.get("total_scenes"),
        "alias_relation_scenes": phase2b.get("alias_relation_scenes"),
        "failed_scenes": phase2b.get("alias_relation_failed_scenes"),
        "total_aliases": phase2b.get("total_aliases"),
        "total_relations": phase2b.get("total_relations"),
        "elapsed_s": phase2b.get("alias_relation_elapsed_s"),
        "total_timeout_s": phase2b.get("alias_relation_total_timeout_s"),
        "concurrency": phase2b.get("alias_relation_concurrency"),
        "degraded": phase2b.get("degraded"),
        "error_kind": phase2b.get("error_kind"),
        "provider": llm_config.get("effective_llm_profile"),
        "issues": "; ".join(issues),
        "log": str(log_path),
    }
    return _append_summary_row(summary_path, "Phase 2b Real LLM Summary", row)


def _write_phase2b_artifact(
    *,
    log_path: Path,
    source_phase2a_artifact_path: Path,
    source_phase2a_payload: dict[str, Any],
    hydrate_summary: dict[str, Any],
    scene_commit_result: SceneCommitResult,
    phase2b_result: dict[str, Any],
    output_counts: dict[str, Any],
    scene_coverage: dict[str, Any],
    expected_phase_shape: dict[str, Any],
    llm_config: dict[str, Any],
    project_id: str,
    task_id: str,
    world_snapshot: dict[str, Any] | None = None,
    repair_summary: dict[str, Any] | None = None,
) -> Path:
    artifact_path = _phase2b_artifact_path(log_path)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "test_mode": "phase2b_only",
        "stage": "alias_relation_phase2b",
        "created_at": datetime.now(UTC).isoformat(),
        "source_log_path": str(log_path),
        "source_phase2a_artifact_path": str(source_phase2a_artifact_path),
        "source_phase1b_artifact_path": source_phase2a_payload.get(
            "source_phase1b_artifact_path"
        ),
        "project_id": project_id,
        "task_id": task_id,
        "expected_chapter_count": EXPECTED_CHAPTER_COUNT,
        "expected_phase_shape": expected_phase_shape,
        "scene_coverage": scene_coverage,
        "llm_config": llm_config,
        "source_phase2a_quality_stats": source_phase2a_payload.get(
            "phase2_quality_stats"
        )
        or {},
        "scene_commit": scene_commit_result.model_dump(mode="json"),
        "hydrate_summary": hydrate_summary,
        "phase2b_result": phase2b_result,
        "output_counts": output_counts,
        "world_snapshot": world_snapshot,
        "repair_summary": repair_summary,
        "later_phases": {"structure_analysis": "skipped"},
    }
    artifact_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return artifact_path


def _write_phase3_summary(
    *,
    log_path: Path,
    wall_clock_s: float,
    result: dict[str, Any],
    output_counts: dict[str, Any],
    scene_coverage: dict[str, Any],
    issues: list[str],
    llm_config: dict[str, Any],
) -> Path:
    summary_path = _phase3_summary_path(log_path)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    phase3 = result.get("quality_stats") or {}
    hydrate_summary = result.get("hydrate_summary") or {}
    structure_counts = output_counts.get("structure_counts") or {}
    row = {
        "test_mode": "phase3_only",
        "stage": "structure_analysis",
        "chapters": EXPECTED_CHAPTER_COUNT,
        "wall_clock_s": round(wall_clock_s, 2),
        "hydrated_entities": hydrate_summary.get("created_entities"),
        "hydrated_relations": hydrate_summary.get("created_relations"),
        "covered": len(scene_coverage.get("covered_chapters") or []),
        "missing": scene_coverage.get("missing_chapters"),
        "threads": structure_counts.get("threads"),
        "arcs": structure_counts.get("arcs"),
        "foreshadowing": structure_counts.get("foreshadowing"),
        "reveals": structure_counts.get("reveals"),
        "quality_threads": phase3.get("total_threads"),
        "quality_arcs": phase3.get("total_arcs"),
        "failed": phase3.get("failed"),
        "error_kind": phase3.get("error_kind"),
        "provider": llm_config.get("effective_llm_profile"),
        "issues": "; ".join(issues),
        "log": str(log_path),
    }
    return _append_summary_row(summary_path, "Phase 3 Real LLM Summary", row)


def _write_phase3_artifact(
    *,
    log_path: Path,
    source_phase2b_artifact_path: Path,
    source_phase2b_payload: dict[str, Any],
    hydrate_summary: dict[str, Any],
    scene_commit_result: SceneCommitResult,
    progress_result: dict[str, Any],
    result: dict[str, Any],
    output_counts: dict[str, Any],
    scene_coverage: dict[str, Any],
    expected_phase_shape: dict[str, Any],
    llm_config: dict[str, Any],
    project_id: str,
    task_id: str,
) -> Path:
    artifact_path = _phase3_artifact_path(log_path)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "test_mode": "phase3_only",
        "stage": "structure_analysis",
        "created_at": datetime.now(UTC).isoformat(),
        "source_log_path": str(log_path),
        "source_phase2b_artifact_path": str(source_phase2b_artifact_path),
        "source_phase2a_artifact_path": source_phase2b_payload.get(
            "source_phase2a_artifact_path"
        ),
        "source_phase1b_artifact_path": source_phase2b_payload.get(
            "source_phase1b_artifact_path"
        ),
        "project_id": project_id,
        "task_id": task_id,
        "expected_chapter_count": EXPECTED_CHAPTER_COUNT,
        "expected_phase_shape": expected_phase_shape,
        "scene_coverage": scene_coverage,
        "llm_config": llm_config,
        "source_phase2b_result": source_phase2b_payload.get("phase2b_result") or {},
        "scene_commit": scene_commit_result.model_dump(mode="json"),
        "hydrate_summary": hydrate_summary,
        "progress_result": progress_result,
        "phase3_result": result,
        "output_counts": output_counts,
        "later_phases": {},
    }
    artifact_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return artifact_path


def _is_passed_phase2a_artifact(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if payload.get("test_mode") != "phase2a_only":
        return False
    if payload.get("stage") != "entity_extraction_phase2a":
        return False
    if payload.get("expected_chapter_count") != EXPECTED_CHAPTER_COUNT:
        return False
    coverage = payload.get("scene_coverage") or {}
    if coverage.get("missing_chapters") or coverage.get("coverage_ratio") != 1.0:
        return False
    quality = payload.get("phase2_quality_stats") or {}
    return (
        int(quality.get("total_scenes", 0) or 0) > 0
        and quality.get("completed_scenes") == quality.get("total_scenes")
        and int(quality.get("failed_scene_count", 0) or 0) == 0
        and not quality.get("phase2_failed_batches")
        and not quality.get("error_kind")
        and int(quality.get("total_created", 0) or 0) > 0
    )


def _has_hydratable_phase2a_snapshot(payload: dict[str, Any]) -> bool:
    world_snapshot = payload.get("world_snapshot") or {}
    return bool(world_snapshot.get("entities")) and int(
        world_snapshot.get("entity_count", 0) or 0
    ) > 0


def _is_hydratable_phase2a_artifact(path: Path) -> bool:
    if not _is_passed_phase2a_artifact(path):
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return _has_hydratable_phase2a_snapshot(payload)


def _phase2a_repair_context() -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    repair_source = _phase2a_repair_source_artifact_path()
    if repair_source is None:
        return None, None
    payload = json.loads(repair_source.read_text(encoding="utf-8"))
    phase2_result = payload.get("phase2_result") or {}
    phase2_quality = payload.get("phase2_quality_stats") or phase2_quality_stats(
        phase2_result
    )
    summary = {
        "source_artifact_path": str(repair_source),
        "source_phase1b_artifact_path": payload.get("source_phase1b_artifact_path"),
        "source_total_scenes": phase2_quality.get("total_scenes"),
        "source_completed_scenes": phase2_quality.get("completed_scenes"),
        "source_failed_scene_count": phase2_quality.get("failed_scene_count"),
        "source_failed_batches": phase2_quality.get("phase2_failed_batches") or [],
        "source_degraded_batches": phase2_quality.get("phase2_degraded_batches") or [],
        "source_error_kind": phase2_quality.get("error_kind"),
        "source_world_snapshot_hydratable": _has_hydratable_phase2a_snapshot(payload),
    }
    return payload, summary


def _phase2a_repair_checkpoints_for_scene_commit(
    source_payload: dict[str, Any] | None,
    scene_commit_result: SceneCommitResult,
) -> dict[str, Any] | None:
    if not source_payload:
        return None
    source_checkpoints = (
        (source_payload.get("phase2_result") or {}).get("checkpoints") or {}
    )
    phase2 = source_checkpoints.get("phase2") or {}
    scenes = phase2.get("scenes") or []
    created_scene_ids = list(scene_commit_result.created_scene_ids or [])
    if not scenes or len(scenes) != len(created_scene_ids):
        return source_checkpoints

    remapped_scenes: list[dict[str, Any]] = []
    for checkpoint, scene_id in zip(scenes, created_scene_ids, strict=True):
        if not isinstance(checkpoint, dict):
            continue
        remapped = dict(checkpoint)
        remapped["source_scene_id"] = checkpoint.get("scene_id")
        remapped["scene_id"] = str(scene_id)
        remapped_scenes.append(remapped)
    return {"phase2": {"scenes": remapped_scenes}}


def _phase2b_repair_context() -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    repair_source = _phase2b_repair_source_artifact_path()
    if repair_source is None:
        return None, None
    payload = json.loads(repair_source.read_text(encoding="utf-8"))
    phase2b = payload.get("phase2b_result") or {}
    source_completed = _phase2b_effective_completed_count(phase2b)
    summary = {
        "source_artifact_path": str(repair_source),
        "source_phase2a_artifact_path": payload.get("source_phase2a_artifact_path"),
        "source_total_scenes": phase2b.get("total_scenes"),
        "source_completed_scenes": source_completed,
        "source_failed_scenes": phase2b.get("alias_relation_failed_scenes") or [],
        "source_skipped_scenes": phase2b.get("alias_relation_skipped_scenes"),
        "source_error_kind": phase2b.get("error_kind"),
        "source_world_snapshot_hydratable": _has_hydratable_phase2a_snapshot(payload),
    }
    return payload, summary


def _phase2b_repair_checkpoints_for_scene_commit(
    source_payload: dict[str, Any] | None,
    scene_commit_result: SceneCommitResult,
) -> dict[str, Any] | None:
    if not source_payload:
        return None
    phase2b = source_payload.get("phase2b_result") or {}
    source_checkpoints = phase2b.get("alias_relation_checkpoints") or {}
    checkpoint_phase = source_checkpoints.get("phase2b") or {}
    scenes = checkpoint_phase.get("scenes") or []
    created_scene_ids = list(scene_commit_result.created_scene_ids or [])
    if not scenes or len(scenes) != len(created_scene_ids):
        return source_checkpoints

    remapped_scenes: list[dict[str, Any]] = []
    for checkpoint, scene_id in zip(scenes, created_scene_ids, strict=True):
        if not isinstance(checkpoint, dict):
            continue
        remapped = dict(checkpoint)
        remapped["source_scene_id"] = checkpoint.get("scene_id")
        remapped["scene_id"] = str(scene_id)
        remapped_scenes.append(remapped)
    return {"phase2b": {"scenes": remapped_scenes}}


def _merge_phase2a_repair_result(
    source_payload: dict[str, Any] | None,
    repair_result: dict[str, Any],
) -> dict[str, Any]:
    if not source_payload:
        return repair_result
    source_result = source_payload.get("phase2_result") or {}
    source_quality = source_payload.get("phase2_quality_stats") or phase2_quality_stats(
        source_result
    )
    repaired_quality = phase2_quality_stats(repair_result)
    merged = {**source_result, **repair_result}
    for key in ("total_created", "total_relations", "total_deltas"):
        merged[key] = int(source_quality.get(key, 0) or 0) + int(
            repaired_quality.get(key, 0) or 0
        )
    failed_scene_indices = repair_result.get("failed_scene_indices") or []
    phase2_failed_batches = repair_result.get("phase2_failed_batches") or []
    checkpoint_counts = repaired_quality.get("checkpoint_status_counts") or {}
    completed_or_reused = int(checkpoint_counts.get("done", 0) or 0) + int(
        checkpoint_counts.get("skipped", 0) or 0
    )
    total_scenes = int(
        repair_result.get("total_scenes")
        or source_quality.get("total_scenes")
        or source_result.get("total_scenes")
        or 0
    )
    if total_scenes and completed_or_reused >= total_scenes and not failed_scene_indices:
        merged["completed_scenes"] = total_scenes
        merged["failed_scene_indices"] = []
        if not phase2_failed_batches:
            merged["phase2_failed_batches"] = []
            merged["degraded"] = False
            merged["error_kind"] = None
            merged["error_message"] = None
    return merged


def _merge_phase2b_repair_result(
    source_payload: dict[str, Any] | None,
    repair_result: dict[str, Any],
) -> dict[str, Any]:
    if not source_payload:
        return repair_result
    source_result = source_payload.get("phase2b_result") or {}
    merged = {**source_result, **repair_result}
    for key in ("total_aliases", "total_relations"):
        merged[key] = int(source_result.get(key, 0) or 0) + int(
            repair_result.get(key, 0) or 0
        )
    failed_scenes = repair_result.get("alias_relation_failed_scenes") or []
    total_scenes = int(
        repair_result.get("total_scenes")
        or source_result.get("total_scenes")
        or 0
    )
    repair_checkpoint_completed = _phase2b_checkpoint_completed_count(
        repair_result.get("alias_relation_checkpoints") or {}
    )
    source_completed = _phase2b_effective_completed_count(source_result)
    repair_completed = int(repair_result.get("alias_relation_scenes", 0) or 0)
    if repair_checkpoint_completed:
        merged["alias_relation_scenes"] = repair_checkpoint_completed
    else:
        merged["alias_relation_scenes"] = min(
            total_scenes or source_completed + repair_completed,
            source_completed + repair_completed,
        )
    if total_scenes and repair_checkpoint_completed >= total_scenes and not failed_scenes:
        merged["alias_relation_scenes"] = total_scenes
        merged["alias_relation_failed_scenes"] = []
        merged["degraded"] = False
        merged["error_kind"] = None
        merged["error_message"] = None
    return merged


def _phase2b_checkpoint_completed_count(checkpoints: dict[str, Any]) -> int:
    scenes = ((checkpoints or {}).get("phase2b") or {}).get("scenes") or []
    return sum(
        1
        for checkpoint in scenes
        if isinstance(checkpoint, dict)
        and checkpoint.get("status") in {"done", "skipped"}
    )


def _phase2b_effective_completed_count(phase2b_result: dict[str, Any]) -> int:
    checkpoint_completed = _phase2b_checkpoint_completed_count(
        phase2b_result.get("alias_relation_checkpoints") or {}
    )
    if checkpoint_completed:
        return checkpoint_completed
    return int(phase2b_result.get("alias_relation_scenes", 0) or 0)


def _phase2b_attempted_or_explained(
    phase2_stats: dict[str, Any],
    phase_errors: list[dict[str, Any]],
) -> bool:
    phase2b_attempts = int(phase2_stats.get("alias_relation_scenes", 0) or 0) + len(
        phase2_stats.get("alias_relation_failed_scenes") or []
    )
    skipped_with_reason = bool(
        phase2_stats.get("alias_relation_skipped")
        and phase2_stats.get("alias_relation_skip_reason")
    )
    return phase2b_attempts > 0 or skipped_with_reason or bool(phase_errors)


def _phase1a_repair_max_failed_batches() -> int:
    raw = os.getenv("PHASE1A_REPAIR_MAX_FAILED_BATCHES")
    if raw is None or raw.strip() == "":
        return 24
    try:
        value = int(raw)
    except ValueError:
        return 24
    return value if value > 0 else 24


def _phase1a_repair_attempts() -> int:
    raw = os.getenv("PHASE1A_REPAIR_ATTEMPTS")
    if raw is None or raw.strip() == "":
        return 2
    try:
        value = int(raw)
    except ValueError:
        return 2
    return value if value > 0 else 2


def _phase1a_repair_batch_ids() -> set[str] | None:
    raw = os.getenv("PHASE1A_REPAIR_BATCH_IDS")
    if raw is None or raw.strip() == "":
        return None
    return {item.strip() for item in raw.split(",") if item.strip()}


async def _repair_phase1a_artifact(
    *,
    db: AsyncSession,
    project_id: uuid.UUID,
    source_artifact_path: Path,
    phase0_result: ScenePrefetchResult,
    chapters: list[dict],
) -> tuple[SceneReinforcementResult, dict[str, Any]]:
    from modules.imports.scene_reinforcement import (
        Phase1aSceneReinforcer,
        _build_quality_stats,
    )

    source_result = _load_phase1a_artifact(source_artifact_path)
    current_candidates = list(source_result.candidates)
    repair_attempts: list[dict[str, Any]] = []
    repaired_batch_ids: list[str] = []
    max_failed = _phase1a_repair_max_failed_batches()
    for attempt in range(1, _phase1a_repair_attempts() + 1):
        failed_candidates = [
            candidate
            for candidate in current_candidates
            if candidate.quality == "failed"
        ]
        allowed_batch_ids = _phase1a_repair_batch_ids()
        if allowed_batch_ids is not None:
            failed_candidates = [
                candidate
                for candidate in failed_candidates
                if candidate.source_batch_id in allowed_batch_ids
            ]
        if not failed_candidates:
            break
        if len(failed_candidates) > max_failed:
            raise AssertionError(
                "phase1a repair source has too many failed batches: "
                f"{len(failed_candidates)} > {max_failed}"
            )
        failed_batch_ids = {candidate.source_batch_id for candidate in failed_candidates}
        phase0_candidates = [
            candidate
            for candidate in phase0_result.candidates
            if candidate.source_batch_id in failed_batch_ids
        ]
        repair_result = await Phase1aSceneReinforcer(
            llm=_Phase1aSceneCandidateLLM(),
            concurrency=_phase0_repair_concurrency(),
            max_retries=1,
        ).run(
            phase0_candidates=phase0_candidates,
            chapters=chapters,
        )
        repaired_batch_ids.extend(
            candidate.source_batch_id for candidate in repair_result.candidates
        )
        merged_by_key = {
            _candidate_batch_key(candidate): candidate
            for candidate in current_candidates
        }
        for candidate in repair_result.candidates:
            merged_by_key[_candidate_batch_key(candidate)] = candidate
        current_candidates = _sorted_phase0_candidates(merged_by_key.values())
        repair_attempts.append(
            {
                "attempt": attempt,
                "input_failed_batches": sorted(failed_batch_ids),
                "output_failed_batches": [
                    candidate.source_batch_id
                    for candidate in current_candidates
                    if candidate.quality == "failed"
                ],
                "repair_quality_stats": repair_result.quality_stats,
            }
        )
        if any(candidate.quality == "failed" for candidate in current_candidates):
            await asyncio.sleep(_phase0_repair_retry_delay_seconds())
    quality_stats = _build_quality_stats(
        current_candidates,
        total_batches=len(current_candidates),
    )
    diagnostics = [
        candidate.diagnostics
        for candidate in current_candidates
        if candidate.diagnostics
    ]
    result = SceneReinforcementResult(
        candidates=current_candidates,
        quality_stats=quality_stats,
        diagnostics=diagnostics,
        blocked=source_result.blocked,
        block_reason=source_result.block_reason,
        did_merge_rounds=False,
    )
    return result, {
        "source_artifact_path": str(source_artifact_path),
        "repair_attempts": repair_attempts,
        "repaired_batch_count": len(repaired_batch_ids),
        "repaired_batches": repaired_batch_ids,
        "remaining_failed": quality_stats.get("failed"),
    }


def _candidate_chapter_coverage(
    candidates: list[Any],
    *,
    start_chapter: int,
    end_chapter: int,
) -> dict[str, Any]:
    covered: set[int] = set()
    duplicate: set[int] = set()
    candidates_with_chapter_ids = 0
    for candidate in candidates:
        raw_indices = (
            candidate.get("source_chapter_indices")
            if isinstance(candidate, dict)
            else getattr(candidate, "source_chapter_indices", None)
        )
        seen_in_candidate: set[int] = set()
        for raw_chapter_id in raw_indices or []:
            try:
                chapter_index = int(raw_chapter_id)
            except (TypeError, ValueError):
                continue
            if chapter_index in seen_in_candidate or chapter_index in covered:
                duplicate.add(chapter_index)
            seen_in_candidate.add(chapter_index)
            covered.add(chapter_index)
        if seen_in_candidate:
            candidates_with_chapter_ids += 1
    expected = set(range(start_chapter, end_chapter + 1))
    return {
        "expected_chapters": sorted(expected),
        "covered_chapters": sorted(covered.intersection(expected)),
        "missing_chapters": sorted(expected - covered),
        "extra_chapters": sorted(covered - expected),
        "duplicate_chapters": sorted(duplicate),
        "candidate_count": len(candidates),
        "candidates_with_chapter_ids": candidates_with_chapter_ids,
        "coverage_ratio": (
            round(len(covered.intersection(expected)) / len(expected), 4)
            if expected
            else 1.0
        ),
    }


def _phase0_result_payload(phase0_result: Any) -> dict[str, Any]:
    diagnostics = getattr(phase0_result, "diagnostics", []) or []
    candidates = getattr(phase0_result, "candidates", []) or []
    return {
        "blocked": bool(getattr(phase0_result, "blocked", False)),
        "block_reason": getattr(phase0_result, "block_reason", None),
        "candidate_count": len(candidates),
        "quality_stats": getattr(phase0_result, "quality_stats", {}) or {},
        "diagnostics_sample": diagnostics[:5],
        "later_phases": {
            "phase1a": "skipped",
            "phase1b": "skipped",
            "scene_commit": "skipped",
            "entity_extraction": "skipped",
            "structure_analysis": "skipped",
        },
    }


def _candidate_scene_count(candidates: list[Any]) -> int:
    count = 0
    for candidate in candidates:
        payload = (
            candidate.get("payload")
            if isinstance(candidate, dict)
            else getattr(candidate, "payload", None)
        )
        if not isinstance(payload, dict):
            continue
        scenes = payload.get("scenes")
        if isinstance(scenes, list):
            count += len(scenes)
    return count


def _phase1a_result_payload(phase0_result: Any, phase1a_result: Any) -> dict[str, Any]:
    phase0_diagnostics = getattr(phase0_result, "diagnostics", []) or []
    phase1a_diagnostics = getattr(phase1a_result, "diagnostics", []) or []
    phase1a_candidates = list(getattr(phase1a_result, "candidates", []) or [])
    return {
        "blocked": bool(getattr(phase1a_result, "blocked", False)),
        "block_reason": getattr(phase1a_result, "block_reason", None),
        "phase0_candidate_count": len(getattr(phase0_result, "candidates", []) or []),
        "phase0_quality_stats": getattr(phase0_result, "quality_stats", {}) or {},
        "phase0_diagnostics_sample": phase0_diagnostics[:5],
        "candidate_count": len(phase1a_candidates),
        "candidate_scene_count": _candidate_scene_count(phase1a_candidates),
        "quality_stats": getattr(phase1a_result, "quality_stats", {}) or {},
        "diagnostics_sample": phase1a_diagnostics[:5],
        "later_phases": {
            "phase1b": "skipped",
            "scene_commit": "skipped",
            "entity_extraction": "skipped",
            "structure_analysis": "skipped",
        },
    }


def _phase1b_result_payload(
    phase1a_result: Any,
    phase1b_result: Any,
) -> dict[str, Any]:
    phase1b_diagnostics = getattr(phase1b_result, "diagnostics", []) or []
    phase1b_candidates = list(getattr(phase1b_result, "candidates", []) or [])
    return {
        "blocked": bool(getattr(phase1b_result, "blocked", False)),
        "degraded": bool(getattr(phase1b_result, "degraded", False)),
        "phase1a_fallback": bool(getattr(phase1b_result, "phase1a_fallback", False)),
        "block_reason": getattr(phase1b_result, "block_reason", None),
        "phase1a_candidate_count": len(
            getattr(phase1a_result, "candidates", []) or []
        ),
        "phase1a_quality_stats": getattr(phase1a_result, "quality_stats", {}) or {},
        "candidate_count": len(phase1b_candidates),
        "quality_stats": getattr(phase1b_result, "quality_stats", {}) or {},
        "diagnostics_sample": phase1b_diagnostics[:5],
        "later_phases": {
            "scene_commit": "skipped",
            "entity_extraction": "skipped",
            "structure_analysis": "skipped",
        },
    }


def _phase2a_result_payload(
    *,
    phase1b_result: Phase1bFusionResult,
    scene_commit_result: SceneCommitResult,
    phase2_result: dict[str, Any],
    phase2_quality: dict[str, Any],
    repair_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "source_phase1b_candidate_count": len(phase1b_result.candidates),
        "source_phase1b_quality_stats": phase1b_result.quality_stats,
        "source_phase1b_degraded": phase1b_result.degraded,
        "source_phase1b_phase1a_fallback": phase1b_result.phase1a_fallback,
        "source_phase1b_blocked": phase1b_result.blocked,
        "scene_commit": scene_commit_result.model_dump(mode="json"),
        "quality_stats": phase2_quality,
        "phase2_result": phase2_result,
        "repair_summary": repair_summary,
        "later_phases": {
            "phase2b": "skipped",
            "structure_analysis": "skipped",
        },
    }


def _phase2b_result_payload(
    *,
    source_phase2a_payload: dict[str, Any],
    scene_commit_result: SceneCommitResult,
    hydrate_summary: dict[str, Any],
    phase2b_result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "source_phase2a_quality_stats": source_phase2a_payload.get(
            "phase2_quality_stats"
        )
        or {},
        "source_phase2a_output_counts": source_phase2a_payload.get("output_counts")
        or {},
        "source_phase2a_has_world_snapshot": _has_hydratable_phase2a_snapshot(
            source_phase2a_payload
        ),
        "scene_commit": scene_commit_result.model_dump(mode="json"),
        "hydrate_summary": hydrate_summary,
        "phase2b_result": phase2b_result,
        "quality_stats": {
            "total_scenes": int(phase2b_result.get("total_scenes", 0) or 0),
            "alias_relation_scenes": int(
                phase2b_result.get("alias_relation_scenes", 0) or 0
            ),
            "alias_relation_failed_scenes": phase2b_result.get(
                "alias_relation_failed_scenes"
            )
            or [],
            "total_aliases": int(phase2b_result.get("total_aliases", 0) or 0),
            "total_relations": int(phase2b_result.get("total_relations", 0) or 0),
            "alias_relation_elapsed_s": phase2b_result.get(
                "alias_relation_elapsed_s"
            ),
            "alias_relation_total_timeout_s": phase2b_result.get(
                "alias_relation_total_timeout_s"
            ),
            "alias_relation_concurrency": phase2b_result.get(
                "alias_relation_concurrency"
            ),
            "degraded": bool(phase2b_result.get("degraded")),
            "error_kind": phase2b_result.get("error_kind"),
        },
        "later_phases": {"structure_analysis": "skipped"},
    }


def _phase3_result_payload(
    *,
    source_phase2b_payload: dict[str, Any],
    scene_commit_result: SceneCommitResult,
    hydrate_summary: dict[str, Any],
    progress_result: dict[str, Any],
) -> dict[str, Any]:
    quality_stats = progress_result.get("quality_stats") or {}
    phase3 = quality_stats.get("phase3") or {}
    return {
        "source_phase2b_result": source_phase2b_payload.get("phase2b_result") or {},
        "source_phase2b_output_counts": source_phase2b_payload.get("output_counts")
        or {},
        "source_phase2b_has_world_snapshot": bool(
            (source_phase2b_payload.get("world_snapshot") or {}).get("entity_count")
        ),
        "scene_commit": scene_commit_result.model_dump(mode="json"),
        "hydrate_summary": hydrate_summary,
        "progress_result": progress_result,
        "quality_stats": phase3,
        "phase_errors": progress_result.get("phase_errors") or [],
        "completed_steps": progress_result.get("completed_steps") or [],
        "phase": progress_result.get("phase"),
        "quality_status": progress_result.get("quality_status"),
        "degraded": bool(progress_result.get("degraded")),
        "snapshot_health_summary": progress_result.get("snapshot_health_summary") or {},
        "audit_summary": progress_result.get("audit_summary") or {},
        "later_phases": {},
    }


def _build_phase_acceptance_task(
    project_id: uuid.UUID,
    *,
    test_mode: str,
    stage: str,
) -> AsyncTask:
    task_type = {
        "phase0_only": "deep_import_phase0_real_llm",
        "phase1a_only": "deep_import_phase1a_real_llm",
        "phase1b_only": "deep_import_phase1b_real_llm",
        "phase2a_only": "deep_import_phase2a_real_llm",
        "phase2b_only": "deep_import_phase2b_real_llm",
        "phase3_only": "deep_import_phase3_real_llm",
    }.get(test_mode, "deep_import_phase_real_llm")
    return AsyncTask(
        id=uuid.uuid4(),
        task_type=task_type,
        status="running",
        meta={
            "novel_id": str(project_id),
            "start_chapter": 1,
            "end_chapter": EXPECTED_CHAPTER_COUNT,
            "test_mode": test_mode,
            "stage": stage,
            "source": "real_llm_acceptance",
        },
        progress=0.0,
        started_at=datetime.now(UTC),
        heartbeat_at=datetime.now(UTC),
    )


def _phase_acceptance_progress_payload(
    *,
    task: AsyncTask,
    test_mode: str,
    stage: str,
    result: dict[str, Any],
    output_counts: dict[str, Any],
    coverage: dict[str, Any],
    expected_phase_shape: dict[str, Any],
    llm_config: dict[str, Any],
    summary_path: Path,
    artifact_path: Path,
    log_path: Path,
    issues: list[str],
) -> dict[str, Any]:
    blocked = bool(result.get("blocked"))
    failed = blocked or bool(issues)
    if test_mode == "phase1b_only":
        quality_stats = {
            "phase1a": result.get("phase1a_quality_stats") or {},
            "phase1b": result.get("quality_stats") or {},
        }
        completed_steps = ["phase1a_reinforce", "phase1b_fusion"]
    elif test_mode == "phase2a_only":
        quality_stats = {
            "scene_commit": result.get("scene_commit") or {},
            "phase2": result.get("quality_stats") or {},
        }
        completed_steps = ["scene_commit", "entity_extraction"]
    elif test_mode == "phase2b_only":
        quality_stats = {
            "scene_commit": result.get("scene_commit") or {},
            "phase2a": result.get("source_phase2a_quality_stats") or {},
            "phase2b": result.get("quality_stats") or {},
        }
        completed_steps = ["scene_commit", "alias_relation_extraction"]
    elif test_mode == "phase3_only":
        quality_stats = {
            "scene_commit": result.get("scene_commit") or {},
            "phase2b": result.get("source_phase2b_result") or {},
            "phase3": result.get("quality_stats") or {},
        }
        completed_steps = ["scene_commit", "structure_analysis"]
    elif test_mode == "phase1a_only":
        quality_stats = {
            "phase0": result.get("phase0_quality_stats") or {},
            "phase1a": result.get("quality_stats") or {},
        }
        completed_steps = ["phase0_prefetch", "phase1a_reinforce"]
    else:
        quality_stats = {"phase0": result.get("quality_stats") or {}}
        completed_steps = ["phase0_prefetch"]

    phase_error_items = [
        {
            "phase": stage,
            "error_kind": "acceptance_issue",
            "message": issue[:300],
        }
        for issue in issues
    ]
    if blocked and not phase_error_items:
        phase_error_items.append(
            {
                "phase": stage,
                "error_kind": str(result.get("block_reason") or "blocked"),
                "message": str(result.get("block_reason") or "stage blocked")[:300],
            }
        )

    progress = DeepImportProgress(
        workflow_id=str(task.id),
        workflow_type=str(task.task_type),
        stage=stage,
        phase="failed" if failed else "done",
        quality_status="failed" if failed else "complete",
        total_steps=len(completed_steps),
        completed_steps=completed_steps if not failed else completed_steps[:-1],
        message=(
            f"{stage} acceptance failed"
            if failed
            else f"{stage} acceptance completed"
        ),
        current_phase=stage,
        phase1_total_batches=int(
            (quality_stats.get("phase0") or {}).get("total_batches", 0) or 0
        )
        + int((quality_stats.get("phase1a") or {}).get("total_batches", 0) or 0),
        phase1_completed_batches=int(
            (quality_stats.get("phase0") or {}).get("completed_batches", 0) or 0
        )
        + int(
            (quality_stats.get("phase1a") or {}).get("completed_batches", 0) or 0
        ),
        phase_timeline=[
            {
                "phase": stage,
                "status": "failed" if failed else "completed",
                "details": {
                    "test_mode": test_mode,
                    "candidate_count": result.get("candidate_count"),
                    "candidate_scene_count": result.get("candidate_scene_count"),
                    "scene_count": output_counts.get("scene_count"),
                    "entity_count": output_counts.get("entity_count"),
                    "covered_chapters": len(coverage.get("covered_chapters") or []),
                    "missing_chapters": coverage.get("missing_chapters") or [],
                    "expected_phase_shape": expected_phase_shape,
                },
                "ended_at": datetime.now(UTC).isoformat(),
            }
        ],
        diagnostic_counts={
            **output_counts,
            "candidate_count": result.get("candidate_count"),
            "candidate_scene_count": result.get("candidate_scene_count"),
            "covered_chapter_count": len(coverage.get("covered_chapters") or []),
            "missing_chapters": coverage.get("missing_chapters") or [],
            "phase_error_count": len(phase_error_items),
            "phase2_total_scenes": (quality_stats.get("phase2") or {}).get(
                "total_scenes"
            ),
            "phase2_completed_scenes": (quality_stats.get("phase2") or {}).get(
                "completed_scenes"
            ),
        },
        quality_stats=quality_stats,
        checkpoints={
            stage: {
                "test_mode": test_mode,
                "log_path": str(log_path),
                "summary_path": str(summary_path),
                "artifact_path": str(artifact_path),
                "coverage": coverage,
                "expected_phase_shape": expected_phase_shape,
            }
        },
        phase_errors=phase_error_items,
        degraded=bool(result.get("quality_stats", {}).get("degraded_fallback")),
        degraded_reason=(
            "degraded_fallback"
            if result.get("quality_stats", {}).get("degraded_fallback")
            else None
        ),
    )
    payload = progress.model_dump(mode="json")
    payload["llm_config"] = llm_config
    payload["result_summary"] = result
    payload["artifact_path"] = str(artifact_path)
    payload["summary_path"] = str(summary_path)
    return payload


async def _persist_phase_acceptance_task_result(
    db: AsyncSession,
    task: AsyncTask,
    *,
    test_mode: str,
    stage: str,
    result: dict[str, Any],
    output_counts: dict[str, Any],
    coverage: dict[str, Any],
    expected_phase_shape: dict[str, Any],
    llm_config: dict[str, Any],
    summary_path: Path,
    artifact_path: Path,
    log_path: Path,
    issues: list[str],
) -> dict[str, Any]:
    payload = _phase_acceptance_progress_payload(
        task=task,
        test_mode=test_mode,
        stage=stage,
        result=result,
        output_counts=output_counts,
        coverage=coverage,
        expected_phase_shape=expected_phase_shape,
        llm_config=llm_config,
        summary_path=summary_path,
        artifact_path=artifact_path,
        log_path=log_path,
        issues=issues,
    )
    task.result = payload
    task.status = "failed" if payload["phase"] == "failed" else "done"
    task.progress = 1.0
    task.finished_at = datetime.now(UTC)
    task.heartbeat_at = task.finished_at
    await db.flush()
    return payload


def _phase0_only_acceptance_checks(
    *,
    result: dict[str, Any],
    output_counts: dict[str, Any],
    coverage: dict[str, Any],
    expected_phase_shape: dict[str, Any],
    expected_chapter_count: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    checks: list[dict[str, Any]] = []
    issues: list[str] = []
    quality_stats = result.get("quality_stats") or {}
    missing_chapters = coverage.get("missing_chapters") or []

    _record_acceptance_check(
        checks,
        issues,
        name="phase0_not_blocked",
        ok=result.get("blocked") is False,
        expected=False,
        actual=result.get("blocked"),
        message=f"phase0 expected blocked false, got {result.get('blocked')}",
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase0_total_batches",
        ok=quality_stats.get("total_batches")
        == expected_phase_shape.get("phase0_total_batches"),
        expected=expected_phase_shape.get("phase0_total_batches"),
        actual=quality_stats.get("total_batches"),
        message=(
            "phase0 total_batches expected "
            f"{expected_phase_shape.get('phase0_total_batches')}, "
            f"got {quality_stats.get('total_batches')}"
        ),
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase0_completed_all_batches",
        ok=quality_stats.get("completed_batches") == quality_stats.get("total_batches"),
        expected=quality_stats.get("total_batches"),
        actual=quality_stats.get("completed_batches"),
        message=(
            "phase0 completed_batches expected total_batches "
            f"{quality_stats.get('total_batches')}, got "
            f"{quality_stats.get('completed_batches')}"
        ),
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase0_no_failed_batches",
        ok=int(quality_stats.get("failed", 0) or 0) == 0,
        expected=0,
        actual=quality_stats.get("failed"),
        message=f"phase0 failed batches expected 0, got {quality_stats.get('failed')}",
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase0_candidate_chapter_coverage_complete",
        ok=not missing_chapters
        and coverage.get("candidates_with_chapter_ids", 0) > 0,
        expected=list(range(1, expected_chapter_count + 1)),
        actual=coverage,
        message=(
            "phase0 candidate chapter coverage missing chapters or source ids: "
            f"{missing_chapters}"
        ),
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase0_no_scene_commit",
        ok=int(output_counts.get("scene_count", 0) or 0) == 0,
        expected=0,
        actual=output_counts.get("scene_count"),
        message=(
            "phase0-only expected no committed scenes, got "
            f"{output_counts.get('scene_count')}"
        ),
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase0_no_phase2_or_phase3_outputs",
        ok=int(output_counts.get("entity_count", 0) or 0) == 0
        and int(output_counts.get("relation_count", 0) or 0) == 0
        and all(
            int(count or 0) == 0
            for count in (output_counts.get("structure_counts") or {}).values()
        ),
        expected="no entity/relation/structure outputs",
        actual=output_counts,
        message="phase0-only unexpectedly wrote later phase outputs",
    )
    return checks, issues


def _phase1a_only_acceptance_checks(
    *,
    result: dict[str, Any],
    output_counts: dict[str, Any],
    coverage: dict[str, Any],
    expected_phase_shape: dict[str, Any],
    expected_chapter_count: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    checks: list[dict[str, Any]] = []
    issues: list[str] = []
    phase0_stats = result.get("phase0_quality_stats") or {}
    phase1a_stats = result.get("quality_stats") or {}
    missing_chapters = coverage.get("missing_chapters") or []
    max_candidate_scenes = max(
        expected_chapter_count * 6,
        int(expected_phase_shape.get("phase1a_total_batches", 0) or 0) * 15,
    )

    _record_acceptance_check(
        checks,
        issues,
        name="phase0_no_failed_batches",
        ok=int(phase0_stats.get("failed", 0) or 0) == 0,
        expected=0,
        actual=phase0_stats.get("failed"),
        message=f"phase0 failed batches expected 0, got {phase0_stats.get('failed')}",
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase1a_not_blocked",
        ok=result.get("blocked") is False,
        expected=False,
        actual=result.get("blocked"),
        message=f"phase1a expected blocked false, got {result.get('blocked')}",
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase1a_total_batches",
        ok=phase1a_stats.get("total_batches")
        == expected_phase_shape.get("phase1a_total_batches"),
        expected=expected_phase_shape.get("phase1a_total_batches"),
        actual=phase1a_stats.get("total_batches"),
        message=(
            "phase1a total_batches expected "
            f"{expected_phase_shape.get('phase1a_total_batches')}, "
            f"got {phase1a_stats.get('total_batches')}"
        ),
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase1a_completed_all_batches",
        ok=phase1a_stats.get("completed_batches")
        == phase1a_stats.get("total_batches"),
        expected=phase1a_stats.get("total_batches"),
        actual=phase1a_stats.get("completed_batches"),
        message=(
            "phase1a completed_batches expected total_batches "
            f"{phase1a_stats.get('total_batches')}, got "
            f"{phase1a_stats.get('completed_batches')}"
        ),
    )
    for key in ("failed", "timeout", "schema_error"):
        _record_acceptance_check(
            checks,
            issues,
            name=f"phase1a_no_{key}",
            ok=int(phase1a_stats.get(key, 0) or 0) == 0,
            expected=0,
            actual=phase1a_stats.get(key),
            message=f"phase1a {key} expected 0, got {phase1a_stats.get(key)}",
        )
    _record_acceptance_check(
        checks,
        issues,
        name="phase1a_candidate_chapter_coverage_complete",
        ok=not missing_chapters
        and coverage.get("candidates_with_chapter_ids", 0) > 0,
        expected=list(range(1, expected_chapter_count + 1)),
        actual=coverage,
        message=(
            "phase1a candidate chapter coverage missing chapters: "
            f"{missing_chapters}"
        ),
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase1a_candidate_scene_count_not_exploded",
        ok=0 < int(result.get("candidate_scene_count", 0) or 0)
        <= max_candidate_scenes,
        expected=f"1..{max_candidate_scenes}",
        actual=result.get("candidate_scene_count"),
        message=(
            "phase1a candidate scene count expected within "
            f"1..{max_candidate_scenes}, got {result.get('candidate_scene_count')}"
        ),
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase1a_no_scene_commit",
        ok=int(output_counts.get("scene_count", 0) or 0) == 0,
        expected=0,
        actual=output_counts.get("scene_count"),
        message=(
            "phase1a-only expected no committed scenes, got "
            f"{output_counts.get('scene_count')}"
        ),
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase1a_no_phase2_or_phase3_outputs",
        ok=int(output_counts.get("entity_count", 0) or 0) == 0
        and int(output_counts.get("relation_count", 0) or 0) == 0
        and all(
            int(count or 0) == 0
            for count in (output_counts.get("structure_counts") or {}).values()
        ),
        expected="no entity/relation/structure outputs",
        actual=output_counts,
        message="phase1a-only unexpectedly wrote later phase outputs",
    )
    return checks, issues


def _phase1b_only_acceptance_checks(
    *,
    result: dict[str, Any],
    output_counts: dict[str, Any],
    coverage: dict[str, Any],
    expected_phase_shape: dict[str, Any],
    expected_chapter_count: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    checks: list[dict[str, Any]] = []
    issues: list[str] = []
    phase1a_stats = result.get("phase1a_quality_stats") or {}
    phase1b_stats = result.get("quality_stats") or {}
    missing_chapters = coverage.get("missing_chapters") or []
    max_candidates = expected_chapter_count * 4

    for key in ("failed", "timeout", "schema_error", "degraded_fallback"):
        _record_acceptance_check(
            checks,
            issues,
            name=f"phase1a_source_no_{key}",
            ok=int(phase1a_stats.get(key, 0) or 0) == 0,
            expected=0,
            actual=phase1a_stats.get(key),
            message=f"phase1a source {key} expected 0, got {phase1a_stats.get(key)}",
        )
    _record_acceptance_check(
        checks,
        issues,
        name="phase1b_not_blocked",
        ok=result.get("blocked") is False,
        expected=False,
        actual=result.get("blocked"),
        message=f"phase1b expected blocked false, got {result.get('blocked')}",
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase1b_not_degraded",
        ok=result.get("degraded") is False,
        expected=False,
        actual=result.get("degraded"),
        message=f"phase1b expected degraded false, got {result.get('degraded')}",
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase1b_no_phase1a_fallback",
        ok=result.get("phase1a_fallback") is False,
        expected=False,
        actual=result.get("phase1a_fallback"),
        message=(
            "phase1b expected phase1a_fallback false, got "
            f"{result.get('phase1a_fallback')}"
        ),
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase1b_total_windows",
        ok=phase1b_stats.get("total_windows")
        == expected_phase_shape.get("phase1b_total_windows"),
        expected=expected_phase_shape.get("phase1b_total_windows"),
        actual=phase1b_stats.get("total_windows"),
        message=(
            "phase1b total_windows expected "
            f"{expected_phase_shape.get('phase1b_total_windows')}, "
            f"got {phase1b_stats.get('total_windows')}"
        ),
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase1b_completed_all_windows",
        ok=phase1b_stats.get("completed_windows")
        == phase1b_stats.get("total_windows"),
        expected=phase1b_stats.get("total_windows"),
        actual=phase1b_stats.get("completed_windows"),
        message=(
            "phase1b completed_windows expected total_windows "
            f"{phase1b_stats.get('total_windows')}, got "
            f"{phase1b_stats.get('completed_windows')}"
        ),
    )
    for key in ("failed", "timeout", "schema_error"):
        _record_acceptance_check(
            checks,
            issues,
            name=f"phase1b_no_{key}",
            ok=int(phase1b_stats.get(key, 0) or 0) == 0,
            expected=0,
            actual=phase1b_stats.get(key),
            message=f"phase1b {key} expected 0, got {phase1b_stats.get(key)}",
        )
    _record_acceptance_check(
        checks,
        issues,
        name="phase1b_candidate_chapter_coverage_complete",
        ok=not missing_chapters
        and coverage.get("candidates_with_chapter_ids", 0) > 0,
        expected=list(range(1, expected_chapter_count + 1)),
        actual=coverage,
        message=(
            "phase1b candidate chapter coverage missing chapters: "
            f"{missing_chapters}"
        ),
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase1b_candidate_count_reasonable",
        ok=0 < int(result.get("candidate_count", 0) or 0) <= max_candidates,
        expected=f"1..{max_candidates}",
        actual=result.get("candidate_count"),
        message=(
            "phase1b candidate count expected within "
            f"1..{max_candidates}, got {result.get('candidate_count')}"
        ),
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase1b_no_scene_commit",
        ok=int(output_counts.get("scene_count", 0) or 0) == 0,
        expected=0,
        actual=output_counts.get("scene_count"),
        message=(
            "phase1b-only expected no committed scenes, got "
            f"{output_counts.get('scene_count')}"
        ),
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase1b_no_phase2_or_phase3_outputs",
        ok=int(output_counts.get("entity_count", 0) or 0) == 0
        and int(output_counts.get("relation_count", 0) or 0) == 0
        and all(
            int(count or 0) == 0
            for count in (output_counts.get("structure_counts") or {}).values()
        ),
        expected="no entity/relation/structure outputs",
        actual=output_counts,
        message="phase1b-only unexpectedly wrote later phase outputs",
    )
    return checks, issues


def _phase2a_only_acceptance_checks(
    *,
    result: dict[str, Any],
    output_counts: dict[str, Any],
    scene_coverage: dict[str, Any],
    expected_chapter_count: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    checks: list[dict[str, Any]] = []
    issues: list[str] = []
    phase1b_stats = result.get("source_phase1b_quality_stats") or {}
    phase2 = result.get("quality_stats") or {}
    scene_commit = result.get("scene_commit") or {}
    checkpoint_counts = phase2.get("checkpoint_status_counts") or {}
    missing_chapters = scene_coverage.get("missing_chapters") or []
    scene_commit_count = int(scene_commit.get("created_count", 0) or 0) + int(
        scene_commit.get("skipped_count", 0) or 0
    )

    for key in ("failed", "timeout", "schema_error"):
        _record_acceptance_check(
            checks,
            issues,
            name=f"source_phase1b_no_{key}",
            ok=int(phase1b_stats.get(key, 0) or 0) == 0,
            expected=0,
            actual=phase1b_stats.get(key),
            message=f"source phase1b {key} expected 0, got {phase1b_stats.get(key)}",
        )
    _record_acceptance_check(
        checks,
        issues,
        name="source_phase1b_not_degraded",
        ok=result.get("source_phase1b_degraded") is False,
        expected=False,
        actual=result.get("source_phase1b_degraded"),
        message=(
            "source phase1b degraded expected false, got "
            f"{result.get('source_phase1b_degraded')}"
        ),
    )
    _record_acceptance_check(
        checks,
        issues,
        name="scene_commit_positive",
        ok=scene_commit_count > 0 and int(output_counts.get("scene_count", 0) or 0) > 0,
        expected="scene commit count > 0",
        actual={
            "scene_commit_count": scene_commit_count,
            "scene_count": output_counts.get("scene_count"),
        },
        message=(
            "phase2a expected committed scenes > 0, got "
            f"{scene_commit_count} / stored {output_counts.get('scene_count')}"
        ),
    )
    _record_acceptance_check(
        checks,
        issues,
        name="scene_chapter_coverage_complete",
        ok=not missing_chapters,
        expected=list(range(1, expected_chapter_count + 1)),
        actual=scene_coverage,
        message=f"phase2a scene coverage missing chapters: {missing_chapters}",
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase2a_total_scenes_positive",
        ok=int(phase2.get("total_scenes", 0) or 0) > 0,
        expected="> 0",
        actual=phase2.get("total_scenes"),
        message=f"phase2a total_scenes expected > 0, got {phase2.get('total_scenes')}",
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase2a_completed_all_scenes",
        ok=phase2.get("completed_scenes") == phase2.get("total_scenes"),
        expected=phase2.get("total_scenes"),
        actual=phase2.get("completed_scenes"),
        message=(
            "phase2a completed_scenes expected total_scenes "
            f"{phase2.get('total_scenes')}, got {phase2.get('completed_scenes')}"
        ),
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase2a_no_failed_scenes",
        ok=int(phase2.get("failed_scene_count", 0) or 0) == 0,
        expected=0,
        actual=phase2.get("failed_scene_count"),
        message=(
            "phase2a failed_scene_count expected 0, got "
            f"{phase2.get('failed_scene_count')}"
        ),
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase2a_no_failed_batches",
        ok=not (phase2.get("phase2_failed_batches") or []),
        expected=[],
        actual=phase2.get("phase2_failed_batches"),
        message=(
            "phase2a failed batches expected [], got "
            f"{phase2.get('phase2_failed_batches')}"
        ),
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase2a_no_error_kind",
        ok=phase2.get("error_kind") is None,
        expected=None,
        actual=phase2.get("error_kind"),
        message=f"phase2a error_kind expected None, got {phase2.get('error_kind')}",
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase2a_created_entities_positive",
        ok=int(phase2.get("total_created", 0) or 0) > 0
        and int(output_counts.get("entity_count", 0) or 0) > 0,
        expected="total_created/entity_count > 0",
        actual={
            "total_created": phase2.get("total_created"),
            "entity_count": output_counts.get("entity_count"),
        },
        message=(
            "phase2a expected entity outputs > 0, got "
            f"{phase2.get('total_created')} / {output_counts.get('entity_count')}"
        ),
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase2a_checkpoint_covers_scenes",
        ok=sum(int(value or 0) for value in checkpoint_counts.values())
        >= int(phase2.get("total_scenes", 0) or 0),
        expected="checkpoint count >= total_scenes",
        actual={
            "checkpoint_status_counts": checkpoint_counts,
            "total_scenes": phase2.get("total_scenes"),
        },
        message="phase2a checkpoint coverage is incomplete",
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase2a_snapshot_or_audit_present",
        ok=bool(
            (result.get("phase2_result") or {}).get("snapshot_health_summary")
            or (result.get("phase2_result") or {}).get("audit_summary")
        ),
        expected="snapshot_health_summary or audit_summary present",
        actual={
            "has_snapshot_health_summary": bool(
                (result.get("phase2_result") or {}).get("snapshot_health_summary")
            ),
            "has_audit_summary": bool(
                (result.get("phase2_result") or {}).get("audit_summary")
            ),
        },
        message="phase2a expected snapshot health or audit summary",
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase2a_phase2b_skipped",
        ok=int(phase2.get("total_aliases", 0) or 0) == 0
        and int(phase2.get("alias_relation_scenes", 0) or 0) == 0
        and not (phase2.get("alias_relation_failed_scenes") or []),
        expected="Phase2b alias/relation zero",
        actual={
            "total_aliases": phase2.get("total_aliases"),
            "alias_relation_scenes": phase2.get("alias_relation_scenes"),
            "alias_relation_failed_scenes": phase2.get(
                "alias_relation_failed_scenes"
            ),
        },
        message="phase2a-only unexpectedly ran or failed Phase2b alias/relation",
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase2a_no_phase3_outputs",
        ok=all(
            int(count or 0) == 0
            for count in (output_counts.get("structure_counts") or {}).values()
        ),
        expected="no structure outputs",
        actual=output_counts.get("structure_counts"),
        message="phase2a-only unexpectedly wrote Phase3 structure outputs",
    )
    return checks, issues


def _phase2b_only_acceptance_checks(
    *,
    result: dict[str, Any],
    output_counts: dict[str, Any],
    scene_coverage: dict[str, Any],
    expected_chapter_count: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    checks: list[dict[str, Any]] = []
    issues: list[str] = []
    phase2a_stats = result.get("source_phase2a_quality_stats") or {}
    phase2b = result.get("phase2b_result") or {}
    hydrate_summary = result.get("hydrate_summary") or {}
    scene_commit = result.get("scene_commit") or {}
    missing_chapters = scene_coverage.get("missing_chapters") or []
    scene_commit_count = int(scene_commit.get("created_count", 0) or 0) + int(
        scene_commit.get("skipped_count", 0) or 0
    )

    _record_acceptance_check(
        checks,
        issues,
        name="source_phase2a_passed",
        ok=int(phase2a_stats.get("total_scenes", 0) or 0) > 0
        and phase2a_stats.get("completed_scenes") == phase2a_stats.get("total_scenes")
        and int(phase2a_stats.get("failed_scene_count", 0) or 0) == 0
        and not (phase2a_stats.get("phase2_failed_batches") or [])
        and phase2a_stats.get("error_kind") is None
        and int(phase2a_stats.get("total_created", 0) or 0) > 0,
        expected="passed Phase2a artifact",
        actual=phase2a_stats,
        message="source phase2a artifact is not passed",
    )
    _record_acceptance_check(
        checks,
        issues,
        name="source_phase2a_hydratable",
        ok=result.get("source_phase2a_has_world_snapshot") is True,
        expected=True,
        actual=result.get("source_phase2a_has_world_snapshot"),
        message="source phase2a artifact missing hydratable world snapshot",
    )
    _record_acceptance_check(
        checks,
        issues,
        name="scene_commit_positive",
        ok=scene_commit_count > 0 and int(output_counts.get("scene_count", 0) or 0) > 0,
        expected="scene commit count > 0",
        actual={
            "scene_commit_count": scene_commit_count,
            "scene_count": output_counts.get("scene_count"),
        },
        message="phase2b expected committed scenes > 0",
    )
    _record_acceptance_check(
        checks,
        issues,
        name="scene_chapter_coverage_complete",
        ok=not missing_chapters,
        expected=list(range(1, expected_chapter_count + 1)),
        actual=scene_coverage,
        message=f"phase2b scene coverage missing chapters: {missing_chapters}",
    )
    _record_acceptance_check(
        checks,
        issues,
        name="world_hydration_positive",
        ok=int(hydrate_summary.get("created_entities", 0) or 0) > 0
        and int(output_counts.get("entity_count", 0) or 0) > 0,
        expected="hydrated entities > 0",
        actual={
            "hydrate_summary": hydrate_summary,
            "entity_count": output_counts.get("entity_count"),
        },
        message="phase2b expected hydrated world objects > 0",
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase2b_total_scenes_positive",
        ok=int(phase2b.get("total_scenes", 0) or 0) > 0,
        expected="> 0",
        actual=phase2b.get("total_scenes"),
        message=f"phase2b total_scenes expected > 0, got {phase2b.get('total_scenes')}",
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase2b_completed_all_scenes",
        ok=phase2b.get("alias_relation_scenes") == phase2b.get("total_scenes"),
        expected=phase2b.get("total_scenes"),
        actual=phase2b.get("alias_relation_scenes"),
        message=(
            "phase2b alias_relation_scenes expected total_scenes "
            f"{phase2b.get('total_scenes')}, got {phase2b.get('alias_relation_scenes')}"
        ),
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase2b_no_failed_scenes",
        ok=not (phase2b.get("alias_relation_failed_scenes") or []),
        expected=[],
        actual=phase2b.get("alias_relation_failed_scenes"),
        message=(
            "phase2b failed scenes expected [], got "
            f"{phase2b.get('alias_relation_failed_scenes')}"
        ),
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase2b_not_degraded",
        ok=phase2b.get("degraded") is False,
        expected=False,
        actual=phase2b.get("degraded"),
        message=f"phase2b degraded expected false, got {phase2b.get('degraded')}",
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase2b_no_error_kind",
        ok=phase2b.get("error_kind") is None,
        expected=None,
        actual=phase2b.get("error_kind"),
        message=f"phase2b error_kind expected None, got {phase2b.get('error_kind')}",
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase2b_non_empty_output",
        ok=int(phase2b.get("total_aliases", 0) or 0)
        + int(phase2b.get("total_relations", 0) or 0)
        > 0,
        expected="aliases + relations > 0",
        actual={
            "total_aliases": phase2b.get("total_aliases"),
            "total_relations": phase2b.get("total_relations"),
        },
        message="phase2b expected aliases or relations > 0",
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase2b_no_phase3_outputs",
        ok=all(
            int(count or 0) == 0
            for count in (output_counts.get("structure_counts") or {}).values()
        ),
        expected="no structure outputs",
        actual=output_counts.get("structure_counts"),
        message="phase2b-only unexpectedly wrote Phase3 structure outputs",
    )
    return checks, issues


def _phase3_only_acceptance_checks(
    *,
    result: dict[str, Any],
    output_counts: dict[str, Any],
    scene_coverage: dict[str, Any],
    expected_chapter_count: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    checks: list[dict[str, Any]] = []
    issues: list[str] = []
    source_phase2b = result.get("source_phase2b_result") or {}
    phase3 = result.get("quality_stats") or {}
    hydrate_summary = result.get("hydrate_summary") or {}
    scene_commit = result.get("scene_commit") or {}
    structure_counts = output_counts.get("structure_counts") or {}
    missing_chapters = scene_coverage.get("missing_chapters") or []
    scene_commit_count = int(scene_commit.get("created_count", 0) or 0) + int(
        scene_commit.get("skipped_count", 0) or 0
    )

    _record_acceptance_check(
        checks,
        issues,
        name="source_phase2b_passed",
        ok=int(source_phase2b.get("total_scenes", 0) or 0) > 0
        and source_phase2b.get("alias_relation_scenes")
        == source_phase2b.get("total_scenes")
        and not (source_phase2b.get("alias_relation_failed_scenes") or [])
        and source_phase2b.get("degraded") is False
        and source_phase2b.get("error_kind") is None,
        expected="passed Phase2b artifact",
        actual=source_phase2b,
        message="source phase2b artifact is not passed",
    )
    _record_acceptance_check(
        checks,
        issues,
        name="source_phase2b_hydratable",
        ok=result.get("source_phase2b_has_world_snapshot") is True,
        expected=True,
        actual=result.get("source_phase2b_has_world_snapshot"),
        message="source phase2b artifact missing hydratable world snapshot",
    )
    _record_acceptance_check(
        checks,
        issues,
        name="scene_commit_positive",
        ok=scene_commit_count > 0 and int(output_counts.get("scene_count", 0) or 0) > 0,
        expected="scene commit count > 0",
        actual={
            "scene_commit_count": scene_commit_count,
            "scene_count": output_counts.get("scene_count"),
        },
        message="phase3 expected committed scenes > 0",
    )
    _record_acceptance_check(
        checks,
        issues,
        name="scene_chapter_coverage_complete",
        ok=not missing_chapters,
        expected=list(range(1, expected_chapter_count + 1)),
        actual=scene_coverage,
        message=f"phase3 scene coverage missing chapters: {missing_chapters}",
    )
    _record_acceptance_check(
        checks,
        issues,
        name="world_hydration_positive",
        ok=int(hydrate_summary.get("created_entities", 0) or 0) > 0
        and int(output_counts.get("entity_count", 0) or 0) > 0,
        expected="hydrated entities > 0",
        actual={
            "hydrate_summary": hydrate_summary,
            "entity_count": output_counts.get("entity_count"),
        },
        message="phase3 expected hydrated world objects > 0",
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase3_done",
        ok=result.get("phase") == "done" and result.get("quality_status") == "complete",
        expected={"phase": "done", "quality_status": "complete"},
        actual={
            "phase": result.get("phase"),
            "quality_status": result.get("quality_status"),
        },
        message="phase3 progress did not complete cleanly",
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase3_completed_step",
        ok="structure_analysis" in (result.get("completed_steps") or []),
        expected="structure_analysis in completed_steps",
        actual=result.get("completed_steps"),
        message="phase3 completed_steps missing structure_analysis",
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase3_not_degraded",
        ok=result.get("degraded") is False,
        expected=False,
        actual=result.get("degraded"),
        message=f"phase3 degraded expected false, got {result.get('degraded')}",
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase3_no_error_kind",
        ok=phase3.get("error_kind") is None and not (result.get("phase_errors") or []),
        expected="no error_kind and no phase_errors",
        actual={"phase3": phase3, "phase_errors": result.get("phase_errors")},
        message="phase3 produced error_kind or phase_errors",
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase3_structure_output",
        ok=all(
            int(structure_counts.get(name, 0) or 0) >= minimum
            for name, minimum in minimum_structure_category_targets(
                expected_chapter_count
            ).items()
        ),
        expected=minimum_structure_category_targets(expected_chapter_count),
        actual=structure_counts,
        message=(
            "phase3 structure counts below expected minimums: "
            f"{structure_counts}"
        ),
    )
    return checks, issues


def _scene_only_acceptance_checks(
    *,
    result: dict[str, Any],
    output_counts: dict[str, Any],
    coverage: dict[str, Any],
    expected_chapter_count: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    checks: list[dict[str, Any]] = []
    issues: list[str] = []
    completed_steps = result.get("completed_steps") or []
    timeline_phases = [
        str(item.get("phase") or "")
        for item in (result.get("phase_timeline") or [])
        if isinstance(item, dict)
    ]
    quality_stats = result.get("quality_stats") or {}
    scene_commit = quality_stats.get("scene_commit") or {}
    phase1a = quality_stats.get("phase1a") or {}
    scene_commit_count = int(scene_commit.get("created_count", 0) or 0) + int(
        scene_commit.get("skipped_count", 0) or 0
    )
    missing_chapters = coverage.get("missing_chapters") or []

    _record_acceptance_check(
        checks,
        issues,
        name="scene_only_phase_done",
        ok=result.get("phase") == "done",
        expected="done",
        actual=result.get("phase"),
        message=f"scene-only phase expected done, got {result.get('phase')}",
    )
    _record_acceptance_check(
        checks,
        issues,
        name="scene_only_completed_steps",
        ok=completed_steps == ["scene_segmentation"],
        expected=["scene_segmentation"],
        actual=completed_steps,
        message=f"scene-only completed_steps mismatch: {completed_steps}",
    )
    _record_acceptance_check(
        checks,
        issues,
        name="scene_only_did_not_enter_later_phases",
        ok=not {"entity_extraction", "structure_analysis"}.intersection(
            timeline_phases
        ),
        expected="no entity_extraction or structure_analysis phase",
        actual=timeline_phases,
        message=f"scene-only entered later phases: {timeline_phases}",
    )
    _record_acceptance_check(
        checks,
        issues,
        name="scene_commit_positive",
        ok=scene_commit_count > 0 and int(output_counts.get("scene_count", 0) or 0) > 0,
        expected="scene commit and stored scene counts > 0",
        actual={
            "scene_commit_count": scene_commit_count,
            "scene_count": output_counts.get("scene_count"),
        },
        message=(
            "scene-only expected committed scenes > 0, got "
            f"{scene_commit_count} / stored {output_counts.get('scene_count')}"
        ),
    )
    _record_acceptance_check(
        checks,
        issues,
        name="scene_chapter_coverage_complete",
        ok=not missing_chapters,
        expected=list(range(1, expected_chapter_count + 1)),
        actual=coverage,
        message=f"scene chapter coverage missing chapters: {missing_chapters}",
    )
    _record_acceptance_check(
        checks,
        issues,
        name="phase1a_no_failed_batches",
        ok=int(phase1a.get("failed", 0) or 0) == 0,
        expected=0,
        actual=phase1a.get("failed"),
        message=f"phase1a failed batches expected 0, got {phase1a.get('failed')}",
    )
    return checks, issues


def _result_log_payload(result: dict[str, Any]) -> dict[str, Any]:
    phase2_stats = (result.get("quality_stats") or {}).get("phase2") or {}
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
        "phase2b": {
            "total_aliases": phase2_stats.get("total_aliases"),
            "total_relations": phase2_stats.get("total_relations"),
            "alias_relation_scenes": phase2_stats.get("alias_relation_scenes"),
            "alias_relation_failed_scenes": phase2_stats.get(
                "alias_relation_failed_scenes",
            ),
        },
        **_phase2_diagnostics_payload(phase2_stats),
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
    relation_count = await _count_by_novel(db, EntityRelation, novel_id)
    alias_counts = await _alias_counts_by_novel(db, project_id)
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
        "relation_count": relation_count,
        **alias_counts,
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
        "relation_status_counts": await _group_count_by_novel(
            db,
            EntityRelation,
            novel_id,
            EntityRelation.status,
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


async def _scene_chapter_coverage(
    db: AsyncSession,
    project_id: uuid.UUID,
    *,
    start_chapter: int,
    end_chapter: int,
) -> dict[str, Any]:
    result = await db.execute(
        select(Scene.chapter_ids).where(Scene.novel_id == project_id)
    )
    covered: set[int] = set()
    duplicate: set[int] = set()
    for chapter_ids in result.scalars().all():
        seen_in_scene: set[int] = set()
        for raw_chapter_id in chapter_ids or []:
            try:
                chapter_index = int(raw_chapter_id)
            except (TypeError, ValueError):
                continue
            if chapter_index in seen_in_scene or chapter_index in covered:
                duplicate.add(chapter_index)
            seen_in_scene.add(chapter_index)
            covered.add(chapter_index)
    expected = set(range(start_chapter, end_chapter + 1))
    return {
        "expected_chapters": sorted(expected),
        "covered_chapters": sorted(covered.intersection(expected)),
        "missing_chapters": sorted(expected - covered),
        "extra_chapters": sorted(covered - expected),
        "duplicate_chapters": sorted(duplicate),
        "coverage_ratio": (
            round(len(covered.intersection(expected)) / len(expected), 4)
            if expected
            else 1.0
        ),
    }


def _build_scene_only_task(project_id: uuid.UUID) -> AsyncTask:
    return AsyncTask(
        id=uuid.uuid4(),
        task_type="scene_auto_extraction",
        status="pending",
        meta={
            "novel_id": str(project_id),
            "start_chapter": 1,
            "end_chapter": EXPECTED_CHAPTER_COUNT,
            "stage": "scenes",
            "context_mode": "working",
            "include_pending_objects": True,
        },
        progress=0.0,
    )


@pytest.mark.asyncio
async def test_real_llm_log_output_counts_include_phase2b_alias_relations(
    db_session: AsyncSession,
) -> None:
    project_id = uuid.uuid4()
    db_session.add(
        Project(
            id=project_id,
            title="Phase 2b 日志计数测试",
            language="zh",
        )
    )
    source_id = uuid.uuid4()
    target_id = uuid.uuid4()
    db_session.add_all(
        [
            CoreEntity(
                id=source_id,
                novel_id=project_id,
                entity_type="character",
                name="克莱恩",
                status="candidate",
                content_json={
                    "aliases": [
                        {
                            "alias": "周明瑞",
                            "status": "candidate",
                            "source": "deep_import",
                            "needs_review": True,
                        },
                        {"alias": "小克", "type": "nickname"},
                    ]
                },
            ),
            CoreEntity(
                id=target_id,
                novel_id=project_id,
                entity_type="character",
                name="梅丽莎",
                status="candidate",
                content_json={"aliases": []},
            ),
            EntityRelation(
                novel_id=project_id,
                source_id=source_id,
                target_id=target_id,
                relation_type="sibling",
                status="candidate",
            ),
        ]
    )
    await db_session.flush()

    output_counts = await _count_acceptance_outputs(db_session, project_id)

    assert output_counts["entity_count"] == 2
    assert output_counts["relation_count"] == 1
    assert output_counts["relation_status_counts"] == {"candidate": 1}
    assert output_counts["total_alias_count"] == 2
    assert output_counts["candidate_alias_count"] == 1
    assert output_counts["deep_import_alias_count"] == 1
    assert output_counts["needs_review_alias_count"] == 1


def test_phase2_batch_tuning_summary_writes_markdown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary_path = tmp_path / "phase2_batch_tuning.md"
    log_path = tmp_path / "deep_import_60_8x8.jsonl"
    monkeypatch.setenv("PHASE2_BATCH_TUNING_GROUP", "8x8")
    monkeypatch.setenv("PHASE2_BATCH_TUNING_SUMMARY_PATH", str(summary_path))
    result = {
        "phase": "done",
        "quality_status": "complete",
        "quality_stats": {
            "phase2": {
                "phase2_batch_size_scenes": 8,
                "phase2_batch_concurrency": 8,
                "completed_scenes": 24,
                "failed_scene_count": 0,
                "phase2_low_confidence": 2,
                "phase2_boundary_supplement_counts": {"created": 1},
                "phase2_action_counts": {"create_new": 10},
                "phase2_dedup_counts": {"checked": 10, "skipped": 1},
                "degraded": False,
                "error_kind": None,
            }
        },
    }
    output_counts = {
        "entity_count": 10,
        "total_alias_count": 3,
        "relation_count": 2,
    }

    written = _write_phase2_batch_tuning_summary(
        log_path=log_path,
        wall_clock_s=12.34,
        result=result,
        output_counts=output_counts,
        issues=[],
    )

    assert written == summary_path
    text = summary_path.read_text(encoding="utf-8")
    assert "Phase 2 Batch Tuning Summary" in text
    assert "| 8x8 |" in text
    assert "| group | chapters | wall_clock_s |" in text


def _scene_only_result_fixture(
    *,
    phase: str = "done",
    completed_steps: list[str] | None = None,
    timeline_phases: list[str] | None = None,
    scene_count: int = 60,
    phase1a_failed: int = 0,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    completed_steps = completed_steps or ["scene_segmentation"]
    timeline_phases = timeline_phases or [
        "phase0_prefetch",
        "phase1a_reinforce",
        "phase1b_fusion",
        "scene_commit",
    ]
    result = {
        "phase": phase,
        "completed_steps": completed_steps,
        "phase_timeline": [{"phase": phase_name} for phase_name in timeline_phases],
        "quality_stats": {
            "phase1a": {"failed": phase1a_failed},
            "scene_commit": {"created_count": scene_count, "skipped_count": 0},
        },
    }
    output_counts = {"scene_count": scene_count}
    coverage = {
        "covered_chapters": list(range(1, 61)),
        "missing_chapters": [],
        "expected_chapters": list(range(1, 61)),
    }
    return result, output_counts, coverage


def _phase0_only_result_fixture(
    *,
    blocked: bool = False,
    total_batches: int = 24,
    completed_batches: int = 24,
    failed: int = 0,
    candidate_count: int = 24,
    scene_count: int = 0,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    result = {
        "blocked": blocked,
        "block_reason": "phase0_422_rate_exceeded" if blocked else None,
        "candidate_count": candidate_count,
        "quality_stats": {
            "total_batches": total_batches,
            "completed_batches": completed_batches,
            "failed": failed,
        },
        "later_phases": {
            "phase1a": "skipped",
            "phase1b": "skipped",
            "scene_commit": "skipped",
            "entity_extraction": "skipped",
            "structure_analysis": "skipped",
        },
    }
    output_counts = {
        "scene_count": scene_count,
        "entity_count": 0,
        "relation_count": 0,
        "structure_counts": {
            "threads": 0,
            "arcs": 0,
            "foreshadowing": 0,
            "reveals": 0,
        },
    }
    coverage = {
        "covered_chapters": list(range(1, 61)),
        "missing_chapters": [],
        "expected_chapters": list(range(1, 61)),
        "candidates_with_chapter_ids": candidate_count,
    }
    expected_phase_shape = {"phase0_total_batches": total_batches}
    return result, output_counts, coverage, expected_phase_shape


def _phase1a_only_result_fixture(
    *,
    phase0_failed: int = 0,
    blocked: bool = False,
    total_batches: int = 24,
    completed_batches: int = 24,
    failed: int = 0,
    timeout: int = 0,
    schema_error: int = 0,
    candidate_count: int = 24,
    candidate_scene_count: int = 180,
    scene_count: int = 0,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    result = {
        "blocked": blocked,
        "block_reason": "phase1a_422_rate_exceeded" if blocked else None,
        "phase0_candidate_count": 24,
        "phase0_quality_stats": {"failed": phase0_failed},
        "candidate_count": candidate_count,
        "candidate_scene_count": candidate_scene_count,
        "quality_stats": {
            "total_batches": total_batches,
            "completed_batches": completed_batches,
            "failed": failed,
            "timeout": timeout,
            "schema_error": schema_error,
        },
        "later_phases": {
            "phase1b": "skipped",
            "scene_commit": "skipped",
            "entity_extraction": "skipped",
            "structure_analysis": "skipped",
        },
    }
    output_counts = {
        "scene_count": scene_count,
        "entity_count": 0,
        "relation_count": 0,
        "structure_counts": {
            "threads": 0,
            "arcs": 0,
            "foreshadowing": 0,
            "reveals": 0,
        },
    }
    coverage = {
        "covered_chapters": list(range(1, 61)),
        "missing_chapters": [],
        "expected_chapters": list(range(1, 61)),
        "candidates_with_chapter_ids": candidate_count,
    }
    expected_phase_shape = {
        "phase0_total_batches": total_batches,
        "phase1a_total_batches": total_batches,
    }
    return result, output_counts, coverage, expected_phase_shape


def _phase1b_only_result_fixture(
    *,
    phase1a_failed: int = 0,
    blocked: bool = False,
    degraded: bool = False,
    phase1a_fallback: bool = False,
    total_windows: int = 2,
    completed_windows: int = 2,
    failed: int = 0,
    timeout: int = 0,
    schema_error: int = 0,
    candidate_count: int = 118,
    scene_count: int = 0,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    result = {
        "blocked": blocked,
        "degraded": degraded,
        "phase1a_fallback": phase1a_fallback,
        "block_reason": "phase1b_reducer_fallback" if degraded else None,
        "phase1a_candidate_count": 24,
        "phase1a_quality_stats": {
            "failed": phase1a_failed,
            "timeout": 0,
            "schema_error": 0,
            "degraded_fallback": 0,
        },
        "candidate_count": candidate_count,
        "quality_stats": {
            "total_windows": total_windows,
            "completed_windows": completed_windows,
            "failed": failed,
            "timeout": timeout,
            "schema_error": schema_error,
        },
        "later_phases": {
            "scene_commit": "skipped",
            "entity_extraction": "skipped",
            "structure_analysis": "skipped",
        },
    }
    output_counts = {
        "scene_count": scene_count,
        "entity_count": 0,
        "relation_count": 0,
        "structure_counts": {
            "threads": 0,
            "arcs": 0,
            "foreshadowing": 0,
            "reveals": 0,
        },
    }
    coverage = {
        "covered_chapters": list(range(1, 61)),
        "missing_chapters": [],
        "expected_chapters": list(range(1, 61)),
        "candidates_with_chapter_ids": candidate_count,
    }
    expected_phase_shape = {"phase1b_total_windows": total_windows}
    return result, output_counts, coverage, expected_phase_shape


def _phase2a_only_result_fixture(
    *,
    source_phase1b_failed: int = 0,
    source_phase1b_degraded: bool = False,
    scene_count: int = 60,
    entity_count: int = 12,
    total_scenes: int = 60,
    completed_scenes: int = 60,
    failed_scene_indices: list[int] | None = None,
    failed_batches: list[str] | None = None,
    error_kind: str | None = None,
    total_created: int = 12,
    total_aliases: int = 0,
    alias_relation_scenes: int = 0,
    alias_relation_failed_scenes: list[int] | None = None,
    missing_chapters: list[int] | None = None,
    structure_count: int = 0,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    failed_scene_indices = failed_scene_indices or []
    result = {
        "source_phase1b_candidate_count": 60,
        "source_phase1b_quality_stats": {
            "total_windows": 6,
            "completed_windows": 6,
            "failed": source_phase1b_failed,
            "timeout": 0,
            "schema_error": 0,
        },
        "source_phase1b_degraded": source_phase1b_degraded,
        "source_phase1b_phase1a_fallback": False,
        "source_phase1b_blocked": False,
        "scene_commit": {
            "created_count": scene_count,
            "skipped_count": 0,
            "conflict_count": 0,
        },
        "quality_stats": {
            "total_created": total_created,
            "total_relations": 0,
            "total_aliases": total_aliases,
            "total_deltas": total_created,
            "total_scenes": total_scenes,
            "completed_scenes": completed_scenes,
            "alias_relation_scenes": alias_relation_scenes,
            "alias_relation_failed_scenes": alias_relation_failed_scenes or [],
            "failed_scene_count": len(failed_scene_indices),
            "phase2_failed_batches": failed_batches or [],
            "phase2_degraded_batches": [],
            "degraded": bool(failed_scene_indices or failed_batches or error_kind),
            "error_kind": error_kind,
            "checkpoint_status_counts": {"completed": completed_scenes},
        },
        "phase2_result": {
            "failed_scene_indices": failed_scene_indices,
            "snapshot_health_summary": {"status": "healthy"},
        },
        "later_phases": {
            "phase2b": "skipped",
            "structure_analysis": "skipped",
        },
    }
    output_counts = {
        "scene_count": scene_count,
        "entity_count": entity_count,
        "relation_count": 0,
        "structure_counts": {
            "threads": structure_count,
            "arcs": 0,
            "foreshadowing": 0,
            "reveals": 0,
        },
    }
    missing_chapters = missing_chapters or []
    covered_chapters = [
        chapter for chapter in range(1, 61) if chapter not in set(missing_chapters)
    ]
    coverage = {
        "covered_chapters": covered_chapters,
        "missing_chapters": missing_chapters,
        "expected_chapters": list(range(1, 61)),
        "coverage_ratio": (
            1.0 if not missing_chapters else round(len(covered_chapters) / 60, 4)
        ),
    }
    return result, output_counts, coverage


def _phase2b_only_result_fixture(
    *,
    source_phase2a_failed: bool = False,
    has_world_snapshot: bool = True,
    scene_count: int = 60,
    entity_count: int = 292,
    alias_count: int = 220,
    relation_count: int = 380,
    total_scenes: int = 60,
    alias_relation_scenes: int = 60,
    failed_scenes: list[int] | None = None,
    degraded: bool = False,
    error_kind: str | None = None,
    total_aliases: int = 20,
    total_relations: int = 29,
    missing_chapters: list[int] | None = None,
    structure_count: int = 0,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    source_phase2a_quality = {
        "total_scenes": 60,
        "completed_scenes": 59 if source_phase2a_failed else 60,
        "failed_scene_count": 1 if source_phase2a_failed else 0,
        "phase2_failed_batches": ["batch-1"] if source_phase2a_failed else [],
        "error_kind": "schema_validation" if source_phase2a_failed else None,
        "total_created": 292,
    }
    result = {
        "source_phase2a_quality_stats": source_phase2a_quality,
        "source_phase2a_output_counts": {"entity_count": 292, "relation_count": 351},
        "source_phase2a_has_world_snapshot": has_world_snapshot,
        "scene_commit": {
            "created_count": scene_count,
            "skipped_count": 0,
            "conflict_count": 0,
        },
        "hydrate_summary": {
            "source_entity_count": 292,
            "source_relation_count": 351,
            "created_entities": entity_count,
            "created_relations": 351 if entity_count else 0,
            "skipped_relations": 0,
        },
        "phase2b_result": {
            "total_aliases": total_aliases,
            "total_relations": total_relations,
            "total_scenes": total_scenes,
            "alias_relation_scenes": alias_relation_scenes,
            "alias_relation_failed_scenes": failed_scenes or [],
            "degraded": degraded,
            "error_kind": error_kind,
            "error_message": None,
            "alias_relation_elapsed_s": 120.0,
            "alias_relation_total_timeout_s": 2085,
            "alias_relation_concurrency": 4,
        },
        "quality_stats": {},
        "later_phases": {"structure_analysis": "skipped"},
    }
    output_counts = {
        "scene_count": scene_count,
        "entity_count": entity_count,
        "relation_count": relation_count,
        "total_alias_count": alias_count,
        "structure_counts": {
            "threads": structure_count,
            "arcs": 0,
            "foreshadowing": 0,
            "reveals": 0,
        },
    }
    missing_chapters = missing_chapters or []
    covered_chapters = [
        chapter for chapter in range(1, 61) if chapter not in set(missing_chapters)
    ]
    coverage = {
        "covered_chapters": covered_chapters,
        "missing_chapters": missing_chapters,
        "expected_chapters": list(range(1, 61)),
        "coverage_ratio": (
            1.0 if not missing_chapters else round(len(covered_chapters) / 60, 4)
        ),
    }
    return result, output_counts, coverage


@pytest.mark.parametrize(
    ("env_var", "enabled_fn"),
    [
        ("RUN_DEEP_IMPORT_60_PHASE0_REAL_LLM", _phase0_real_llm_enabled),
        ("RUN_DEEP_IMPORT_60_PHASE1A_REAL_LLM", _phase1a_real_llm_enabled),
        ("RUN_DEEP_IMPORT_60_PHASE1B_REAL_LLM", _phase1b_real_llm_enabled),
        ("RUN_DEEP_IMPORT_60_PHASE2A_REAL_LLM", _phase2a_real_llm_enabled),
        ("RUN_DEEP_IMPORT_60_PHASE2B_REAL_LLM", _phase2b_real_llm_enabled),
    ],
)
def test_phase_real_llm_enabled_helpers(
    monkeypatch: pytest.MonkeyPatch,
    env_var: str,
    enabled_fn,
) -> None:
    monkeypatch.delenv(env_var, raising=False)
    assert enabled_fn() is False

    monkeypatch.setenv(env_var, "1")
    assert enabled_fn() is True


def test_candidate_chapter_coverage_from_phase0_candidates() -> None:
    candidates = [
        {"source_chapter_indices": [1, 2, 3]},
        {"source_chapter_indices": [3, 4, 5]},
    ]

    coverage = _candidate_chapter_coverage(
        candidates,
        start_chapter=1,
        end_chapter=5,
    )

    assert coverage["covered_chapters"] == [1, 2, 3, 4, 5]
    assert coverage["missing_chapters"] == []
    assert coverage["duplicate_chapters"] == [3]
    assert coverage["candidates_with_chapter_ids"] == 2


def test_phase0_only_acceptance_passes_for_phase0_only_result() -> None:
    result, output_counts, coverage, expected_phase_shape = (
        _phase0_only_result_fixture()
    )

    checks, issues = _phase0_only_acceptance_checks(
        result=result,
        output_counts=output_counts,
        coverage=coverage,
        expected_phase_shape=expected_phase_shape,
        expected_chapter_count=60,
    )

    assert issues == []
    assert {check["status"] for check in checks} == {"passed"}


@pytest.mark.parametrize(
    ("mutator", "expected_issue"),
    [
        (
            lambda result, _counts, _coverage: result.update({"blocked": True}),
            "phase0 expected blocked false, got True",
        ),
        (
            lambda result, _counts, _coverage: result["quality_stats"].update(
                {"completed_batches": 23}
            ),
            "phase0 completed_batches expected total_batches",
        ),
        (
            lambda result, _counts, _coverage: result["quality_stats"].update(
                {"failed": 1}
            ),
            "phase0 failed batches expected 0, got 1",
        ),
        (
            lambda _result, _counts, coverage: coverage.update(
                {"covered_chapters": list(range(1, 60)), "missing_chapters": [60]}
            ),
            "phase0 candidate chapter coverage missing chapters",
        ),
        (
            lambda _result, _counts, coverage: coverage.update(
                {"covered_chapters": [], "candidates_with_chapter_ids": 0}
            ),
            "phase0 candidate chapter coverage missing chapters or source ids",
        ),
        (
            lambda _result, counts, _coverage: counts.update({"scene_count": 1}),
            "phase0-only expected no committed scenes, got 1",
        ),
    ],
)
def test_phase0_only_acceptance_reports_guardrail_failures(
    mutator,
    expected_issue: str,
) -> None:
    result, output_counts, coverage, expected_phase_shape = (
        _phase0_only_result_fixture()
    )
    mutator(result, output_counts, coverage)

    _checks, issues = _phase0_only_acceptance_checks(
        result=result,
        output_counts=output_counts,
        coverage=coverage,
        expected_phase_shape=expected_phase_shape,
        expected_chapter_count=60,
    )

    assert any(expected_issue in issue for issue in issues)


def test_phase0_summary_writes_markdown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary_path = tmp_path / "phase0_real_llm.md"
    log_path = tmp_path / "deep_import_60_phase0_20260702T000000Z.jsonl"
    monkeypatch.setenv("PHASE0_REAL_LLM_SUMMARY_PATH", str(summary_path))
    result, output_counts, coverage, expected_phase_shape = (
        _phase0_only_result_fixture()
    )

    written = _write_phase0_summary(
        log_path=log_path,
        wall_clock_s=123.45,
        result=result,
        output_counts=output_counts,
        coverage=coverage,
        expected_phase_shape=expected_phase_shape,
        issues=[],
        llm_config={"effective_llm_profile": {"model": "deepseek-v4-flash"}},
    )

    assert written == summary_path
    text = summary_path.read_text(encoding="utf-8")
    assert "Phase 0 Real LLM Summary" in text
    assert "| test_mode | stage | chapters |" in text
    assert "| phase0_only | phase0_prefetch | 60 |" in text
    assert "deepseek-v4-flash" in text


def test_phase0_artifact_round_trips_scene_prefetch_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_path = tmp_path / "phase0.artifact.json"
    log_path = tmp_path / "deep_import_60_phase0_20260702T000000Z.jsonl"
    project_id = uuid.uuid4()
    task_id = uuid.uuid4()
    monkeypatch.setenv("PHASE0_REAL_LLM_ARTIFACT_PATH", str(artifact_path))
    phase0_result = ScenePrefetchResult(
        candidates=[
            SceneCandidate(
                candidate_id="phase0-A-0001",
                source_round="A",
                source_batch_id="A-0001-1-5",
                source_batch_index=1,
                source_chapter_indices=[1, 2, 3, 4, 5],
                quality="high",
                payload={"scenes": [{"title": "候选"}]},
            )
        ],
        quality_stats={"total_batches": 24, "failed": 0},
        diagnostics=[{"final_status": "success"}],
        blocked=False,
    )

    written = _write_phase0_artifact(
        log_path=log_path,
        phase0_result=phase0_result,
        coverage={"covered_chapters": [1, 2, 3, 4, 5]},
        expected_phase_shape={"phase0_total_batches": 24},
        llm_config={"effective_llm_profile": {"model": "deepseek-v4-flash"}},
        project_id=str(project_id),
        task_id=str(task_id),
    )
    payload = json.loads(written.read_text(encoding="utf-8"))
    loaded = _load_phase0_artifact(written)

    assert written == artifact_path
    assert payload["project_id"] == str(project_id)
    assert payload["task_id"] == str(task_id)
    assert loaded.quality_stats == {"total_batches": 24, "failed": 0}
    assert loaded.diagnostics == [{"final_status": "success"}]
    assert loaded.candidates[0].candidate_id == "phase0-A-0001"
    assert loaded.candidates[0].source_chapter_indices == [1, 2, 3, 4, 5]
    assert loaded.candidates[0].payload["scenes"][0]["title"] == "候选"


def _write_phase0_artifact_payload(
    path: Path,
    *,
    failed: int = 0,
    missing_chapters: list[int] | None = None,
    candidate_id: str = "phase0-A-0001",
) -> None:
    path.write_text(
        json.dumps(
            {
                "test_mode": "phase0_only",
                "stage": "phase0_prefetch",
                "expected_chapter_count": EXPECTED_CHAPTER_COUNT,
                "expected_phase_shape": {"phase0_total_batches": 24},
                "coverage": {
                    "coverage_ratio": 1.0 if not missing_chapters else 0.9,
                    "missing_chapters": missing_chapters or [],
                },
                "phase0_result": {
                    "candidates": [
                        {
                            "candidate_id": candidate_id,
                            "source_round": "A",
                            "source_batch_id": "A-0001-1-5",
                            "source_batch_index": 1,
                            "source_chapter_indices": [1, 2, 3, 4, 5],
                            "quality": "high",
                            "payload": {"scenes": [{"title": "候选"}]},
                        }
                    ],
                    "quality_stats": {
                        "total_batches": 24,
                        "completed_batches": 24,
                        "failed": failed,
                    },
                    "diagnostics": [],
                    "blocked": False,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_phase1a_defaults_to_latest_passed_phase0_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PHASE1A_PHASE0_ARTIFACT_PATH", raising=False)
    monkeypatch.setattr(sys.modules[__name__], "DEFAULT_LOG_DIR", tmp_path)
    failed_artifact = tmp_path / "phase0_real_llm_20260702T000000Z.artifact.json"
    old_passed_artifact = tmp_path / "phase0_real_llm_20260702T010000Z.artifact.json"
    latest_passed_artifact = (
        tmp_path / "phase0_real_llm_20260702T020000Z.artifact.json"
    )
    _write_phase0_artifact_payload(
        failed_artifact,
        failed=1,
        candidate_id="failed",
    )
    _write_phase0_artifact_payload(
        old_passed_artifact,
        candidate_id="old-passed",
    )
    _write_phase0_artifact_payload(
        latest_passed_artifact,
        candidate_id="latest-passed",
    )

    os.utime(failed_artifact, (100, 100))
    os.utime(old_passed_artifact, (200, 200))
    os.utime(latest_passed_artifact, (300, 300))

    assert _phase1a_phase0_artifact_path() == latest_passed_artifact
    assert _load_phase0_artifact(latest_passed_artifact).candidates[
        0
    ].candidate_id == "latest-passed"


def test_phase1a_phase0_artifact_env_overrides_latest_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured_artifact = tmp_path / "configured.artifact.json"
    monkeypatch.setenv("PHASE1A_PHASE0_ARTIFACT_PATH", str(configured_artifact))
    monkeypatch.setattr(sys.modules[__name__], "DEFAULT_LOG_DIR", tmp_path / "logs")

    assert _phase1a_phase0_artifact_path() == configured_artifact


def _write_phase1a_artifact_payload(
    path: Path,
    *,
    failed: int = 0,
    timeout: int = 0,
    schema_error: int = 0,
    degraded_fallback: int = 0,
    missing_chapters: list[int] | None = None,
    candidate_id: str = "phase1a-A-0001",
) -> None:
    path.write_text(
        json.dumps(
            {
                "test_mode": "phase1a_only",
                "stage": "phase1a_reinforce",
                "expected_chapter_count": EXPECTED_CHAPTER_COUNT,
                "expected_phase_shape": {"phase1a_total_batches": 24},
                "coverage": {
                    "coverage_ratio": 1.0 if not missing_chapters else 0.9,
                    "missing_chapters": missing_chapters or [],
                },
                "phase1a_result": {
                    "candidates": [
                        {
                            "candidate_id": candidate_id,
                            "source_round": "A",
                            "source_batch_id": "A-0001-1-5",
                            "source_batch_index": 1,
                            "source_chapter_indices": [1, 2, 3, 4, 5],
                            "quality": "high",
                            "payload": {"scenes": [{"title": "候选"}]},
                        }
                    ],
                    "quality_stats": {
                        "total_batches": 24,
                        "completed_batches": 24,
                        "failed": failed,
                        "timeout": timeout,
                        "schema_error": schema_error,
                        "degraded_fallback": degraded_fallback,
                    },
                    "diagnostics": [],
                    "blocked": False,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_phase1b_artifact_payload(
    path: Path,
    *,
    failed: int = 0,
    timeout: int = 0,
    schema_error: int = 0,
    degraded: bool = False,
    phase1a_fallback: bool = False,
    missing_chapters: list[int] | None = None,
    candidate_id: str = "phase1b-0001",
) -> None:
    path.write_text(
        json.dumps(
            {
                "test_mode": "phase1b_only",
                "stage": "phase1b_fusion",
                "expected_chapter_count": EXPECTED_CHAPTER_COUNT,
                "expected_phase_shape": {"phase1b_total_windows": 6},
                "coverage": {
                    "coverage_ratio": 1.0 if not missing_chapters else 0.9,
                    "missing_chapters": missing_chapters or [],
                },
                "phase1b_result": {
                    "candidates": [
                        {
                            "candidate_id": candidate_id,
                            "title": "候选场景",
                            "goal": "用于 Phase2a 测试的候选场景",
                            "scene_chunks": [
                                {
                                    "chapter_index": 1,
                                    "start_paragraph": 1,
                                    "end_paragraph": 3,
                                    "summary": "开场",
                                }
                            ],
                            "source_candidate_ids": ["phase1a-A-0001"],
                            "source_rounds": ["A"],
                            "source_chapter_indices": [1],
                            "operation": "kept",
                        }
                    ],
                    "quality_stats": {
                        "total_windows": 6,
                        "completed_windows": 6,
                        "failed": failed,
                        "timeout": timeout,
                        "schema_error": schema_error,
                    },
                    "diagnostics": [],
                    "degraded": degraded,
                    "phase1a_fallback": phase1a_fallback,
                    "blocked": False,
                    "block_reason": None,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_phase1b_defaults_to_latest_passed_phase1a_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PHASE1B_PHASE1A_ARTIFACT_PATH", raising=False)
    monkeypatch.setattr(sys.modules[__name__], "DEFAULT_LOG_DIR", tmp_path)
    failed_artifact = tmp_path / "phase1a_real_llm_20260702T000000Z.artifact.json"
    old_passed_artifact = tmp_path / "phase1a_real_llm_20260702T010000Z.artifact.json"
    latest_passed_artifact = (
        tmp_path / "phase1a_real_llm_20260702T020000Z.artifact.json"
    )
    _write_phase1a_artifact_payload(
        failed_artifact,
        failed=1,
        candidate_id="failed",
    )
    _write_phase1a_artifact_payload(
        old_passed_artifact,
        candidate_id="old-passed",
    )
    _write_phase1a_artifact_payload(
        latest_passed_artifact,
        candidate_id="latest-passed",
    )

    os.utime(failed_artifact, (100, 100))
    os.utime(old_passed_artifact, (200, 200))
    os.utime(latest_passed_artifact, (300, 300))

    assert _phase1b_phase1a_artifact_path() == latest_passed_artifact
    assert _load_phase1a_artifact(latest_passed_artifact).candidates[
        0
    ].candidate_id == "latest-passed"


def test_phase1b_phase1a_artifact_env_overrides_latest_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured_artifact = tmp_path / "configured.artifact.json"
    monkeypatch.setenv("PHASE1B_PHASE1A_ARTIFACT_PATH", str(configured_artifact))
    monkeypatch.setattr(sys.modules[__name__], "DEFAULT_LOG_DIR", tmp_path / "logs")

    assert _phase1b_phase1a_artifact_path() == configured_artifact


def test_phase2a_defaults_to_latest_passed_phase1b_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PHASE2A_PHASE1B_ARTIFACT_PATH", raising=False)
    monkeypatch.delenv("PHASE2A_REPAIR_SOURCE_ARTIFACT_PATH", raising=False)
    monkeypatch.setattr(sys.modules[__name__], "DEFAULT_LOG_DIR", tmp_path)
    failed_artifact = tmp_path / "phase1b_real_llm_20260702T000000Z.artifact.json"
    old_passed_artifact = tmp_path / "phase1b_real_llm_20260702T010000Z.artifact.json"
    latest_passed_artifact = (
        tmp_path / "phase1b_real_llm_20260702T020000Z.artifact.json"
    )
    _write_phase1b_artifact_payload(
        failed_artifact,
        failed=1,
        candidate_id="failed",
    )
    _write_phase1b_artifact_payload(
        old_passed_artifact,
        candidate_id="old-passed",
    )
    _write_phase1b_artifact_payload(
        latest_passed_artifact,
        candidate_id="latest-passed",
    )

    os.utime(failed_artifact, (100, 100))
    os.utime(old_passed_artifact, (200, 200))
    os.utime(latest_passed_artifact, (300, 300))

    assert _phase2a_phase1b_artifact_path() == latest_passed_artifact
    assert _load_phase1b_artifact(latest_passed_artifact).candidates[
        0
    ].candidate_id == "latest-passed"


def test_phase2a_phase1b_artifact_env_overrides_latest_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured_artifact = tmp_path / "configured.artifact.json"
    monkeypatch.setenv("PHASE2A_PHASE1B_ARTIFACT_PATH", str(configured_artifact))
    monkeypatch.setattr(sys.modules[__name__], "DEFAULT_LOG_DIR", tmp_path / "logs")

    assert _phase2a_phase1b_artifact_path() == configured_artifact


def test_phase2a_repair_source_reuses_original_phase1b_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_phase1b_artifact = tmp_path / "phase1b.artifact.json"
    failed_phase2a_artifact = tmp_path / "phase2a.artifact.json"
    failed_phase2a_artifact.write_text(
        json.dumps(
            {
                "test_mode": "phase2a_only",
                "source_phase1b_artifact_path": str(source_phase1b_artifact),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("PHASE2A_PHASE1B_ARTIFACT_PATH", raising=False)
    monkeypatch.setenv(
        "PHASE2A_REPAIR_SOURCE_ARTIFACT_PATH",
        str(failed_phase2a_artifact),
    )

    assert _phase2a_phase1b_artifact_path() == source_phase1b_artifact


def test_phase2a_repair_checkpoints_remap_to_new_scene_commit_ids() -> None:
    source_payload = {
        "phase2_result": {
            "checkpoints": {
                "phase2": {
                    "scenes": [
                        {
                            "scene_id": "old-scene-1",
                            "scene_index": 0,
                            "status": "done",
                        },
                        {
                            "scene_id": "old-scene-2",
                            "scene_index": 0,
                            "status": "failed",
                            "retry_count": 1,
                        },
                    ]
                }
            }
        }
    }
    scene_commit_result = SceneCommitResult(
        created_count=2,
        created_scene_ids=["new-scene-1", "new-scene-2"],
    )

    remapped = _phase2a_repair_checkpoints_for_scene_commit(
        source_payload,
        scene_commit_result,
    )

    scenes = remapped["phase2"]["scenes"]
    assert [scene["scene_id"] for scene in scenes] == [
        "new-scene-1",
        "new-scene-2",
    ]
    assert [scene["source_scene_id"] for scene in scenes] == [
        "old-scene-1",
        "old-scene-2",
    ]
    assert scenes[1]["status"] == "failed"
    assert scenes[1]["retry_count"] == 1


def _write_phase2a_artifact_payload(
    path: Path,
    *,
    failed: bool = False,
    with_world_snapshot: bool = True,
    entity_count: int = 2,
) -> None:
    path.write_text(
        json.dumps(
            {
                "test_mode": "phase2a_only",
                "stage": "entity_extraction_phase2a",
                "expected_chapter_count": EXPECTED_CHAPTER_COUNT,
                "scene_coverage": {
                    "coverage_ratio": 1.0,
                    "missing_chapters": [],
                },
                "source_phase1b_artifact_path": "/tmp/phase1b.artifact.json",
                "phase2_quality_stats": {
                    "total_scenes": 60,
                    "completed_scenes": 59 if failed else 60,
                    "failed_scene_count": 1 if failed else 0,
                    "phase2_failed_batches": ["batch-1"] if failed else [],
                    "error_kind": "schema_validation" if failed else None,
                    "total_created": entity_count,
                },
                "output_counts": {"entity_count": entity_count},
                "world_snapshot": (
                    {
                        "schema_version": 1,
                        "entity_count": entity_count,
                        "relation_count": 1,
                        "entities": [
                            {
                                "id": "old-entity-1",
                                "entity_type": "character",
                                "name": "克莱恩",
                                "status": "candidate",
                                "content_json": {"aliases": []},
                            }
                        ],
                        "relations": [],
                    }
                    if with_world_snapshot
                    else None
                ),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_phase2b_defaults_to_latest_hydratable_phase2a_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PHASE2B_PHASE2A_ARTIFACT_PATH", raising=False)
    monkeypatch.delenv("PHASE2B_REPAIR_SOURCE_ARTIFACT_PATH", raising=False)
    monkeypatch.setattr(sys.modules[__name__], "DEFAULT_LOG_DIR", tmp_path)
    failed_artifact = tmp_path / "phase2a_real_llm_20260702T000000Z.artifact.json"
    old_hydratable_artifact = (
        tmp_path / "phase2a_real_llm_20260702T010000Z.artifact.json"
    )
    latest_without_snapshot = (
        tmp_path / "phase2a_real_llm_20260702T020000Z.artifact.json"
    )
    latest_hydratable_artifact = (
        tmp_path / "phase2a_real_llm_20260702T030000Z.artifact.json"
    )
    _write_phase2a_artifact_payload(failed_artifact, failed=True)
    _write_phase2a_artifact_payload(old_hydratable_artifact)
    _write_phase2a_artifact_payload(
        latest_without_snapshot,
        with_world_snapshot=False,
    )
    _write_phase2a_artifact_payload(latest_hydratable_artifact)

    os.utime(failed_artifact, (100, 100))
    os.utime(old_hydratable_artifact, (200, 200))
    os.utime(latest_without_snapshot, (300, 300))
    os.utime(latest_hydratable_artifact, (400, 400))

    assert _phase2b_phase2a_artifact_path() == latest_hydratable_artifact


def test_phase2b_phase2a_artifact_env_overrides_latest_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured_artifact = tmp_path / "configured.artifact.json"
    monkeypatch.setenv("PHASE2B_PHASE2A_ARTIFACT_PATH", str(configured_artifact))
    monkeypatch.delenv("PHASE2B_REPAIR_SOURCE_ARTIFACT_PATH", raising=False)
    monkeypatch.setattr(sys.modules[__name__], "DEFAULT_LOG_DIR", tmp_path / "logs")

    assert _phase2b_phase2a_artifact_path() == configured_artifact


def test_phase2b_repair_source_reuses_original_phase2a_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_phase2a_artifact = tmp_path / "phase2a.artifact.json"
    failed_phase2b_artifact = tmp_path / "phase2b.artifact.json"
    failed_phase2b_artifact.write_text(
        json.dumps(
            {
                "test_mode": "phase2b_only",
                "source_phase2a_artifact_path": str(source_phase2a_artifact),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("PHASE2B_PHASE2A_ARTIFACT_PATH", raising=False)
    monkeypatch.setenv(
        "PHASE2B_REPAIR_SOURCE_ARTIFACT_PATH",
        str(failed_phase2b_artifact),
    )

    assert _phase2b_phase2a_artifact_path() == source_phase2a_artifact


def test_phase2b_repair_checkpoints_remap_to_new_scene_commit_ids() -> None:
    source_payload = {
        "phase2b_result": {
            "alias_relation_checkpoints": {
                "phase2b": {
                    "scenes": [
                        {
                            "scene_id": "old-scene-1",
                            "scene_index": 1,
                            "status": "done",
                            "aliases": 2,
                            "relations": 3,
                        },
                        {
                            "scene_id": "old-scene-2",
                            "scene_index": 2,
                            "status": "failed",
                            "retry_count": 1,
                        },
                    ]
                }
            }
        }
    }
    scene_commit_result = SceneCommitResult(
        created_count=2,
        created_scene_ids=["new-scene-1", "new-scene-2"],
    )

    remapped = _phase2b_repair_checkpoints_for_scene_commit(
        source_payload,
        scene_commit_result,
    )

    scenes = remapped["phase2b"]["scenes"]
    assert [scene["scene_id"] for scene in scenes] == [
        "new-scene-1",
        "new-scene-2",
    ]
    assert [scene["source_scene_id"] for scene in scenes] == [
        "old-scene-1",
        "old-scene-2",
    ]
    assert scenes[0]["aliases"] == 2
    assert scenes[1]["status"] == "failed"


def test_phase2b_repair_merge_keeps_source_completed_count() -> None:
    source_payload = {
        "phase2b_result": {
            "total_scenes": 60,
            "alias_relation_scenes": 1,
            "total_aliases": 5,
            "total_relations": 9,
            "alias_relation_failed_scenes": [4, 5],
            "alias_relation_checkpoints": {
                "phase2b": {
                    "scenes": [
                        {"status": "skipped"},
                        {"status": "skipped"},
                        {"status": "skipped"},
                        {"status": "done"},
                    ]
                }
            },
        }
    }
    repair_result = {
        "total_scenes": 60,
        "alias_relation_scenes": 2,
        "total_aliases": 1,
        "total_relations": 4,
        "alias_relation_failed_scenes": [6],
        "alias_relation_checkpoints": {
            "phase2b": {
                "scenes": [
                    {"status": "skipped"},
                    {"status": "skipped"},
                    {"status": "skipped"},
                    {"status": "done"},
                    {"status": "done"},
                    {"status": "failed"},
                ]
            }
        },
    }

    merged = _merge_phase2b_repair_result(source_payload, repair_result)

    assert merged["alias_relation_scenes"] == 5
    assert merged["total_aliases"] == 6
    assert merged["total_relations"] == 13
    assert merged["alias_relation_failed_scenes"] == [6]


def test_phase2b_attempted_or_explained_accepts_skipped_with_reason() -> None:
    phase2_stats = {
        "alias_relation_scenes": 0,
        "alias_relation_failed_scenes": [],
        "alias_relation_skipped": True,
        "alias_relation_skip_reason": "phase2_alias_relation_supplement_disabled",
    }

    assert _phase2b_attempted_or_explained(phase2_stats, []) is True


def test_phase2b_attempted_or_explained_rejects_silent_skip() -> None:
    phase2_stats = {
        "alias_relation_scenes": 0,
        "alias_relation_failed_scenes": [],
        "alias_relation_skipped": True,
        "alias_relation_skip_reason": None,
    }

    assert _phase2b_attempted_or_explained(phase2_stats, []) is False


def _write_phase2b_artifact_payload(
    path: Path,
    *,
    failed: bool = False,
    with_world_snapshot: bool = True,
    entity_count: int = 2,
) -> None:
    path.write_text(
        json.dumps(
            {
                "test_mode": "phase2b_only",
                "stage": "alias_relation_phase2b",
                "source_phase1b_artifact_path": "/tmp/phase1b.artifact.json",
                "source_phase2a_artifact_path": "/tmp/phase2a.artifact.json",
                "phase2b_result": {
                    "total_scenes": 60,
                    "alias_relation_scenes": 59 if failed else 60,
                    "alias_relation_failed_scenes": [60] if failed else [],
                    "degraded": failed,
                    "error_kind": "timeout" if failed else None,
                },
                "world_snapshot": (
                    {
                        "schema_version": 1,
                        "entity_count": entity_count,
                        "relation_count": 1,
                        "entities": [
                            {
                                "id": "old-entity-1",
                                "entity_type": "character",
                                "name": "克莱恩",
                                "status": "candidate",
                                "content_json": {"aliases": []},
                            }
                        ],
                        "relations": [],
                    }
                    if with_world_snapshot
                    else None
                ),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_phase3_defaults_to_latest_passed_phase2b_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PHASE3_PHASE2B_ARTIFACT_PATH", raising=False)
    monkeypatch.setattr(sys.modules[__name__], "DEFAULT_LOG_DIR", tmp_path)
    failed_artifact = tmp_path / "phase2b_real_llm_20260702T000000Z.artifact.json"
    old_passed_artifact = tmp_path / "phase2b_real_llm_20260702T010000Z.artifact.json"
    latest_without_snapshot = (
        tmp_path / "phase2b_real_llm_20260702T020000Z.artifact.json"
    )
    latest_passed_artifact = (
        tmp_path / "phase2b_real_llm_20260702T030000Z.artifact.json"
    )
    _write_phase2b_artifact_payload(failed_artifact, failed=True)
    _write_phase2b_artifact_payload(old_passed_artifact)
    _write_phase2b_artifact_payload(
        latest_without_snapshot,
        with_world_snapshot=False,
    )
    _write_phase2b_artifact_payload(latest_passed_artifact)

    os.utime(failed_artifact, (100, 100))
    os.utime(old_passed_artifact, (200, 200))
    os.utime(latest_without_snapshot, (300, 300))
    os.utime(latest_passed_artifact, (400, 400))

    assert _phase3_phase2b_artifact_path() == latest_passed_artifact


def test_phase3_phase2b_artifact_env_overrides_latest_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured_artifact = tmp_path / "configured.artifact.json"
    monkeypatch.setenv("PHASE3_PHASE2B_ARTIFACT_PATH", str(configured_artifact))
    monkeypatch.setattr(sys.modules[__name__], "DEFAULT_LOG_DIR", tmp_path / "logs")

    assert _phase3_phase2b_artifact_path() == configured_artifact


def test_phase_acceptance_task_uses_stage_specific_task_type() -> None:
    project_id = uuid.uuid4()

    phase0_task = _build_phase_acceptance_task(
        project_id,
        test_mode="phase0_only",
        stage="phase0_prefetch",
    )
    phase1a_task = _build_phase_acceptance_task(
        project_id,
        test_mode="phase1a_only",
        stage="phase1a_reinforce",
    )
    phase1b_task = _build_phase_acceptance_task(
        project_id,
        test_mode="phase1b_only",
        stage="phase1b_fusion",
    )
    phase2a_task = _build_phase_acceptance_task(
        project_id,
        test_mode="phase2a_only",
        stage="entity_extraction_phase2a",
    )
    phase2b_task = _build_phase_acceptance_task(
        project_id,
        test_mode="phase2b_only",
        stage="alias_relation_phase2b",
    )
    phase3_task = _build_phase_acceptance_task(
        project_id,
        test_mode="phase3_only",
        stage="structure_analysis",
    )

    assert phase0_task.task_type == "deep_import_phase0_real_llm"
    assert phase1a_task.task_type == "deep_import_phase1a_real_llm"
    assert phase1b_task.task_type == "deep_import_phase1b_real_llm"
    assert phase2a_task.task_type == "deep_import_phase2a_real_llm"
    assert phase2b_task.task_type == "deep_import_phase2b_real_llm"
    assert phase3_task.task_type == "deep_import_phase3_real_llm"
    assert phase0_task.meta["novel_id"] == str(project_id)
    assert phase1a_task.meta["novel_id"] == str(project_id)
    assert phase1a_task.meta["stage"] == "phase1a_reinforce"
    assert phase1b_task.meta["stage"] == "phase1b_fusion"
    assert phase2a_task.meta["stage"] == "entity_extraction_phase2a"
    assert phase2b_task.meta["stage"] == "alias_relation_phase2b"
    assert phase3_task.meta["stage"] == "structure_analysis"


@pytest.mark.asyncio
async def test_phase_acceptance_task_result_links_project_and_artifact(
    db_session: AsyncSession,
    tmp_path: Path,
) -> None:
    project_id = uuid.uuid4()
    db_session.add(
        Project(
            id=project_id,
            title="Phase0 分阶段结果项目映射",
            language="zh",
        )
    )
    task = _build_phase_acceptance_task(
        project_id,
        test_mode="phase0_only",
        stage="phase0_prefetch",
    )
    db_session.add(task)
    await db_session.flush()

    result, output_counts, coverage, expected_phase_shape = (
        _phase0_only_result_fixture()
    )
    summary_path = tmp_path / "phase0.md"
    artifact_path = tmp_path / "phase0.artifact.json"
    log_path = tmp_path / "phase0.jsonl"

    payload = await _persist_phase_acceptance_task_result(
        db_session,
        task,
        test_mode="phase0_only",
        stage="phase0_prefetch",
        result=result,
        output_counts=output_counts,
        coverage=coverage,
        expected_phase_shape=expected_phase_shape,
        llm_config={"effective_llm_profile": {"model": "deepseek-v4-flash"}},
        summary_path=summary_path,
        artifact_path=artifact_path,
        log_path=log_path,
        issues=[],
    )

    saved_task = await db_session.get(AsyncTask, task.id)
    saved_project = await db_session.get(Project, project_id)
    assert saved_project is not None
    assert saved_task is not None
    assert saved_task.status == "done"
    assert saved_task.progress == 1.0
    assert saved_task.meta["novel_id"] == str(project_id)
    assert saved_task.meta["test_mode"] == "phase0_only"
    assert saved_task.result["workflow_id"] == str(task.id)
    assert saved_task.result["stage"] == "phase0_prefetch"
    assert saved_task.result["quality_stats"]["phase0"]["failed"] == 0
    assert saved_task.result["checkpoints"]["phase0_prefetch"]["artifact_path"] == str(
        artifact_path
    )
    assert payload["llm_config"]["effective_llm_profile"]["model"] == (
        "deepseek-v4-flash"
    )


def test_phase1a_only_acceptance_passes_for_phase1a_only_result() -> None:
    result, output_counts, coverage, expected_phase_shape = (
        _phase1a_only_result_fixture()
    )

    checks, issues = _phase1a_only_acceptance_checks(
        result=result,
        output_counts=output_counts,
        coverage=coverage,
        expected_phase_shape=expected_phase_shape,
        expected_chapter_count=60,
    )

    assert issues == []
    assert {check["status"] for check in checks} == {"passed"}


@pytest.mark.parametrize(
    ("mutator", "expected_issue"),
    [
        (
            lambda result, _counts, _coverage: result[
                "phase0_quality_stats"
            ].update({"failed": 1}),
            "phase0 failed batches expected 0, got 1",
        ),
        (
            lambda result, _counts, _coverage: result.update({"blocked": True}),
            "phase1a expected blocked false, got True",
        ),
        (
            lambda result, _counts, _coverage: result["quality_stats"].update(
                {"completed_batches": 23}
            ),
            "phase1a completed_batches expected total_batches",
        ),
        (
            lambda result, _counts, _coverage: result["quality_stats"].update(
                {"failed": 1}
            ),
            "phase1a failed expected 0, got 1",
        ),
        (
            lambda result, _counts, _coverage: result["quality_stats"].update(
                {"timeout": 1}
            ),
            "phase1a timeout expected 0, got 1",
        ),
        (
            lambda result, _counts, _coverage: result["quality_stats"].update(
                {"schema_error": 1}
            ),
            "phase1a schema_error expected 0, got 1",
        ),
        (
            lambda _result, _counts, coverage: coverage.update(
                {"covered_chapters": list(range(1, 60)), "missing_chapters": [60]}
            ),
            "phase1a candidate chapter coverage missing chapters: [60]",
        ),
        (
            lambda result, _counts, _coverage: result.update(
                {"candidate_scene_count": 361}
            ),
            "phase1a candidate scene count expected within 1..360, got 361",
        ),
        (
            lambda _result, counts, _coverage: counts.update({"scene_count": 1}),
            "phase1a-only expected no committed scenes, got 1",
        ),
    ],
)
def test_phase1a_only_acceptance_reports_guardrail_failures(
    mutator,
    expected_issue: str,
) -> None:
    result, output_counts, coverage, expected_phase_shape = (
        _phase1a_only_result_fixture()
    )
    mutator(result, output_counts, coverage)

    _checks, issues = _phase1a_only_acceptance_checks(
        result=result,
        output_counts=output_counts,
        coverage=coverage,
        expected_phase_shape=expected_phase_shape,
        expected_chapter_count=60,
    )

    assert any(expected_issue in issue for issue in issues)


def test_phase1b_only_acceptance_passes_for_phase1b_only_result() -> None:
    result, output_counts, coverage, expected_phase_shape = (
        _phase1b_only_result_fixture()
    )

    checks, issues = _phase1b_only_acceptance_checks(
        result=result,
        output_counts=output_counts,
        coverage=coverage,
        expected_phase_shape=expected_phase_shape,
        expected_chapter_count=60,
    )

    assert issues == []
    assert {check["status"] for check in checks} == {"passed"}


@pytest.mark.parametrize(
    ("mutator", "expected_issue"),
    [
        (
            lambda result, _counts, _coverage: result[
                "phase1a_quality_stats"
            ].update({"failed": 1}),
            "phase1a source failed expected 0, got 1",
        ),
        (
            lambda result, _counts, _coverage: result.update({"blocked": True}),
            "phase1b expected blocked false, got True",
        ),
        (
            lambda result, _counts, _coverage: result.update({"degraded": True}),
            "phase1b expected degraded false, got True",
        ),
        (
            lambda result, _counts, _coverage: result.update(
                {"phase1a_fallback": True}
            ),
            "phase1b expected phase1a_fallback false, got True",
        ),
        (
            lambda result, _counts, _coverage: result["quality_stats"].update(
                {"completed_windows": 1}
            ),
            "phase1b completed_windows expected total_windows",
        ),
        (
            lambda result, _counts, _coverage: result["quality_stats"].update(
                {"failed": 1}
            ),
            "phase1b failed expected 0, got 1",
        ),
        (
            lambda result, _counts, _coverage: result["quality_stats"].update(
                {"timeout": 1}
            ),
            "phase1b timeout expected 0, got 1",
        ),
        (
            lambda result, _counts, _coverage: result["quality_stats"].update(
                {"schema_error": 1}
            ),
            "phase1b schema_error expected 0, got 1",
        ),
        (
            lambda _result, _counts, coverage: coverage.update(
                {"covered_chapters": list(range(1, 60)), "missing_chapters": [60]}
            ),
            "phase1b candidate chapter coverage missing chapters: [60]",
        ),
        (
            lambda result, _counts, _coverage: result.update({"candidate_count": 0}),
            "phase1b candidate count expected within 1..240, got 0",
        ),
        (
            lambda _result, counts, _coverage: counts.update({"scene_count": 1}),
            "phase1b-only expected no committed scenes, got 1",
        ),
    ],
)
def test_phase1b_only_acceptance_reports_guardrail_failures(
    mutator,
    expected_issue: str,
) -> None:
    result, output_counts, coverage, expected_phase_shape = (
        _phase1b_only_result_fixture()
    )
    mutator(result, output_counts, coverage)

    _checks, issues = _phase1b_only_acceptance_checks(
        result=result,
        output_counts=output_counts,
        coverage=coverage,
        expected_phase_shape=expected_phase_shape,
        expected_chapter_count=60,
    )

    assert any(expected_issue in issue for issue in issues)


def test_phase2a_only_acceptance_passes_for_phase2a_only_result() -> None:
    result, output_counts, scene_coverage = _phase2a_only_result_fixture()

    checks, issues = _phase2a_only_acceptance_checks(
        result=result,
        output_counts=output_counts,
        scene_coverage=scene_coverage,
        expected_chapter_count=60,
    )

    assert issues == []
    assert {check["status"] for check in checks} == {"passed"}


@pytest.mark.parametrize(
    ("mutator", "expected_issue"),
    [
        (
            lambda result, _counts, _coverage: result[
                "source_phase1b_quality_stats"
            ].update({"failed": 1}),
            "source phase1b failed expected 0, got 1",
        ),
        (
            lambda result, _counts, _coverage: result.update(
                {"source_phase1b_degraded": True}
            ),
            "source phase1b degraded expected false, got True",
        ),
        (
            lambda _result, counts, _coverage: counts.update({"scene_count": 0}),
            "phase2a expected committed scenes > 0",
        ),
        (
            lambda _result, _counts, coverage: coverage.update(
                {"covered_chapters": list(range(1, 60)), "missing_chapters": [60]}
            ),
            "phase2a scene coverage missing chapters: [60]",
        ),
        (
            lambda result, _counts, _coverage: result["quality_stats"].update(
                {"completed_scenes": 59}
            ),
            "phase2a completed_scenes expected total_scenes",
        ),
        (
            lambda result, _counts, _coverage: result["quality_stats"].update(
                {"failed_scene_count": 1}
            ),
            "phase2a failed_scene_count expected 0, got 1",
        ),
        (
            lambda result, _counts, _coverage: result["quality_stats"].update(
                {"phase2_failed_batches": ["batch-1"]}
            ),
            "phase2a failed batches expected [], got ['batch-1']",
        ),
        (
            lambda result, _counts, _coverage: result["quality_stats"].update(
                {"error_kind": "schema_validation"}
            ),
            "phase2a error_kind expected None, got schema_validation",
        ),
        (
            lambda result, _counts, _coverage: result["quality_stats"].update(
                {"total_created": 0}
            ),
            "phase2a expected entity outputs > 0",
        ),
        (
            lambda result, _counts, _coverage: result["quality_stats"].update(
                {"total_aliases": 1}
            ),
            "phase2a-only unexpectedly ran or failed Phase2b alias/relation",
        ),
        (
            lambda _result, counts, _coverage: counts["structure_counts"].update(
                {"threads": 1}
            ),
            "phase2a-only unexpectedly wrote Phase3 structure outputs",
        ),
    ],
)
def test_phase2a_only_acceptance_reports_guardrail_failures(
    mutator,
    expected_issue: str,
) -> None:
    result, output_counts, scene_coverage = _phase2a_only_result_fixture()
    mutator(result, output_counts, scene_coverage)

    _checks, issues = _phase2a_only_acceptance_checks(
        result=result,
        output_counts=output_counts,
        scene_coverage=scene_coverage,
        expected_chapter_count=60,
    )

    assert any(expected_issue in issue for issue in issues)


def test_phase2b_only_acceptance_passes_for_phase2b_only_result() -> None:
    result, output_counts, scene_coverage = _phase2b_only_result_fixture()

    checks, issues = _phase2b_only_acceptance_checks(
        result=result,
        output_counts=output_counts,
        scene_coverage=scene_coverage,
        expected_chapter_count=60,
    )

    assert issues == []
    assert {check["status"] for check in checks} == {"passed"}


@pytest.mark.parametrize(
    ("mutator", "expected_issue"),
    [
        (
            lambda result, _counts, _coverage: result[
                "source_phase2a_quality_stats"
            ].update({"failed_scene_count": 1}),
            "source phase2a artifact is not passed",
        ),
        (
            lambda result, _counts, _coverage: result.update(
                {"source_phase2a_has_world_snapshot": False}
            ),
            "source phase2a artifact missing hydratable world snapshot",
        ),
        (
            lambda _result, counts, _coverage: counts.update({"scene_count": 0}),
            "phase2b expected committed scenes > 0",
        ),
        (
            lambda _result, _counts, coverage: coverage.update(
                {"covered_chapters": list(range(1, 60)), "missing_chapters": [60]}
            ),
            "phase2b scene coverage missing chapters: [60]",
        ),
        (
            lambda result, _counts, _coverage: result["hydrate_summary"].update(
                {"created_entities": 0}
            ),
            "phase2b expected hydrated world objects > 0",
        ),
        (
            lambda result, _counts, _coverage: result["phase2b_result"].update(
                {"alias_relation_scenes": 59}
            ),
            "phase2b alias_relation_scenes expected total_scenes",
        ),
        (
            lambda result, _counts, _coverage: result["phase2b_result"].update(
                {"alias_relation_failed_scenes": [60]}
            ),
            "phase2b failed scenes expected [], got [60]",
        ),
        (
            lambda result, _counts, _coverage: result["phase2b_result"].update(
                {"degraded": True}
            ),
            "phase2b degraded expected false, got True",
        ),
        (
            lambda result, _counts, _coverage: result["phase2b_result"].update(
                {"error_kind": "timeout"}
            ),
            "phase2b error_kind expected None, got timeout",
        ),
        (
            lambda result, _counts, _coverage: result["phase2b_result"].update(
                {"total_aliases": 0, "total_relations": 0}
            ),
            "phase2b expected aliases or relations > 0",
        ),
        (
            lambda _result, counts, _coverage: counts["structure_counts"].update(
                {"threads": 1}
            ),
            "phase2b-only unexpectedly wrote Phase3 structure outputs",
        ),
    ],
)
def test_phase2b_only_acceptance_reports_guardrail_failures(
    mutator,
    expected_issue: str,
) -> None:
    result, output_counts, scene_coverage = _phase2b_only_result_fixture()
    mutator(result, output_counts, scene_coverage)

    _checks, issues = _phase2b_only_acceptance_checks(
        result=result,
        output_counts=output_counts,
        scene_coverage=scene_coverage,
        expected_chapter_count=60,
    )

    assert any(expected_issue in issue for issue in issues)


def test_phase3_only_acceptance_requires_long_form_structure_coverage() -> None:
    result = {
        "source_phase2b_result": {
            "total_scenes": 60,
            "alias_relation_scenes": 60,
            "alias_relation_failed_scenes": [],
            "degraded": False,
            "error_kind": None,
        },
        "source_phase2b_has_world_snapshot": True,
        "scene_commit": {"created_count": 60, "skipped_count": 0},
        "hydrate_summary": {"created_entities": 292},
        "phase": "done",
        "quality_status": "complete",
        "completed_steps": ["structure_analysis"],
        "degraded": False,
        "quality_stats": {"error_kind": None},
        "phase_errors": [],
    }
    output_counts = {
        "scene_count": 60,
        "entity_count": 292,
        "structure_counts": {
            "threads": 3,
            "arcs": 3,
            "foreshadowing": 1,
            "reveals": 1,
        },
    }
    scene_coverage = {
        "covered_chapters": list(range(1, 61)),
        "missing_chapters": [],
        "expected_chapters": list(range(1, 61)),
    }

    checks, issues = _phase3_only_acceptance_checks(
        result=result,
        output_counts=output_counts,
        scene_coverage=scene_coverage,
        expected_chapter_count=60,
    )

    structure_check = next(
        check for check in checks if check["name"] == "phase3_structure_output"
    )
    assert structure_check["status"] == "failed"
    assert any(
        "phase3 structure counts below expected minimums" in issue
        for issue in issues
    )


def test_phase3_only_acceptance_passes_long_form_structure_minimums() -> None:
    result = {
        "source_phase2b_result": {
            "total_scenes": 60,
            "alias_relation_scenes": 60,
            "alias_relation_failed_scenes": [],
            "degraded": False,
            "error_kind": None,
        },
        "source_phase2b_has_world_snapshot": True,
        "scene_commit": {"created_count": 60, "skipped_count": 0},
        "hydrate_summary": {"created_entities": 292},
        "phase": "done",
        "quality_status": "complete",
        "completed_steps": ["structure_analysis"],
        "degraded": False,
        "quality_stats": {"error_kind": None},
        "phase_errors": [],
    }
    output_counts = {
        "scene_count": 60,
        "entity_count": 292,
        "structure_counts": {
            "threads": 3,
            "arcs": 4,
            "foreshadowing": 3,
            "reveals": 3,
        },
    }
    scene_coverage = {
        "covered_chapters": list(range(1, 61)),
        "missing_chapters": [],
        "expected_chapters": list(range(1, 61)),
    }

    checks, issues = _phase3_only_acceptance_checks(
        result=result,
        output_counts=output_counts,
        scene_coverage=scene_coverage,
        expected_chapter_count=60,
    )

    assert issues == []
    assert {check["status"] for check in checks} == {"passed"}


@pytest.mark.asyncio
async def test_world_snapshot_round_trips_entities_and_relations(
    db_session: AsyncSession,
) -> None:
    source_project_id = uuid.uuid4()
    target_project_id = uuid.uuid4()
    db_session.add_all(
        [
            Project(id=source_project_id, title="Phase2a source", language="zh"),
            Project(id=target_project_id, title="Phase2b hydrate", language="zh"),
        ]
    )
    await db_session.flush()
    source_entity = CoreEntity(
        id=uuid.uuid4(),
        novel_id=source_project_id,
        entity_type="character",
        name="克莱恩",
        summary="值夜者候选",
        status="candidate",
        content_json={"aliases": [{"alias": "周明瑞"}]},
        created_by="ai_import",
    )
    target_entity = CoreEntity(
        id=uuid.uuid4(),
        novel_id=source_project_id,
        entity_type="character",
        name="邓恩",
        status="candidate",
        content_json={"aliases": []},
        created_by="ai_import",
    )
    db_session.add_all([source_entity, target_entity])
    await db_session.flush()
    db_session.add(
        EntityRelation(
            novel_id=source_project_id,
            source_id=source_entity.id,
            target_id=target_entity.id,
            relation_type="captain_of",
            description="邓恩带领克莱恩进入值夜者",
            status="candidate",
            strength=0.7,
        )
    )
    await db_session.flush()

    snapshot = await _world_snapshot_for_phase_artifact(
        db_session,
        source_project_id,
    )
    hydrate_summary = await _hydrate_world_snapshot(
        db_session,
        target_project_id,
        snapshot,
    )
    output_counts = await _count_acceptance_outputs(db_session, target_project_id)

    assert snapshot["entity_count"] == 2
    assert snapshot["relation_count"] == 1
    assert hydrate_summary["created_entities"] == 2
    assert hydrate_summary["created_relations"] == 1
    assert output_counts["entity_count"] == 2
    assert output_counts["relation_count"] == 1
    assert output_counts["total_alias_count"] == 1


def test_phase2a_summary_writes_markdown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary_path = tmp_path / "phase2a_real_llm.md"
    log_path = tmp_path / "deep_import_60_phase2a_20260702T000000Z.jsonl"
    monkeypatch.setenv("PHASE2A_REAL_LLM_SUMMARY_PATH", str(summary_path))
    result, output_counts, scene_coverage = _phase2a_only_result_fixture()

    written = _write_phase2a_summary(
        log_path=log_path,
        wall_clock_s=345.67,
        result=result,
        output_counts=output_counts,
        scene_coverage=scene_coverage,
        issues=[],
        llm_config={"effective_llm_profile": {"model": "deepseek-v4-flash"}},
    )

    assert written == summary_path
    text = summary_path.read_text(encoding="utf-8")
    assert "Phase 2a Real LLM Summary" in text
    assert "| test_mode | stage | chapters |" in text
    assert "phase2a_only" in text
    assert "entity_extraction_phase2a" in text
    assert "deepseek-v4-flash" in text


def test_phase1a_summary_writes_markdown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary_path = tmp_path / "phase1a_real_llm.md"
    log_path = tmp_path / "deep_import_60_phase1a_20260702T000000Z.jsonl"
    monkeypatch.setenv("PHASE1A_REAL_LLM_SUMMARY_PATH", str(summary_path))
    result, output_counts, coverage, expected_phase_shape = (
        _phase1a_only_result_fixture()
    )

    written = _write_phase1a_summary(
        log_path=log_path,
        wall_clock_s=234.56,
        result=result,
        output_counts=output_counts,
        coverage=coverage,
        expected_phase_shape=expected_phase_shape,
        issues=[],
        llm_config={"effective_llm_profile": {"model": "deepseek-v4-flash"}},
    )

    assert written == summary_path
    text = summary_path.read_text(encoding="utf-8")
    assert "Phase 1a Real LLM Summary" in text
    assert "| test_mode | stage | chapters |" in text
    assert "| phase1a_only | phase1a_reinforce | 60 |" in text
    assert "deepseek-v4-flash" in text


def test_scene_only_real_llm_task_uses_scene_stage() -> None:
    project_id = uuid.uuid4()

    task = _build_scene_only_task(project_id)

    assert task.task_type == "scene_auto_extraction"
    assert task.meta["stage"] == "scenes"
    assert task.meta["novel_id"] == str(project_id)
    assert task.meta["start_chapter"] == 1


def test_phase01_scene_max_tokens_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.imports import workflow_llm_adapters

    monkeypatch.delenv("PHASE01_SCENE_MAX_TOKENS", raising=False)
    assert workflow_llm_adapters._phase01_scene_max_tokens(4096) == 4096

    monkeypatch.setenv("PHASE01_SCENE_MAX_TOKENS", "8192")
    assert workflow_llm_adapters._phase01_scene_max_tokens(4096) == 8192

    monkeypatch.setenv("PHASE01_SCENE_MAX_TOKENS", "nope")
    assert workflow_llm_adapters._phase01_scene_max_tokens(4096) == 4096


def test_deep_import_structured_max_fix_attempts_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.imports import workflow_llm_adapters

    monkeypatch.delenv("DEEP_IMPORT_STRUCTURED_MAX_FIX_ATTEMPTS", raising=False)
    assert workflow_llm_adapters._deep_import_structured_max_fix_attempts() == 2

    monkeypatch.setenv("DEEP_IMPORT_STRUCTURED_MAX_FIX_ATTEMPTS", "3")
    assert workflow_llm_adapters._deep_import_structured_max_fix_attempts() == 3

    monkeypatch.setenv("DEEP_IMPORT_STRUCTURED_MAX_FIX_ATTEMPTS", "0")
    assert workflow_llm_adapters._deep_import_structured_max_fix_attempts() == 2

    monkeypatch.setenv("DEEP_IMPORT_STRUCTURED_MAX_FIX_ATTEMPTS", "nope")
    assert workflow_llm_adapters._deep_import_structured_max_fix_attempts() == 2


def test_scene_only_acceptance_passes_for_scene_segmentation_only() -> None:
    result, output_counts, coverage = _scene_only_result_fixture()

    checks, issues = _scene_only_acceptance_checks(
        result=result,
        output_counts=output_counts,
        coverage=coverage,
        expected_chapter_count=60,
    )

    assert issues == []
    assert {check["status"] for check in checks} == {"passed"}


@pytest.mark.parametrize(
    ("mutator", "expected_issue"),
    [
        (
            lambda result, _counts, coverage: coverage.update(
                {"covered_chapters": list(range(1, 60)), "missing_chapters": [60]}
            ),
            "scene chapter coverage missing chapters: [60]",
        ),
        (
            lambda result, _counts, _coverage: result.update(
                {
                    "completed_steps": ["scene_segmentation", "entity_extraction"],
                    "phase_timeline": [
                        {"phase": "phase0_prefetch"},
                        {"phase": "entity_extraction"},
                    ],
                }
            ),
            "scene-only entered later phases",
        ),
        (
            lambda result, counts, _coverage: (
                counts.update({"scene_count": 0}),
                result["quality_stats"]["scene_commit"].update({"created_count": 0}),
            ),
            "scene-only expected committed scenes > 0",
        ),
        (
            lambda result, _counts, _coverage: result["quality_stats"][
                "phase1a"
            ].update({"failed": 1}),
            "phase1a failed batches expected 0, got 1",
        ),
    ],
)
def test_scene_only_acceptance_reports_guardrail_failures(
    mutator,
    expected_issue: str,
) -> None:
    result, output_counts, coverage = _scene_only_result_fixture()
    mutator(result, output_counts, coverage)

    _checks, issues = _scene_only_acceptance_checks(
        result=result,
        output_counts=output_counts,
        coverage=coverage,
        expected_chapter_count=60,
    )

    assert any(expected_issue in issue for issue in issues)


def test_phase01_scene_summary_writes_markdown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary_path = tmp_path / "phase01_scene_real_llm.md"
    log_path = tmp_path / "deep_import_60_scene_8x8.jsonl"
    monkeypatch.setenv("PHASE01_SCENE_REAL_LLM_SUMMARY_PATH", str(summary_path))
    result, output_counts, coverage = _scene_only_result_fixture()

    written = _write_phase01_scene_summary(
        log_path=log_path,
        wall_clock_s=456.78,
        result=result,
        output_counts=output_counts,
        coverage=coverage,
        issues=[],
    )

    assert written == summary_path
    text = summary_path.read_text(encoding="utf-8")
    assert "Phase 0/1 Scene Real LLM Summary" in text
    assert "| chapters | wall_clock_s |" in text
    assert "| 60 | 456.78 |" in text


@pytest.mark.asyncio
@pytest.mark.real_llm
@phase0_real_llm_required
async def test_deep_import_60_phase0_real_llm_acceptance(
    db_session: AsyncSession,
) -> None:
    assert EXPECTED_CHAPTER_COUNT == 60
    log = PersistentAcceptanceLogger.from_env()
    expected_phase_shape = _expected_phase_shape()
    llm_config = _llm_config_log_payload()
    log.write(
        "test_started",
        test_mode="phase0_only",
        stage="phase0_prefetch",
        log_path=str(log.path),
        file_path=str(REAL_FILE_PATH),
        expected_chapter_count=EXPECTED_CHAPTER_COUNT,
        expected_phase_shape=expected_phase_shape,
        llm_config=llm_config,
    )
    assert REAL_FILE_PATH.exists(), f"真实文件不存在: {REAL_FILE_PATH}"
    file_bytes = REAL_FILE_PATH.read_bytes()
    chapters = parse_txt(file_bytes)
    assert len(chapters) == EXPECTED_CHAPTER_COUNT
    assert all(chapter.get("content") for chapter in chapters)
    log.write(
        "file_parsed",
        test_mode="phase0_only",
        stage="phase0_prefetch",
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
            title="诡秘之主 第一部 前60章 Phase0-only 验收",
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
    log.set_context(project_id=str(project_id))
    log.write(
        "chapters_imported",
        test_mode="phase0_only",
        stage="phase0_prefetch",
        project_id=str(project_id),
        total_chapters=import_result.total_chapters,
        imported_chapters=import_result.imported_chapters,
    )
    assert import_result.total_chapters == EXPECTED_CHAPTER_COUNT
    assert import_result.imported_chapters == EXPECTED_CHAPTER_COUNT

    task = _build_phase_acceptance_task(
        project_id,
        test_mode="phase0_only",
        stage="phase0_prefetch",
    )
    db_session.add(task)
    await db_session.flush()
    log.set_context(project_id=str(project_id), task_id=str(task.id))
    log.write(
        "task_created",
        test_mode="phase0_only",
        stage="phase0_prefetch",
        task_id=str(task.id),
        task_type=task.task_type,
        project_id=str(project_id),
        meta=task.meta,
    )

    workflow = DeepImportWorkflow()
    log.write(
        "phase_started",
        test_mode="phase0_only",
        stage="phase0_prefetch",
        phase="phase0_prefetch",
        status="running",
        project_id=str(project_id),
        expected_phase_shape=expected_phase_shape,
    )
    try:
        repair_source_artifact = _phase0_repair_source_artifact_path()
        if repair_source_artifact is not None:
            phase0_result, repair_summary = await _repair_phase0_artifact(
                db=db_session,
                project_id=project_id,
                source_artifact_path=repair_source_artifact,
            )
            log.write(
                "phase0_repair_completed",
                test_mode="phase0_only",
                stage="phase0_prefetch",
                phase="phase0_prefetch",
                status="completed",
                project_id=str(project_id),
                **repair_summary,
            )
        else:
            phase0_result = await workflow._run_phase0_prefetch(
                db_session,
                str(project_id),
                1,
                EXPECTED_CHAPTER_COUNT,
            )
    except BaseException as exc:
        log.write(
            "exception",
            test_mode="phase0_only",
            stage="phase0_prefetch",
            error_type=exc.__class__.__name__,
            error_message=str(exc),
            project_id=str(project_id),
        )
        try:
            log.write(
                "interrupted_counts",
                test_mode="phase0_only",
                stage="phase0_prefetch",
                **await _count_acceptance_outputs(db_session, project_id),
            )
        except Exception as count_exc:
            log.write(
                "interrupted_count_failed",
                test_mode="phase0_only",
                stage="phase0_prefetch",
                error_type=count_exc.__class__.__name__,
                error_message=str(count_exc),
            )
        raise

    result = _phase0_result_payload(phase0_result)
    log.write(
        "phase_completed",
        test_mode="phase0_only",
        stage="phase0_prefetch",
        phase="phase0_prefetch",
        status="completed" if not result["blocked"] else "failed",
        project_id=str(project_id),
        details=result["quality_stats"],
        block_reason=result["block_reason"],
    )
    log.write(
        "result",
        test_mode="phase0_only",
        stage="phase0_prefetch",
        project_id=str(project_id),
        **result,
    )
    output_counts = await _count_acceptance_outputs(db_session, project_id)
    coverage = _candidate_chapter_coverage(
        list(phase0_result.candidates),
        start_chapter=1,
        end_chapter=EXPECTED_CHAPTER_COUNT,
    )
    log.write(
        "output_counts",
        test_mode="phase0_only",
        stage="phase0_prefetch",
        project_id=str(project_id),
        **output_counts,
    )
    log.write(
        "candidate_chapter_coverage",
        test_mode="phase0_only",
        stage="phase0_prefetch",
        project_id=str(project_id),
        **coverage,
    )

    acceptance_rule_results, acceptance_issues = _phase0_only_acceptance_checks(
        result=result,
        output_counts=output_counts,
        coverage=coverage,
        expected_phase_shape=expected_phase_shape,
        expected_chapter_count=EXPECTED_CHAPTER_COUNT,
    )
    log.write(
        "acceptance_checks",
        test_mode="phase0_only",
        stage="phase0_prefetch",
        checks=acceptance_rule_results,
        issues=acceptance_issues,
    )
    summary_path = _write_phase0_summary(
        log_path=log.path,
        wall_clock_s=time.monotonic() - log.started_at,
        result=result,
        output_counts=output_counts,
        coverage=coverage,
        expected_phase_shape=expected_phase_shape,
        issues=acceptance_issues,
        llm_config=llm_config,
    )
    artifact_path = _write_phase0_artifact(
        log_path=log.path,
        phase0_result=phase0_result,
        coverage=coverage,
        expected_phase_shape=expected_phase_shape,
        llm_config=llm_config,
        project_id=str(project_id),
        task_id=str(task.id),
    )
    task_result = await _persist_phase_acceptance_task_result(
        db_session,
        task,
        test_mode="phase0_only",
        stage="phase0_prefetch",
        result=result,
        output_counts=output_counts,
        coverage=coverage,
        expected_phase_shape=expected_phase_shape,
        llm_config=llm_config,
        summary_path=summary_path,
        artifact_path=artifact_path,
        log_path=log.path,
        issues=acceptance_issues,
    )
    log.write(
        "task_result_persisted",
        test_mode="phase0_only",
        stage="phase0_prefetch",
        task_id=str(task.id),
        project_id=str(project_id),
        task_status=task.status,
        result_phase=task_result.get("phase"),
        quality_status=task_result.get("quality_status"),
        artifact_path=str(artifact_path),
    )
    log.write(
        "final_summary",
        test_mode="phase0_only",
        stage="phase0_prefetch",
        wall_clock_s=round(time.monotonic() - log.started_at, 2),
        phase0_summary_path=str(summary_path),
        phase0_artifact_path=str(artifact_path),
        project_id=str(project_id),
        task_id=str(task.id),
        issues=acceptance_issues,
        output_counts=output_counts,
        candidate_chapter_coverage=coverage,
        result=result,
    )
    if acceptance_issues:
        pytest.fail("\n".join(acceptance_issues))


@pytest.mark.asyncio
@pytest.mark.real_llm
@phase1a_real_llm_required
async def test_deep_import_60_phase1a_real_llm_acceptance(
    db_session: AsyncSession,
) -> None:
    assert EXPECTED_CHAPTER_COUNT == 60
    log = PersistentAcceptanceLogger.from_env()
    expected_phase_shape = _expected_phase_shape()
    llm_config = _llm_config_log_payload()
    log.write(
        "test_started",
        test_mode="phase1a_only",
        stage="phase1a_reinforce",
        log_path=str(log.path),
        file_path=str(REAL_FILE_PATH),
        expected_chapter_count=EXPECTED_CHAPTER_COUNT,
        expected_phase_shape=expected_phase_shape,
        llm_config=llm_config,
    )
    assert REAL_FILE_PATH.exists(), f"真实文件不存在: {REAL_FILE_PATH}"
    file_bytes = REAL_FILE_PATH.read_bytes()
    chapters = parse_txt(file_bytes)
    assert len(chapters) == EXPECTED_CHAPTER_COUNT
    assert all(chapter.get("content") for chapter in chapters)
    log.write(
        "file_parsed",
        test_mode="phase1a_only",
        stage="phase1a_reinforce",
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
            title="诡秘之主 第一部 前60章 Phase1a-only 验收",
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
    log.set_context(project_id=str(project_id))
    log.write(
        "chapters_imported",
        test_mode="phase1a_only",
        stage="phase1a_reinforce",
        project_id=str(project_id),
        total_chapters=import_result.total_chapters,
        imported_chapters=import_result.imported_chapters,
    )
    assert import_result.total_chapters == EXPECTED_CHAPTER_COUNT
    assert import_result.imported_chapters == EXPECTED_CHAPTER_COUNT

    task = _build_phase_acceptance_task(
        project_id,
        test_mode="phase1a_only",
        stage="phase1a_reinforce",
    )
    db_session.add(task)
    await db_session.flush()
    log.set_context(project_id=str(project_id), task_id=str(task.id))
    log.write(
        "task_created",
        test_mode="phase1a_only",
        stage="phase1a_reinforce",
        task_id=str(task.id),
        task_type=task.task_type,
        project_id=str(project_id),
        meta=task.meta,
    )

    workflow = DeepImportWorkflow()
    try:
        phase0_artifact_path = _phase1a_phase0_artifact_path()
        if phase0_artifact_path is not None:
            phase0_result = _load_phase0_artifact(phase0_artifact_path)
            log.write(
                "phase0_artifact_loaded",
                test_mode="phase1a_only",
                stage="phase0_prefetch",
                phase="phase0_prefetch",
                status="loaded",
                project_id=str(project_id),
                phase0_artifact_path=str(phase0_artifact_path),
                details=phase0_result.quality_stats,
                candidate_count=len(phase0_result.candidates),
            )
        else:
            log.write(
                "phase_started",
                test_mode="phase1a_only",
                stage="phase0_prefetch",
                phase="phase0_prefetch",
                status="running",
                project_id=str(project_id),
                expected_phase_shape=expected_phase_shape,
            )
            phase0_result = await workflow._run_phase0_prefetch(
                db_session,
                str(project_id),
                1,
                EXPECTED_CHAPTER_COUNT,
            )
            log.write(
                "phase_completed",
                test_mode="phase1a_only",
                stage="phase0_prefetch",
                phase="phase0_prefetch",
                status="completed" if not phase0_result.blocked else "failed",
                project_id=str(project_id),
                details=phase0_result.quality_stats,
                block_reason=phase0_result.block_reason,
            )
        log.write(
            "phase_started",
            test_mode="phase1a_only",
            stage="phase1a_reinforce",
            phase="phase1a_reinforce",
            status="running",
            project_id=str(project_id),
        )
        phase1a_repair_source = _phase1a_repair_source_artifact_path()
        if phase1a_repair_source is not None:
            phase1a_result, repair_summary = await _repair_phase1a_artifact(
                db=db_session,
                project_id=project_id,
                source_artifact_path=phase1a_repair_source,
                phase0_result=phase0_result,
                chapters=chapters,
            )
            log.write(
                "phase1a_repair_completed",
                test_mode="phase1a_only",
                stage="phase1a_reinforce",
                phase="phase1a_reinforce",
                status="completed",
                project_id=str(project_id),
                **repair_summary,
            )
        else:
            phase1a_result = await workflow._run_phase1a_reinforcement(
                db_session,
                str(project_id),
                1,
                EXPECTED_CHAPTER_COUNT,
                phase0_result.candidates,
            )
    except BaseException as exc:
        log.write(
            "exception",
            test_mode="phase1a_only",
            stage="phase1a_reinforce",
            error_type=exc.__class__.__name__,
            error_message=str(exc),
            project_id=str(project_id),
        )
        try:
            log.write(
                "interrupted_counts",
                test_mode="phase1a_only",
                stage="phase1a_reinforce",
                **await _count_acceptance_outputs(db_session, project_id),
            )
        except Exception as count_exc:
            log.write(
                "interrupted_count_failed",
                test_mode="phase1a_only",
                stage="phase1a_reinforce",
                error_type=count_exc.__class__.__name__,
                error_message=str(count_exc),
            )
        raise

    result = _phase1a_result_payload(phase0_result, phase1a_result)
    log.write(
        "phase_completed",
        test_mode="phase1a_only",
        stage="phase1a_reinforce",
        phase="phase1a_reinforce",
        status="completed" if not result["blocked"] else "failed",
        project_id=str(project_id),
        details=result["quality_stats"],
        block_reason=result["block_reason"],
    )
    log.write(
        "result",
        test_mode="phase1a_only",
        stage="phase1a_reinforce",
        project_id=str(project_id),
        **result,
    )
    output_counts = await _count_acceptance_outputs(db_session, project_id)
    coverage = _candidate_chapter_coverage(
        list(phase1a_result.candidates),
        start_chapter=1,
        end_chapter=EXPECTED_CHAPTER_COUNT,
    )
    log.write(
        "output_counts",
        test_mode="phase1a_only",
        stage="phase1a_reinforce",
        project_id=str(project_id),
        **output_counts,
    )
    log.write(
        "candidate_chapter_coverage",
        test_mode="phase1a_only",
        stage="phase1a_reinforce",
        project_id=str(project_id),
        **coverage,
    )

    acceptance_rule_results, acceptance_issues = _phase1a_only_acceptance_checks(
        result=result,
        output_counts=output_counts,
        coverage=coverage,
        expected_phase_shape=expected_phase_shape,
        expected_chapter_count=EXPECTED_CHAPTER_COUNT,
    )
    log.write(
        "acceptance_checks",
        test_mode="phase1a_only",
        stage="phase1a_reinforce",
        checks=acceptance_rule_results,
        issues=acceptance_issues,
    )
    summary_path = _write_phase1a_summary(
        log_path=log.path,
        wall_clock_s=time.monotonic() - log.started_at,
        result=result,
        output_counts=output_counts,
        coverage=coverage,
        expected_phase_shape=expected_phase_shape,
        issues=acceptance_issues,
        llm_config=llm_config,
    )
    artifact_path = _write_phase1a_artifact(
        log_path=log.path,
        phase0_result=phase0_result,
        phase1a_result=phase1a_result,
        coverage=coverage,
        expected_phase_shape=expected_phase_shape,
        llm_config=llm_config,
        project_id=str(project_id),
        task_id=str(task.id),
    )
    task_result = await _persist_phase_acceptance_task_result(
        db_session,
        task,
        test_mode="phase1a_only",
        stage="phase1a_reinforce",
        result=result,
        output_counts=output_counts,
        coverage=coverage,
        expected_phase_shape=expected_phase_shape,
        llm_config=llm_config,
        summary_path=summary_path,
        artifact_path=artifact_path,
        log_path=log.path,
        issues=acceptance_issues,
    )
    log.write(
        "task_result_persisted",
        test_mode="phase1a_only",
        stage="phase1a_reinforce",
        task_id=str(task.id),
        project_id=str(project_id),
        task_status=task.status,
        result_phase=task_result.get("phase"),
        quality_status=task_result.get("quality_status"),
        artifact_path=str(artifact_path),
    )
    log.write(
        "final_summary",
        test_mode="phase1a_only",
        stage="phase1a_reinforce",
        wall_clock_s=round(time.monotonic() - log.started_at, 2),
        phase1a_summary_path=str(summary_path),
        phase1a_artifact_path=str(artifact_path),
        project_id=str(project_id),
        task_id=str(task.id),
        issues=acceptance_issues,
        output_counts=output_counts,
        candidate_chapter_coverage=coverage,
        result=result,
    )
    if acceptance_issues:
        pytest.fail("\n".join(acceptance_issues))


@pytest.mark.asyncio
@pytest.mark.real_llm
@phase1b_real_llm_required
async def test_deep_import_60_phase1b_real_llm_acceptance(
    db_session: AsyncSession,
) -> None:
    assert EXPECTED_CHAPTER_COUNT == 60
    log = PersistentAcceptanceLogger.from_env()
    expected_phase_shape = _expected_phase_shape()
    llm_config = _llm_config_log_payload()
    log.write(
        "test_started",
        test_mode="phase1b_only",
        stage="phase1b_fusion",
        log_path=str(log.path),
        expected_chapter_count=EXPECTED_CHAPTER_COUNT,
        expected_phase_shape=expected_phase_shape,
        llm_config=llm_config,
    )

    phase1a_artifact_path = _phase1b_phase1a_artifact_path()
    assert phase1a_artifact_path is not None, (
        "未找到已通过的 Phase1a artifact；请先运行 "
        "RUN_DEEP_IMPORT_60_PHASE1A_REAL_LLM=1，或设置 "
        "PHASE1B_PHASE1A_ARTIFACT_PATH"
    )
    phase1a_result = _load_phase1a_artifact(phase1a_artifact_path)

    project_id = uuid.uuid4()
    db_session.add(
        Project(
            id=project_id,
            title="诡秘之主 第一部 前60章 Phase1b-only 验收",
            genre="西方奇幻",
            tone="维多利亚风格、黑暗",
            language="zh",
            target_length="novel",
            current_stage="writing",
        )
    )
    await db_session.flush()

    task = _build_phase_acceptance_task(
        project_id,
        test_mode="phase1b_only",
        stage="phase1b_fusion",
    )
    db_session.add(task)
    await db_session.flush()
    log.set_context(project_id=str(project_id), task_id=str(task.id))
    log.write(
        "task_created",
        test_mode="phase1b_only",
        stage="phase1b_fusion",
        task_id=str(task.id),
        task_type=task.task_type,
        project_id=str(project_id),
        meta=task.meta,
    )
    log.write(
        "phase1a_artifact_loaded",
        test_mode="phase1b_only",
        stage="phase1a_reinforce",
        phase="phase1a_reinforce",
        status="loaded",
        project_id=str(project_id),
        phase1a_artifact_path=str(phase1a_artifact_path),
        details=phase1a_result.quality_stats,
        candidate_count=len(phase1a_result.candidates),
    )

    workflow = DeepImportWorkflow()
    try:
        log.write(
            "phase_started",
            test_mode="phase1b_only",
            stage="phase1b_fusion",
            phase="phase1b_fusion",
            status="running",
            project_id=str(project_id),
        )
        phase1b_result = await workflow._run_phase1b_fusion(
            phase1a_result.candidates,
            start_chapter=1,
            end_chapter=EXPECTED_CHAPTER_COUNT,
        )
    except BaseException as exc:
        log.write(
            "exception",
            test_mode="phase1b_only",
            stage="phase1b_fusion",
            error_type=exc.__class__.__name__,
            error_message=str(exc),
            project_id=str(project_id),
        )
        raise

    result = _phase1b_result_payload(phase1a_result, phase1b_result)
    log.write(
        "phase_completed",
        test_mode="phase1b_only",
        stage="phase1b_fusion",
        phase="phase1b_fusion",
        status=(
            "degraded"
            if result["degraded"]
            else "completed"
            if not result["blocked"]
            else "failed"
        ),
        project_id=str(project_id),
        details=result["quality_stats"],
        block_reason=result["block_reason"],
    )
    log.write(
        "result",
        test_mode="phase1b_only",
        stage="phase1b_fusion",
        project_id=str(project_id),
        **result,
    )
    output_counts = await _count_acceptance_outputs(db_session, project_id)
    coverage = _candidate_chapter_coverage(
        list(phase1b_result.candidates),
        start_chapter=1,
        end_chapter=EXPECTED_CHAPTER_COUNT,
    )
    log.write(
        "output_counts",
        test_mode="phase1b_only",
        stage="phase1b_fusion",
        project_id=str(project_id),
        **output_counts,
    )
    log.write(
        "candidate_chapter_coverage",
        test_mode="phase1b_only",
        stage="phase1b_fusion",
        project_id=str(project_id),
        **coverage,
    )

    acceptance_rule_results, acceptance_issues = _phase1b_only_acceptance_checks(
        result=result,
        output_counts=output_counts,
        coverage=coverage,
        expected_phase_shape=expected_phase_shape,
        expected_chapter_count=EXPECTED_CHAPTER_COUNT,
    )
    log.write(
        "acceptance_checks",
        test_mode="phase1b_only",
        stage="phase1b_fusion",
        checks=acceptance_rule_results,
        issues=acceptance_issues,
    )
    summary_path = _write_phase1b_summary(
        log_path=log.path,
        wall_clock_s=time.monotonic() - log.started_at,
        result=result,
        output_counts=output_counts,
        coverage=coverage,
        expected_phase_shape=expected_phase_shape,
        issues=acceptance_issues,
        llm_config=llm_config,
    )
    artifact_path = _write_phase1b_artifact(
        log_path=log.path,
        phase1a_artifact_path=phase1a_artifact_path,
        phase1a_result=phase1a_result,
        phase1b_result=phase1b_result,
        coverage=coverage,
        expected_phase_shape=expected_phase_shape,
        llm_config=llm_config,
        project_id=str(project_id),
        task_id=str(task.id),
    )
    task_result = await _persist_phase_acceptance_task_result(
        db_session,
        task,
        test_mode="phase1b_only",
        stage="phase1b_fusion",
        result=result,
        output_counts=output_counts,
        coverage=coverage,
        expected_phase_shape=expected_phase_shape,
        llm_config=llm_config,
        summary_path=summary_path,
        artifact_path=artifact_path,
        log_path=log.path,
        issues=acceptance_issues,
    )
    log.write(
        "task_result_persisted",
        test_mode="phase1b_only",
        stage="phase1b_fusion",
        task_id=str(task.id),
        project_id=str(project_id),
        task_status=task.status,
        result_phase=task_result.get("phase"),
        quality_status=task_result.get("quality_status"),
        artifact_path=str(artifact_path),
    )
    log.write(
        "final_summary",
        test_mode="phase1b_only",
        stage="phase1b_fusion",
        wall_clock_s=round(time.monotonic() - log.started_at, 2),
        phase1b_summary_path=str(summary_path),
        phase1b_artifact_path=str(artifact_path),
        source_phase1a_artifact_path=str(phase1a_artifact_path),
        project_id=str(project_id),
        task_id=str(task.id),
        issues=acceptance_issues,
        output_counts=output_counts,
        candidate_chapter_coverage=coverage,
        result=result,
    )
    if acceptance_issues:
        pytest.fail("\n".join(acceptance_issues))


@pytest.mark.asyncio
@pytest.mark.real_llm
@phase2a_real_llm_required
async def test_deep_import_60_phase2a_real_llm_acceptance(
    db_session: AsyncSession,
) -> None:
    assert EXPECTED_CHAPTER_COUNT == 60
    log = PersistentAcceptanceLogger.from_env()
    expected_phase_shape = _expected_phase_shape()
    llm_config = _llm_config_log_payload()
    phase2_batch_tuning = _phase2_batch_runtime_payload()
    log.write(
        "test_started",
        test_mode="phase2a_only",
        stage="entity_extraction_phase2a",
        log_path=str(log.path),
        file_path=str(REAL_FILE_PATH),
        expected_chapter_count=EXPECTED_CHAPTER_COUNT,
        expected_phase_shape=expected_phase_shape,
        llm_config=llm_config,
        phase2_batch_tuning=phase2_batch_tuning,
    )
    assert REAL_FILE_PATH.exists(), f"真实文件不存在: {REAL_FILE_PATH}"
    file_bytes = REAL_FILE_PATH.read_bytes()
    chapters = parse_txt(file_bytes)
    assert len(chapters) == EXPECTED_CHAPTER_COUNT
    assert all(chapter.get("content") for chapter in chapters)
    log.write(
        "file_parsed",
        test_mode="phase2a_only",
        stage="entity_extraction_phase2a",
        chapter_count=len(chapters),
        bytes=len(file_bytes),
        first_title=_chapter_title(chapters[0]) if chapters else None,
        last_title=_chapter_title(chapters[-1]) if chapters else None,
        nonempty_content_count=sum(1 for chapter in chapters if chapter.get("content")),
    )

    phase1b_artifact_path = _phase2a_phase1b_artifact_path()
    assert phase1b_artifact_path is not None, (
        "未找到已通过的 Phase1b artifact；请先运行 "
        "RUN_DEEP_IMPORT_60_PHASE1B_REAL_LLM=1，或设置 "
        "PHASE2A_PHASE1B_ARTIFACT_PATH"
    )
    assert _is_passed_phase1b_artifact(phase1b_artifact_path), (
        "Phase2a source Phase1b artifact 未通过验收，不能作为输入: "
        f"{phase1b_artifact_path}"
    )
    phase1b_result = _load_phase1b_artifact(phase1b_artifact_path)
    repair_source_payload, repair_summary = _phase2a_repair_context()

    project_id = uuid.uuid4()
    db_session.add(
        Project(
            id=project_id,
            title="诡秘之主 第一部 前60章 Phase2a-only 验收",
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
    log.set_context(project_id=str(project_id))
    log.write(
        "chapters_imported",
        test_mode="phase2a_only",
        stage="entity_extraction_phase2a",
        project_id=str(project_id),
        total_chapters=import_result.total_chapters,
        imported_chapters=import_result.imported_chapters,
    )
    assert import_result.total_chapters == EXPECTED_CHAPTER_COUNT
    assert import_result.imported_chapters == EXPECTED_CHAPTER_COUNT

    task = _build_phase_acceptance_task(
        project_id,
        test_mode="phase2a_only",
        stage="entity_extraction_phase2a",
    )
    db_session.add(task)
    await db_session.flush()
    workflow_id = str(task.id)
    log.set_context(project_id=str(project_id), task_id=workflow_id)
    log.write(
        "task_created",
        test_mode="phase2a_only",
        stage="entity_extraction_phase2a",
        task_id=workflow_id,
        task_type=task.task_type,
        project_id=str(project_id),
        meta=task.meta,
    )
    log.write(
        "phase1b_artifact_loaded",
        test_mode="phase2a_only",
        stage="phase1b_fusion",
        phase="phase1b_fusion",
        status="loaded",
        project_id=str(project_id),
        phase1b_artifact_path=str(phase1b_artifact_path),
        details=phase1b_result.quality_stats,
        candidate_count=len(phase1b_result.candidates),
        repair_summary=repair_summary,
    )

    try:
        log.write(
            "phase_started",
            test_mode="phase2a_only",
            stage="scene_commit",
            phase="scene_commit",
            status="running",
            project_id=str(project_id),
        )
        scene_commit_result = await SceneCommitter().commit(
            db_session,
            str(project_id),
            phase1b_result.candidates,
            workflow_id,
        )
        await db_session.flush()
        log.write(
            "phase_completed",
            test_mode="phase2a_only",
            stage="scene_commit",
            phase="scene_commit",
            status="completed",
            project_id=str(project_id),
            details=scene_commit_result.model_dump(mode="json"),
        )
        if repair_source_payload is not None:
            existing_checkpoints = _phase2a_repair_checkpoints_for_scene_commit(
                repair_source_payload,
                scene_commit_result,
            )
            if repair_summary is not None:
                checkpoint_scenes = (
                    ((existing_checkpoints or {}).get("phase2") or {}).get("scenes")
                    or []
                )
                repair_summary = {
                    **repair_summary,
                    "remapped_checkpoint_count": len(checkpoint_scenes),
                }
            log.write(
                "repair_checkpoints_remapped",
                test_mode="phase2a_only",
                stage="entity_extraction_phase2a",
                project_id=str(project_id),
                remapped_checkpoint_count=(
                    len(
                        (((existing_checkpoints or {}).get("phase2") or {}).get(
                            "scenes"
                        ))
                        or []
                    )
                ),
            )

            source_world_snapshot = repair_source_payload.get("world_snapshot") or {}
            if _has_hydratable_phase2a_snapshot(repair_source_payload):
                hydrate_summary = await _hydrate_world_snapshot(
                    db_session,
                    project_id,
                    source_world_snapshot,
                )
                if repair_summary is not None:
                    repair_summary = {
                        **repair_summary,
                        "repair_hydrate_summary": hydrate_summary,
                    }
                log.write(
                    "repair_world_snapshot_hydrated",
                    test_mode="phase2a_only",
                    stage="entity_extraction_phase2a",
                    project_id=str(project_id),
                    **hydrate_summary,
                )
            else:
                log.write(
                    "repair_world_snapshot_missing",
                    test_mode="phase2a_only",
                    stage="entity_extraction_phase2a",
                    project_id=str(project_id),
                    source_world_snapshot_keys=sorted(source_world_snapshot),
                )
        else:
            existing_checkpoints = None

        progress_events: list[dict[str, int]] = []

        async def _on_scene_progress(completed: int, total: int) -> None:
            event = {"completed": completed, "total": total}
            progress_events.append(event)
            log.write(
                "phase2a_progress",
                test_mode="phase2a_only",
                stage="entity_extraction_phase2a",
                phase="entity_extraction_phase2a",
                status="running",
                project_id=str(project_id),
                **event,
            )

        log.write(
            "phase_started",
            test_mode="phase2a_only",
            stage="entity_extraction_phase2a",
            phase="entity_extraction_phase2a",
            status="running",
            project_id=str(project_id),
            phase2_batch_tuning=phase2_batch_tuning,
            has_repair_source=repair_source_payload is not None,
        )
        phase2_raw_result = await SceneEntityExtractionService().extract_by_scenes(
            db_session,
            str(project_id),
            workflow_id=workflow_id,
            on_scene_progress=_on_scene_progress,
            existing_checkpoints=existing_checkpoints,
            start_chapter=1,
            end_chapter=EXPECTED_CHAPTER_COUNT,
            include_alias_relations=False,
        )
        await db_session.flush()
    except BaseException as exc:
        log.write(
            "exception",
            test_mode="phase2a_only",
            stage="entity_extraction_phase2a",
            error_type=exc.__class__.__name__,
            error_message=str(exc),
            project_id=str(project_id),
        )
        try:
            log.write(
                "interrupted_counts",
                test_mode="phase2a_only",
                stage="entity_extraction_phase2a",
                **await _count_acceptance_outputs(db_session, project_id),
            )
        except Exception as count_exc:
            log.write(
                "interrupted_count_failed",
                test_mode="phase2a_only",
                stage="entity_extraction_phase2a",
                error_type=count_exc.__class__.__name__,
                error_message=str(count_exc),
            )
        raise

    phase2_result = _merge_phase2a_repair_result(
        repair_source_payload,
        phase2_raw_result,
    )
    phase2_quality = phase2_quality_stats(phase2_result)
    if repair_summary is not None:
        repair_summary = {
            **repair_summary,
            "repair_completed_scenes": phase2_raw_result.get("completed_scenes"),
            "repair_skipped_scenes": phase2_raw_result.get("skipped_scenes"),
            "repair_rerun_scenes": phase2_raw_result.get("rerun_scenes"),
            "repair_failed_scene_indices": phase2_raw_result.get(
                "failed_scene_indices"
            )
            or [],
            "merged_total_created": phase2_quality.get("total_created"),
            "merged_completed_scenes": phase2_quality.get("completed_scenes"),
        }
    result = _phase2a_result_payload(
        phase1b_result=phase1b_result,
        scene_commit_result=scene_commit_result,
        phase2_result=phase2_result,
        phase2_quality=phase2_quality,
        repair_summary=repair_summary,
    )
    log.write(
        "phase_completed",
        test_mode="phase2a_only",
        stage="entity_extraction_phase2a",
        phase="entity_extraction_phase2a",
        status="degraded" if phase2_quality.get("degraded") else "completed",
        project_id=str(project_id),
        details=phase2_quality,
        repair_summary=repair_summary,
    )
    log.write(
        "result",
        test_mode="phase2a_only",
        stage="entity_extraction_phase2a",
        project_id=str(project_id),
        **result,
    )
    output_counts = await _count_acceptance_outputs(db_session, project_id)
    scene_coverage = await _scene_chapter_coverage(
        db_session,
        project_id,
        start_chapter=1,
        end_chapter=EXPECTED_CHAPTER_COUNT,
    )
    log.write(
        "output_counts",
        test_mode="phase2a_only",
        stage="entity_extraction_phase2a",
        project_id=str(project_id),
        **output_counts,
    )
    log.write(
        "scene_chapter_coverage",
        test_mode="phase2a_only",
        stage="entity_extraction_phase2a",
        project_id=str(project_id),
        **scene_coverage,
    )

    acceptance_rule_results, acceptance_issues = _phase2a_only_acceptance_checks(
        result=result,
        output_counts=output_counts,
        scene_coverage=scene_coverage,
        expected_chapter_count=EXPECTED_CHAPTER_COUNT,
    )
    log.write(
        "acceptance_checks",
        test_mode="phase2a_only",
        stage="entity_extraction_phase2a",
        checks=acceptance_rule_results,
        issues=acceptance_issues,
    )
    summary_path = _write_phase2a_summary(
        log_path=log.path,
        wall_clock_s=time.monotonic() - log.started_at,
        result=result,
        output_counts=output_counts,
        scene_coverage=scene_coverage,
        issues=acceptance_issues,
        llm_config=llm_config,
    )
    world_snapshot = await _world_snapshot_for_phase_artifact(db_session, project_id)
    log.write(
        "world_snapshot_captured",
        test_mode="phase2a_only",
        stage="entity_extraction_phase2a",
        project_id=str(project_id),
        entity_count=world_snapshot.get("entity_count"),
        relation_count=world_snapshot.get("relation_count"),
    )
    artifact_path = _write_phase2a_artifact(
        log_path=log.path,
        source_phase1b_artifact_path=phase1b_artifact_path,
        phase1b_result=phase1b_result,
        scene_commit_result=scene_commit_result,
        phase2_result=phase2_result,
        phase2_quality=phase2_quality,
        output_counts=output_counts,
        scene_coverage=scene_coverage,
        expected_phase_shape=expected_phase_shape,
        llm_config=llm_config,
        project_id=str(project_id),
        task_id=workflow_id,
        repair_summary=repair_summary,
        world_snapshot=world_snapshot,
    )
    task_result = await _persist_phase_acceptance_task_result(
        db_session,
        task,
        test_mode="phase2a_only",
        stage="entity_extraction_phase2a",
        result=result,
        output_counts=output_counts,
        coverage=scene_coverage,
        expected_phase_shape=expected_phase_shape,
        llm_config=llm_config,
        summary_path=summary_path,
        artifact_path=artifact_path,
        log_path=log.path,
        issues=acceptance_issues,
    )
    log.write(
        "task_result_persisted",
        test_mode="phase2a_only",
        stage="entity_extraction_phase2a",
        task_id=workflow_id,
        project_id=str(project_id),
        task_status=task.status,
        result_phase=task_result.get("phase"),
        quality_status=task_result.get("quality_status"),
        artifact_path=str(artifact_path),
    )
    log.write(
        "final_summary",
        test_mode="phase2a_only",
        stage="entity_extraction_phase2a",
        wall_clock_s=round(time.monotonic() - log.started_at, 2),
        phase2a_summary_path=str(summary_path),
        phase2a_artifact_path=str(artifact_path),
        source_phase1b_artifact_path=str(phase1b_artifact_path),
        project_id=str(project_id),
        task_id=workflow_id,
        issues=acceptance_issues,
        output_counts=output_counts,
        scene_chapter_coverage=scene_coverage,
        phase2_batch_tuning=phase2_batch_tuning,
        repair_summary=repair_summary,
        result=result,
    )
    if acceptance_issues:
        pytest.fail("\n".join(acceptance_issues))


@pytest.mark.asyncio
@pytest.mark.real_llm
@phase2b_real_llm_required
async def test_deep_import_60_phase2b_real_llm_acceptance(
    db_session: AsyncSession,
) -> None:
    assert EXPECTED_CHAPTER_COUNT == 60
    log = PersistentAcceptanceLogger.from_env()
    expected_phase_shape = _expected_phase_shape()
    llm_config = _llm_config_log_payload()
    log.write(
        "test_started",
        test_mode="phase2b_only",
        stage="alias_relation_phase2b",
        log_path=str(log.path),
        file_path=str(REAL_FILE_PATH),
        expected_chapter_count=EXPECTED_CHAPTER_COUNT,
        expected_phase_shape=expected_phase_shape,
        llm_config=llm_config,
    )
    assert REAL_FILE_PATH.exists(), f"真实文件不存在: {REAL_FILE_PATH}"
    file_bytes = REAL_FILE_PATH.read_bytes()
    chapters = parse_txt(file_bytes)
    assert len(chapters) == EXPECTED_CHAPTER_COUNT
    assert all(chapter.get("content") for chapter in chapters)

    phase2a_artifact_path = _phase2b_phase2a_artifact_path()
    assert phase2a_artifact_path is not None, (
        "未找到带 world_snapshot 的已通过 Phase2a artifact；请先重新运行 "
        "RUN_DEEP_IMPORT_60_PHASE2A_REAL_LLM=1，或设置 "
        "PHASE2B_PHASE2A_ARTIFACT_PATH"
    )
    assert _is_hydratable_phase2a_artifact(phase2a_artifact_path), (
        "Phase2b source Phase2a artifact 未通过或缺少 world_snapshot，不能作为输入: "
        f"{phase2a_artifact_path}"
    )
    phase2a_payload = _load_phase2a_artifact_payload(phase2a_artifact_path)
    phase1b_artifact_path = Path(
        str(phase2a_payload.get("source_phase1b_artifact_path") or "")
    ).expanduser()
    assert phase1b_artifact_path.exists(), (
        "Phase2a artifact 缺少可读取的 source Phase1b artifact: "
        f"{phase1b_artifact_path}"
    )
    phase1b_result = _load_phase1b_artifact(phase1b_artifact_path)
    repair_source_payload, repair_summary = _phase2b_repair_context()

    project_id = uuid.uuid4()
    db_session.add(
        Project(
            id=project_id,
            title="诡秘之主 第一部 前60章 Phase2b-only 验收",
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
    assert import_result.total_chapters == EXPECTED_CHAPTER_COUNT
    assert import_result.imported_chapters == EXPECTED_CHAPTER_COUNT

    task = _build_phase_acceptance_task(
        project_id,
        test_mode="phase2b_only",
        stage="alias_relation_phase2b",
    )
    db_session.add(task)
    await db_session.flush()
    workflow_id = str(task.id)
    log.set_context(project_id=str(project_id), task_id=workflow_id)
    log.write(
        "task_created",
        test_mode="phase2b_only",
        stage="alias_relation_phase2b",
        task_id=workflow_id,
        task_type=task.task_type,
        project_id=str(project_id),
        meta=task.meta,
        source_phase2a_artifact_path=str(phase2a_artifact_path),
    )

    try:
        log.write(
            "phase_started",
            test_mode="phase2b_only",
            stage="scene_commit",
            phase="scene_commit",
            status="running",
            project_id=str(project_id),
        )
        scene_commit_result = await SceneCommitter().commit(
            db_session,
            str(project_id),
            phase1b_result.candidates,
            workflow_id,
        )
        await db_session.flush()
        log.write(
            "phase_completed",
            test_mode="phase2b_only",
            stage="scene_commit",
            phase="scene_commit",
            status="completed",
            project_id=str(project_id),
            details=scene_commit_result.model_dump(mode="json"),
        )
        existing_checkpoints = _phase2b_repair_checkpoints_for_scene_commit(
            repair_source_payload,
            scene_commit_result,
        )
        if repair_summary is not None:
            checkpoint_scenes = (
                ((existing_checkpoints or {}).get("phase2b") or {}).get("scenes")
                or []
            )
            repair_summary = {
                **repair_summary,
                "remapped_checkpoint_count": len(checkpoint_scenes),
            }
            log.write(
                "repair_checkpoints_remapped",
                test_mode="phase2b_only",
                stage="alias_relation_phase2b",
                project_id=str(project_id),
                remapped_checkpoint_count=len(checkpoint_scenes),
            )

        hydrate_source_payload = (
            repair_source_payload
            if _has_hydratable_phase2a_snapshot(repair_source_payload or {})
            else phase2a_payload
        )
        hydrate_summary = await _hydrate_world_snapshot(
            db_session,
            project_id,
            hydrate_source_payload.get("world_snapshot") or {},
        )
        if repair_summary is not None:
            repair_summary = {
                **repair_summary,
                "repair_hydrate_source": (
                    "phase2b_artifact"
                    if hydrate_source_payload is repair_source_payload
                    else "phase2a_artifact"
                ),
                "repair_hydrate_summary": hydrate_summary,
            }
        log.write(
            "world_snapshot_hydrated",
            test_mode="phase2b_only",
            stage="alias_relation_phase2b",
            phase="phase2a_artifact_hydration",
            status="completed",
            project_id=str(project_id),
            repair_summary=repair_summary,
            **hydrate_summary,
        )

        progress_events: list[dict[str, int]] = []

        async def _on_phase2b_progress(completed: int, total: int) -> None:
            event = {"completed": completed, "total": total}
            progress_events.append(event)
            log.write(
                "phase2b_progress",
                test_mode="phase2b_only",
                stage="alias_relation_phase2b",
                phase="alias_relation_phase2b",
                status="running",
                project_id=str(project_id),
                **event,
            )

        log.write(
            "phase_started",
            test_mode="phase2b_only",
            stage="alias_relation_phase2b",
            phase="alias_relation_phase2b",
            status="running",
            project_id=str(project_id),
            has_repair_source=repair_source_payload is not None,
        )
        phase2b_raw_result = await SceneEntityExtractionService().extract_alias_relations(
            db_session,
            str(project_id),
            workflow_id=workflow_id,
            start_chapter=1,
            end_chapter=EXPECTED_CHAPTER_COUNT,
            on_scene_progress=_on_phase2b_progress,
            existing_checkpoints=existing_checkpoints,
        )
        await db_session.flush()
    except BaseException as exc:
        log.write(
            "exception",
            test_mode="phase2b_only",
            stage="alias_relation_phase2b",
            error_type=exc.__class__.__name__,
            error_message=str(exc),
            project_id=str(project_id),
        )
        try:
            log.write(
                "interrupted_counts",
                test_mode="phase2b_only",
                stage="alias_relation_phase2b",
                **await _count_acceptance_outputs(db_session, project_id),
            )
        except Exception as count_exc:
            log.write(
                "interrupted_count_failed",
                test_mode="phase2b_only",
                stage="alias_relation_phase2b",
                error_type=count_exc.__class__.__name__,
                error_message=str(count_exc),
            )
        raise

    phase2b_result = _merge_phase2b_repair_result(
        repair_source_payload,
        phase2b_raw_result,
    )
    if repair_summary is not None:
        repair_summary = {
            **repair_summary,
            "repair_completed_scenes": phase2b_raw_result.get(
                "alias_relation_scenes"
            ),
            "repair_skipped_scenes": phase2b_raw_result.get(
                "alias_relation_skipped_scenes"
            ),
            "repair_rerun_scenes": phase2b_raw_result.get(
                "alias_relation_rerun_scenes"
            ),
            "repair_failed_scenes": phase2b_raw_result.get(
                "alias_relation_failed_scenes"
            )
            or [],
            "merged_alias_relation_scenes": phase2b_result.get(
                "alias_relation_scenes"
            ),
            "merged_total_aliases": phase2b_result.get("total_aliases"),
            "merged_total_relations": phase2b_result.get("total_relations"),
        }
    result = _phase2b_result_payload(
        source_phase2a_payload=phase2a_payload,
        scene_commit_result=scene_commit_result,
        hydrate_summary=hydrate_summary,
        phase2b_result=phase2b_result,
    )
    log.write(
        "phase_completed",
        test_mode="phase2b_only",
        stage="alias_relation_phase2b",
        phase="alias_relation_phase2b",
        status="degraded" if phase2b_result.get("degraded") else "completed",
        project_id=str(project_id),
        details=result["quality_stats"],
        repair_summary=repair_summary,
    )
    output_counts = await _count_acceptance_outputs(db_session, project_id)
    scene_coverage = await _scene_chapter_coverage(
        db_session,
        project_id,
        start_chapter=1,
        end_chapter=EXPECTED_CHAPTER_COUNT,
    )
    log.write(
        "output_counts",
        test_mode="phase2b_only",
        stage="alias_relation_phase2b",
        project_id=str(project_id),
        **output_counts,
    )
    log.write(
        "scene_chapter_coverage",
        test_mode="phase2b_only",
        stage="alias_relation_phase2b",
        project_id=str(project_id),
        **scene_coverage,
    )

    acceptance_rule_results, acceptance_issues = _phase2b_only_acceptance_checks(
        result=result,
        output_counts=output_counts,
        scene_coverage=scene_coverage,
        expected_chapter_count=EXPECTED_CHAPTER_COUNT,
    )
    log.write(
        "acceptance_checks",
        test_mode="phase2b_only",
        stage="alias_relation_phase2b",
        checks=acceptance_rule_results,
        issues=acceptance_issues,
    )
    summary_path = _write_phase2b_summary(
        log_path=log.path,
        wall_clock_s=time.monotonic() - log.started_at,
        result=result,
        output_counts=output_counts,
        scene_coverage=scene_coverage,
        issues=acceptance_issues,
        llm_config=llm_config,
    )
    world_snapshot = await _world_snapshot_for_phase_artifact(db_session, project_id)
    log.write(
        "world_snapshot_captured",
        test_mode="phase2b_only",
        stage="alias_relation_phase2b",
        project_id=str(project_id),
        entity_count=world_snapshot.get("entity_count"),
        relation_count=world_snapshot.get("relation_count"),
    )
    artifact_path = _write_phase2b_artifact(
        log_path=log.path,
        source_phase2a_artifact_path=phase2a_artifact_path,
        source_phase2a_payload=phase2a_payload,
        hydrate_summary=hydrate_summary,
        scene_commit_result=scene_commit_result,
        phase2b_result=phase2b_result,
        output_counts=output_counts,
        scene_coverage=scene_coverage,
        expected_phase_shape=expected_phase_shape,
        llm_config=llm_config,
        project_id=str(project_id),
        task_id=workflow_id,
        world_snapshot=world_snapshot,
        repair_summary=repair_summary,
    )
    task_result = await _persist_phase_acceptance_task_result(
        db_session,
        task,
        test_mode="phase2b_only",
        stage="alias_relation_phase2b",
        result=result,
        output_counts=output_counts,
        coverage=scene_coverage,
        expected_phase_shape=expected_phase_shape,
        llm_config=llm_config,
        summary_path=summary_path,
        artifact_path=artifact_path,
        log_path=log.path,
        issues=acceptance_issues,
    )
    log.write(
        "task_result_persisted",
        test_mode="phase2b_only",
        stage="alias_relation_phase2b",
        task_id=workflow_id,
        project_id=str(project_id),
        task_status=task.status,
        result_phase=task_result.get("phase"),
        quality_status=task_result.get("quality_status"),
        artifact_path=str(artifact_path),
    )
    log.write(
        "final_summary",
        test_mode="phase2b_only",
        stage="alias_relation_phase2b",
        wall_clock_s=round(time.monotonic() - log.started_at, 2),
        phase2b_summary_path=str(summary_path),
        phase2b_artifact_path=str(artifact_path),
        source_phase2a_artifact_path=str(phase2a_artifact_path),
        project_id=str(project_id),
        task_id=workflow_id,
        repair_summary=repair_summary,
        issues=acceptance_issues,
        output_counts=output_counts,
        scene_chapter_coverage=scene_coverage,
        result=result,
    )
    if acceptance_issues:
        pytest.fail("\n".join(acceptance_issues))


@pytest.mark.asyncio
@pytest.mark.real_llm
@phase3_real_llm_required
async def test_deep_import_60_phase3_real_llm_acceptance(
    db_session: AsyncSession,
) -> None:
    assert EXPECTED_CHAPTER_COUNT == 60
    log = PersistentAcceptanceLogger.from_env()
    expected_phase_shape = _expected_phase_shape()
    llm_config = _llm_config_log_payload()
    log.write(
        "test_started",
        test_mode="phase3_only",
        stage="structure_analysis",
        log_path=str(log.path),
        file_path=str(REAL_FILE_PATH),
        expected_chapter_count=EXPECTED_CHAPTER_COUNT,
        expected_phase_shape=expected_phase_shape,
        llm_config=llm_config,
    )
    assert REAL_FILE_PATH.exists(), f"真实文件不存在: {REAL_FILE_PATH}"
    file_bytes = REAL_FILE_PATH.read_bytes()
    chapters = parse_txt(file_bytes)
    assert len(chapters) == EXPECTED_CHAPTER_COUNT
    assert all(chapter.get("content") for chapter in chapters)

    phase2b_artifact_path = _phase3_phase2b_artifact_path()
    assert phase2b_artifact_path is not None, (
        "未找到已通过 Phase2b artifact；请先运行 "
        "RUN_DEEP_IMPORT_60_PHASE2B_REAL_LLM=1，或设置 "
        "PHASE3_PHASE2B_ARTIFACT_PATH"
    )
    assert _is_passed_phase2b_artifact(phase2b_artifact_path), (
        "Phase3 source Phase2b artifact 未通过或缺少 world_snapshot，不能作为输入: "
        f"{phase2b_artifact_path}"
    )
    phase2b_payload = _load_phase2b_artifact_payload(phase2b_artifact_path)
    phase1b_artifact_path = Path(
        str(phase2b_payload.get("source_phase1b_artifact_path") or "")
    ).expanduser()
    assert phase1b_artifact_path.exists(), (
        "Phase2b artifact 缺少可读取的 source Phase1b artifact: "
        f"{phase1b_artifact_path}"
    )
    phase1b_result = _load_phase1b_artifact(phase1b_artifact_path)

    project_id = uuid.uuid4()
    db_session.add(
        Project(
            id=project_id,
            title="诡秘之主 第一部 前60章 Phase3-only 验收",
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
    assert import_result.total_chapters == EXPECTED_CHAPTER_COUNT
    assert import_result.imported_chapters == EXPECTED_CHAPTER_COUNT

    task = _build_phase_acceptance_task(
        project_id,
        test_mode="phase3_only",
        stage="structure_analysis",
    )
    db_session.add(task)
    await db_session.flush()
    workflow_id = str(task.id)
    log.set_context(project_id=str(project_id), task_id=workflow_id)
    log.write(
        "task_created",
        test_mode="phase3_only",
        stage="structure_analysis",
        task_id=workflow_id,
        task_type=task.task_type,
        project_id=str(project_id),
        meta=task.meta,
        source_phase2b_artifact_path=str(phase2b_artifact_path),
    )

    try:
        log.write(
            "phase_started",
            test_mode="phase3_only",
            stage="scene_commit",
            phase="scene_commit",
            status="running",
            project_id=str(project_id),
        )
        scene_commit_result = await SceneCommitter().commit(
            db_session,
            str(project_id),
            phase1b_result.candidates,
            workflow_id,
        )
        await db_session.flush()
        log.write(
            "phase_completed",
            test_mode="phase3_only",
            stage="scene_commit",
            phase="scene_commit",
            status="completed",
            project_id=str(project_id),
            details=scene_commit_result.model_dump(mode="json"),
        )

        hydrate_summary = await _hydrate_world_snapshot(
            db_session,
            project_id,
            phase2b_payload.get("world_snapshot") or {},
        )
        await db_session.commit()
        log.write(
            "world_snapshot_hydrated",
            test_mode="phase3_only",
            stage="structure_analysis",
            phase="phase2b_artifact_hydration",
            status="completed",
            project_id=str(project_id),
            **hydrate_summary,
        )

        progress_events: list[dict[str, Any]] = []

        async def _on_phase3_progress(
            progress: DeepImportProgress,
            fraction: float,
        ) -> None:
            event = {
                "fraction": round(float(fraction), 4),
                "phase": progress.current_phase,
                "current_step": (
                    progress.current_step.value
                    if progress.current_step is not None
                    else None
                ),
                "quality_status": progress.quality_status,
            }
            progress_events.append(event)
            log.write(
                "phase3_progress",
                test_mode="phase3_only",
                stage="structure_analysis",
                status="running",
                project_id=str(project_id),
                **event,
            )

        log.write(
            "phase_started",
            test_mode="phase3_only",
            stage="structure_analysis",
            phase="structure_analysis",
            status="running",
            project_id=str(project_id),
        )
        progress = DeepImportProgress(
            workflow_id=workflow_id,
            workflow_type=str(task.task_type),
            stage="structure_analysis",
        )
        progress = await DeepImportWorkflow().run_structure_analysis_only(
            db_session,
            str(project_id),
            1,
            EXPECTED_CHAPTER_COUNT,
            progress,
            workflow_id=workflow_id,
            context_mode="working",
            include_pending_objects=True,
            on_progress=_on_phase3_progress,
        )
        await db_session.flush()
    except BaseException as exc:
        log.write(
            "exception",
            test_mode="phase3_only",
            stage="structure_analysis",
            error_type=exc.__class__.__name__,
            error_message=str(exc),
            project_id=str(project_id),
        )
        try:
            log.write(
                "interrupted_counts",
                test_mode="phase3_only",
                stage="structure_analysis",
                **await _count_acceptance_outputs(db_session, project_id),
            )
        except Exception as count_exc:
            log.write(
                "interrupted_count_failed",
                test_mode="phase3_only",
                stage="structure_analysis",
                error_type=count_exc.__class__.__name__,
                error_message=str(count_exc),
            )
        raise

    progress_result = progress.model_dump(mode="json")
    result = _phase3_result_payload(
        source_phase2b_payload=phase2b_payload,
        scene_commit_result=scene_commit_result,
        hydrate_summary=hydrate_summary,
        progress_result=progress_result,
    )
    log.write(
        "phase_completed",
        test_mode="phase3_only",
        stage="structure_analysis",
        phase="structure_analysis",
        status="degraded" if result.get("degraded") else "completed",
        project_id=str(project_id),
        details=result["quality_stats"],
        progress_events=progress_events[-5:],
    )
    output_counts = await _count_acceptance_outputs(db_session, project_id)
    scene_coverage = await _scene_chapter_coverage(
        db_session,
        project_id,
        start_chapter=1,
        end_chapter=EXPECTED_CHAPTER_COUNT,
    )
    log.write(
        "output_counts",
        test_mode="phase3_only",
        stage="structure_analysis",
        project_id=str(project_id),
        **output_counts,
    )
    log.write(
        "scene_chapter_coverage",
        test_mode="phase3_only",
        stage="structure_analysis",
        project_id=str(project_id),
        **scene_coverage,
    )

    acceptance_rule_results, acceptance_issues = _phase3_only_acceptance_checks(
        result=result,
        output_counts=output_counts,
        scene_coverage=scene_coverage,
        expected_chapter_count=EXPECTED_CHAPTER_COUNT,
    )
    log.write(
        "acceptance_checks",
        test_mode="phase3_only",
        stage="structure_analysis",
        checks=acceptance_rule_results,
        issues=acceptance_issues,
    )
    summary_path = _write_phase3_summary(
        log_path=log.path,
        wall_clock_s=time.monotonic() - log.started_at,
        result=result,
        output_counts=output_counts,
        scene_coverage=scene_coverage,
        issues=acceptance_issues,
        llm_config=llm_config,
    )
    artifact_path = _write_phase3_artifact(
        log_path=log.path,
        source_phase2b_artifact_path=phase2b_artifact_path,
        source_phase2b_payload=phase2b_payload,
        hydrate_summary=hydrate_summary,
        scene_commit_result=scene_commit_result,
        progress_result=progress_result,
        result=result,
        output_counts=output_counts,
        scene_coverage=scene_coverage,
        expected_phase_shape=expected_phase_shape,
        llm_config=llm_config,
        project_id=str(project_id),
        task_id=workflow_id,
    )
    task_result = await _persist_phase_acceptance_task_result(
        db_session,
        task,
        test_mode="phase3_only",
        stage="structure_analysis",
        result=result,
        output_counts=output_counts,
        coverage=scene_coverage,
        expected_phase_shape=expected_phase_shape,
        llm_config=llm_config,
        summary_path=summary_path,
        artifact_path=artifact_path,
        log_path=log.path,
        issues=acceptance_issues,
    )
    log.write(
        "task_result_persisted",
        test_mode="phase3_only",
        stage="structure_analysis",
        task_id=workflow_id,
        project_id=str(project_id),
        task_status=task.status,
        result_phase=task_result.get("phase"),
        quality_status=task_result.get("quality_status"),
        artifact_path=str(artifact_path),
    )
    log.write(
        "final_summary",
        test_mode="phase3_only",
        stage="structure_analysis",
        wall_clock_s=round(time.monotonic() - log.started_at, 2),
        phase3_summary_path=str(summary_path),
        phase3_artifact_path=str(artifact_path),
        source_phase2b_artifact_path=str(phase2b_artifact_path),
        project_id=str(project_id),
        task_id=workflow_id,
        issues=acceptance_issues,
        output_counts=output_counts,
        scene_chapter_coverage=scene_coverage,
        result=result,
    )
    if acceptance_issues:
        pytest.fail("\n".join(acceptance_issues))


@pytest.mark.asyncio
@pytest.mark.real_llm
@scene_real_llm_required
async def test_deep_import_60_scene_real_llm_acceptance(
    db_session: AsyncSession,
) -> None:
    assert EXPECTED_CHAPTER_COUNT == 60
    log = PersistentAcceptanceLogger.from_env()
    expected_phase_shape = _expected_phase_shape()
    log.write(
        "test_started",
        test_mode="scene_only",
        stage="scenes",
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
    assert all(chapter.get("content") for chapter in chapters)
    log.write(
        "file_parsed",
        test_mode="scene_only",
        stage="scenes",
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
            title="诡秘之主 第一部 前60章 Scene-only 验收",
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
        test_mode="scene_only",
        stage="scenes",
        project_id=str(project_id),
        total_chapters=import_result.total_chapters,
        imported_chapters=import_result.imported_chapters,
    )
    assert import_result.total_chapters == EXPECTED_CHAPTER_COUNT
    assert import_result.imported_chapters == EXPECTED_CHAPTER_COUNT

    task = _build_scene_only_task(project_id)
    db_session.add(task)
    await db_session.flush()
    log.set_context(project_id=str(project_id), task_id=str(task.id))
    log.write(
        "task_created",
        test_mode="scene_only",
        stage="scenes",
        task_id=str(task.id),
        task_type=task.task_type,
        project_id=str(project_id),
        meta=task.meta,
    )

    emitted_phase_events: set[tuple[str, str]] = set()

    async def _observe_progress(progress, progress_value: float, _task) -> None:
        payload = _progress_log_payload(progress, progress_value)
        log.write(
            "progress",
            test_mode="scene_only",
            stage="scenes",
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
                test_mode="scene_only",
                stage="scenes",
                task_id=str(_task.id),
                project_id=str(project_id),
                **item,
            )
        log.write(
            "diagnostic_snapshot",
            test_mode="scene_only",
            stage="scenes",
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
        result = await orchestrator.run_stage_task(db_session, task, stage="scenes")
    except BaseException as exc:
        log.write(
            "exception",
            test_mode="scene_only",
            stage="scenes",
            error_type=exc.__class__.__name__,
            error_message=str(exc),
            project_id=str(project_id),
            task_id=str(task.id),
        )
        try:
            log.write(
                "interrupted_counts",
                test_mode="scene_only",
                stage="scenes",
                **await _count_acceptance_outputs(db_session, project_id),
            )
        except Exception as count_exc:
            log.write(
                "interrupted_count_failed",
                test_mode="scene_only",
                stage="scenes",
                error_type=count_exc.__class__.__name__,
                error_message=str(count_exc),
            )
        raise

    log.write(
        "result",
        test_mode="scene_only",
        stage="scenes",
        **_result_log_payload(result),
    )
    output_counts = await _count_acceptance_outputs(db_session, project_id)
    coverage = await _scene_chapter_coverage(
        db_session,
        project_id,
        start_chapter=1,
        end_chapter=EXPECTED_CHAPTER_COUNT,
    )
    log.write(
        "output_counts",
        test_mode="scene_only",
        stage="scenes",
        **output_counts,
    )
    log.write(
        "scene_chapter_coverage",
        test_mode="scene_only",
        stage="scenes",
        **coverage,
    )

    acceptance_rule_results, acceptance_issues = _scene_only_acceptance_checks(
        result=result,
        output_counts=output_counts,
        coverage=coverage,
        expected_chapter_count=EXPECTED_CHAPTER_COUNT,
    )
    log.write(
        "acceptance_checks",
        test_mode="scene_only",
        stage="scenes",
        checks=acceptance_rule_results,
        issues=acceptance_issues,
    )
    summary_path = _write_phase01_scene_summary(
        log_path=log.path,
        wall_clock_s=time.monotonic() - log.started_at,
        result=result,
        output_counts=output_counts,
        coverage=coverage,
        issues=acceptance_issues,
    )
    log.write(
        "final_summary",
        test_mode="scene_only",
        stage="scenes",
        wall_clock_s=round(time.monotonic() - log.started_at, 2),
        phase01_scene_summary_path=str(summary_path),
        project_id=str(project_id),
        task_id=str(task.id),
        issues=acceptance_issues,
        output_counts=output_counts,
        scene_chapter_coverage=coverage,
        result=_result_log_payload(result),
    )
    if acceptance_issues:
        pytest.fail("\n".join(acceptance_issues))


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
        phase2_batch_tuning=_phase2_batch_runtime_payload(),
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
        expected_phase1a_batches = (
            EXPECTED_CHAPTER_COUNT
            if quality_stats["phase1a"].get("direct_single_chapter_fallback")
            else expected_phase_shape["phase1a_total_batches"]
        )
        expected_phase_checks = {
            "phase0_total_batches": (
                quality_stats["phase0"].get("total_batches"),
                expected_phase_shape["phase0_total_batches"],
            ),
            "phase1a_total_batches": (
                quality_stats["phase1a"].get("total_batches"),
                expected_phase1a_batches,
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
        summary_path = _write_phase2_batch_tuning_summary(
            log_path=log.path,
            wall_clock_s=time.monotonic() - log.started_at,
            result=result,
            output_counts=output_counts,
            issues=acceptance_issues,
        )
        log.write(
            "final_summary",
            wall_clock_s=round(time.monotonic() - log.started_at, 2),
            phase2_batch_tuning_summary_path=str(summary_path),
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
    phase2_stats = quality_stats.get("phase2") or {}
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
    phase2b_required_stats = {
        "total_aliases",
        "total_relations",
        "alias_relation_scenes",
        "alias_relation_failed_scenes",
    }
    _record_acceptance_check(
        acceptance_rule_results,
        acceptance_issues,
        name="phase2b_quality_stats_logged",
        ok=phase2b_required_stats.issubset(phase2_stats),
        expected=sorted(phase2b_required_stats),
        actual=sorted(phase2_stats.keys()),
        message="phase2 quality_stats missing Phase 2b alias/relation fields",
    )
    _record_acceptance_check(
        acceptance_rule_results,
        acceptance_issues,
        name="phase2b_attempted_or_explained",
        ok=_phase2b_attempted_or_explained(phase2_stats, phase_errors),
        expected=(
            "alias_relation_scenes + failed_scenes > 0, skipped with reason, "
            "or phase_errors"
        ),
        actual={
            "alias_relation_scenes": phase2_stats.get("alias_relation_scenes"),
            "alias_relation_failed_scenes": phase2_stats.get(
                "alias_relation_failed_scenes",
            ),
            "alias_relation_skipped": phase2_stats.get("alias_relation_skipped"),
            "alias_relation_skip_reason": phase2_stats.get(
                "alias_relation_skip_reason"
            ),
            "phase_error_count": len(phase_errors),
        },
        message="Phase 2b alias/relation extraction was not attempted or explained",
    )
    _record_acceptance_check(
        acceptance_rule_results,
        acceptance_issues,
        name="phase2_batch_diagnostics_recorded",
        ok=(
            phase2_stats.get("phase2_batches_total") is not None
            and phase2_stats.get("phase2_boundary_windows_total") is not None
            and phase2_stats.get("phase2_action_counts") is not None
            and phase2_stats.get("phase2_dedup_counts") is not None
        ),
        expected="phase2 batch/boundary/action/dedup diagnostics present",
        actual={
            "phase2_batches": phase2_stats.get("phase2_batches_total") is not None,
            "phase2_boundary": (
                phase2_stats.get("phase2_boundary_windows_total") is not None
            ),
            "phase2_actions": phase2_stats.get("phase2_action_counts") is not None,
            "phase2_dedup": phase2_stats.get("phase2_dedup_counts") is not None,
        },
        message="phase2 quality_stats missing batch diagnostics",
    )
    phase2b_output_fields = {
        "relation_count",
        "relation_status_counts",
        "total_alias_count",
        "candidate_alias_count",
        "deep_import_alias_count",
        "needs_review_alias_count",
    }
    _record_acceptance_check(
        acceptance_rule_results,
        acceptance_issues,
        name="phase2b_output_counts_logged",
        ok=phase2b_output_fields.issubset(output_counts),
        expected=sorted(phase2b_output_fields),
        actual=sorted(output_counts.keys()),
        message="output_counts missing Phase 2b alias/relation diagnostics",
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
    summary_path = _write_phase2_batch_tuning_summary(
        log_path=log.path,
        wall_clock_s=time.monotonic() - log.started_at,
        result=result,
        output_counts=output_counts,
        issues=acceptance_issues,
    )
    log.write(
        "final_summary",
        wall_clock_s=round(time.monotonic() - log.started_at, 2),
        phase2_batch_tuning_summary_path=str(summary_path),
        project_id=str(project_id),
        task_id=str(task.id),
        issues=acceptance_issues,
        output_counts=output_counts,
        result=_result_log_payload(result),
    )
    if acceptance_issues:
        pytest.fail("\n".join(acceptance_issues))
