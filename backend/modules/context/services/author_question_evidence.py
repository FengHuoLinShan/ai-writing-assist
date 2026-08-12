"""Budget a ranked, already-hydrated evidence packet for author questions."""

from __future__ import annotations

import re
from typing import Any

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def compile_author_question_evidence(
    sources: list[dict[str, Any]],
    *,
    max_sources: int = 5,
    max_chars: int = 24_000,
) -> dict[str, Any]:
    """Return model-visible evidence plus content-free exclusion diagnostics."""
    if not 1 <= max_sources <= 10:
        raise ValueError("max_sources must be between 1 and 10")
    if not 2_000 <= max_chars <= 60_000:
        raise ValueError("max_chars must be between 2000 and 60000")

    ranked = sorted(
        enumerate(sources),
        key=lambda item: (-float(item[1].get("score") or 0.0), item[0]),
    )
    included: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    truncated: list[str] = []
    seen: set[str] = set()
    remaining = max_chars
    for _index, raw in ranked:
        key = str(raw.get("key") or "").strip()
        title = str(raw.get("title") or "来源").strip()
        content = str(raw.get("content") or "").strip()
        source_hash = str(raw.get("source_hash") or "")
        if not key or not content or not _SHA256.fullmatch(source_hash):
            excluded.append(
                {
                    "key": key or "invalid",
                    "title": title,
                    "reason": "invalid_source",
                }
            )
            continue
        if key in seen:
            excluded.append({"key": key, "title": title, "reason": "duplicate"})
            continue
        seen.add(key)
        if len(included) >= max_sources:
            excluded.append({"key": key, "title": title, "reason": "rank_budget"})
            continue
        if remaining <= 0:
            excluded.append({"key": key, "title": title, "reason": "character_budget"})
            continue
        visible = content[:remaining]
        item = {**raw, "content": visible}
        included.append(item)
        remaining -= len(visible)
        if len(visible) < len(content):
            truncated.append(key)

    return {
        "included": included,
        "trace": {
            "included_source_keys": [item["key"] for item in included],
            "excluded": excluded,
            "truncated_source_keys": truncated,
            "source_count_before_budget": len(sources),
            "source_count_after_budget": len(included),
            "character_budget": max_chars,
            "characters_used": max_chars - remaining,
        },
    }
