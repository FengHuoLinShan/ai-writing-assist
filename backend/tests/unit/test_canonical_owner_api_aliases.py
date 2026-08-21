"""Canonical owner routes must be the same endpoints as one-release aliases."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from fastapi.routing import APIRoute

from app.main import app


def _iter_routes(
    routes: list[Any],
    prefix: str = "",
) -> Iterator[tuple[str, str, APIRoute]]:
    for route in routes:
        if isinstance(route, APIRoute):
            for method in route.methods or set():
                yield method, f"{prefix}{route.path}", route
            continue
        original_router = getattr(route, "original_router", None)
        if original_router is None:
            continue
        include_context = getattr(route, "include_context", None)
        nested_prefix = str(getattr(include_context, "prefix", "") or "")
        yield from _iter_routes(original_router.routes, prefix + nested_prefix)


def _route_index() -> dict[tuple[str, str], APIRoute]:
    return {
        (method, path): route
        for method, path, route in _iter_routes(app.routes)
    }


def _alias_pairs() -> list[tuple[str, str, str]]:
    routes = _route_index()
    pairs: list[tuple[str, str, str]] = []
    for method, path in routes:
        if path.startswith("/api/rag/"):
            pairs.append(
                (method, path, path.replace("/api/rag", "/api/evidence/indexing", 1))
            )
        elif path.startswith("/api/context/"):
            pairs.append(
                (
                    method,
                    path,
                    path.replace("/api/context", "/api/evidence/compilation", 1),
                )
            )
        elif path == "/api/settings/projects-using-defaults":
            pairs.append(
                (method, path, "/api/account/settings/projects-using-defaults")
            )
        elif path.startswith("/api/settings/projects/{project_id}/author-preferences"):
            pairs.append(
                (
                    method,
                    path,
                    path.replace("/api/settings/projects", "/api/projects", 1),
                )
            )
        elif path.startswith("/api/settings/"):
            route = routes[(method, path)]
            if route.endpoint.__module__ == "modules.account.settings_api":
                pairs.append(
                    (
                        method,
                        path,
                        path.replace("/api/settings", "/api/account/settings", 1),
                    )
                )
    return sorted(pairs)


def _dependency_calls(route: APIRoute) -> list[Any]:
    return [dependency.call for dependency in route.dependant.dependencies]


def _normalized_operation(operation: dict[str, Any]) -> dict[str, Any]:
    def normalize(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: normalize(item)
                for key, item in value.items()
                if key not in {"operationId", "tags", "title"}
            }
        if isinstance(value, list):
            return [normalize(item) for item in value]
        return value

    return normalize(operation)


def test_canonical_and_compatibility_paths_share_endpoints_and_wire_contracts() -> None:
    routes = _route_index()
    pairs = _alias_pairs()
    assert len(pairs) == 47

    for method, legacy_path, canonical_path in pairs:
        legacy = routes[(method, legacy_path)]
        canonical = routes[(method, canonical_path)]
        assert canonical.endpoint is legacy.endpoint, (
            method,
            legacy_path,
            canonical_path,
        )
        assert canonical.response_model is legacy.response_model
        assert canonical.status_code == legacy.status_code
        assert canonical.response_class is legacy.response_class
        assert _dependency_calls(canonical) == _dependency_calls(legacy)


def test_canonical_and_compatibility_openapi_operations_are_wire_equivalent() -> None:
    document = app.openapi()
    pairs = _alias_pairs()

    for method, legacy_path, canonical_path in pairs:
        legacy = document["paths"][legacy_path][method.lower()]
        canonical = document["paths"][canonical_path][method.lower()]
        assert _normalized_operation(canonical) == _normalized_operation(legacy), (
            method,
            legacy_path,
            canonical_path,
        )
