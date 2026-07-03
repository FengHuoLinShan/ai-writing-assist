"""Small helpers for redacting provider diagnostics."""

from __future__ import annotations

import re

_BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_AUTH_HEADER_RE = re.compile(
    r"Authorization\s*:\s*[^\s,;]+(?:\s+[^\s,;]+)?",
    re.IGNORECASE,
)
_API_KEY_RE = re.compile(
    r"(?i)(api[_-]?key|token|secret)\s*[:=]\s*[^\s,;&]+",
)
_SK_RE = re.compile(r"\bsk-[A-Za-z0-9._-]{6,}\b")


def redact_diagnostic(value: object, *, limit: int | None = None) -> str:
    """Return a short diagnostic string with credentials removed."""
    text = str(value)
    text = _AUTH_HEADER_RE.sub("Authorization: [REDACTED]", text)
    text = _BEARER_RE.sub("Bearer [REDACTED]", text)
    text = _API_KEY_RE.sub(lambda m: f"{m.group(1)}=[REDACTED]", text)
    text = _SK_RE.sub("[REDACTED]", text)
    if limit is not None:
        return text[:limit]
    return text
