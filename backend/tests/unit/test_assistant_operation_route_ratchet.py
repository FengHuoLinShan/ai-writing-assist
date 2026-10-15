"""Every new write route is bound or explicitly exempt; legacy gaps only shrink."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import BaseModel
from starlette.requests import Request

from app.main import (
    _install_operation_trace_route_adapters,
    _trace_route_arguments,
    app,
)
from core.container import get
from core.service_keys import ASSISTANT_OPERATIONS

A1_BOUND_ROUTES = {
    "/api/world/revision-notes": "world.history.set_note",
    "/api/world/entities/{entity_id}/rollback-by-revision": (
        "world.entity.restore_revision"
    ),
    "/api/world/entities/fusion-suggestions/apply": "world.entity.fuse",
    "/api/outline/scenes/reorder": "story.scene.reorder",
    "/api/outline/scene-workbench/merge": "story.scene.merge",
    "/api/writing/drafts/{draft_id}/editorial-ready": (
        "writing.chapter.mark_editorial_ready"
    ),
    "/api/writing/comments/{comment_id}": "writing.comment.set_status",
    "/api/evolution/reading/preview": "evolution.prepare_reading",
    "/api/assistant/operation-http/world/entity/transition-type": (
        "world.entity.transition_type"
    ),
    "/api/assistant/operation-http/story/scene/split": "story.scene.split",
    "/api/assistant/operation-http/writing/chapter/rename": "writing.chapter.rename",
    "/api/assistant/operation-http/writing/chapter/check-conflicts": (
        "writing.conflict_check.create"
    ),
    "/api/assistant/operation-http/evidence/search": "evidence.project.search",
    "/api/assistant/operation-http/evidence/read": "evidence.source.read",
    "/api/assistant/operation-http/evidence/inspect": "evidence.knowledge.preview_scope",
}
A1_PREVIEW_ROUTES = {
    "/api/assistant/operation-http/previews/world/entity/transition-type": (
        "world.entity.transition_type"
    ),
    "/api/assistant/operation-http/previews/story/scene/split": "story.scene.split",
    "/api/assistant/operation-http/previews/writing/chapter/rename": (
        "writing.chapter.rename"
    ),
    "/api/assistant/operation-http/previews/writing/chapter/check-conflicts": (
        "writing.conflict_check.create"
    ),
}
C2_BOUND_ROUTES = {
    "/api/assistant/operation-http/evidence/object-dossier-brief": (
        "evidence.object_dossier_brief.read"
    ),
}
C2_PREVIEW_ROUTES = {
    "/api/assistant/operation-http/previews/story/character-card": (
        "story.character_card.generate"
    ),
    "/api/assistant/operation-http/previews/story/reactions": ("story.reaction.generate"),
}
C4_DIRECTOR_ROUTES = {
    "/api/story/scenes/director/budget-preview": ("story.scene_director.preview", "POST"),
    "/api/story/scenes/{scene_id}/director": ("story.scene_director.start", "POST"),
    "/api/story/director/roots/{root_id}/budget-preview": (
        "story.scene_director.continue_preview",
        "POST",
    ),
    "/api/story/director/roots/{root_id}/branches": (
        "story.scene_director.continue",
        "POST",
    ),
    "/api/story/director/roots/{root_id}/advance": (
        "story.scene_director.advance",
        "POST",
    ),
    "/api/story/scenes/{scene_id}/director/history": (
        "story.scene_director.history",
        "GET",
    ),
    "/api/story/director/rounds/{round_id}/consistency": (
        "story.scene_director.check_consistency",
        "GET",
    ),
    "/api/story/director/rounds/{round_id}/references": (
        "story.scene_director.save_reference",
        "POST",
    ),
    "/api/story/director/rounds/{round_id}/world-candidates": (
        "story.scene_director.transfer_world_candidate",
        "POST",
    ),
}

C5_WORLD_PROGRESSION_ROUTES = {
    "/api/story/world-progression/history": (
        "story.world_progression.history",
        "GET",
    ),
    "/api/story/world-progression/compare": (
        "story.world_progression.compare",
        "POST",
    ),
    "/api/story/world-progression/budget-preview": (
        "story.world_progression.preview",
        "POST",
    ),
    "/api/story/world-progression/roots": (
        "story.world_progression.start",
        "POST",
    ),
    "/api/story/world-progression/roots/{root_id}/steps": (
        "story.world_progression.advance",
        "POST",
    ),
    "/api/story/world-progression/roots/{root_id}/branches/{branch_id}/resume": (
        "story.world_progression.resume",
        "POST",
    ),
    "/api/story/world-progression/hooks/preview": (
        "story.world_progression.preview_hook",
        "POST",
    ),
    "/api/story/world-progression/hooks/adopt": (
        "story.world_progression.adopt_hook",
        "POST",
    ),
    (
        "/api/story/world-progression/roots/{root_id}/branches/{branch_id}"
        "/continuous-authorization"
    ): (
        "story.world_progression.read_continuous_authorization",
        "GET",
    ),
}
C0_DOSSIER_INTERCHANGE_ROUTES = (
    (
        "/api/world/dossier-templates/{profile_type}/author",
        "world.dossier.template.borrowed.read",
        "GET",
    ),
    (
        "/api/world/dossier-templates/{profile_type}/author",
        "world.dossier.template.borrowed.edit",
        "PUT",
    ),
    (
        "/api/world/entities/{entity_id}/dossier/manifest/preview",
        "world.dossier.manifest.preview",
        "POST",
    ),
    (
        "/api/world/entities/{entity_id}/dossier/manifest/apply",
        "world.dossier.manifest.apply",
        "POST",
    ),
)

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


def test_a1_http_routes_bind_each_catalog_operation_with_declared_trace_fields():
    operations = get(ASSISTANT_OPERATIONS)
    routes = dict(_route_entries(app.routes))
    assert len(A1_BOUND_ROUTES) == 15
    for path, operation_id in A1_BOUND_ROUTES.items():
        extra = routes[path].openapi_extra or {}
        assert extra.get("x-novelcraft-operation-id") == operation_id
        assert set(extra.get("x-novelcraft-operation-trace-fields") or {}) == set(
            operations[operation_id].schema.model_fields
        )
    for path, operation_id in A1_PREVIEW_ROUTES.items():
        extra = routes[path].openapi_extra or {}
        assert extra.get("x-novelcraft-operation-id") == operation_id
        assert extra.get("x-novelcraft-operation-phase") == "prepare"
        assert "x-novelcraft-operation-confirmation-field" not in extra


def test_c2_http_routes_bind_read_and_previews_without_enqueueing():
    operations = get(ASSISTANT_OPERATIONS)
    routes = dict(_route_entries(app.routes))
    for path, operation_id in (C2_BOUND_ROUTES | C2_PREVIEW_ROUTES).items():
        extra = routes[path].openapi_extra or {}
        assert extra.get("x-novelcraft-operation-id") == operation_id
        assert set(extra.get("x-novelcraft-operation-trace-fields") or {}) == set(
            operations[operation_id].schema.model_fields
        )
        if path in C2_PREVIEW_ROUTES:
            assert extra.get("x-novelcraft-operation-phase") == "prepare"
            assert "x-novelcraft-operation-confirmation-field" not in extra


def test_c4_director_http_routes_bind_the_frozen_catalog():
    operations = get(ASSISTANT_OPERATIONS)
    routes = dict(_route_entries(app.routes))
    assert len(C4_DIRECTOR_ROUTES) == 9
    for path, (operation_id, method) in C4_DIRECTOR_ROUTES.items():
        route = routes[path]
        extra = route.openapi_extra or {}
        assert method in route.methods
        assert extra.get("x-novelcraft-operation-id") == operation_id
        assert set(extra.get("x-novelcraft-operation-trace-fields") or {}) == set(
            operations[operation_id].schema.model_fields
        )
        if method == "POST":
            fields = extra["x-novelcraft-operation-trace-fields"]
            assert all(
                source.startswith("data.")
                for field, source in fields.items()
                if field != "round_id"
            )
            if "round_id" in fields:
                assert path.endswith("/rounds/{round_id}/world-candidates")
                assert fields["round_id"] == "round_id"
    for path, route in routes.items():
        if path.startswith("/api/story/director/") and path not in C4_DIRECTOR_ROUTES:
            assert (route.openapi_extra or {}).get("x-novelcraft-operation-exemption")


def test_c5_and_c0_routes_bind_new_catalog_without_unmarked_write_paths():
    operations = get(ASSISTANT_OPERATIONS)
    routes = {
        (method, path): route
        for path, route in _route_entries(app.routes)
        for method in route.methods or ()
    }
    assert len(C5_WORLD_PROGRESSION_ROUTES) == 9
    for path, (operation_id, method) in C5_WORLD_PROGRESSION_ROUTES.items():
        route = routes[(method, path)]
        extra = route.openapi_extra or {}
        assert extra.get("x-novelcraft-operation-id") == operation_id
        assert set(extra.get("x-novelcraft-operation-trace-fields") or {}) == set(
            operations[operation_id].schema.model_fields
        )
    for path, operation_id, method in C0_DOSSIER_INTERCHANGE_ROUTES:
        route = routes[(method, path)]
        assert (route.openapi_extra or {}).get(
            "x-novelcraft-operation-id"
        ) == operation_id
        assert operation_id in operations
    for (method, path), route in routes.items():
        if path.startswith("/api/story/world-progression/") and (
            method,
            path,
        ) not in {
            (bound_method, bound_path)
            for bound_path, (_, bound_method) in C5_WORLD_PROGRESSION_ROUTES.items()
        }:
            assert (route.openapi_extra or {}).get("x-novelcraft-operation-exemption")


def test_trace_extracts_declared_pydantic_request_fields_without_raw_request():
    class Body(BaseModel):
        query: str
        secret: str

    body = Body(query="safe query", secret="private manuscript")
    raw_request = Request({"type": "http", "method": "POST", "path": "/"})
    values = {"request": body, "raw": raw_request, "novel_id": "novel"}
    assert _trace_route_arguments(values, trace_fields={"query": "request.query"}) == {
        "query": "safe query"
    }
    assert _trace_route_arguments({"request": raw_request}) == {}


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
        probe.openapi()["paths"]["/api/late/bound"]["post"]["x-novelcraft-operation-id"]
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


def test_director_candidate_route_binds_r3_confirmation_and_exact_trace_fields():
    operation_id = "story.scene_director.transfer_world_candidate"
    operation = get(ASSISTANT_OPERATIONS)[operation_id]
    path = "/api/story/director/rounds/{round_id}/world-candidates"
    route = dict(_route_entries(app.routes))[path]
    extra = route.openapi_extra or {}
    assert extra["x-novelcraft-operation-id"] == operation_id
    assert extra["x-novelcraft-operation-phase"] == "execute"
    assert extra["x-novelcraft-operation-confirmation-field"] == "data.confirmed"
    assert set(extra["x-novelcraft-operation-trace-fields"]) == set(
        operation.schema.model_fields
    )
    assert extra["x-novelcraft-operation-trace-fields"]["round_id"] == "round_id"
