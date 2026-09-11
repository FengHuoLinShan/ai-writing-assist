"""Hash helpers for immutable manuscript source references."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any


def hash_text(text: str | None) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def compiled_context_fingerprint(compiled: object) -> dict[str, Any]:
    sections: list[dict[str, Any]] = []
    for section in getattr(compiled, "sections", []):
        retrieval_metadata = dict(getattr(section, "retrieval_metadata", None) or {})
        retrieval_metadata.pop("latency_metadata", None)
        tier = getattr(section, "tier", 0)
        try:
            tier = int(tier)
        except (TypeError, ValueError):
            tier = str(tier)
        sections.append(
            {
                "key": getattr(section, "key", None),
                "tier": tier,
                "content": getattr(section, "content", None),
                "token_count": getattr(section, "token_count", None),
                "status": getattr(section, "status", None),
                "sources": deepcopy(getattr(section, "sources", None) or []),
                "excluded": bool(getattr(section, "excluded", False)),
                "truncated_reason": getattr(section, "truncated_reason", None),
                "retrieval_metadata": deepcopy(retrieval_metadata),
            }
        )
    budget_events = [
        event.model_dump(mode="json")
        if hasattr(event, "model_dump")
        else deepcopy(event)
        for event in getattr(compiled, "budget_events", [])
    ]
    return {
        "sections": sections,
        "total_tokens": getattr(compiled, "total_tokens", None),
        "budget_tokens": getattr(compiled, "budget_tokens", None),
        "evicted_keys": list(getattr(compiled, "evicted_keys", []) or []),
        "truncated_keys": list(getattr(compiled, "truncated_keys", []) or []),
        "budget_events": budget_events,
        "warnings": list(getattr(compiled, "warnings", []) or []),
    }


def substantive_text(text: str | None) -> str:
    """Return the body used for automatic version-change comparisons.

    Storage keeps the author's exact text. Only automatic version detection
    ignores Unicode whitespace so formatting-only edits remain local until the
    author explicitly checkpoints them.
    """

    return "".join(char for char in (text or "") if not char.isspace())


def has_substantive_change(before: str | None, after: str | None) -> bool:
    return substantive_text(before) != substantive_text(after)
