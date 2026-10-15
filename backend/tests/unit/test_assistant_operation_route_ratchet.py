"""Every new write route is bound or explicitly exempt; legacy gaps only shrink."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.main import _install_operation_trace_route_adapters, app
from core.container import get
from core.service_keys import ASSISTANT_OPERATIONS

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
BASELINE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "assistant_operation_unbound_write_routes.json"
)


def _route_entries(routes, prefix: str = ""):
    for route in routes:
        if isinstance(route, APIRoute):
            yield f"{prefix}{route.path}", route
            continue
        nested = getattr(route, "original_router", None)
        if nested is not None:
            context = getattr(route, "include_context", None)
            nested_prefix = str(getattr(context, "prefix", "") or "")
            yield from _route_entries(nested.routes, prefix + nested_prefix)


def test_write_routes_are_bound_or_explicitly_exempt_and_legacy_gaps_only_shrink():
    operations = get(ASSISTANT_OPERATIONS)
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    legacy = {(row["method"], row["path"]) for row in baseline}
    assert len(legacy) == len(baseline)
    assert all(
        row["method"] in WRITE_METHODS
        and row["path"].startswith("/api/")
        and row["path"] in row["reason"]
        and row["reason"].strip()
        for row in baseline
    )

    unbound = set()
    for path, route in _route_entries(app.routes):
        extra = route.openapi_extra or {}
        operation_id = extra.get("x-novelcraft-operation-id")
        exemption = extra.get("x-novelcraft-operation-exemption")
        assert not (operation_id and exemption), f"{path} has conflicting route markers"
        if operation_id:
            assert operation_id in operations, f"{path} references unknown operation"
        if exemption is not None:
            assert isinstance(exemption, str) and len(exemption.strip()) >= 20
        for method in (route.methods or set()) & WRITE_METHODS:
            if not operation_id and not exemption:
                unbound.add((method, path))

    additions = sorted(unbound - legacy)
    assert not additions, (
        "new unbound write routes require an operation ID or explicit exemption:\n"
        + "\n".join(f"{method} {path}" for method, path in additions)
    )


def test_route_adapter_handles_included_and_late_routes_without_changing_openapi():
    probe = FastAPI()
    initial = APIRouter(prefix="/api/probe")

    @initial.post(
        "/bound", openapi_extra={"x-novelcraft-operation-id": "project.add_task"}
    )
    async def bound():
        return {"ok": True}

    @initial.post("/unbound")
    async def unbound():
        return {"ok": True}

    probe.include_router(initial)
    expected_openapi = probe.openapi()
    _install_operation_trace_route_adapters(probe)
    _install_operation_trace_route_adapters(probe)
    assert probe.openapi() == expected_openapi

    late = APIRouter(prefix="/api/late")

    @late.post("/bound", openapi_extra={"x-novelcraft-operation-id": "project.add_task"})
    async def late_bound():
        return {"ok": True}

    probe.include_router(late)
    _install_operation_trace_route_adapters(probe)
    probe.openapi_schema = None
    assert (
        probe.openapi()["paths"]["/api/late/bound"]["post"]
        ["x-novelcraft-operation-id"]
        == "project.add_task"
    )

    included = [
        context
        for branch in probe.routes
        if (effective_routes := getattr(branch, "effective_route_contexts", None))
        for context in effective_routes()
    ]
    assert (
        sum(bool(getattr(route, "_trace_adapter_installed", False)) for route in included)
        == 2
    )
    assert all(
        not getattr(route, "_trace_adapter_installed", False)
        for route in included
        if route.path == "/api/probe/unbound"
    )
    with TestClient(probe) as client:
        assert client.post("/api/probe/unbound").json() == {"ok": True}
        assert client.post("/api/probe/bound").json() == {"ok": True}
        assert client.post("/api/late/bound").json() == {"ok": True}
