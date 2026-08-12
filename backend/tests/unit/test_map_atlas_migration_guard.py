from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20260812_ai_map_atlas.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "test_map_atlas_migration_guard_module",
        MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def _bind(*, has_projects: bool) -> MagicMock:
    bind = MagicMock()
    bind.execute.return_value.scalar_one.return_value = has_projects
    return bind


def test_non_development_project_database_requires_one_time_backup_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _load_migration()
    monkeypatch.setenv("APP_ENV", "production")

    with pytest.raises(RuntimeError, match="verified pre-migration backup"):
        migration._require_destructive_confirmation(_bind(has_projects=True))

    monkeypatch.setenv(
        "MAP_ATLAS_DESTRUCTIVE_MIGRATION_CONFIRMATION",
        "DROP_LEGACY_MAP_DATA_20260812",
    )
    monkeypatch.setenv(
        "MAP_ATLAS_DESTRUCTIVE_MIGRATION_BACKUP_NAME",
        "20260812T120000Z.dump",
    )
    monkeypatch.setenv(
        "MAP_ATLAS_DESTRUCTIVE_MIGRATION_BACKUP_SHA256",
        "a" * 64,
    )

    migration._require_destructive_confirmation(_bind(has_projects=True))


def test_fresh_and_development_databases_do_not_require_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _load_migration()
    monkeypatch.setenv("APP_ENV", "production")
    migration._require_destructive_confirmation(_bind(has_projects=False))

    monkeypatch.setenv("APP_ENV", "test")
    bind = _bind(has_projects=True)
    migration._require_destructive_confirmation(bind)
    bind.execute.assert_not_called()
