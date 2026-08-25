"""Direct contract tests for the shared FastAPI dependency aliases."""

import re
import tomllib
from pathlib import Path
from typing import get_args

from fastapi.params import Depends

from core.config import Settings, get_settings
from core.database import get_db as database_get_db
from core.dependencies import AppSettings, CurrentProject, DbSession, get_db

BACKEND_ROOT = Path(__file__).resolve().parents[2]
FASTAPI_FUNCTION_SCOPE_MINIMUM = (0, 121, 1)


def _dependency_parts(alias):
    value_type, *metadata = get_args(alias)
    dependencies = [item for item in metadata if isinstance(item, Depends)]
    assert len(dependencies) == 1
    return value_type, dependencies[0]


def _minimum_fastapi_version(requirement: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"fastapi>=(\d+)\.(\d+)\.(\d+)", requirement)
    assert match is not None
    return tuple(int(part) for part in match.groups())


def test_get_db_is_the_database_dependency_reexport() -> None:
    assert get_db is database_get_db


def test_db_session_alias_retains_get_db_dependency() -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    value_type, dependency = _dependency_parts(DbSession)

    assert value_type is AsyncSession
    assert dependency.dependency is get_db
    assert dependency.scope == "function"


def test_fastapi_dependency_declares_function_scope_minimum() -> None:
    project = tomllib.loads((BACKEND_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    pyproject_requirement = next(
        item for item in project["project"]["dependencies"] if item.startswith("fastapi")
    )
    pyproject_minimum = _minimum_fastapi_version(pyproject_requirement)

    assert pyproject_minimum >= FASTAPI_FUNCTION_SCOPE_MINIMUM
    lock_specifier = ".".join(str(part) for part in pyproject_minimum)
    assert f'{{ name = "fastapi", specifier = ">={lock_specifier}" }}' in (
        BACKEND_ROOT / "uv.lock"
    ).read_text(encoding="utf-8")


def test_app_settings_alias_retains_settings_dependency() -> None:
    value_type, dependency = _dependency_parts(AppSettings)

    assert value_type is Settings
    assert dependency.dependency is get_settings


def test_current_project_preserves_novel_id_without_normalization() -> None:
    novel_id = "project-scope-contract"

    assert CurrentProject(novel_id).novel_id == novel_id
