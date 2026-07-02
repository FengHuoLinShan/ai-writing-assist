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
from infrastructure.llm.profiles import resolve_llm_profile
from infrastructure.tasks.models import AsyncTask
from modules.imports.orchestrator import DeepImportOrchestrator
from modules.imports.parsers import parse_txt
from modules.imports.scene_entity_config import (
    phase2_batch_concurrency,
    phase2_batch_size_scenes,
    phase2_batch_tuning_group,
)
from modules.imports.services import ImportService
from modules.imports.workflow import DeepImportWorkflow
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


def _full_real_llm_enabled() -> bool:
    return (
        os.getenv("RUN_DEEP_IMPORT_5_REAL_LLM") == "1"
        or os.getenv("RUN_DEEP_IMPORT_60_REAL_LLM") == "1"
        or os.getenv("RUN_DEEP_IMPORT_213_REAL_LLM") == "1"
    )


def _scene_real_llm_enabled() -> bool:
    return os.getenv("RUN_DEEP_IMPORT_60_SCENE_REAL_LLM") == "1"


def _phase0_real_llm_enabled() -> bool:
    return os.getenv("RUN_DEEP_IMPORT_60_PHASE0_REAL_LLM") == "1"


def _expected_chapter_count() -> int:
    configured = os.getenv("DEEP_IMPORT_EXPECTED_CHAPTERS")
    if configured:
        return int(configured)
    if (
        os.getenv("RUN_DEEP_IMPORT_60_REAL_LLM") == "1"
        or os.getenv("RUN_DEEP_IMPORT_213_REAL_LLM") == "1"
        or _scene_real_llm_enabled()
        or _phase0_real_llm_enabled()
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
            if _phase0_real_llm_enabled():
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


def _phase2_batch_tuning_summary_path(log_path: Path) -> Path:
    configured = os.getenv("PHASE2_BATCH_TUNING_SUMMARY_PATH")
    if configured:
        path = Path(configured).expanduser()
        return path if path.is_absolute() else BACKEND_ROOT / path
    stamp = log_path.stem.rsplit("_", 1)[-1]
    return log_path.parent / f"phase2_batch_tuning_{stamp}.md"


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
    headers = list(row)
    if not summary_path.exists():
        summary_path.write_text(
            "# Phase 2 Batch Tuning Summary\n\n"
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
            + " | ".join(
                _phase2_summary_value(row[key]).replace("\n", " ")
                for key in headers
            )
            + " |\n"
        )
    return summary_path


def _phase01_scene_summary_path(log_path: Path) -> Path:
    configured = os.getenv("PHASE01_SCENE_REAL_LLM_SUMMARY_PATH")
    if configured:
        path = Path(configured).expanduser()
        return path if path.is_absolute() else BACKEND_ROOT / path
    stamp = log_path.stem.rsplit("_", 1)[-1]
    return log_path.parent / f"phase01_scene_real_llm_{stamp}.md"


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
    headers = list(row)
    if not summary_path.exists():
        summary_path.write_text(
            "# Phase 0/1 Scene Real LLM Summary\n\n"
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


def _phase0_summary_path(log_path: Path) -> Path:
    configured = os.getenv("PHASE0_REAL_LLM_SUMMARY_PATH")
    if configured:
        path = Path(configured).expanduser()
        return path if path.is_absolute() else BACKEND_ROOT / path
    stamp = log_path.stem.rsplit("_", 1)[-1]
    return log_path.parent / f"phase0_real_llm_{stamp}.md"


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
    headers = list(row)
    if not summary_path.exists():
        summary_path.write_text(
            "# Phase 0 Real LLM Summary\n\n"
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


def test_phase0_real_llm_enabled_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RUN_DEEP_IMPORT_60_PHASE0_REAL_LLM", raising=False)
    assert _phase0_real_llm_enabled() is False

    monkeypatch.setenv("RUN_DEEP_IMPORT_60_PHASE0_REAL_LLM", "1")
    assert _phase0_real_llm_enabled() is True


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
    log.write(
        "final_summary",
        test_mode="phase0_only",
        stage="phase0_prefetch",
        wall_clock_s=round(time.monotonic() - log.started_at, 2),
        phase0_summary_path=str(summary_path),
        project_id=str(project_id),
        issues=acceptance_issues,
        output_counts=output_counts,
        candidate_chapter_coverage=coverage,
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
    phase2b_attempts = int(phase2_stats.get("alias_relation_scenes", 0) or 0) + len(
        phase2_stats.get("alias_relation_failed_scenes") or []
    )
    _record_acceptance_check(
        acceptance_rule_results,
        acceptance_issues,
        name="phase2b_attempted_or_explained",
        ok=phase2b_attempts > 0 or bool(phase_errors),
        expected="alias_relation_scenes + failed_scenes > 0 or phase_errors",
        actual={
            "alias_relation_scenes": phase2_stats.get("alias_relation_scenes"),
            "alias_relation_failed_scenes": phase2_stats.get(
                "alias_relation_failed_scenes",
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
