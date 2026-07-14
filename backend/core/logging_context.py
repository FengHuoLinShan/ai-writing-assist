"""Request/task-local logging context for safe project correlation."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_NO_NOVEL_ID = "<none>"
_INVALID_NOVEL_ID = "<invalid>"
_MULTIPLE_NOVEL_IDS = "<multiple>"

_scope_active: ContextVar[bool] = ContextVar("log_scope_active", default=False)
_novel_id: ContextVar[str] = ContextVar("log_novel_id", default=_NO_NOVEL_ID)


def _safe_novel_id(value: Any, *, invalid: str) -> str:
    if value is None:
        return _NO_NOVEL_ID
    if isinstance(value, uuid.UUID):
        return str(value)
    if not isinstance(value, str) or len(value) > 64:
        return invalid
    try:
        return str(uuid.UUID(value.strip()))
    except ValueError:
        return invalid


def novel_id_for_log(value: Any) -> str:
    """Return a bounded canonical project identifier without echoing invalid input."""
    return _safe_novel_id(value, invalid=_INVALID_NOVEL_ID)


def current_novel_id_for_log() -> str:
    """Return the safe project identifier bound to the current request/task."""
    return _novel_id.get()


def bind_validated_novel_id(value: Any) -> bool:
    """Bind a validated project ID only while an explicit log scope is active."""
    if not _scope_active.get():
        return False
    normalized = _safe_novel_id(value, invalid=_NO_NOVEL_ID)
    if normalized == _NO_NOVEL_ID:
        return False

    current = _novel_id.get()
    if current == _NO_NOVEL_ID:
        _novel_id.set(normalized)
        return True
    if current == normalized:
        return True
    _novel_id.set(_MULTIPLE_NOVEL_IDS)
    return False


@contextmanager
def novel_log_scope(initial_novel_id: Any = None) -> Iterator[None]:
    """Isolate project log context across concurrent requests and worker tasks."""
    active_token = _scope_active.set(True)
    novel_token = _novel_id.set(novel_id_for_log(initial_novel_id))
    try:
        yield
    finally:
        _novel_id.reset(novel_token)
        _scope_active.reset(active_token)
