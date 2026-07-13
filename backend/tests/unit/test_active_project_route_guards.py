"""Static inventory for platform API active-project boundaries."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]

GUARDED_ROUTES = {
    "modules/imports/api.py": {
        "upload_file",
        "list_imports",
        "get_import",
        "submit_deep_import",
        "submit_scene_auto_extraction",
        "submit_world_object_auto_extraction",
        "submit_plot_structure_auto_extraction",
        "resume_deep_import",
        "abandon_deep_import",
    },
    "modules/settings/api.py": {
        "api_get_project_author_prefs",
        "api_put_project_author_prefs",
        "api_reset_project_author_prefs_field",
    },
    "modules/memory/api.py": {
        "get_panorama",
        "list_events",
        "get_entity_timeline",
        "trigger_capture",
        "list_snapshots",
        "trigger_rebuild",
        "get_status",
    },
    "modules/rag/api.py": {
        "create_rag_chunk",
        "list_rag_chunks",
        "retrieve_chunks",
        "rebuild_rag_index",
        "retry_embeddings",
    },
    "infrastructure/tasks/api.py": {
        "submit_task",
        "get_task_status",
        "cancel_task",
        "retry_task",
    },
}

EXEMPT_ROUTES = {
    "modules/settings/api.py": {
        "api_get_global_llm_defaults",
        "api_put_global_llm_defaults",
        "api_get_global_author_prefs",
        "api_put_global_author_prefs",
        "api_list_projects_using_defaults",
        "api_refresh_settings",
    },
    "modules/rag/api.py": {
        "get_rag_metrics",
        "prewarm_rag_embedding",
        "split_text",
    },
}


def _local_call_graph(path: Path) -> dict[str, set[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    graph: dict[str, set[str]] = {}
    for name, function in functions.items():
        calls: set[str] = set()
        for node in ast.walk(function):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name):
                calls.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                calls.add(node.func.attr)
        graph[name] = calls
    return graph


def _reaches_guard(graph: dict[str, set[str]], entrypoint: str) -> bool:
    pending = [entrypoint]
    visited: set[str] = set()
    while pending:
        name = pending.pop()
        if name in visited:
            continue
        visited.add(name)
        calls = graph.get(name, set())
        if "_require_active_project" in calls:
            return True
        pending.extend(calls & graph.keys())
    return False


@pytest.mark.parametrize(
    ("relative_path", "entrypoint"),
    [
        (relative_path, entrypoint)
        for relative_path, entrypoints in GUARDED_ROUTES.items()
        for entrypoint in sorted(entrypoints)
    ],
)
def test_project_scoped_platform_routes_reach_active_project_guard(
    relative_path: str,
    entrypoint: str,
) -> None:
    graph = _local_call_graph(BACKEND_ROOT / relative_path)
    assert entrypoint in graph
    assert _reaches_guard(graph, entrypoint)


@pytest.mark.parametrize(
    ("relative_path", "entrypoint"),
    [
        (relative_path, entrypoint)
        for relative_path, entrypoints in EXEMPT_ROUTES.items()
        for entrypoint in sorted(entrypoints)
    ],
)
def test_global_platform_routes_remain_explicitly_guard_exempt(
    relative_path: str,
    entrypoint: str,
) -> None:
    graph = _local_call_graph(BACKEND_ROOT / relative_path)
    assert entrypoint in graph
    assert not _reaches_guard(graph, entrypoint)
