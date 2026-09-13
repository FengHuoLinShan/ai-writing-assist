"""Structural guards for the shared pytest harness."""

from __future__ import annotations

import ast
import io
import re
import shlex
import subprocess
import tokenize
import tomllib
from pathlib import Path

import yaml

from tests.support.inventory import (
    production_python_files,
    python_ast,
    python_source,
    repository_python_files,
)
from tests.support.inventory import (
    test_python_files as repository_test_python_files,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
MODULES_ROOT = BACKEND_ROOT / "modules"


def _fixture_names(path: Path) -> set[str]:
    tree = python_ast(path)
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


def test_repository_inventory_caches_files_sources_and_asts() -> None:
    inventory = repository_python_files()
    support_file = BACKEND_ROOT / "tests/support/inventory.py"

    assert inventory is repository_python_files()
    assert support_file in inventory
    assert support_file in repository_test_python_files()
    assert support_file not in production_python_files()
    assert all(
        "__pycache__" not in path.parts
        and not any(part.startswith(".") for part in path.relative_to(BACKEND_ROOT).parts)
        for path in inventory
    )
    assert python_source(support_file) is python_source(support_file)
    assert python_ast(support_file) is python_ast(support_file)


def _unautospecced_patch_calls(source: str, *, filename: str) -> list[int]:
    """Require autospec unless the call documents why this object cannot use it."""
    tree = ast.parse(source, filename=filename)
    comments = {
        token.start[0]: token.string
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type == tokenize.COMMENT
    }
    patch_aliases: set[str] = set()
    mock_aliases: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "unittest.mock":
            patch_aliases.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name == "patch"
            )
        elif isinstance(node, ast.ImportFrom) and node.module == "unittest":
            mock_aliases.update(
                alias.asname or alias.name for alias in node.names if alias.name == "mock"
            )
        elif isinstance(node, ast.Import):
            mock_aliases.update(
                alias.asname
                for alias in node.names
                if alias.name == "unittest.mock" and alias.asname
            )

    def is_patch_call(node: ast.Call) -> bool:
        function = node.func
        if isinstance(function, ast.Name):
            return function.id in patch_aliases
        if not isinstance(function, ast.Attribute):
            return False
        if function.attr == "object":
            function = function.value
        if isinstance(function, ast.Name):
            return function.id in patch_aliases
        return (
            isinstance(function, ast.Attribute)
            and function.attr == "patch"
            and isinstance(function.value, ast.Name)
            and function.value.id in mock_aliases
        )

    violations: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not is_patch_call(node):
            continue
        autospec_values = [
            keyword.value for keyword in node.keywords if keyword.arg == "autospec"
        ]
        if not (
            len(autospec_values) == 1
            and isinstance(autospec_values[0], ast.Constant)
            and autospec_values[0].value is True
        ):
            comment = comments.get(node.end_lineno, "")
            reason = re.search(r"# autospec-exempt: (\S.*)", comment)
            if reason is None:
                violations.append(node.lineno)
    return sorted(violations)


def test_patch_autospec_guard_recognizes_aliases_decorators_and_object_calls() -> None:
    source = """
from unittest.mock import patch as replace
from unittest import mock as unit_mock

@replace("package.decorated")
def decorated(mocked):
    pass

with replace.object(object(), "attribute", autospec=True):
    pass

with unit_mock.patch("package.context", autospec=False):
    pass

with unit_mock.patch.object(object(), "attribute", autospec=True):
    pass
"""

    assert _unautospecced_patch_calls(source, filename="aliases.py") == [5, 12]


def test_all_unittest_patch_calls_use_literal_autospec_true() -> None:
    violations: list[str] = []
    for path in repository_test_python_files():
        relative_path = path.relative_to(BACKEND_ROOT)
        lines = _unautospecced_patch_calls(
            python_source(path),
            filename=str(path),
        )
        violations.extend(f"{relative_path}:{line}" for line in lines)

    assert violations == []


def test_autospec_exception_requires_a_reason_on_the_call() -> None:
    source = """from unittest.mock import patch
patch("native.extension")  # autospec-exempt: native callable has no inspectable signature
patch("package.service")  # autospec-exempt:
patch("package.service")
patch("text # autospec-exempt: not a comment")
"""
    assert _unautospecced_patch_calls(source, filename="exceptions.py") == [3, 4, 5]


def test_every_module_test_directory_is_a_package() -> None:
    test_directories = sorted(
        path
        for path in MODULES_ROOT.glob("*/tests")
        if path.is_dir() and any(path.glob("test_*.py"))
    )

    assert test_directories
    missing = [path for path in test_directories if not (path / "__init__.py").is_file()]
    assert missing == []


def test_tests_do_not_import_conftest_as_python_module() -> None:
    violations: list[str] = []

    def is_conftest_module(module: str | None) -> bool:
        return bool(module and (module == "conftest" or module.endswith(".conftest")))

    for path in repository_test_python_files():
        tree = python_ast(path)
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
    tree = python_ast(BACKEND_ROOT / "conftest.py")
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    required_modules = {
        "infrastructure.tasks.models",
        "modules.evidence.models",
        "modules.imports.models",
        "modules.story.continuity.models",
        "modules.story.outline_state.models",
        "modules.project.models",
        "modules.project.settings_models",
        "modules.account.settings_models",
        "modules.world.map_atlas_models",
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


def test_backend_coverage_policy_excludes_test_code() -> None:
    config = tomllib.loads((BACKEND_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    coverage_config = config["tool"]["coverage"]
    assert set(coverage_config["run"]["source"]) == {
        "app",
        "core",
        "shared",
        "infrastructure",
        "modules",
    }
    assert {
        "*/tests/*",
        "*/tests.py",
        "*/*_test.py",
        "*/test_*.py",
        "*/conftest.py",
    } <= set(coverage_config["run"]["omit"])


def _make_dry_run(target: str, *variables: str) -> str:
    result = subprocess.run(
        ["make", "--no-print-directory", "-n", target, *variables],
        cwd=BACKEND_ROOT.parent,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_automated_backend_quality_targets_use_the_locked_ci_runner() -> None:
    runner = "uv run --locked --extra ci --"
    target_tools = {
        "test": "pytest",
        "test-fast-coverage": "pytest",
        "test-e2e": "pytest",
        "test-postgresql-critical": "pytest",
        "test-deploy": "pytest",
        "lint": "ruff",
        "lint-fix": "ruff",
        "format": "ruff",
        "format-fix": "ruff",
    }

    for target, tool in target_tools.items():
        command = _make_dry_run(target)
        assert command.count(runner) == 1, target
        assert f"cd {BACKEND_ROOT} &&" in command, target
        assert f"{runner} {tool}" in command, target
        assert f"&& {tool}" not in command, target


def test_architecture_docs_rechecks_pr_body_edits() -> None:
    workflow_path = BACKEND_ROOT.parent / ".github/workflows/architecture-docs.yml"
    workflow = yaml.load(
        workflow_path.read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )

    assert workflow["on"]["pull_request"]["types"] == [
        "opened",
        "synchronize",
        "reopened",
        "edited",
    ]
    assert workflow["on"]["push"] == {"branches": ["main"]}


def test_default_test_target_accepts_native_pytest_selection() -> None:
    command = _make_dry_run("test", "TESTS=tests/unit", "ARGS=-x")

    assert "pytest tests/unit --timeout=120 -x" in command


def test_coverage_target_reuses_default_test_layer() -> None:
    default = _make_dry_run("test")
    coverage = _make_dry_run("test-fast-coverage", "TEST_WORKERS=2")

    for flag in (
        " -n 2 --dist=loadscope",
        " --cov=app",
        " --cov=core",
        " --cov=shared",
        " --cov=infrastructure",
        " --cov=modules",
        " --cov-report=term-missing:skip-covered",
    ):
        coverage = coverage.replace(flag, "")
    assert shlex.split(coverage) == shlex.split(default)


def test_timeout_is_not_forced_onto_explicit_acceptance_layers() -> None:
    for target in ("test-e2e", "test-real-llm", "test-manual"):
        command = _make_dry_run(target)
        assert "--timeout" not in command
        assert "--cov" not in command


def test_production_toolchain_uses_pinned_images_and_consistent_versions() -> None:
    repo_root = BACKEND_ROOT.parent
    python_version = (BACKEND_ROOT / ".python-version").read_text().strip()
    node_version = (repo_root / "frontend-console/.node-version").read_text().strip()
    for path, family, version in (
        (BACKEND_ROOT / "Dockerfile", "python", python_version),
        (repo_root / "frontend-console/Dockerfile", "node", node_version),
    ):
        source = path.read_text()
        images = re.findall(r"^FROM (\S+)", source, re.MULTILINE)
        assert images
        assert all(
            re.fullmatch(r"[^@]+:[^@]+@sha256:[0-9a-f]{64}", image) for image in images
        )
        assert any(image.startswith(f"{family}:{version}-") for image in images)
        assert re.search(r"^USER (?!root\b|0\b)\S+", source, re.MULTILINE)

    postgres_images = set()
    for path in (repo_root / ".github/workflows").glob("*.yml"):
        workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
        for job in workflow.get("jobs", {}).values():
            for service in job.get("services", {}).values():
                if "pgvector/pgvector:" in service.get("image", ""):
                    postgres_images.add(service["image"])
            for step in job.get("steps", []):
                options = step.get("with", {})
                if "python-version" in options:
                    assert options["python-version"] == python_version
                if "node-version-file" in options:
                    assert (
                        repo_root / options["node-version-file"]
                    ).read_text().strip() == node_version
    assert len(postgres_images) == 1
    assert all(
        re.fullmatch(r"[^@]+:[^@]+@sha256:[0-9a-f]{64}", image)
        for image in postgres_images
    )
    command = _make_dry_run("test-production-images")
    assert command.count("docker build") == 2
    assert command.count("docker run --rm") == 2
    docker_run_lines = [
        line for line in command.splitlines() if line.startswith("docker run --rm")
    ]
    assert len(docker_run_lines) == 2
    backend_run, frontend_run = docker_run_lines
    assert "--entrypoint sh contract-smoke-backend:fixed-toolchain -ec" in backend_run
    assert "--entrypoint" not in frontend_run
    assert "contract-smoke-frontend:fixed-toolchain sh -ec" in frontend_run
    assert command.count("--read-only") == 2
    assert command.count("--cap-drop ALL") == 2
    assert command.count("--security-opt no-new-privileges=true") == 2
    assert "--tmpfs /tmp:mode=1777" in command
    assert "--tmpfs /run:mode=0755,uid=101,gid=101" in command
    assert "--tmpfs /var/cache/nginx:mode=0755,uid=101,gid=101" in command
    assert 'test "$(id -u)" -ne 0' in command
    assert 'test "$(id -u)" -eq 101' in command
    assert "CapEff:" in command
    assert "0000000000000000" in command
    assert "NoNewPrivs:" in command
    assert "test ! -w /app" in command
    assert "test ! -w /usr/share/nginx/html" in command
    assert "! command -v uv" in command
    assert "! command -v pip" in command
    assert "from app.main import app" in command
    assert "NamedTemporaryFile" in command
    assert 'Path(\\"/tmp\\")' in command
    assert "nginx -t" in command
    assert 'nginx -g "daemon off;" &' in command
    assert "/healthz" in command
    assert "/asset-inventory.txt" in command
