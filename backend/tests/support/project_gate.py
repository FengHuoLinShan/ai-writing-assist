"""Structural assertions shared by project-scoped API route tests."""

from __future__ import annotations

import ast
import inspect
import textwrap

from fastapi import APIRouter
from fastapi.routing import APIRoute


def routes_without_leading_active_project_guard(router: APIRouter) -> list[str]:
    """Return endpoint names that do not start with the active-project guard."""
    unguarded: list[str] = []
    for route in router.routes:
        if not isinstance(route, APIRoute):
            continue
        tree = ast.parse(textwrap.dedent(inspect.getsource(route.endpoint)))
        function = tree.body[0]
        if not isinstance(function, ast.AsyncFunctionDef | ast.FunctionDef):
            unguarded.append(route.name)
            continue
        statements = function.body
        if statements and isinstance(statements[0], ast.Expr):
            if isinstance(statements[0].value, ast.Constant):
                statements = statements[1:]
        first = statements[0] if statements else None
        guarded = (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Await)
            and isinstance(first.value.value, ast.Call)
            and isinstance(first.value.value.func, ast.Name)
            and first.value.value.func.id == "require_active_project"
        )
        if not guarded:
            unguarded.append(route.name)
    return unguarded
