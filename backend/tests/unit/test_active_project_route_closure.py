"""Closed inventory for active-project guards on every scoped API route."""

from __future__ import annotations

import ast
import inspect
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

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
    "GET /api/projects/{project_id}/editorial-brief": "read_editorial_brief",
    "GET /api/projects/{project_id}/editorial-brief/for-writing": (
        "read_editorial_brief_writing_toggle"
    ),
    "GET /api/projects/{project_id}/author-examples": "read_author_examples",
    "GET /api/projects/{project_id}/author-examples/for-writing": (
        "read_author_examples_writing_toggle"
    ),
    "GET /api/projects/{project_id}/ai-usage": "get_project_ai_usage",
    "GET /api/projects/{project_id}/llm-cost-saving": "read_cost_saving_toggle",
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
    "GET /api/projects/{project_id}/author-tasks": "list_tasks",
    "GET /api/projects/{project_id}/workspace-summary": "get_summary",
    "PATCH /api/projects/{project_id}/author-tasks/{task_id}": "patch_task",
    "POST /api/projects/{project_id}/author-tasks": "create_task",
    "POST /api/projects/{project_id}/smart-dedup/apply": "get_project",
    "POST /api/projects/{project_id}/smart-dedup/scan": "get_project",
    "PUT /api/projects/{project_id}": "update_project",
    "PUT /api/projects/{project_id}/editorial-brief": "save_editorial_brief",
    "PUT /api/projects/{project_id}/editorial-brief/for-writing": (
        "set_editorial_brief_for_writing"
    ),
    "PUT /api/projects/{project_id}/author-examples": "save_author_examples",
    "PUT /api/projects/{project_id}/author-examples/for-writing": (
        "set_author_examples_for_writing"
    ),
    "PUT /api/projects/{project_id}/llm-cost-saving": "set_cost_saving_toggle",
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
    ]
    for legacy_path, task_path in replacements:
        assert document["paths"][legacy_path]["post"]["deprecated"] is True
        assert "202" in document["paths"][task_path]["post"]["responses"]
    for removed_path in (
        "/api/writing/conflict-checks/{check_id}/ai-review",
        "/api/writing/conflict-check-items/{item_id}/ai-suggestion",
    ):
        assert removed_path not in document["paths"]


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
        "modules.world.api.adoption",
        "modules.world.api.aliases",
        "modules.world.api.bible",
        "modules.world.api.canon",
        "modules.world.api.characters",
        "modules.world.api.cocreation",
        "modules.world.api.entities",
        "modules.world.api.events",
        "modules.world.api.generation_center",
        "modules.world.api.history",
        "modules.world.api.knowledge",
        "modules.world.api.library",
        "modules.world.api.prompt_templates",
        "modules.world.api.relations",
        "modules.world.api.revisions",
        "modules.world.api.stress",
        "modules.world.api.suggestions",
        "modules.world.api.validation",
        "modules.world.api.workspace",
        "modules.world.map_atlas_api",
        "modules.writing.api",
    }
    assert required_modules <= covered_modules
    assert not failures, "\n" + "\n".join(failures)


@pytest.mark.parametrize("project_state", ["missing", "foreign", "recycled"])
@pytest.mark.parametrize("trace_enabled", [True, False])
async def test_new_scoped_http_routes_reject_before_trace_or_business_write(
    async_client, db_session, test_project_id, project_state, trace_enabled, monkeypatch
):
    if not trace_enabled:
        from core.config import get_settings
        from modules.assistant import operation_trace_service

        monkeypatch.setattr(
            operation_trace_service,
            "get_settings",
            lambda: replace(get_settings(), assistant_operation_trace_enabled=False),
        )

    from modules.account.context import bind_principal, reset_principal
    from modules.account.contracts import AccountPrincipal
    from modules.account.models import Account
    from modules.assistant.operation_trace_models import (
        AssistantOperationTrace,
        AssistantOperationTraceProjectSalt,
    )
    from modules.project.models import Project
    from modules.world.project_vocabulary_models import ProjectVocabularyTerm

    novel_id = uuid.uuid4() if project_state == "missing" else uuid.UUID(test_project_id)
    token = None
    if project_state == "foreign":
        stranger = Account(id=uuid.uuid4(), status="active", support_code="ROUTE-FOREIGN")
        db_session.add(stranger)
        await db_session.flush()
        token = bind_principal(
            AccountPrincipal(
                account_id=stranger.id,
                status="active",
                identity_type="email",
                support_code=stranger.support_code,
            )
        )
    elif project_state == "recycled":
        project = await db_session.get(Project, novel_id)
        project.deleted_at = datetime.now(UTC)
        await db_session.flush()

    pending_trace_rows = []

    def observe_trace(_session, _context, _instances):
        pending_trace_rows.extend(
            type(row).__name__
            for row in _session.new
            if isinstance(
                row, (AssistantOperationTrace, AssistantOperationTraceProjectSalt)
            )
        )

    event.listen(Session, "before_flush", observe_trace)
    try:
        base = f"/api/world/project-vocabulary/{novel_id}"
        requests = (
            (
                "GET",
                "/api/assistant/operation-traces/aggregate",
                {"params": {"novel_id": str(novel_id)}},
            ),
            (
                "GET",
                "/api/assistant/operation-traces/export",
                {"params": {"novel_id": str(novel_id)}},
            ),
            (
                "GET",
                "/api/assistant/unified-notices",
                {"params": {"novel_id": str(novel_id), "chapter_index": 1}},
            ),
            ("GET", base, {}),
            ("POST", f"{base}/terms", {"json": {"kind": "feature", "name": "合成词条"}}),
            (
                "POST",
                f"/api/world/map-atlas/{novel_id}/spatial-clues/{uuid.uuid4()}/review",
                {
                    "json": {
                        "action": "reject",
                        "expected_fingerprint": "f" * 64,
                        "confirmed": True,
                    }
                },
            ),
        )
        for method, path, options in requests:
            response = await async_client.request(method, path, **options)
            assert response.status_code == 404, (
                project_state,
                method,
                path,
                response.text,
            )
    finally:
        event.remove(Session, "before_flush", observe_trace)
        if token is not None:
            reset_principal(token)

    assert pending_trace_rows == []
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(AssistantOperationTrace)
            .where(AssistantOperationTrace.novel_id == novel_id)
        )
        == 0
    )
    assert await db_session.get(AssistantOperationTraceProjectSalt, novel_id) is None
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(ProjectVocabularyTerm)
            .where(ProjectVocabularyTerm.novel_id == novel_id)
        )
        == 0
    )


async def test_http_terminal_trace_never_opens_a_different_database(
    async_client, db_session, test_project_id, monkeypatch
):
    """A traced 4xx must not use the global pool behind a test DB override."""
    from core import database

    attempted_sessions = []

    def forbidden_session_factory():
        attempted_sessions.append(True)
        raise AssertionError("terminal trace must not open the unrelated pool")

    wrong_engine = object()
    assert wrong_engine is not db_session.get_bind().engine
    monkeypatch.setattr(
        database,
        "get_manager",
        lambda: SimpleNamespace(
            engine=SimpleNamespace(sync_engine=wrong_engine),
            session_factory=forbidden_session_factory,
        ),
    )

    response = await async_client.patch(
        f"/api/world/project-vocabulary/{test_project_id}/terms/{uuid.uuid4()}",
        json={"name": "不存在的词条", "expected_revision_id": str(uuid.uuid4())},
    )

    assert response.status_code == 404
    assert response.headers["x-novelcraft-operation-trace-incomplete"] == "true"
    assert attempted_sessions == []
