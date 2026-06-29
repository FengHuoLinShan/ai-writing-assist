"""Conflict evidence payload helpers for writing checks."""

from __future__ import annotations

from typing import Any


def evidence_location(
    *,
    source_module: str,
    source_type: str,
    source_id: str | None,
    source_label: str,
    source_field: str,
    source_excerpt: str,
    open_target: dict[str, Any],
    text_range: dict[str, int] | None = None,
    needs_review_reason: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "source": {
            "module": source_module,
            "type": source_type,
            "id": source_id,
            "label": source_label,
            "field": source_field,
            "excerpt": source_excerpt,
        },
        "open_target": open_target,
        "needs_review_reason": needs_review_reason,
    }
    if text_range is not None:
        payload["text_range"] = text_range
    return payload


def snapshot_location(location_json: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(location_json, dict):
        return None
    result: dict[str, Any] = {}
    source = location_json.get("source")
    open_target = location_json.get("open_target")
    if isinstance(source, dict):
        result["source"] = source
    if isinstance(open_target, dict):
        result["open_target"] = open_target
    if "needs_review_reason" in location_json:
        result["needs_review_reason"] = location_json.get("needs_review_reason")
    return result or None
