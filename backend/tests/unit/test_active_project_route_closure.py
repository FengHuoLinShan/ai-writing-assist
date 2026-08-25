"""Closed inventory for active-project guards on every scoped API route."""

from __future__ import annotations

import ast
import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi.routing import APIRoute

from app.main import app
from tests.support.inventory import python_ast

PROJECT_ID_NAMES = {"novel_id", "project_id"}
GUARD_CALLS = {
    "require_active_project",
    "_require_active_project",
    "_require_active_project_exclusive",
    "_require_task_owner_active_project",
}
PRE_GUARD_SAFE_CALLS = {"HTTPException", "get_settings"}
DERIVED_SCOPED_ROUTES = {
    "POST /api/imports/deep/abandon": (
        "_require_task_owner_active_project",
        "abandon_deep_import",
    ),
    "POST /api/imports/deep/resume": (
        "_require_task_owner_active_project",
        "resume_deep_import",
    ),
    "POST /api/tasks": ("_require_active_project", "enqueue_task"),
}
PROJECT_LIFECYCLE_EXEMPTIONS = {
    "DELETE /api/projects/{project_id}",
    "DELETE /api/projects/{project_id}/permanent",
    "GET /api/projects/recycle-bin",
    "POST /api/projects/{project_id}/restore",
    "POST /api/projects/recycle-bin/permanent-delete",
}
GLOBAL_EXEMPTIONS = {
    "GET /api/account/settings/author-preferences",
    "GET /api/account/settings/llm-defaults",
    "GET /api/account/settings/projects-using-defaults",
    "GET /api/evidence/indexing/metrics",
    "POST /api/account/settings/refresh",
    "POST /api/evidence/indexing/chunks/split",
    "POST /api/evidence/indexing/prewarm",
    "PUT /api/account/settings/author-preferences",
    "PUT /api/account/settings/llm-defaults",
}

# Project owns this aggregate, so these first calls are its active-object boundary.
# Keeping the route key in this map makes a newly added project route fail closed.
PROJECT_OWNED_ACTIVE_BOUNDARIES = {
    "DELETE /api/projects/{project_id}/author-preferences/field/{field_name}": (
        "reset_project_author_preferences_field"
    ),
    "DELETE /api/projects/{project_id}/llm-settings/field/{field_name}": (
        "reset_llm_settings_field"
    ),
    "GET /api/projects/{project_id}": "get_project",
    "GET /api/projects/{project_id}/effective-author-preferences": (
        "get_effective_author_prefs"
    ),
    "GET /api/projects/{project_id}/effective-llm-settings": (
        "get_effective_llm_settings"
    ),
    "GET /api/projects/{project_id}/llm-settings": "get_llm_settings",
    "GET /api/projects/{project_id}/author-preferences": (
        "get_project_author_preferences"
    ),
    "GET /api/projects/{project_id}/workspace-summary": "get_summary",
    "POST /api/projects/{project_id}/smart-dedup/apply": "get_project",
    "POST /api/projects/{project_id}/smart-dedup/scan": "get_project",
    "PUT /api/projects/{project_id}": "update_project",
    "PUT /api/projects/{project_id}/llm-settings": "update_llm_settings",
    "PUT /api/projects/{project_id}/author-preferences": (
        "upsert_project_author_preferences"
    ),
}


@dataclass(frozen=True)
class FunctionSummary:
    has_guard: bool
    guard_before_business: bool
    first_business_call: str | None


@dataclass(frozen=True)
class ModuleAst:
    functions: dict[str, ast.AsyncFunctionDef | ast.FunctionDef]


def _route_key(route: APIRoute) -> str:
    method = next(iter(route.methods or {""}))
    return f"{method} {route.path}"


def _field_annotation(field: Any) -> Any:
    return getattr(getattr(field, "field_info", None), "annotation", None)


def _body_declares_project_id(route: APIRoute) -> bool:
    for field in route.dependant.body_params:
        if field.name in PROJECT_ID_NAMES:
            return True
        annotation = _field_annotation(field)
        model_fields = getattr(annotation, "model_fields", {})
        if PROJECT_ID_NAMES & set(model_fields):
            return True
    return False


def _is_declared_project_scoped(route: APIRoute) -> bool:
    signature_names = set(inspect.signature(route.endpoint).parameters)
    path_names = {name for name in PROJECT_ID_NAMES if f"{{{name}}}" in route.path}
    return bool(
        PROJECT_ID_NAMES & signature_names
        or path_names
        or _body_declares_project_id(route)
    )


def _all_api_routes() -> dict[str, APIRoute]:
    def iter_routes(routes: list[Any], prefix: str = ""):
        for route in routes:
            if isinstance(route, APIRoute):
                method = next(iter(route.methods or {""}))
                yield f"{method} {prefix}{route.path}", route
                continue
            original_router = getattr(route, "original_router", None)
            if original_router is not None:
                include_context = getattr(route, "include_context", None)
                nested_prefix = str(getattr(include_context, "prefix", "") or "")
                yield from iter_routes(original_router.routes, prefix + nested_prefix)

    return dict(iter_routes(app.routes))


def test_long_ai_compatibility_routes_are_deprecated_in_openapi() -> None:
    document = app.openapi()
    replacements = [
        (
            "/api/world/generation-center/suggestions",
            "/api/world/generation-center/suggestions/task",
        ),
        (
            "/api/outline/scene-workbench/fusion/preview",
            "/api/outline/scene-workbench/fusion/preview-task",
        ),
        (
            "/api/writing/conflict-checks/{check_id}/ai-review",
            "/api/writing/conflict-checks/{check_id}/ai-review-task",
        ),
        (
            "/api/writing/conflict-check-items/{item_id}/ai-suggestion",
            "/api/writing/conflict-check-items/{item_id}/ai-suggestion-task",
        ),
    ]
    for legacy_path, task_path in replacements:
        assert document["paths"][legacy_path]["post"]["deprecated"] is True
        assert "202" in document["paths"][task_path]["post"]["responses"]


def _module_ast(source_file: str) -> ModuleAst:
    tree = python_ast(Path(source_file))
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
    }
    return ModuleAst(functions=functions)


def _endpoint_node(
    route: APIRoute,
) -> tuple[ModuleAst, ast.AsyncFunctionDef | ast.FunctionDef]:
    source_file = inspect.getsourcefile(route.endpoint)
    assert source_file is not None, _route_key(route)
    module_ast = _module_ast(source_file)
    node = module_ast.functions.get(route.endpoint.__name__)
    assert node is not None, _route_key(route)
    return module_ast, node


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _summarize_function(
    module_ast: ModuleAst,
    function: ast.AsyncFunctionDef | ast.FunctionDef,
    *,
    visiting: frozenset[str] = frozenset(),
) -> FunctionSummary:
    calls = sorted(
        (
            node
            for statement in function.body
            for node in ast.walk(statement)
            if isinstance(node, ast.Call)
        ),
        key=lambda node: (node.lineno, node.col_offset),
    )
    first_guard: tuple[int, int] | None = None
    first_business: tuple[int, int, str] | None = None
    for call in calls:
        name = _call_name(call)
        position = (call.lineno, call.col_offset)
        if name in GUARD_CALLS:
            first_guard = min(first_guard, position) if first_guard else position
            continue
        if name in PRE_GUARD_SAFE_CALLS:
            continue
        helper = module_ast.functions.get(name or "")
        if helper is not None and name not in visiting:
            summary = _summarize_function(
                module_ast,
                helper,
                visiting=visiting | {function.name},
            )
            if summary.has_guard and summary.guard_before_business:
                first_guard = min(first_guard, position) if first_guard else position
                # The helper proves its own guard-before-business ordering, so
                # the wrapper call is one guarded unit rather than an unguarded
                # business call at the same source position.
                continue
        # Be conservative: any other runtime call may read, write, enqueue, or
        # expose data. Harmless argument normalization on the guard's own line
        # sorts after the outer guard call and therefore remains allowed.
        candidate = (*position, name or "<call>")
        first_business = min(first_business, candidate) if first_business else candidate

    return FunctionSummary(
        has_guard=first_guard is not None,
        guard_before_business=(
            first_guard is not None
            and (first_business is None or first_guard < first_business[:2])
        ),
        first_business_call=first_business[2] if first_business else None,
    )


def _has_pre_endpoint_guard(route: APIRoute) -> bool:
    pending = list(route.dependant.dependencies)
    while pending:
        dependency = pending.pop()
        pending.extend(dependency.dependencies)
        call = dependency.call
        if call is None:
            continue
        source_file = inspect.getsourcefile(call)
        if source_file is None:
            continue
        module_ast = _module_ast(source_file)
        function = module_ast.functions.get(getattr(call, "__name__", ""))
        if function is None:
            continue
        if _summarize_function(module_ast, function).guard_before_business:
            return True
    return False


def _call_precedes(
    function: ast.AsyncFunctionDef | ast.FunctionDef,
    first_name: str,
    second_name: str,
) -> bool:
    positions: dict[str, list[tuple[int, int]]] = {}
    for statement in function.body:
        for call in ast.walk(statement):
            if not isinstance(call, ast.Call):
                continue
            name = _call_name(call)
            if name is not None:
                positions.setdefault(name, []).append((call.lineno, call.col_offset))
    return bool(
        positions.get(first_name)
        and positions.get(second_name)
        and min(positions[first_name]) < min(positions[second_name])
    )


def _summary_from_source(source: str, function_name: str) -> FunctionSummary:
    tree = ast.parse(source)
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
    }
    module_ast = ModuleAst(functions=functions)
    return _summarize_function(module_ast, functions[function_name])


def test_guard_order_analyzer_rejects_business_before_guard() -> None:
    guarded = _summary_from_source(
        """
async def endpoint(db, novel_id):
    await require_active_project(db, novel_id)
    return await _service.read(db, novel_id)
""",
        "endpoint",
    )
    late = _summary_from_source(
        """
async def endpoint(db, novel_id):
    value = await _service.read(db, novel_id)
    await require_active_project(db, novel_id)
    return value
""",
        "endpoint",
    )

    assert guarded.guard_before_business is True
    assert late.guard_before_business is False


def test_guard_order_analyzer_follows_local_guarded_helpers() -> None:
    summary = _summary_from_source(
        """
async def guarded_helper(db, novel_id):
    await require_active_project(db, novel_id)
    return await _service.read(db, novel_id)

async def endpoint(db, novel_id):
    return await guarded_helper(db, novel_id)
""",
        "endpoint",
    )

    assert summary.guard_before_business is True


def test_active_project_guard_inventory_is_closed() -> None:
    routes = _all_api_routes()
    declared = {
        key for key, route in routes.items() if _is_declared_project_scoped(route)
    }
    scoped = (declared | DERIVED_SCOPED_ROUTES.keys()) - PROJECT_LIFECYCLE_EXEMPTIONS

    # This is a lower-bound drift alarm, not a frozen route count.
    assert len(declared) >= 229
    assert DERIVED_SCOPED_ROUTES.keys() <= routes.keys()
    assert PROJECT_LIFECYCLE_EXEMPTIONS <= routes.keys()
    assert GLOBAL_EXEMPTIONS <= routes.keys()
    assert not (GLOBAL_EXEMPTIONS & declared)

    failures: list[str] = []
    covered_modules: set[str] = set()
    for key in sorted(scoped):
        route = routes[key]
        covered_modules.add(route.endpoint.__module__)
        if _has_pre_endpoint_guard(route):
            continue
        module_ast, function = _endpoint_node(route)
        summary = _summarize_function(module_ast, function)
        if key in DERIVED_SCOPED_ROUTES:
            guard_call, mutation_call = DERIVED_SCOPED_ROUTES[key]
            if _call_precedes(function, guard_call, mutation_call):
                continue
            failures.append(
                f"{key}: derived guard {guard_call!r} does not precede "
                f"mutation {mutation_call!r}"
            )
            continue
        expected_project_boundary = PROJECT_OWNED_ACTIVE_BOUNDARIES.get(key)
        if expected_project_boundary is not None:
            if summary.first_business_call == expected_project_boundary:
                continue
            failures.append(
                f"{key}: expected project boundary {expected_project_boundary!r}, "
                f"got {summary.first_business_call!r}"
            )
            continue
        if not summary.guard_before_business:
            failures.append(
                f"{key}: active-project guard missing or follows first business call "
                f"{summary.first_business_call!r}"
            )

    required_modules = {
        "infrastructure.tasks.api",
        "modules.evidence.compilation.api",
        "modules.imports.api",
        "modules.story.continuity.api",
        "modules.story.outline_state.api",
        "modules.evidence.indexing.api",
        "modules.project.settings_api",
        "modules.world.api",
        "modules.world.map_atlas_api",
        "modules.writing.api",
    }
    assert required_modules <= covered_modules
    assert not failures, "\n" + "\n".join(failures)
