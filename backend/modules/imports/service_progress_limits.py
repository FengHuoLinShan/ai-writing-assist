"""Bound unbounded diagnostic lists in import workflow progress payloads."""

from __future__ import annotations

from typing import Any

from modules.imports.workflow_schemas import DeepImportProgress

MAX_PHASE_TIMELINE_ITEMS = 120
MAX_ACCEPTANCE_CHECKS = 200
MAX_PHASE_ERRORS = 120


def trim_progress_diagnostics(progress: DeepImportProgress) -> None:
    """Keep diagnostic arrays bounded while preserving the most recent entries."""

    _trim_list(
        progress.phase_timeline,
        max_items=MAX_PHASE_TIMELINE_ITEMS,
        dropped_count_key="dropped_phase_timeline_count",
    )
    _trim_list(
        progress.acceptance_checks,
        max_items=MAX_ACCEPTANCE_CHECKS,
        dropped_count_key="dropped_acceptance_check_count",
    )
    _trim_list(
        progress.phase_errors,
        max_items=MAX_PHASE_ERRORS,
        dropped_count_key="dropped_phase_error_count",
    )


def _trim_list(
    items: list[dict[str, Any]],
    *,
    max_items: int,
    dropped_count_key: str,
) -> None:
    if len(items) <= max_items:
        return

    dropped = len(items) - max_items
    previous_dropped = _int_value(items[0].get(dropped_count_key, 0))
    kept = items[-max_items:]
    first = kept[0]
    first["truncated"] = True
    first[dropped_count_key] = (
        previous_dropped + _int_value(first.get(dropped_count_key, 0)) + dropped
    )
    items[:] = kept


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
