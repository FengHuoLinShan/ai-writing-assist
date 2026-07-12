"""Structural guards for the shared pytest harness."""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
MODULES_ROOT = BACKEND_ROOT / "modules"


def _python_test_files() -> list[Path]:
    return sorted(
        path
        for path in BACKEND_ROOT.rglob("*.py")
        if path.name.startswith("test_")
        or "tests" in path.relative_to(BACKEND_ROOT).parts
    )


def _fixture_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for decorator in node.decorator_list:
            fixture_call = decorator if isinstance(decorator, ast.Call) else None
            fixture_ref = fixture_call.func if fixture_call else decorator
            is_fixture = (
                isinstance(fixture_ref, ast.Name) and fixture_ref.id == "fixture"
            ) or (
                isinstance(fixture_ref, ast.Attribute) and fixture_ref.attr == "fixture"
            )
            if not is_fixture:
                continue
            public_name = node.name
            if fixture_call:
                for keyword in fixture_call.keywords:
                    if (
                        keyword.arg == "name"
                        and isinstance(keyword.value, ast.Constant)
                        and isinstance(keyword.value.value, str)
                    ):
                        public_name = keyword.value.value
            names.add(public_name)
    return names


def test_every_module_test_directory_is_a_package() -> None:
    test_directories = sorted(
        path for path in MODULES_ROOT.glob("*/tests") if path.is_dir()
    )

    assert test_directories
    missing = [path for path in test_directories if not (path / "__init__.py").is_file()]
    assert missing == []


def test_tests_do_not_import_conftest_as_python_module() -> None:
    violations: list[str] = []

    def is_conftest_module(module: str | None) -> bool:
        return bool(module and (module == "conftest" or module.endswith(".conftest")))

    for path in _python_test_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and is_conftest_module(node.module):
                violations.append(f"{path.relative_to(BACKEND_ROOT)}:{node.lineno}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if is_conftest_module(alias.name):
                        violations.append(
                            f"{path.relative_to(BACKEND_ROOT)}:{node.lineno}"
                        )

    assert violations == []


def test_module_conftests_do_not_shadow_root_fixtures() -> None:
    root_fixture_names = _fixture_names(BACKEND_ROOT / "conftest.py")
    violations: dict[str, list[str]] = {}

    for path in sorted(MODULES_ROOT.glob("*/tests/conftest.py")):
        overlaps = sorted(root_fixture_names & _fixture_names(path))
        if overlaps:
            violations[str(path.relative_to(BACKEND_ROOT))] = overlaps

    assert violations == {}


def test_root_conftest_registers_all_orm_metadata() -> None:
    tree = ast.parse(
        (BACKEND_ROOT / "conftest.py").read_text(encoding="utf-8"),
        filename="conftest.py",
    )
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    required_modules = {
        "infrastructure.tasks.models",
        "modules.context.models",
        "modules.imports.models",
        "modules.memory.models",
        "modules.outline.models",
        "modules.project.models",
        "modules.rag.models",
        "modules.settings.models",
        "modules.world.map_models",
        "modules.world.models",
        "modules.writing.models",
    }

    assert required_modules <= imported_modules


def test_default_pytest_layer_keeps_strict_external_markers() -> None:
    config = tomllib.loads((BACKEND_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    pytest_config = config["tool"]["pytest"]["ini_options"]
    markers = {entry.split(":", maxsplit=1)[0] for entry in pytest_config["markers"]}
    addopts = pytest_config["addopts"]

    assert "--strict-markers" in addopts
    assert {"e2e", "real_llm", "external_data"} <= markers
    marker_expression = addopts[addopts.index("-m") + 1]
    for marker in ("e2e", "real_llm", "external_data"):
        assert f"not {marker}" in marker_expression
