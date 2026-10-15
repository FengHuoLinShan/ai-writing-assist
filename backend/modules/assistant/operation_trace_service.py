"""Best-effort operation trace port with a savepoint isolated from business writes."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
from collections.abc import Mapping
from contextvars import ContextVar, Token
from datetime import UTC, date, datetime, time, timedelta
from secrets import token_hex
from uuid import UUID

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.exc import IntegrityError

from core.config import get_settings
from modules.account.facade import is_demo_readonly_principal
from modules.assistant.contracts import AssistantOperation
from modules.assistant.operation_trace_models import (
    AssistantOperationSequenceAggregate,
    AssistantOperationTraceLifecycleAggregate,
    AssistantOperationTraceMetricAggregate,
    AssistantOperationTrace,
    AssistantOperationTraceAggregate,
    AssistantOperationTracePreference,
    AssistantOperationTraceProjectSalt,
)

logger = logging.getLogger(__name__)

_active_trace_context: ContextVar[dict | None] = ContextVar(
    "assistant_operation_trace_context", default=None
)


def bind_operation_trace_context(context: dict) -> Token:
    return _active_trace_context.set(context)


def reset_operation_trace_context(token: Token) -> None:
    _active_trace_context.reset(token)


def current_operation_trace_context() -> dict | None:
    return _active_trace_context.get()


_USAGE_COUNTS = frozenset(
    {
        "requests",
        "tool_attempts",
        "web_requests",
        "prompt_tokens",
        "completion_tokens",
        "pending_usage",
    }
)
_USAGE_FLAGS = frozenset({"usage_complete", "usage_unknown"})
_TRACE_EVENT_TYPES = frozenset(
    {
        "proposed",
        "previewed",
        "confirmed",
        "declined",
        "edited",
        "executed",
        "failed",
        "restored",
        "undone",
        "outcome_unknown",
    }
)
_REFERENCE_FIELDS = frozenset(
    {
        "id",
        "target_id",
        "task_id",
        "run_id",
        "session_id",
        "draft_id",
        "revision_id",
        "node_id",
        "entity_id",
        "suggestion_id",
        "receipt_id",
        "result_id",
    }
)
_REFERENCE_TYPE_FIELDS = frozenset({"type", "target_type", "kind"})
_REFERENCE_KIND = re.compile(r"^[a-z][a-z0-9_.-]{0,79}$")
_ERROR_CODE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


def _bucket(size: int) -> str:
    if size <= 0:
        return "0"
    if size == 1:
        return "1"
    if size <= 4:
        return "2-4"
    if size <= 9:
        return "5-9"
    if size <= 49:
        return "10-49"
    return "50+"


def _project_hash(novel_id: str, project_salt: str, value: str) -> str:
    settings = get_settings()
    key = (settings.auth_secret_key or project_salt).encode("utf-8")
    salt = hashlib.sha256(
        b"assistant-operation-trace\0" + novel_id.encode() + project_salt.encode()
    ).digest()
    return hmac.new(key, salt + value.encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def _parameter_summary(
    operation: AssistantOperation,
    novel_id: str,
    project_salt: str,
    arguments: object,
) -> dict:
    values = arguments if isinstance(arguments, Mapping) else {}
    declared = set(operation.trace_rule.parameter_fields)
    fields: dict[str, dict] = {}
    for name in sorted(declared):
        if name not in values:
            fields[name] = {"present": False}
            continue
        value = values[name]
        item = {"present": True}
        if value is None:
            item["type"] = "null"
        elif isinstance(value, bool):
            item.update({"type": "boolean", "value": value})
        elif isinstance(value, (int, float)):
            item.update({"type": "number", "size": _bucket(abs(int(value)))})
        elif isinstance(value, str):
            item.update(
                {
                    "type": "string",
                    "length": len(value),
                    "project_hash": _project_hash(novel_id, project_salt, value),
                }
            )
        elif isinstance(value, (list, tuple, set)):
            item.update({"type": "array", "count": _bucket(len(value))})
        elif isinstance(value, Mapping):
            # Nested payloads can contain prose or arbitrary future fields. Keep
            # their size only; never infer a new field's logging policy.
            item.update({"type": "object", "field_count": _bucket(len(value))})
        else:
            item["type"] = type(value).__name__[:40]
        fields[name] = item
    unknown = set(values) - declared
    return {
        "fields": fields,
        # Even an unknown key can be supplied by a caller and contain content.
        "unknown_fields": {"present": bool(unknown)},
    }


def _refs(*values: object) -> list[dict]:
    found: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, value: object) -> None:
        if value is None or isinstance(value, (dict, list, tuple, set)):
            return
        # Domain receipts use UUIDs. An arbitrary string under an ``id`` key
        # may be author content, so never copy it into the trace table.
        try:
            rendered = str(UUID(str(value)))
        except (ValueError, TypeError, AttributeError):
            return
        if not _REFERENCE_KIND.fullmatch(kind):
            return
        key = (kind, rendered)
        if key not in seen:
            seen.add(key)
            found.append({"type": key[0], "id": rendered})

    def visit(value: object, depth: int = 0) -> None:
        if depth > 3 or len(found) >= 24:
            return
        if isinstance(value, Mapping):
            explicit_type = next(
                (value.get(key) for key in _REFERENCE_TYPE_FIELDS if value.get(key)),
                None,
            )
            for key, item in value.items():
                if key in _REFERENCE_FIELDS:
                    add(str(explicit_type or key.removesuffix("_id")), item)
                elif key in {"target", "target_ref", "receipt", "result", "references"}:
                    visit(item, depth + 1)
                elif isinstance(item, (Mapping, list, tuple)):
                    visit(item, depth + 1)
        elif isinstance(value, (list, tuple)):
            for item in value[:24]:
                visit(item, depth + 1)

    for value in values:
        visit(value)
    return found


def _usage_summary(value: object) -> dict | None:
    if not isinstance(value, Mapping):
        return None
    result = {
        key: item
        for key in _USAGE_COUNTS
        if type(item := value.get(key)) is int and item >= 0
    }
    result.update(
        {key: item for key in _USAGE_FLAGS if type(item := value.get(key)) is bool}
    )
    return result or None


def _event_metadata(operation: AssistantOperation, value: object) -> dict:
    if not isinstance(value, Mapping):
        return {}
    result: dict = {}
    changed = value.get("changed_fields")
    if isinstance(changed, (list, tuple, set)):
        allowed = set(operation.schema.model_fields)
        fields = sorted(
            {
                name
                for name in changed
                if isinstance(name, str) and name in allowed
            }
        )
        if fields:
            result["changed_fields"] = fields
    usage_scope = value.get("usage_scope")
    if usage_scope in {"goal_step_phase", "goal_step_total"}:
        result["usage_scope"] = usage_scope
    return result


def operation_trace_sequences(rows) -> list[tuple[date, list[str]]]:
    """Return one deterministic terminal operation sequence per UTC day group."""
    groups: dict[tuple[date, str], list[AssistantOperationTrace]] = {}
    for row in rows:
        if row.event_type not in {"executed", "failed", "outcome_unknown"}:
            continue
        occurred_on = _utc_datetime(row.occurred_at).date()
        group_id = str(row.session_id or row.run_id or row.call_id or row.id)
        groups.setdefault((occurred_on, group_id), []).append(row)

    sequences: list[tuple[date, list[str]]] = []
    for (occurred_on, _group_id), items in groups.items():
        latest_terminal: dict[tuple[str, str], AssistantOperationTrace] = {}
        for row in items:
            call_key = str(row.call_id) if row.call_id is not None else f"row:{row.id}"
            key = (row.op_id, call_key)
            previous = latest_terminal.get(key)
            if previous is None or row.id > previous.id:
                latest_terminal[key] = row
        ordered = sorted(latest_terminal.values(), key=lambda item: item.id)
        if ordered:
            sequences.append((occurred_on, [row.op_id for row in ordered]))
    return sequences


def _lifecycle_daily_counts(rows) -> dict[tuple[date, str], dict[str, int]]:
    grouped: dict[tuple[date, str, str], list[AssistantOperationTrace]] = {}
    result: dict[tuple[date, str], dict[str, int]] = {}

    def bucket(key: tuple[date, str]) -> dict[str, int]:
        return result.setdefault(
            key,
            {
                "proposed_count": 0,
                "accepted_count": 0,
                "declined_count": 0,
                "edited_accepted_count": 0,
                "unresolved_count": 0,
                "unmatched_decision_count": 0,
                "ambiguous_count": 0,
                "unlinked_proposal_events": 0,
                "unlinked_decision_events": 0,
                "executed_count": 0,
                "matched_reversal_count": 0,
                "unmatched_reversal_count": 0,
            },
        )

    unlinked: list[AssistantOperationTrace] = []
    for row in rows:
        occurred_on = _utc_datetime(row.occurred_at).date()
        if row.call_id is None:
            unlinked.append(row)
            continue
        grouped.setdefault((occurred_on, row.op_id, str(row.call_id)), []).append(row)

    for row in unlinked:
        counts = bucket((_utc_datetime(row.occurred_at).date(), row.op_id))
        if row.event_type == "proposed":
            counts["unlinked_proposal_events"] += 1
        elif row.event_type in {"confirmed", "declined"}:
            counts["unlinked_decision_events"] += 1
        elif row.event_type in {"restored", "undone"}:
            counts["unmatched_reversal_count"] += 1
        elif row.event_type == "executed":
            counts["executed_count"] += 1

    for (occurred_on, op_id, _call_id), items in grouped.items():
        events = {row.event_type for row in items}
        counts = bucket((occurred_on, op_id))
        has_proposal = "proposed" in events
        decisions = events.intersection({"confirmed", "declined"})
        if has_proposal:
            counts["proposed_count"] += 1
            if len(decisions) > 1:
                counts["ambiguous_count"] += 1
            elif "confirmed" in decisions:
                counts["accepted_count"] += 1
                if "edited" in events:
                    counts["edited_accepted_count"] += 1
            elif "declined" in decisions:
                counts["declined_count"] += 1
            else:
                counts["unresolved_count"] += 1
        elif decisions:
            counts["unmatched_decision_count"] += 1

        if "executed" in events:
            counts["executed_count"] += 1
        if events.intersection({"restored", "undone"}):
            if "executed" in events:
                counts["matched_reversal_count"] += 1
            else:
                counts["unmatched_reversal_count"] += 1
    return result


def _metric_values(row: AssistantOperationTrace) -> dict:
    usage = _usage_summary(row.usage) or {}
    usage_totals = {
        key: value for key, value in usage.items() if key in _USAGE_COUNTS
    }
    return {
        "observed_event_count": 1,
        "duration_count": int(row.duration_ms is not None),
        "duration_ms_total": max(0, int(row.duration_ms or 0)),
        "usage_event_count": int(bool(usage)),
        "usage_complete_count": int(usage.get("usage_complete") is True),
        "usage_unknown_count": int(usage.get("usage_unknown") is True),
        "usage_pending_count": int(usage.get("pending_usage") or 0),
        "usage_totals": usage_totals,
        "usage_field_counts": {key: 1 for key in usage_totals},
    }


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def operation_trace_cutoff(now: datetime) -> datetime:
    """Use a fixed UTC-day retention boundary so archive batches never split a day."""
    day = (_utc_datetime(now) - timedelta(days=180)).date()
    return datetime.combine(day, time.min, tzinfo=UTC)


def _uuid_or_none(value: object) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


async def operation_trace_enabled(db, owner_id: str) -> bool:
    """Resolve the account switch; local defaults on, public defaults off."""
    settings = get_settings()
    if not settings.assistant_operation_trace_enabled:
        return False
    if is_demo_readonly_principal():
        return False
    preference = await db.get(AssistantOperationTracePreference, UUID(str(owner_id)))
    if preference is not None and preference.enabled is not None:
        return bool(preference.enabled)
    return settings.auth_mode.strip().lower() != "public"


async def set_operation_trace_preference(db, owner_id: str, enabled: bool) -> None:
    preference = await db.get(AssistantOperationTracePreference, UUID(str(owner_id)))
    if preference is None:
        db.add(
            AssistantOperationTracePreference(
                owner_id=UUID(str(owner_id)), enabled=bool(enabled)
            )
        )
    else:
        preference.enabled = bool(enabled)
    await db.flush()


async def _project_salt(db, novel_id: str, owner_id: str) -> str:
    novel_uuid = UUID(str(novel_id))
    salt_row = await db.get(AssistantOperationTraceProjectSalt, novel_uuid)
    if salt_row is not None:
        return salt_row.salt
    candidate = AssistantOperationTraceProjectSalt(
        novel_id=novel_uuid,
        owner_id=UUID(str(owner_id)),
        salt=token_hex(32),
    )
    try:
        async with db.begin_nested():
            db.add(candidate)
            await db.flush()
        return candidate.salt
    except IntegrityError:
        existing = await db.get(AssistantOperationTraceProjectSalt, novel_uuid)
        if existing is None:
            raise
        return existing.salt


async def _increment_aggregate(db, model, identity: dict, field: str, amount: int = 1):
    key = tuple(identity[column.name] for column in model.__table__.primary_key.columns)
    row = await db.get(model, key)
    if row is None:
        db.add(model(**identity, **{field: amount}))
    else:
        setattr(row, field, getattr(row, field) + amount)
        if "operation_sequence" in identity:
            row.operation_sequence = identity["operation_sequence"]
            row.sequence_complete = (
                row.sequence_complete and identity["sequence_complete"]
            )


async def _increment_structured_aggregate(
    db, model, identity: dict, amounts: dict[str, int | dict]
) -> None:
    key = tuple(identity[column.name] for column in model.__table__.primary_key.columns)
    row = await db.get(model, key)
    if row is None:
        db.add(model(**identity, **amounts))
        return
    for field, amount in amounts.items():
        if isinstance(amount, dict):
            current = dict(getattr(row, field) or {})
            for name, value in amount.items():
                current[name] = current.get(name, 0) + value
            setattr(row, field, current)
        else:
            setattr(row, field, getattr(row, field) + amount)


async def archive_expired_operation_traces(
    db,
    novel_id: str,
    *,
    now: datetime | None = None,
    max_days: int | None = None,
) -> int:
    """Aggregate whole UTC days so a session/day sequence is never split by retention."""
    if max_days is not None and max_days < 1:
        raise ValueError("max_days must be positive")
    postgres = db.get_bind().dialect.name == "postgresql"
    # Use the same transaction clock as the append-only trigger and pin one
    # UTC-day boundary for the whole archive/read operation.
    current = _utc_datetime(now or (
        await db.scalar(select(func.now())) if postgres else datetime.now(UTC)
    ))
    cutoff = operation_trace_cutoff(current)
    novel_uuid = UUID(str(novel_id))
    if postgres:
        # The owner read and worker tick may archive the same work at once.
        # Serialize the read/count/delete unit so aggregates cannot double count.
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"assistant-operation-trace-retention:{novel_uuid}"},
        )
    expired = (
        AssistantOperationTrace.novel_id == novel_uuid,
        AssistantOperationTrace.occurred_at < cutoff,
    )
    day_expr = (
        func.date(func.timezone("UTC", AssistantOperationTrace.occurred_at))
        if postgres
        else func.date(AssistantOperationTrace.occurred_at)
    )
    if max_days is None:
        selected_days = None
    else:
        selected_days = list(
            (
                await db.scalars(
                    select(day_expr)
                    .where(*expired)
                    .distinct()
                    .order_by(day_expr)
                    .limit(max_days)
                )
            ).all()
        )
        if not selected_days:
            return 0
    day_filter = (
        or_(
            *[
                and_(
                    AssistantOperationTrace.occurred_at
                    >= datetime.combine(
                        value if isinstance(value, date) else date.fromisoformat(value),
                        time.min,
                        tzinfo=UTC,
                    ),
                    AssistantOperationTrace.occurred_at
                    < datetime.combine(
                        (value if isinstance(value, date) else date.fromisoformat(value))
                        + timedelta(days=1),
                        time.min,
                        tzinfo=UTC,
                    ),
                )
                for value in selected_days
            ]
        )
        if selected_days is not None
        else None
    )
    conditions = [*expired]
    if day_filter is not None:
        conditions.append(day_filter)
    rows = list(
        (
            await db.scalars(
                select(AssistantOperationTrace)
                .where(*conditions)
                .order_by(AssistantOperationTrace.id)
            )
        ).all()
    )
    if not rows:
        return 0

    event_counts: dict[tuple[date, str, str], int] = {}
    for row in rows:
        occurred_on = _utc_datetime(row.occurred_at).date()
        key = (occurred_on, row.op_id, row.event_type)
        event_counts[key] = event_counts.get(key, 0) + 1

    for (occurred_on, op_id, event_type), count in event_counts.items():
        await _increment_aggregate(
            db,
            AssistantOperationTraceAggregate,
            {
                "novel_id": novel_uuid,
                "occurred_on": occurred_on,
                "op_id": op_id,
                "event_type": event_type,
            },
            "event_count",
            count,
        )
    for occurred_on, sequence in operation_trace_sequences(rows):
        sequence_json = json.dumps(sequence, separators=(",", ":"), ensure_ascii=True)
        sequence_hash = hashlib.sha256(sequence_json.encode()).hexdigest()
        await _increment_aggregate(
            db,
            AssistantOperationSequenceAggregate,
            {
                "novel_id": novel_uuid,
                "occurred_on": occurred_on,
                "sequence_hash": sequence_hash,
                "operation_sequence": sequence,
                "sequence_complete": True,
            },
            "sequence_count",
        )

    metric_values: dict[tuple[date, str, str], dict] = {}
    for row in rows:
        key = (_utc_datetime(row.occurred_at).date(), row.op_id, row.event_type)
        values = metric_values.setdefault(
            key,
            {
                "observed_event_count": 0,
                "duration_count": 0,
                "duration_ms_total": 0,
                "usage_event_count": 0,
                "usage_complete_count": 0,
                "usage_unknown_count": 0,
                "usage_pending_count": 0,
                "usage_totals": {},
                "usage_field_counts": {},
            },
        )
        delta = _metric_values(row)
        for field in (
            "observed_event_count",
            "duration_count",
            "duration_ms_total",
            "usage_event_count",
            "usage_complete_count",
            "usage_unknown_count",
            "usage_pending_count",
        ):
            values[field] += delta[field]
        for field in ("usage_totals", "usage_field_counts"):
            for name, amount in delta[field].items():
                values[field][name] = values[field].get(name, 0) + amount
    for (occurred_on, op_id, event_type), values in metric_values.items():
        await _increment_structured_aggregate(
            db,
            AssistantOperationTraceMetricAggregate,
            {
                "novel_id": novel_uuid,
                "occurred_on": occurred_on,
                "op_id": op_id,
                "event_type": event_type,
            },
            values,
        )

    lifecycle_values = _lifecycle_daily_counts(rows)
    for (occurred_on, op_id), values in lifecycle_values.items():
        await _increment_structured_aggregate(
            db,
            AssistantOperationTraceLifecycleAggregate,
            {
                "novel_id": novel_uuid,
                "occurred_on": occurred_on,
                "op_id": op_id,
            },
            values,
        )
    for row in rows:
        await db.delete(row)
    await db.flush()
    return len(rows)


async def archive_one_expired_operation_trace_project(db) -> int:
    """Archive one idle project's expired details per existing worker tick."""
    postgres = db.get_bind().dialect.name == "postgresql"
    current = _utc_datetime(
        await db.scalar(select(func.now())) if postgres else datetime.now(UTC)
    )
    cutoff = operation_trace_cutoff(current)
    novel_id = await db.scalar(
        select(AssistantOperationTrace.novel_id)
        .where(AssistantOperationTrace.occurred_at < cutoff)
        .order_by(AssistantOperationTrace.occurred_at)
        .limit(1)
    )
    if novel_id is None:
        return 0
    return await archive_expired_operation_traces(
        db, str(novel_id), now=current, max_days=1
    )


async def record_operation_trace(
    db,
    *,
    enabled: bool | None = None,
    novel_id: str,
    owner_id: str,
    operation: AssistantOperation,
    event_type: str,
    arguments: object = None,
    preview: object = None,
    result: object = None,
    error_code: str | None = None,
    duration_ms: int | None = None,
    actor_type: str = "assistant",
    entrypoint: str = "assistant.turn",
    run_id: str | None = None,
    session_id: str | None = None,
    usage: object = None,
    call_id: str | None = None,
    parent_call_id: str | None = None,
    metadata: object = None,
) -> bool:
    """Return false only when enabled trace persistence failed."""
    if operation.trace_rule.mode == "exempt":
        return True
    try:
        if enabled is False or not await operation_trace_enabled(db, owner_id):
            return True
        stable_error = (
            error_code if error_code and _ERROR_CODE.fullmatch(error_code) else None
        )
        salt = await _project_salt(db, novel_id, owner_id)
        row = AssistantOperationTrace(
            call_id=_uuid_or_none(call_id),
            parent_call_id=_uuid_or_none(parent_call_id),
            novel_id=UUID(str(novel_id)),
            owner_id=UUID(str(owner_id)),
            actor_type=actor_type
            if actor_type
            in {"assistant", "guided_flow", "goal", "ui", "background", "system"}
            else "assistant",
            entrypoint=entrypoint[:80],
            run_id=_uuid_or_none(run_id),
            session_id=_uuid_or_none(session_id),
            op_id=operation.op_id,
            op_version=operation.op_version,
            risk_level=operation.risk_level,
            fee_category=operation.fee_category,
            event_type=event_type,
            target_type=operation.target_type,
            target_refs=_refs(preview),
            parameter_summary=_parameter_summary(
                operation, str(novel_id), salt, arguments
            ),
            result_refs=_refs(result),
            error_code=stable_error,
            duration_ms=max(0, int(duration_ms)) if duration_ms is not None else None,
            usage=_usage_summary(usage),
            event_metadata=_event_metadata(operation, metadata),
        )
        # The savepoint is intentionally narrower than the business transaction:
        # trace failure must not undo a successful domain write.
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except Exception as exc:  # trace is auxiliary; never fail the business action
        active = current_operation_trace_context()
        if active is not None:
            active["incomplete_count"] = active.get("incomplete_count", 0) + 1
        logger.warning(
            "assistant operation trace persistence failed",
            extra={
                "op_id": operation.op_id,
                "event_type": event_type,
                "error_type": type(exc).__name__,
            },
        )
        return False
    return True


__all__ = [
    "bind_operation_trace_context",
    "current_operation_trace_context",
    "archive_expired_operation_traces",
    "archive_one_expired_operation_trace_project",
    "operation_trace_enabled",
    "operation_trace_cutoff",
    "operation_trace_sequences",
    "record_operation_trace",
    "reset_operation_trace_context",
    "set_operation_trace_preference",
]
