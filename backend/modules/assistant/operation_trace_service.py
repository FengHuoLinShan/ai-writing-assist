"""Best-effort operation trace port with a savepoint isolated from business writes."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
from collections.abc import Mapping
from contextvars import ContextVar, Token
from datetime import UTC, date, datetime, timedelta
from secrets import token_hex
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from core.config import get_settings
from modules.assistant.contracts import AssistantOperation
from modules.assistant.operation_trace_models import (
    AssistantOperationSequenceAggregate,
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


_USAGE_FIELDS = frozenset(
    {
        "requests",
        "tool_attempts",
        "web_requests",
        "prompt_tokens",
        "completion_tokens",
        "usage_complete",
        "usage_unknown",
        "pending_usage",
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
        "unknown_fields": {name: {"present": True} for name in sorted(unknown)},
    }


def _refs(*values: object) -> list[dict]:
    found: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, value: object) -> None:
        if value is None or isinstance(value, (dict, list, tuple, set)):
            return
        rendered = str(value)
        if len(rendered) > 160:
            return
        key = (kind[:80], rendered)
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
    return {key: value[key] for key in _USAGE_FIELDS if key in value}


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
    from modules.account.facade import is_demo_readonly_principal

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


async def archive_expired_operation_traces(
    db, novel_id: str, *, now: datetime | None = None
) -> int:
    """Aggregate and delete details after 180 days; aggregate rows have no IDs."""
    current = now or datetime.now(UTC)
    cutoff = current - timedelta(days=180)
    novel_uuid = UUID(str(novel_id))
    rows = list(
        (
            await db.scalars(
                select(AssistantOperationTrace)
                .where(
                    AssistantOperationTrace.novel_id == novel_uuid,
                    AssistantOperationTrace.occurred_at < cutoff,
                )
                .order_by(AssistantOperationTrace.id)
            )
        ).all()
    )
    if not rows:
        return 0

    event_counts: dict[tuple[date, str, str], int] = {}
    sequence_rows: dict[tuple[date, str], list[AssistantOperationTrace]] = {}
    for row in rows:
        occurred_on = row.occurred_at.date()
        key = (occurred_on, row.op_id, row.event_type)
        event_counts[key] = event_counts.get(key, 0) + 1
        if row.event_type in {"executed", "failed", "outcome_unknown"}:
            group_id = str(row.session_id or row.run_id or row.call_id or row.id)
            sequence_rows.setdefault((occurred_on, group_id), []).append(row)

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
    for (occurred_on, _group_id), sequence_rows_for_day in sequence_rows.items():
        sequence = [row.op_id for row in sequence_rows_for_day]
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
            },
            "sequence_count",
        )
    for row in rows:
        await db.delete(row)
    await db.flush()
    return len(rows)


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
        )
        # The savepoint is intentionally narrower than the business transaction:
        # trace failure must not undo a successful domain write.
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except Exception as exc:  # trace is auxiliary; never fail the business action
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
    "operation_trace_enabled",
    "record_operation_trace",
    "reset_operation_trace_context",
    "set_operation_trace_preference",
]
