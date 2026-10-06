"""Closed gate: the app middleware is the only XHR gate for every /api write.

``_ApiSecurityMiddleware`` rejects any state-changing request under ``/api/``
that lacks ``X-Requested-With: XMLHttpRequest`` before routing happens.  These
tests enumerate every registered route (scripted, not sampled) so that:

1. no write route can live outside the middleware's ``/api/`` prefix;
2. every ``/api`` write route really returns the middleware 403 without the
   header -- regardless of auth fixtures, path params, body, or existence of
   the probed resource;
3. the middleware's 401/403/404 ordering is pinned as a regression alarm.

Route-level ``Depends(require_xhr_request)`` duplicates are intentionally not
required here; this test is what proves their removal keeps the gate closed.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

import pytest
from fastapi.routing import APIRoute
from httpx import AsyncClient

from app.main import app
from core.config import get_settings

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# Lower-bound drift alarm, not a frozen count.
MIN_WRITE_ROUTES = 400
_XHR_DETAIL = "Missing X-Requested-With header"
_PATH_PARAM = re.compile(r"\{[^}]+\}")


def _iter_route_entries(routes: list, prefix: str = "") -> Iterator[tuple[str, object]]:
    """Yield ``(prefixed_path, route)`` for every registered route entry."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield f"{prefix}{route.path}", route
            continue
        original_router = getattr(route, "original_router", None)
        if original_router is not None:
            include_context = getattr(route, "include_context", None)
            nested_prefix = str(getattr(include_context, "prefix", "") or "")
            yield from _iter_route_entries(
                original_router.routes, prefix + nested_prefix
            )
            continue
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if isinstance(path, str) and methods is not None:
            # Plain starlette Route (openapi/docs/static fallbacks).
            yield f"{prefix}{path}", route
            continue
        raise AssertionError(
            f"unhandled route type {type(route).__name__}; extend the enumerator "
            "so write routes cannot hide behind a new routing wrapper"
        )


def _write_routes() -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for path, route in _iter_route_entries(app.routes):
        for method in sorted(getattr(route, "methods", None) or set()):
            if method in WRITE_METHODS:
                entries.append((method, path))
    return entries


def test_every_write_route_lives_under_the_api_gate_prefix() -> None:
    write_routes = _write_routes()

    assert len(write_routes) >= MIN_WRITE_ROUTES
    assert {method for method, _ in write_routes} == WRITE_METHODS

    outside = sorted(
        f"{method} {path}"
        for method, path in write_routes
        if not path.startswith("/api/")
    )
    assert not outside, (
        "write routes outside the /api/ middleware gate (unguarded):\n"
        + "\n".join(outside)
    )


def test_write_routes_carry_no_duplicate_route_level_xhr_dependency() -> None:
    """The middleware is the single gate; write routes keep no route-level copy.

    Read routes may still opt into ``require_xhr_request`` (e.g. the forecast
    GET endpoints); only state-changing routes are asserted duplicate-free.
    """

    duplicates: list[str] = []
    for path, route in _iter_route_entries(app.routes):
        route_methods = getattr(route, "methods", None) or set()
        methods = {m for m in route_methods if m in WRITE_METHODS}
        if not methods or not isinstance(route, APIRoute):
            continue
        pending = list(route.dependant.dependencies)
        while pending:
            dependency = pending.pop()
            pending.extend(dependency.dependencies)
            if getattr(dependency.call, "__name__", "") == "require_xhr_request":
                duplicates.append(f"{sorted(methods)} {path}")
                break

    assert not duplicates, (
        "write routes duplicating the middleware XHR gate:\n" + "\n".join(duplicates)
    )


@pytest.mark.asyncio
async def test_every_api_write_route_rejects_missing_xhr_header(
    raw_async_client: AsyncClient,
) -> None:
    write_routes = _write_routes()
    assert len(write_routes) >= MIN_WRITE_ROUTES

    failures: list[str] = []
    for method, path in write_routes:
        # The middleware runs before routing and body parsing, so probe paths
        # need no real identifiers and no request body.
        probe_path = _PATH_PARAM.sub("xhr-gate-probe", path)
        response = await raw_async_client.request(method, probe_path)
        detail: str | None = None
        try:
            detail = response.json().get("detail")
        except ValueError:
            pass
        if response.status_code != 403 or detail != _XHR_DETAIL:
            failures.append(
                f"{method} {path}: status={response.status_code} "
                f"body={response.text[:200]!r}"
            )

    assert not failures, (
        f"{len(failures)} of {len(write_routes)} write routes are not covered by "
        "the middleware XHR gate:\n" + "\n".join(failures)
    )


@pytest.mark.asyncio
async def test_xhr_gate_precedes_route_resolution(
    raw_async_client: AsyncClient,
) -> None:
    """An unknown /api write path still gets the middleware 403, not a 404."""
    response = await raw_async_client.post("/api/__xhr_gate_probe_missing_route__")

    assert response.status_code == 403
    assert response.json()["detail"] == _XHR_DETAIL


@pytest.mark.asyncio
async def test_closed_test_token_gate_precedes_the_xhr_gate(
    raw_async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pins the existing order: closed-test bearer 401 fires before XHR 403."""
    monkeypatch.setenv("APP_ACCESS_TOKEN", "xhr-gate-token")
    get_settings.cache_clear()
    try:
        unauthenticated = await raw_async_client.post(
            "/api/projects", json={"title": "xhr-gate"}
        )
        authenticated = await raw_async_client.post(
            "/api/projects",
            json={"title": "xhr-gate"},
            headers={"Authorization": "Bearer xhr-gate-token"},
        )
    finally:
        get_settings.cache_clear()

    assert unauthenticated.status_code == 401
    assert authenticated.status_code == 403
    assert authenticated.json()["detail"] == _XHR_DETAIL
