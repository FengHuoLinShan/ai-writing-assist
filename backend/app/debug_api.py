"""Development/debug endpoints shared by the local frontend and tests."""

from __future__ import annotations

import re
from collections import deque
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from core.config import get_settings

router = APIRouter(prefix="/api/debug", tags=["debug"])

_MAX_FRONTEND_ERRORS = 200
_MAX_STRING_LENGTH = 2000
_SENSITIVE_KEY_RE = re.compile(
    r"(api[_-]?key|authorization|bearer|token|password|secret|credential)",
    re.IGNORECASE,
)
_SECRET_VALUE_RE = re.compile(
    r"(sk-[A-Za-z0-9_\-]{12,}|Bearer\s+[A-Za-z0-9._\-]{12,})",
    re.IGNORECASE,
)
_frontend_errors: deque[dict[str, Any]] = deque(maxlen=_MAX_FRONTEND_ERRORS)
_frontend_error_id = 0


class FrontendErrorRequest(BaseModel):
    """Frontend runtime error entry mirrored from the browser error logger."""

    level: Literal["error"] = "error"
    message: str = Field(..., min_length=1, max_length=_MAX_STRING_LENGTH)
    type: str = Field(default="runtime", max_length=80)
    frontend_id: int | None = Field(default=None, alias="frontendId")
    timestamp: str | None = Field(default=None, max_length=80)
    view: str | None = Field(default=None, max_length=120)
    sub_view: str | None = Field(default=None, max_length=120, alias="subView")
    stack: str | None = Field(default=None, max_length=6000)
    request: dict[str, Any] | None = None
    browser: dict[str, Any] | None = None
    page: dict[str, Any] | None = None

    @field_validator("type", "view", "sub_view", mode="before")
    @classmethod
    def _coerce_optional_string(cls, value: Any) -> Any:
        if value is None:
            return value
        return str(value)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _SENSITIVE_KEY_RE.search(key_text):
                result[key_text] = "[redacted]"
            else:
                result[key_text] = _redact(item)
        return result
    if isinstance(value, list):
        return [_redact(item) for item in value[:50]]
    if isinstance(value, str):
        cleaned = _SECRET_VALUE_RE.sub("[redacted]", value)
        if len(cleaned) > _MAX_STRING_LENGTH:
            return cleaned[:_MAX_STRING_LENGTH] + "...[truncated]"
        return cleaned
    if isinstance(value, int | float | bool) or value is None:
        return value
    return str(value)[:_MAX_STRING_LENGTH]


def _ensure_debug_allowed() -> None:
    if get_settings().app_env.lower() == "production":
        raise HTTPException(status_code=404, detail="Not found")


@router.post("/frontend-errors", status_code=202)
async def record_frontend_error(payload: FrontendErrorRequest) -> dict[str, Any]:
    """Store one frontend error for local test/debug inspection."""
    _ensure_debug_allowed()
    global _frontend_error_id
    _frontend_error_id += 1
    item = {
        "id": _frontend_error_id,
        "received_at": datetime.now(UTC).isoformat(),
        **_redact(payload.model_dump(by_alias=True, exclude_none=True)),
    }
    _frontend_errors.append(item)
    return {"id": item["id"], "stored": True}


@router.get("/frontend-errors")
async def list_frontend_errors(
    limit: int = Query(default=50, ge=1, le=_MAX_FRONTEND_ERRORS),
) -> dict[str, Any]:
    """Return recent frontend errors for tests and local debugging."""
    _ensure_debug_allowed()
    items = list(_frontend_errors)[-limit:]
    return {
        "items": list(reversed(items)),
        "total": len(_frontend_errors),
        "limit": limit,
    }


@router.delete("/frontend-errors")
async def clear_frontend_errors() -> dict[str, Any]:
    """Clear collected frontend errors."""
    _ensure_debug_allowed()
    count = len(_frontend_errors)
    _frontend_errors.clear()
    return {"cleared": count}
