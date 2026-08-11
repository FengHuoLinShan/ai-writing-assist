"""Small helpers for redacting provider diagnostics."""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

_BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_AUTH_HEADER_RE = re.compile(
    r"Authorization\s*:\s*[^\s,;]+(?:\s+[^\s,;]+)?",
    re.IGNORECASE,
)
_API_KEY_RE = re.compile(
    r"(?i)(api[_-]?key|token|secret)\s*[:=]\s*[^\s,;&]+",
)
_SK_RE = re.compile(r"\bsk-[A-Za-z0-9._-]{6,}\b")
_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]+")


def _redact_url(match: re.Match[str]) -> str:
    """Strip credentials, query values, and fragments from one URL."""
    raw = match.group(0)
    try:
        parsed = urlsplit(raw)
        hostname = parsed.hostname or ""
        if not hostname:
            return "[REDACTED_URL]"
        try:
            port = f":{parsed.port}" if parsed.port is not None else ""
        except ValueError:
            port = ""
        query = "[REDACTED]" if parsed.query else ""
        return urlunsplit((parsed.scheme, f"{hostname}{port}", parsed.path, query, ""))
    except ValueError:
        return "[REDACTED_URL]"


def redact_diagnostic(value: object, *, limit: int | None = None) -> str:
    """Return a short diagnostic string with credentials removed."""
    text = str(value)
    text = _URL_RE.sub(_redact_url, text)
    text = _AUTH_HEADER_RE.sub("Authorization: [REDACTED]", text)
    text = _BEARER_RE.sub("Bearer [REDACTED]", text)
    text = _API_KEY_RE.sub(lambda m: f"{m.group(1)}=[REDACTED]", text)
    text = _SK_RE.sub("[REDACTED]", text)
    text = _CONTROL_CHAR_RE.sub(" ", text)
    if limit is not None:
        return text[:limit]
    return text
