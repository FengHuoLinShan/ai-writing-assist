"""Source-bound omission signals; these are search leads, never adoption decisions."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def completion_hints(extraction: Any, *, scene_id: str, source_text: str) -> list[dict]:
    """Keep concrete names/field failures, not every candidate or empty field."""
    hints = []
    for item in getattr(extraction, "entities", []):
        name = str(item.name or "").strip()
        reason = str(item.candidate_reason or "")
        fields = [
            field
            for field in ("summary", "public_info", "hidden_truth")
            if f"{field}_evidence_not_found" in reason
        ]
        identity_issue = any(
            part in reason
            for part in (
                "unknown_existing_identity_ref",
                "existing_identity_type_mismatch",
                "identity_uncertain",
            )
        )
        if not name or name not in source_text or not (fields or identity_issue):
            continue
        quotes = [
            quote for quote in item.evidence_quotes if quote and quote in source_text
        ]
        if not quotes:
            continue
        hints.append(
            {
                "name": name,
                "entity_type": item.entity_type,
                "scene_id": scene_id,
                "kind": "field_gap" if fields else "identity_gap",
                "fields": fields,
                "reason": reason,
                "quote": quotes[0],
            }
        )
    for item in getattr(extraction, "uncertain_items", []):
        description = str(getattr(item, "description", "") or "")
        # Only these local materializer prefixes carry an unambiguous name.
        prefixes = ("世界对象类型待确认：", "世界对象身份待确认：")
        name = str(getattr(item, "mention_name", "") or "").strip() or next(
            (
                description[len(prefix) :].strip()
                for prefix in prefixes
                if description.startswith(prefix)
            ),
            "",
        )
        quotes = [
            quote
            for quote in getattr(item, "evidence_quotes", [])
            if quote and quote in source_text
        ]
        if name and name in source_text and quotes:
            hints.append(
                {
                    "name": name,
                    "scene_id": scene_id,
                    "kind": "identity_gap",
                    "fields": [],
                    "reason": item.reason,
                    "quote": quotes[0],
                }
            )
    return deduplicate_hints(hints)


def alias_completion_hints(
    diagnostics: list[dict], *, scene_id: str, source_text: str, context_bundle: dict
) -> list[dict]:
    identities = {
        str(item.get("prompt_ref")): item
        for item in context_bundle.get("identity_candidates", [])
        if isinstance(item, dict)
    }
    hints = []
    for item in diagnostics:
        if item.get("kind") not in {
            "alias_identity",
            "relation_endpoint",
            "relation_change",
        }:
            continue
        quotes = [
            quote
            for quote in item.get("evidence_quotes", [])
            if quote and quote in source_text
        ]
        if not quotes:
            continue
        name = str(item.get("mention_name") or "").strip()
        if name and name in source_text and any(name in quote for quote in quotes):
            hints.append(
                {
                    "name": name,
                    "scene_id": scene_id,
                    "kind": str(item["kind"]),
                    "reason": str(item.get("reason") or ""),
                    "fields": [],
                    "quote": quotes[0],
                }
            )
        for ref in item.get("related_refs", []):
            identity = identities.get(str(ref), {})
            name = str(identity.get("name") or "").strip()
            if name and name in source_text:
                hints.append(
                    {
                        "name": name,
                        "scene_id": scene_id,
                        "kind": str(item["kind"]),
                        "reason": str(item.get("reason") or ""),
                        "fields": [],
                        "quote": quotes[0],
                    }
                )
    return deduplicate_hints(hints)


def deduplicate_hints(hints: list[dict]) -> list[dict]:
    unique = {}
    for hint in hints:
        key = hashlib.sha256(
            json.dumps(hint, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        unique.setdefault(key, {**hint, "key": key})
    return list(unique.values())
