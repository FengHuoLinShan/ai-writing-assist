"""Structural guards for the shared pytest harness."""

from __future__ import annotations

import ast
import os
import re
import shlex
import subprocess
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
    assert python_source(support_file) is python_source(support_file)
    assert python_ast(support_file) is python_ast(support_file)


def _unautospecced_patch_calls(source: str, *, filename: str) -> list[int]:
    """Return unittest.mock.patch call lines without literal autospec=True."""
    tree = ast.parse(source, filename=filename)
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


def _async_pytest_fixture_definitions(source: str, *, filename: str) -> list[str]:
    tree = ast.parse(source, filename=filename)
    pytest_aliases = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
        if alias.name == "pytest"
    }
    fixture_aliases = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "pytest"
        for alias in node.names
        if alias.name == "fixture"
    }
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        for decorator in node.decorator_list:
            fixture_ref = decorator.func if isinstance(decorator, ast.Call) else decorator
            is_pytest_fixture = (
                isinstance(fixture_ref, ast.Name) and fixture_ref.id in fixture_aliases
            ) or (
                isinstance(fixture_ref, ast.Attribute)
                and isinstance(fixture_ref.value, ast.Name)
                and fixture_ref.value.id in pytest_aliases
                and fixture_ref.attr == "fixture"
            )
            if is_pytest_fixture:
                violations.append(f"{node.lineno}:{node.name}")
    return violations


def test_async_fixture_guard_covers_root_conftest() -> None:
    assert BACKEND_ROOT / "conftest.py" in repository_test_python_files()


def test_async_fixture_guard_recognizes_aliases_calls_and_nested_classes() -> None:
    cases = {
        "direct": """
import pytest

@pytest.fixture
async def direct_fixture():
    pass
""",
        "module_alias_and_call": """
import pytest as pt

class TestNested:
    @pt.fixture(scope="module")
    async def nested_fixture(self):
        pass
""",
        "import_alias": """
from pytest import fixture as pytest_fixture

@pytest_fixture()
async def imported_fixture():
    pass
""",
    }

    for name, source in cases.items():
        violations = _async_pytest_fixture_definitions(source, filename=name)
        assert len(violations) == 1, name


def test_async_fixture_guard_allows_explicit_async_and_sync_fixtures() -> None:
    source = """
import pytest
import pytest_asyncio

@pytest_asyncio.fixture
async def explicit_async_fixture():
    pass

@pytest.fixture
def sync_fixture():
    pass
"""

    assert _async_pytest_fixture_definitions(source, filename="allowed") == []


def test_async_fixtures_use_pytest_asyncio_decorator() -> None:
    violations: list[str] = []

    for path in repository_test_python_files():
        relative_path = path.relative_to(BACKEND_ROOT)
        definitions = _async_pytest_fixture_definitions(
            python_source(path),
            filename=str(path),
        )
        violations.extend(f"{relative_path}:{definition}" for definition in definitions)

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


def test_fast_layer_has_timeout_parallel_and_coverage_ci_guards() -> None:
    config = tomllib.loads((BACKEND_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    optional_dependencies = config["project"]["optional-dependencies"]
    for extra in ("ci", "dev", "test"):
        package_names = {
            requirement.split(">=", maxsplit=1)[0]
            for requirement in optional_dependencies[extra]
        }
        assert {"pytest-cov", "pytest-timeout", "pytest-xdist"} <= package_names

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
    assert coverage_config["report"]["fail_under"] >= 85.0
    assert coverage_config["report"]["show_missing"] is True

    repo_root = BACKEND_ROOT.parent
    makefile = (repo_root / "Makefile").read_text(encoding="utf-8")
    backend_workflow = (repo_root / ".github/workflows/backend-ci.yml").read_text(
        encoding="utf-8"
    )
    frontend_workflow = (repo_root / ".github/workflows/frontend-ci.yml").read_text(
        encoding="utf-8"
    )

    assert "test-fast-parallel:" in makefile
    assert "test-fast-coverage:" in makefile
    assert "secret-hygiene:" in makefile
    assert "--timeout=$(FAST_TEST_TIMEOUT_SECONDS)" in makefile
    assert "-n $(TEST_WORKERS) --dist=loadscope" in makefile
    assert "python3 backend/tools/secret_hygiene.py" in backend_workflow
    assert backend_workflow.index(
        "Check repository secret hygiene"
    ) < backend_workflow.index("Install uv and Python")
    assert "name: Audit locked backend dependencies" in backend_workflow
    assert "make audit-backend-deps" in backend_workflow
    assert "run: make audit-backend-deps" in backend_workflow
    assert (
        backend_workflow.index("Install uv and Python")
        < backend_workflow.index("name: Audit locked backend dependencies")
        < backend_workflow.index("Install locked backend dependencies")
        < backend_workflow.index("name: Lint backend")
    )
    assert "make test-fast-coverage TEST_WORKERS=2" in backend_workflow
    assert 'ARGS="-W error::RuntimeWarning"' in backend_workflow
    assert "name: Frontend unit quality" in frontend_workflow
    assert "working-directory: frontend-console" in frontend_workflow
    assert "run: npm ci" in frontend_workflow
    assert "name: Audit frontend dependency lockfile" in frontend_workflow
    assert "run: npm audit --package-lock-only --audit-level=high" in frontend_workflow
    assert "run: npm test" in frontend_workflow
    assert (
        frontend_workflow.index("run: npm ci")
        < frontend_workflow.index("name: Audit frontend dependency lockfile")
        < frontend_workflow.index("run: npm test")
    )
    assert "test-ci:" in makefile
    assert "make test-deploy" in backend_workflow


def _make_dry_run(
    target: str,
    *variables: str,
    environment: dict[str, str] | None = None,
) -> str:
    result = subprocess.run(
        ["make", "--no-print-directory", "-n", target, *variables],
        cwd=BACKEND_ROOT.parent,
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    return result.stdout.strip()


def test_make_dry_run_suppresses_recursive_make_directory_chatter() -> None:
    environment = os.environ | {"MAKELEVEL": "1", "MAKEFLAGS": "w"}

    command = _make_dry_run("audit-backend-deps", environment=environment)

    assert "Entering directory" not in command
    assert "Leaving directory" not in command
    assert "uv audit --locked" in command


def test_automated_backend_quality_targets_use_the_locked_ci_runner() -> None:
    runner = "uv run --locked --extra ci --"
    target_tools = {
        "test-collect": "pytest",
        "test-fast": "pytest",
        "test-fast-parallel": "pytest",
        "test-fast-coverage": "pytest",
        "test-v": "pytest",
        "test-integration": "pytest",
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


def test_backend_ci_uses_self_locking_make_quality_targets() -> None:
    workflow = (BACKEND_ROOT.parent / ".github/workflows/backend-ci.yml").read_text(
        encoding="utf-8"
    )

    lint_step = workflow.split("      - name: Lint backend\n", maxsplit=1)[1].split(
        "\n      - name:", maxsplit=1
    )[0]
    fast_coverage_step = workflow.split(
        "      - name: Run fast backend tests with coverage\n", maxsplit=1
    )[1].split("\n\n  postgresql-critical:", maxsplit=1)[0]
    postgresql_step = workflow.split(
        "      - name: Run serial PostgreSQL critical contracts\n", maxsplit=1
    )[1].split("\n      - name:", maxsplit=1)[0]

    assert lint_step.strip() == "run: make lint"
    assert "make test-fast-coverage TEST_WORKERS=2" in fast_coverage_step
    assert "uv run" not in fast_coverage_step
    assert postgresql_step.strip() == "run: make -C .. test-postgresql-critical"


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


def test_fast_targets_expand_to_the_same_guarded_test_layer() -> None:
    serial = _make_dry_run("test-fast")
    default = _make_dry_run("test")
    parallel = _make_dry_run("test-fast-parallel", "TEST_WORKERS=2")

    assert default == serial
    assert "--timeout=120" in serial
    assert '-m "not e2e and not real_llm and not external_data"' in serial
    assert parallel.replace(" -n 2 --dist=loadscope", "") == serial


def test_coverage_target_reuses_parallel_fast_layer() -> None:
    parallel = _make_dry_run("test-fast-parallel", "TEST_WORKERS=2")
    coverage = _make_dry_run("test-fast-coverage", "TEST_WORKERS=2")

    for flag in (
        " --cov=app",
        " --cov=core",
        " --cov=shared",
        " --cov=infrastructure",
        " --cov=modules",
        " --cov-report=term-missing:skip-covered",
    ):
        coverage = coverage.replace(flag, "")
    assert coverage == parallel


def test_aggregate_targets_reuse_existing_backend_and_frontend_targets() -> None:
    makefile = (BACKEND_ROOT.parent / "Makefile").read_text(encoding="utf-8")

    assert '$(MAKE) test-fast ARGS="$(BACKEND_ARGS)"' in makefile
    assert '$(MAKE) test-frontend FRONTEND_ARGS="$(FRONTEND_ARGS)"' in makefile
    assert "audit-backend-deps:" in makefile
    assert "audit-frontend-deps:" in makefile
    assert (
        "test-ci: docs-check secret-hygiene audit-backend-deps "
        "lint test-deploy audit-frontend-deps" in makefile
    )
    assert "$(MAKE) test-fast-coverage TEST_WORKERS=$(TEST_WORKERS)" in makefile
    assert 'ARGS="$(ARGS) -W error::RuntimeWarning"' in makefile


def test_frontend_dependency_audit_target_uses_high_lockfile_gate() -> None:
    command = _make_dry_run("audit-frontend-deps")

    assert "npm audit --package-lock-only --audit-level=high" in command


def test_backend_dependency_audit_target_covers_the_entire_lockfile() -> None:
    command = _make_dry_run("audit-backend-deps")
    tokens = shlex.split(command)

    assert tokens[:2] == ["cd", str(BACKEND_ROOT)]
    assert tokens[2:5] == ["&&", "uv", "audit"]
    assert "--locked" in tokens
    assert "--no-build" in tokens
    assert tokens[tokens.index("--preview-features") + 1] == "audit"
    assert tokens[tokens.index("--python-version") + 1] == "3.12"
    assert tokens[tokens.index("--python-platform") + 1] == "x86_64-unknown-linux-gnu"
    ignored_until_fixed = {
        tokens[index + 1]
        for index, token in enumerate(tokens)
        if token == "--ignore-until-fixed"
    }
    assert ignored_until_fixed == {"GHSA-w8v5-vhqr-4h9v", "GHSA-95ww-475f-pr4f"}
    assert tokens.count("--ignore-until-fixed") == 2
    assert not any(
        token == "--ignore" or token.startswith("--ignore=") for token in tokens
    )
    assert not any(
        token == "--no-extra" or token.startswith("--no-extra=") for token in tokens
    )
    assert not any(
        token == "--exclude" or token.startswith("--exclude=") for token in tokens
    )


def test_deployment_contract_tests_are_a_required_ci_gate() -> None:
    workflow = (BACKEND_ROOT.parent / ".github/workflows/backend-ci.yml").read_text(
        encoding="utf-8"
    )
    command = _make_dry_run("test-deploy")

    assert (
        "test-ci: docs-check secret-hygiene audit-backend-deps "
        "lint test-deploy audit-frontend-deps"
        in (BACKEND_ROOT.parent / "Makefile").read_text(encoding="utf-8")
    )
    assert "uv run --locked --extra ci --" in command
    assert "pytest -c pyproject.toml ../deploy/tests" in command

    deployment_step = workflow.split(
        "      - name: Run deployment contract tests\n", maxsplit=1
    )[1].split("\n      - name:", maxsplit=1)[0]
    assert deployment_step.strip() == "run: make test-deploy"


def test_timeout_is_not_forced_onto_explicit_acceptance_layers() -> None:
    for target in ("test-e2e", "test-real-llm", "test-manual"):
        command = _make_dry_run(target)
        assert "--timeout" not in command
        assert "--cov" not in command


def test_production_toolchain_contract_is_pinned_everywhere() -> None:
    repo_root = BACKEND_ROOT.parent
    backend_dockerfile = (BACKEND_ROOT / "Dockerfile").read_text(encoding="utf-8")
    frontend_dockerfile = (repo_root / "frontend-console" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    workflow = "\n".join(
        (repo_root / workflow_path).read_text(encoding="utf-8")
        for workflow_path in (
            ".github/workflows/backend-ci.yml",
            ".github/workflows/frontend-ci.yml",
            ".github/workflows/production-image-ci.yml",
        )
    )
    e2e_workflow = (repo_root / ".github/workflows/backend-postgresql-e2e.yml").read_text(
        encoding="utf-8"
    )
    python_image = (
        "python:3.12.13-slim-bookworm@sha256:"
        "d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b"
    )
    node_image = (
        "node:24.18.0-alpine3.23@sha256:"
        "595398b0081eacda8e1c4c5b97b76cd1020e4d58a8ebcb4843b9bca1e79e7436"
    )
    nginx_image = (
        "nginx:1.30.4-alpine@sha256:"
        "97d490c12ba55b4946b01546d1c3ed324e8d41ab1c9fcb2a616aa470620e5b46"
    )
    postgres_image = (
        "pgvector/pgvector:0.8.6-pg17-bookworm@sha256:"
        "7ae6051efd0e60444282c27c7e141af07f322ce033300e727a49c3dd11075e38"
    )

    assert backend_dockerfile.count(f"FROM {python_image}") == 2
    assert "AS build" in backend_dockerfile
    assert "AS runtime" in backend_dockerfile
    assert "ARG UV_VERSION=0.11.28" in backend_dockerfile
    assert "USER app" in backend_dockerfile
    assert "COPY --from=build --chown=app:app /app /app" in backend_dockerfile
    assert f"FROM {node_image} AS build" in frontend_dockerfile
    assert f"FROM {nginx_image}" in frontend_dockerfile
    assert "asset-manifest.json asset-inventory.txt index.html" in frontend_dockerfile
    assert "nginx -t" in frontend_dockerfile
    assert "chown nginx:nginx /run /var/cache/nginx" in frontend_dockerfile
    assert frontend_dockerfile.rstrip().endswith(
        "CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1"
    )
    assert "USER nginx\n\nEXPOSE 8080" in frontend_dockerfile

    assert (BACKEND_ROOT / ".python-version").read_text(encoding="utf-8") == "3.12.13\n"
    assert (repo_root / "frontend-console/.node-version").read_text(
        encoding="utf-8"
    ) == "24.18.0\n"
    assert workflow.count("runs-on: ubuntu-24.04") == 7
    assert e2e_workflow.count("runs-on: ubuntu-24.04") == 1
    assert workflow.count('python-version: "3.12.13"') == 5
    assert e2e_workflow.count('python-version: "3.12.13"') == 1
    assert len(re.findall(r"uses: actions/setup-node@[0-9a-f]{40}", workflow)) == 4
    assert workflow.count("node-version-file: frontend-console/.node-version") == 4
    assert (
        workflow.count("cache-dependency-path: frontend-console/package-lock.json") == 4
    )
    assert workflow.count(f"image: {postgres_image}") == 4
    assert e2e_workflow.count(f"image: {postgres_image}") == 1

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
    assert "from app.main import app" in command
    assert "NamedTemporaryFile" in command
    assert 'Path(\\"/tmp\\")' in command
    assert "nginx -t" in command
    assert 'nginx -g "daemon off;" &' in command
    assert "/healthz" in command
    assert "/asset-inventory.txt" in command
    assert "production-image-contract:" in workflow
    assert "run: make test-production-images" in workflow
