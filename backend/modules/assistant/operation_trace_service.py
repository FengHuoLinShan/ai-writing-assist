"""Best-effort operation trace port with a savepoint isolated from business writes."""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
from collections.abc import Mapping
from time import monotonic
from uuid import UUID

from core.config import get_settings
from modules.assistant.contracts import AssistantOperation
from modules.assistant.operation_trace_models import AssistantOperationTrace

logger = logging.getLogger(__name__)

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


def _project_hash(novel_id: str, value: str) -> str:
    settings = get_settings()
    key = (settings.auth_secret_key or novel_id).encode("utf-8")
    salt = hashlib.sha256(b"assistant-operation-trace\0" + novel_id.encode()).digest()
    return hmac.new(key + salt, value.encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def _parameter_summary(
    operation: AssistantOperation, novel_id: str, arguments: object
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
                    "project_hash": _project_hash(novel_id, value),
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


async def record_operation_trace(
    db,
    *,
    enabled: bool,
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
) -> bool:
    """Return false only when enabled trace persistence failed."""
    if not enabled or operation.trace_rule.mode == "exempt":
        return True
    from modules.assistant.operation_trace_models import AssistantOperationTrace

    stable_error = error_code if error_code and _ERROR_CODE.fullmatch(error_code) else None
    row = AssistantOperationTrace(
        novel_id=UUID(str(novel_id)),
        owner_id=UUID(str(owner_id)),
        actor_type=actor_type if actor_type in {
            "assistant", "guided_flow", "goal", "ui", "background", "system"
        } else "assistant",
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
        parameter_summary=_parameter_summary(operation, str(novel_id), arguments),
        result_refs=_refs(result),
        error_code=stable_error,
        duration_ms=max(0, int(duration_ms)) if duration_ms is not None else None,
        usage=_usage_summary(usage),
    )
    try:
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


__all__ = ["record_operation_trace"]
