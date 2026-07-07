from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.main import app, domain_error_handler
from core.errors import ConflictError, DomainError, NotFoundError, ValidationError


def _backend_path(*parts: str) -> Path:
    backend_root = Path(__file__).resolve().parents[2]
    return backend_root.joinpath(*parts)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (NotFoundError("missing", code="map_not_found"), 404, "map_not_found"),
        (
            ConflictError("duplicate", code="duplicate_map_name"),
            409,
            "duplicate_map_name",
        ),
        (ValidationError("invalid", code="invalid_map"), 400, "invalid_map"),
    ],
)
async def test_domain_error_handler_maps_status_code_and_message(
    error,
    status_code: int,
    code: str,
) -> None:
    response = await domain_error_handler(None, error)
    body = json.loads(response.body)

    assert response.status_code == status_code
    assert body == {
        "error": code,
        "detail": error.message,
        "message": error.message,
        "status_code": status_code,
    }


def test_non_api_backend_code_has_no_fastapi_http_exception_dependency() -> None:
    offenders: list[str] = []
    for root in (Path("backend/core"), Path("backend/shared"), Path("backend/modules")):
        for path in root.rglob("*.py"):
            if "/tests/" in path.as_posix() or path.name == "api.py":
                continue
            source = path.read_text()
            if "HTTPException" in source:
                offenders.append(path.as_posix())

    assert offenders == []


def test_legacy_application_error_handler_is_not_registered_in_main() -> None:
    source = _backend_path("app", "main.py").read_text()
    legacy_error_name = "App" + "Error"

    assert f"class {legacy_error_name}" not in source
    assert f"exception_handler({legacy_error_name})" not in source


def test_domain_error_handler_is_registered() -> None:
    assert app.exception_handlers[DomainError] is domain_error_handler
