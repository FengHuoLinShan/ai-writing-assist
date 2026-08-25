"""Cached repository source and AST inventory for structural test gates.

The repository is immutable during a pytest run.  Caching the closed file list,
source text, and parsed trees lets independent policy tests keep their own
assertions and file filters without repeatedly walking and parsing the tree.
"""

from __future__ import annotations

import ast
import os
from functools import cache
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
MODULES_ROOT = BACKEND_ROOT / "modules"


@cache
def repository_python_files() -> tuple[Path, ...]:
    """Return the cached, non-hidden Python file inventory for the backend."""
    paths: list[Path] = []
    for directory, children, filenames in os.walk(BACKEND_ROOT, topdown=True):
        children[:] = sorted(
            name
            for name in children
            if not name.startswith(".") and name != "__pycache__"
        )
        root = Path(directory)
        paths.extend(root / name for name in filenames if name.endswith(".py"))
    return tuple(sorted(paths))


def module_python_files(*, include_tests: bool = False) -> tuple[Path, ...]:
    """Select module Python files from the shared repository inventory."""
    return tuple(
        path
        for path in repository_python_files()
        if path.is_relative_to(MODULES_ROOT)
        and (
            include_tests
            or "tests" not in path.relative_to(MODULES_ROOT).parts
        )
    )


def production_python_files() -> tuple[Path, ...]:
    """Select production files while excluding every pytest support surface."""
    return tuple(
        path
        for path in repository_python_files()
        if "tests" not in path.relative_to(BACKEND_ROOT).parts
        and path.name != "conftest.py"
        and not path.name.startswith("test_")
    )


def test_python_files() -> tuple[Path, ...]:
    """Select root conftest and all test/support Python files."""
    root_conftest = BACKEND_ROOT / "conftest.py"
    return tuple(
        path
        for path in repository_python_files()
        if path == root_conftest
        or path.name.startswith("test_")
        or "tests" in path.relative_to(BACKEND_ROOT).parts
    )


@cache
def python_source(path: Path) -> str:
    """Read a repository Python file once per pytest process."""
    return path.read_text(encoding="utf-8")


@cache
def python_ast(path: Path) -> ast.Module:
    """Parse a repository Python file once per pytest process."""
    return ast.parse(python_source(path), filename=str(path))
