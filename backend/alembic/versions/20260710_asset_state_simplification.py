"""normalize legacy author-created world assets

Revision ID: 20260710_asset_state_simple
Revises: 20260710_novel_evidence

The author-facing lifecycle is a derived API projection and therefore needs no
new columns.  This data migration only removes the old double-confirmation
requirement for legacy manual CoreEntity rows and for accepted world creation
suggestions whose result was historically persisted as ``draft``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

import sqlalchemy as sa

from alembic import op

revision = "20260710_asset_state_simple"
down_revision = "20260710_novel_evidence"
branch_labels = None
depends_on = None

_AI_SOURCES = frozenset(
    {
        "ai",
        "ai_chatbox",
        "ai_generated",
        "ai_import",
        "ai_world_bible",
        "deep_import",
        "llm",
        "world_bible_ai_generation",
    }
)
_MANUAL_SOURCES = frozenset({"author", "human", "manual", "manual_edit", "user"})


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "core_entities" not in tables:
        return

    entity_columns = {column["name"] for column in inspector.get_columns("core_entities")}
    if not {
        "id",
        "status",
        "created_by",
        "approved_by",
        "content_json",
    }.issubset(entity_columns):
        return

    accepted_ids: set[str] = set()
    if "creation_suggestion_queue" in tables:
        accepted_ids = _load_accepted_core_entity_ids(bind)

    rows = bind.execute(
        sa.text(
            "SELECT id, status, created_by, approved_by, content_json "
            "FROM core_entities WHERE status = 'draft'"
        )
    ).mappings()
    for row in rows:
        entity_id = str(row["id"])
        if entity_id not in accepted_ids and not _is_legacy_manual_entity(row):
            continue
        approved_by = row.get("approved_by") or row.get("created_by") or "manual"
        bind.execute(
            sa.text(
                "UPDATE core_entities "
                "SET status = 'canonical', approved_by = :approved_by "
                "WHERE id = :entity_id AND status = 'draft'"
            ),
            {"entity_id": row["id"], "approved_by": approved_by},
        )


def downgrade() -> None:
    # The previous status cannot be reconstructed without inventing provenance.
    # Demo databases may be rebuilt; a downgrade deliberately keeps adopted data.
    return


def _load_accepted_core_entity_ids(bind: Any) -> set[str]:
    rows = bind.execute(
        sa.text(
            "SELECT status, target_type, result_ref_json "
            "FROM creation_suggestion_queue "
            "WHERE status = 'accepted'"
        )
    ).mappings()
    return _accepted_core_entity_ids(rows)


def _accepted_core_entity_ids(rows: Iterable[Mapping[str, Any]]) -> set[str]:
    accepted: set[str] = set()
    for row in rows:
        if row.get("status") != "accepted":
            continue
        if row.get("target_type") not in {"core_entity", "core_entity_draft"}:
            continue
        result_ref = _json_object(row.get("result_ref_json"))
        if result_ref.get("type") != "core_entity" or not result_ref.get("id"):
            continue
        accepted.add(str(result_ref["id"]))
    return accepted


def _is_legacy_manual_entity(row: Mapping[str, Any]) -> bool:
    if str(row.get("status") or "") != "draft":
        return False
    content = _json_object(row.get("content_json"))
    meta = _json_object(content.get("_meta"))
    if meta.get("auto_ingested") is True:
        return False
    created_by = str(row.get("created_by") or "").strip().lower()
    source = str(meta.get("source") or "").strip().lower()
    if source and source not in _MANUAL_SOURCES:
        return False
    if not created_by:
        return source in _MANUAL_SOURCES
    if created_by in _AI_SOURCES or created_by.startswith(("ai_", "llm_")):
        return False
    return True


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return dict(decoded) if isinstance(decoded, dict) else {}
    return {}
