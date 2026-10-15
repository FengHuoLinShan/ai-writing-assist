"""Every new write route is bound or explicitly exempt; legacy gaps only shrink."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.routing import APIRoute

from app.main import app
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
