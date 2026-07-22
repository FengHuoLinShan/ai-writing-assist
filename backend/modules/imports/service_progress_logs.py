"""Service-level progress events and acceptance checks for imports workflows."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from infrastructure.llm.redaction import redact_diagnostic
from modules.imports.service_progress_limits import trim_progress_diagnostics
from modules.imports.workflow_schemas import DeepImportProgress

MAX_PROGRESS_EVENTS = 200


def record_progress_event(
    progress: DeepImportProgress,
    event: str,
    *,
    phase: str | None = None,
    status: str | None = None,
    level: str = "info",
    message: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entry = {
        "event": str(event),
        "phase": phase or progress.current_phase,
        "status": status,
        "level": level,
        "message": _short_message(message),
        "details": sanitize_log_payload(details or {}),
        "created_at": _now_iso(),
    }
    progress.progress_events.append(entry)
    _trim_progress_events(progress)
    return entry


def record_acceptance_check(
    progress: DeepImportProgress,
    name: str,
    *,
    phase: str | None = None,
    ok: bool,
    severity: str = "error",
    message: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    check = {
        "name": str(name),
        "phase": phase or progress.current_phase,
        "ok": bool(ok),
        "severity": severity,
        "message": _short_message(message),
        "details": sanitize_log_payload(details or {}),
        "created_at": _now_iso(),
    }
    progress.acceptance_checks.append(check)
    trim_progress_diagnostics(progress)
    if not ok:
        record_progress_event(
            progress,
            "acceptance_gate",
            phase=phase,
            status="failed",
            level="warning" if severity == "warning" else "error",
            message=message or name,
            details={"check": name, **(details or {})},
        )
    return check


def sanitize_log_payload(value: Any, *, depth: int = 0) -> Any:
    from modules.imports.service_phase_artifacts import _sanitize

    return _sanitize(value, depth=depth)


def _trim_progress_events(progress: DeepImportProgress) -> None:
    if len(progress.progress_events) <= MAX_PROGRESS_EVENTS:
        return
    dropped = len(progress.progress_events) - MAX_PROGRESS_EVENTS
    previous_dropped = int(progress.progress_events[0].get("dropped_event_count", 0) or 0)
    progress.progress_events = progress.progress_events[-MAX_PROGRESS_EVENTS:]
    if progress.progress_events:
        first = progress.progress_events[0]
        first["truncated"] = True
        first["dropped_event_count"] = (
            previous_dropped + int(first.get("dropped_event_count", 0) or 0) + dropped
        )


def _short_message(message: Any) -> str | None:
    if message is None:
        return None
    return redact_diagnostic(message, limit=300)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
