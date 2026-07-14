"""Direct contract tests for the shared FastAPI dependency aliases."""

from typing import get_args

from fastapi.params import Depends

from core.config import Settings, get_settings
from core.database import get_db as database_get_db
from core.dependencies import AppSettings, CurrentProject, DbSession, get_db


def _dependency_parts(alias):
    value_type, *metadata = get_args(alias)
    dependencies = [item for item in metadata if isinstance(item, Depends)]
    assert len(dependencies) == 1
    return value_type, dependencies[0].dependency


def test_get_db_is_the_database_dependency_reexport() -> None:
    assert get_db is database_get_db


def test_db_session_alias_retains_get_db_dependency() -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    value_type, dependency = _dependency_parts(DbSession)

    assert value_type is AsyncSession
    assert dependency is get_db


def test_app_settings_alias_retains_settings_dependency() -> None:
    value_type, dependency = _dependency_parts(AppSettings)

    assert value_type is Settings
    assert dependency is get_settings


def test_current_project_preserves_novel_id_without_normalization() -> None:
    novel_id = "project-scope-contract"

    assert CurrentProject(novel_id).novel_id == novel_id
