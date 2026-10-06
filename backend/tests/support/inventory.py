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
REPO_ROOT = BACKEND_ROOT.parent
MODULES_ROOT = BACKEND_ROOT / "modules"
GENERATED_DIR_NAMES = {"build", "dist", "node_modules", "output"}


@cache
def repository_python_files(root: Path = BACKEND_ROOT) -> tuple[Path, ...]:
    """Return the cached, non-hidden Python file inventory under ``root``."""
    paths: list[Path] = []
    for directory, children, filenames in os.walk(root, topdown=True):
        children[:] = sorted(
            name
            for name in children
            if not name.startswith(".")
            and name != "__pycache__"
            and name not in GENERATED_DIR_NAMES
            and not name.endswith(".egg-info")
        )
        base = Path(directory)
        paths.extend(
            base / name
            for name in filenames
            if name.endswith(".py") and not name.startswith(".")
        )
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
    """Select repository-wide test/support Python files, including deploy/tests."""
    root_conftest = BACKEND_ROOT / "conftest.py"
    return tuple(
        path
        for path in repository_python_files(REPO_ROOT)
        if path == root_conftest
        or path.name.startswith("test_")
        or "tests" in path.parts
    )


@cache
def python_source(path: Path) -> str:
    """Read a repository Python file once per pytest process."""
    return path.read_text(encoding="utf-8")


@cache
def python_ast(path: Path) -> ast.Module:
    """Parse a repository Python file once per pytest process."""
    return ast.parse(python_source(path), filename=str(path))
