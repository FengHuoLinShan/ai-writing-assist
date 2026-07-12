"""Compact service artifacts and gates for deep import stages."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from modules.imports.env_helpers import positive_float_env, positive_int_env
from modules.imports.service_progress_logs import (
    record_acceptance_check,
    record_progress_event,
)
from modules.imports.workflow_schemas import DeepImportProgress

ARTIFACT_MAX_CHARS = 32_000
REPAIR_ATTEMPTS_ENV = "DEEP_IMPORT_STAGE_REPAIR_ATTEMPTS"
REPAIR_MAX_FAILED_UNITS_ENV = "DEEP_IMPORT_STAGE_REPAIR_MAX_FAILED_UNITS"
REPAIR_MAX_FAILED_RATIO_ENV = "DEEP_IMPORT_STAGE_REPAIR_MAX_FAILED_RATIO"

SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "password",
    "secret",
    "token",
)

FORBIDDEN_PAYLOAD_KEY_PARTS = (
    "raw_prompt",
    "prompt_text",
    "system_prompt",
    "user_prompt",
    "rendered_prompt",
    "raw_output",
    "raw_llm_output",
    "llm_output",
    "llm_response",
    "model_output",
    "completion",
    "body_text",
    "chapter_text",
    "rendered_context",
)
FORBIDDEN_PAYLOAD_EXACT_KEYS = {
    "prompt",
    "messages",
    "content",
    "body",
    "text",
    "context",
    "input",
    "output",
}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def repair_policy() -> dict[str, Any]:
    return {
        "attempts": positive_int_env(REPAIR_ATTEMPTS_ENV, 1),
        "max_failed_units": positive_int_env(REPAIR_MAX_FAILED_UNITS_ENV, 6),
        "max_failed_ratio": positive_float_env(REPAIR_MAX_FAILED_RATIO_ENV, 0.20),
    }


def failed_units_within_repair_policy(
    failed_count: int,
    total_count: int,
    *,
    policy: dict[str, Any] | None = None,
) -> bool:
    active_policy = policy or repair_policy()
    if failed_count <= 0:
        return False
    if failed_count > int(active_policy.get("max_failed_units", 0) or 0):
        return False
    if total_count <= 0:
        return False
    ratio = failed_count / total_count
    return ratio <= float(active_policy.get("max_failed_ratio", 0.0) or 0.0)


def candidate_chapter_coverage(
    candidates: list[Any] | tuple[Any, ...],
    start_chapter: int,
    end_chapter: int,
) -> dict[str, Any]:
    covered: set[int] = set()
    candidates_with_chapters = 0
    for candidate in candidates:
        chapters = _candidate_chapters(candidate)
        if chapters:
            candidates_with_chapters += 1
        for chapter in chapters:
            if start_chapter <= chapter <= end_chapter:
                covered.add(chapter)
    return coverage_summary(
        covered,
        start_chapter,
        end_chapter,
        candidates_with_chapter_ids=candidates_with_chapters,
    )


def coverage_summary(
    covered_chapters: set[int] | list[int] | tuple[int, ...],
    start_chapter: int,
    end_chapter: int,
    *,
    candidates_with_chapter_ids: int | None = None,
) -> dict[str, Any]:
    expected = list(range(start_chapter, end_chapter + 1))
    covered = sorted(
        {
            int(chapter)
            for chapter in covered_chapters
            if start_chapter <= int(chapter) <= end_chapter
        }
    )
    missing = [chapter for chapter in expected if chapter not in set(covered)]
    summary = {
        "start_chapter": start_chapter,
        "end_chapter": end_chapter,
        "expected_chapters": expected,
        "covered_chapters": covered,
        "missing_chapters": missing,
        "coverage_complete": not missing,
    }
    if candidates_with_chapter_ids is not None:
        summary["candidates_with_chapter_ids"] = candidates_with_chapter_ids
    return summary


def add_phase_artifact(
    progress: DeepImportProgress,
    phase: str,
    *,
    start_chapter: int,
    end_chapter: int,
    status: str,
    quality_status: str | None = None,
    quality_stats: dict[str, Any] | None = None,
    counts: dict[str, Any] | None = None,
    coverage: dict[str, Any] | None = None,
    repair_summary: dict[str, Any] | None = None,
    errors: list[dict[str, Any]] | None = None,
    provider_summary: dict[str, Any] | None = None,
    checkpoint_summary: dict[str, Any] | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    artifact = {
        "phase": phase,
        "stage": progress.stage,
        "workflow_type": progress.workflow_type,
        "chapter_range": {
            "start_chapter": start_chapter,
            "end_chapter": end_chapter,
        },
        "status": status,
        "quality_status": quality_status or progress.quality_status,
        "counts": _sanitize(counts or {}),
        "coverage": _sanitize(coverage or {}),
        "quality_stats": _sanitize(_compact_quality_stats(quality_stats or {})),
        "checkpoint_summary": _sanitize(checkpoint_summary or {}),
        "repair": _sanitize(repair_summary or {"policy": repair_policy()}),
        "provider_summary": _sanitize(provider_summary or progress.llm_health or {}),
        "errors": _sanitize(errors or []),
        "diagnostics": _sanitize(diagnostics or {}),
        "produced_at": now_iso(),
    }
    artifact = _enforce_artifact_budget(artifact)
    progress.phase_artifacts[phase] = artifact
    _record_artifact_progress(progress, phase, artifact)
    return artifact


def phase_error(
    *,
    phase: str,
    error_kind: str,
    message: str,
) -> dict[str, str]:
    return {
        "phase": phase,
        "error_kind": error_kind,
        "message": message[:300],
    }


def phase2_checkpoint_summary(checkpoints: dict[str, Any] | None) -> dict[str, Any]:
    phase2 = (checkpoints or {}).get("phase2")
    scenes = phase2.get("scenes") if isinstance(phase2, dict) else []
    phase2b = (checkpoints or {}).get("phase2b")
    alias_scenes = phase2b.get("scenes") if isinstance(phase2b, dict) else []
    return {
        "phase2": _status_counts(scenes if isinstance(scenes, list) else []),
        "phase2b": _status_counts(alias_scenes if isinstance(alias_scenes, list) else []),
    }


def scene_phase_repair_summary(
    stats: dict[str, Any],
    *,
    phase: str,
    repaired: bool = False,
    reason: str | None = None,
) -> dict[str, Any]:
    total = int(stats.get("total_batches", 0) or 0)
    failed = max(0, total - int(stats.get("completed_batches", 0) or 0))
    for key in ("failed", "timeout", "schema_error"):
        failed = max(failed, int(stats.get(key, 0) or 0))
    policy = repair_policy()
    return {
        "policy": policy,
        "phase": phase,
        "failed_units": failed,
        "total_units": total,
        "within_policy": failed_units_within_repair_policy(
            failed,
            total,
            policy=policy,
        ),
        "attempted": repaired,
        "attempts": 1 if repaired else 0,
        "reason": reason,
    }


def phase2_repair_summary(
    result: dict[str, Any],
    *,
    attempted: bool = False,
    reason: str | None = None,
) -> dict[str, Any]:
    total = int(result.get("total_scenes", 0) or 0)
    failed_scenes = result.get("failed_scene_indices") or []
    failed_batches = result.get("phase2_failed_batches") or []
    failed = max(len(failed_scenes), len(failed_batches))
    policy = repair_policy()
    return {
        "policy": policy,
        "failed_units": failed,
        "total_units": total,
        "within_policy": failed_units_within_repair_policy(
            failed,
            total,
            policy=policy,
        ),
        "attempted": attempted,
        "attempts": 1 if attempted else 0,
        "reason": reason,
        "failed_scene_indices": failed_scenes,
        "failed_scene_ids": result.get("failed_scene_ids") or [],
        "failed_batches": failed_batches,
        "rerun_scenes": int(result.get("rerun_scenes", 0) or 0),
        "skipped_scenes": int(result.get("skipped_scenes", 0) or 0),
    }


def _candidate_chapters(candidate: Any) -> list[int]:
    raw = getattr(candidate, "source_chapter_indices", None)
    if raw is None and isinstance(candidate, dict):
        raw = candidate.get("source_chapter_indices")
    chapters: list[int] = []
    for value in raw or []:
        try:
            chapters.append(int(value))
        except (TypeError, ValueError):
            continue
    return sorted(set(chapters))


def _status_counts(items: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for item in items:
        status = str(item.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return {"total": len(items), "status_counts": counts}


def _compact_quality_stats(stats: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key, value in stats.items():
        if key.endswith("_diagnostics") or _is_forbidden_payload_key(str(key)):
            continue
        compact[key] = value
    return compact


def _sanitize(value: Any, *, depth: int = 0) -> Any:
    if depth > 8:
        return "<truncated>"
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_str = str(key)
            lower = key_str.lower()
            if _is_forbidden_payload_key(lower):
                continue
            if any(part in lower for part in SENSITIVE_KEY_PARTS):
                sanitized[key_str] = "<redacted>"
            else:
                sanitized[key_str] = _sanitize(item, depth=depth + 1)
        return sanitized
    if isinstance(value, list):
        return [_sanitize(item, depth=depth + 1) for item in value[:100]]
    if isinstance(value, str):
        return value if len(value) <= 500 else f"{value[:500]}..."
    return value


def _is_forbidden_payload_key(key: str) -> bool:
    lower = key.lower()
    if lower in FORBIDDEN_PAYLOAD_EXACT_KEYS:
        return True
    if lower.endswith("_content") or lower.endswith("_body"):
        return True
    return any(part in lower for part in FORBIDDEN_PAYLOAD_KEY_PARTS)


def _record_artifact_progress(
    progress: DeepImportProgress,
    phase: str,
    artifact: dict[str, Any],
) -> None:
    coverage = artifact.get("coverage") or {}
    repair = artifact.get("repair") or {}
    counts = artifact.get("counts") or {}
    errors = artifact.get("errors") or []
    status = str(artifact.get("status") or "unknown")
    event_level = (
        "warning" if status == "degraded" else ("error" if status == "failed" else "info")
    )

    record_progress_event(
        progress,
        "artifact_produced",
        phase=phase,
        status=status,
        level=event_level,
        message=f"{phase} artifact {status}",
        details={
            "quality_status": artifact.get("quality_status"),
            "counts": counts,
            "coverage": {
                "coverage_complete": coverage.get("coverage_complete"),
                "missing_chapters": coverage.get("missing_chapters") or [],
            },
            "repair": {
                "attempts": repair.get("attempts", 0),
                "failed_units": repair.get("failed_units", 0),
                "within_policy": repair.get("within_policy"),
            },
        },
    )

    if "coverage_complete" in coverage:
        record_acceptance_check(
            progress,
            f"{phase}_coverage",
            phase=phase,
            ok=bool(coverage.get("coverage_complete")),
            severity="error",
            message=(
                "章节覆盖完整" if coverage.get("coverage_complete") else "章节覆盖缺失"
            ),
            details={
                "missing_chapters": coverage.get("missing_chapters") or [],
                "covered_chapters": coverage.get("covered_chapters") or [],
            },
        )

    if repair:
        failed_units = int(repair.get("failed_units", 0) or 0)
        record_acceptance_check(
            progress,
            f"{phase}_failed_units",
            phase=phase,
            ok=failed_units == 0 or bool(repair.get("attempted")),
            severity="warning",
            message="失败单元 repair 状态",
            details={
                "failed_units": failed_units,
                "total_units": repair.get("total_units"),
                "attempts": repair.get("attempts", 0),
                "within_policy": repair.get("within_policy"),
            },
        )

    if status in {"completed", "degraded"} and counts:
        output_count = _primary_output_count(counts)
        if output_count is not None:
            record_acceptance_check(
                progress,
                f"{phase}_non_empty_output",
                phase=phase,
                ok=output_count > 0 or status == "degraded",
                severity="warning",
                message="阶段输出非空",
                details={"output_count": output_count, "counts": counts},
            )

    for error in errors if isinstance(errors, list) else []:
        if not isinstance(error, dict):
            continue
        record_acceptance_check(
            progress,
            f"{phase}_{error.get('error_kind') or 'error'}",
            phase=phase,
            ok=False,
            severity="warning" if status == "degraded" else "error",
            message=error.get("message") or error.get("error_kind"),
            details=error,
        )


def _primary_output_count(counts: dict[str, Any]) -> int | None:
    for key in (
        "candidate_count",
        "total_scenes",
        "total_created",
        "created_count",
        "total_threads",
        "total_arcs",
    ):
        if key in counts:
            return int(counts.get(key, 0) or 0)
    return None


def _enforce_artifact_budget(artifact: dict[str, Any]) -> dict[str, Any]:
    try:
        encoded = json.dumps(artifact, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return {
            "phase": artifact.get("phase"),
            "stage": artifact.get("stage"),
            "status": "degraded",
            "error_kind": "artifact_over_budget",
            "produced_at": artifact.get("produced_at") or now_iso(),
        }
    if len(encoded) <= ARTIFACT_MAX_CHARS:
        return artifact
    compact = dict(artifact)
    compact["quality_stats"] = {
        key: value
        for key, value in (artifact.get("quality_stats") or {}).items()
        if isinstance(value, (int, float, bool, str)) or value is None
    }
    compact["diagnostics"] = _compact_artifact_diagnostics(
        artifact.get("diagnostics") or {}
    )
    compact["errors"] = (artifact.get("errors") or [])[:5]
    compact["budget_truncated"] = True
    compact["error_kind"] = "artifact_over_budget"
    return compact


def _compact_artifact_diagnostics(diagnostics: Any) -> dict[str, Any]:
    if not isinstance(diagnostics, dict):
        return {}
    compact: dict[str, Any] = {}
    for key, value in diagnostics.items():
        if not isinstance(value, dict):
            compact[key] = value
            continue
        entry = dict(value)
        for list_key in ("samples", "slowest", "failed"):
            if isinstance(entry.get(list_key), list):
                entry[list_key] = entry[list_key][:3]
        entry["budget_truncated"] = True
        compact[key] = entry
    return compact
