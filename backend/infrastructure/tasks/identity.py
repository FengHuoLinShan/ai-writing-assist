"""Canonical task project identity handling.

``AsyncTask.novel_id`` is the authoritative project boundary.  The matching
``meta.novel_id`` stays as a handler/API compatibility projection.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any


def normalize_task_novel_id(value: Any) -> uuid.UUID | None:
    """Return one UUID project identity, rejecting malformed non-null values."""
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("task novel_id must be a UUID when provided") from exc


def task_novel_id_from_meta(meta: Mapping[str, Any] | None) -> uuid.UUID | None:
    """Read the optional compatibility projection from task metadata."""
    if not isinstance(meta, Mapping) or "novel_id" not in meta:
        return None
    return normalize_task_novel_id(meta.get("novel_id"))


def prepare_task_identity(
    meta: Mapping[str, Any] | None,
    *,
    novel_id: Any = None,
) -> tuple[uuid.UUID | None, dict[str, Any]]:
    """Normalize one immutable identity and its metadata projection."""
    if meta is not None and not isinstance(meta, Mapping):
        raise ValueError("task metadata must be an object")
    payload = dict(meta or {})
    metadata_novel_id = task_novel_id_from_meta(payload)
    explicit_novel_id = normalize_task_novel_id(novel_id)
    if (
        metadata_novel_id is not None
        and explicit_novel_id is not None
        and metadata_novel_id != explicit_novel_id
    ):
        raise ValueError("task novel_id does not match meta.novel_id")
    authoritative = explicit_novel_id or metadata_novel_id
    if authoritative is not None:
        payload["novel_id"] = str(authoritative)
    return authoritative, payload


def require_matching_task_identity(
    *,
    novel_id: Any,
    meta: Mapping[str, Any] | None,
) -> uuid.UUID | None:
    """Reject ownership drift from a detached or ORM task update."""
    authoritative = normalize_task_novel_id(novel_id)
    metadata_novel_id = task_novel_id_from_meta(meta)
    if authoritative != metadata_novel_id:
        raise ValueError("task meta.novel_id cannot change after enqueue")
    return authoritative
