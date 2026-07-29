"""Regression tests for account-level LLM credential migration."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_migration():
    path = (
        Path(__file__).parents[2]
        / "alembic"
        / "versions"
        / "20260728_account_llm_credentials.py"
    )
    spec = importlib.util.spec_from_file_location(
        "test_account_llm_migration_module",
        path,
    )
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_migration_only_removes_legacy_project_key_fields() -> None:
    migration = _load_migration()
    original = {
        "theme": "dark",
        "llm": {
            "provider_id": "deepseek",
            "model": "legacy-model",
            "api_key": {"encrypted": True, "value": "secret"},
            "api_keys_by_provider": {
                "deepseek": {"encrypted": True, "value": "secret"}
            },
        },
        "deep_import": {"global": {"structured_max_fix_attempts": 3}},
    }

    cleaned, changed = migration._strip_project_llm_secrets(original)

    assert changed is True
    assert cleaned["theme"] == "dark"
    assert cleaned["llm"] == {
        "provider_id": "deepseek",
        "model": "legacy-model",
    }
    assert cleaned["deep_import"] == original["deep_import"]
    assert original["llm"]["api_key"]["value"] == "secret"


def test_migration_leaves_projects_without_llm_keys_unchanged() -> None:
    migration = _load_migration()
    original = {
        "llm": {"provider_id": "kimi", "model": "kimi-k2.6"},
        "other": {"kept": True},
    }

    cleaned, changed = migration._strip_project_llm_secrets(original)

    assert changed is False
    assert cleaned == original
