from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.main import _TimingMiddleware, app, domain_error_handler
from core.errors import ConflictError, DomainError, NotFoundError, ValidationError


def _backend_path(*parts: str) -> Path:
    backend_root = Path(__file__).resolve().parents[2]
    return backend_root.joinpath(*parts)


def _domain_log_records(
    caplog: pytest.LogCaptureFixture,
) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if record.name == "app.main"
        and record.getMessage().startswith("Domain request rejected ")
    ]


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


@pytest.mark.asyncio
async def test_domain_error_handler_adds_context_only_when_present() -> None:
    error = ConflictError(
        "blocked",
        code="entity_type_change_blocked",
        context={"blockers": [{"kind": "event_extension", "count": 1}]},
    )

    response = await domain_error_handler(None, error)

    assert json.loads(response.body)["context"] == error.context


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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_level"),
    [
        (
            ValidationError(
                "用户正文 secret-token 不应进入日志",
                code="invalid_map",
            ),
            logging.INFO,
        ),
        (
            DomainError(
                "Bearer sk-sensitive 不应进入日志",
                code="import_failed",
                status_code=500,
            ),
            logging.ERROR,
        ),
    ],
)
async def test_domain_error_handler_logs_only_safe_structured_fields(
    error: DomainError,
    expected_level: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw_project_id = "123e4567-e89b-12d3-a456-426614174000"
    request = SimpleNamespace(
        scope={
            "type": "http",
            "method": "patch",
            "path": f"/api/projects/{raw_project_id}/maps/private-name",
            "route": SimpleNamespace(path="/api/projects/{project_id}/maps/{map_id}"),
        }
    )

    with caplog.at_level(logging.INFO, logger="app.main"):
        response = await domain_error_handler(request, error)

    records = _domain_log_records(caplog)
    assert len(records) == 1
    record = records[0]
    assert record.levelno == expected_level
    assert record.exc_info is None
    assert record.getMessage() == (
        "Domain request rejected method=PATCH "
        f"route=/api/projects/{{project_id}}/maps/{{map_id}} "
        f"status={error.status_code} code={error.code} novel_id=<none>"
    )
    assert raw_project_id not in caplog.text
    assert error.message not in caplog.text
    assert response.status_code == error.status_code


@pytest.mark.asyncio
@pytest.mark.parametrize("scope_kind", ["missing", "malformed_http", "websocket"])
async def test_domain_error_handler_falls_back_for_untrusted_log_metadata(
    scope_kind: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "Bearer secret"
    error = DomainError("safe response", code=f"bad\n{secret}")
    if scope_kind == "missing":
        request = None
    else:
        request = SimpleNamespace(
            scope={
                "type": "http" if scope_kind == "malformed_http" else "websocket",
                "method": f"GET\n{secret}",
                "route": SimpleNamespace(path=f"/private\n{secret}"),
            }
        )

    with caplog.at_level(logging.INFO, logger="app.main"):
        response = await domain_error_handler(request, error)

    records = _domain_log_records(caplog)
    assert len(records) == 1
    assert records[0].getMessage() == (
        "Domain request rejected method=UNKNOWN route=<unresolved> "
        "status=400 code=domain_error novel_id=<none>"
    )
    assert secret not in caplog.text
    assert json.loads(response.body)["error"] == f"bad\n{secret}"


@pytest.mark.asyncio
async def test_domain_error_handler_gets_route_template_in_real_fastapi_scope(
    caplog: pytest.LogCaptureFixture,
) -> None:
    test_app = FastAPI()
    test_app.add_exception_handler(DomainError, domain_error_handler)
    test_app.add_middleware(_TimingMiddleware)

    @test_app.get("/probe/{item_id}")
    async def _raise_domain_error(item_id: str) -> None:
        raise DomainError(
            f"private item {item_id}", code="probe_not_found", status_code=404
        )

    private_item_id = "customer-private-id"
    transport = ASGITransport(app=test_app)
    with caplog.at_level(logging.INFO, logger="app.main"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(f"/probe/{private_item_id}")

    records = _domain_log_records(caplog)
    assert len(records) == 1
    assert records[0].getMessage() == (
        "Domain request rejected method=GET route=/probe/{item_id} "
        "status=404 code=probe_not_found novel_id=<none>"
    )
    assert private_item_id not in caplog.text
    assert response.status_code == 404
    assert response.json() == {
        "error": "probe_not_found",
        "detail": f"private item {private_item_id}",
        "message": f"private item {private_item_id}",
        "status_code": 404,
    }
