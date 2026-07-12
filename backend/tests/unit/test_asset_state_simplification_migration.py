from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    BACKEND_ROOT / "alembic" / "versions" / "20260710_asset_state_simplification.py"
)

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _load_migration_module():
    spec = importlib.util.spec_from_file_location(
        "test_asset_state_simplification_migration_module",
        MIGRATION_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MIGRATION = _load_migration_module()


def test_manual_legacy_draft_is_adopted_but_ai_and_import_drafts_are_not() -> None:
    assert MIGRATION._is_legacy_manual_entity(
        {
            "status": "draft",
            "created_by": "author-1",
            "content_json": {},
        }
    )
    assert not MIGRATION._is_legacy_manual_entity(
        {
            "status": "draft",
            "created_by": "ai_chatbox",
            "content_json": {},
        }
    )
    assert not MIGRATION._is_legacy_manual_entity(
        {
            "status": "draft",
            "created_by": "author-1",
            "content_json": {"_meta": {"auto_ingested": True}},
        }
    )
    assert not MIGRATION._is_legacy_manual_entity(
        {
            "status": "draft",
            "created_by": None,
            "content_json": {},
        }
    )
    assert not MIGRATION._is_legacy_manual_entity(
        {
            "status": "draft",
            "created_by": None,
            "content_json": {"_meta": {"source": "unknown_legacy_source"}},
        }
    )
    assert MIGRATION._is_legacy_manual_entity(
        {
            "status": "draft",
            "created_by": None,
            "content_json": {"_meta": {"source": "manual"}},
        }
    )


def test_accepted_suggestion_result_ids_only_include_core_entities() -> None:
    rows = [
        {
            "status": "accepted",
            "target_type": "core_entity_draft",
            "result_ref_json": '{"type":"core_entity","id":"entity-1"}',
        },
        {
            "status": "accepted",
            "target_type": "entity_alias",
            "result_ref_json": {"type": "entity_alias", "id": "alias-1"},
        },
        {
            "status": "pending",
            "target_type": "core_entity",
            "result_ref_json": {"type": "core_entity", "id": "entity-2"},
        },
    ]

    assert MIGRATION._accepted_core_entity_ids(rows) == {"entity-1"}
