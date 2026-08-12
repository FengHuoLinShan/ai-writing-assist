"""Contracts for explicit API and worker task-handler composition."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import call, patch

import pytest

from app import task_runtime

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _registered_catalog(composition: str) -> dict[str, dict[str, int | str]]:
    """Read a freshly composed handler catalog from an isolated Python process."""
    script = "\n".join(
        (
            composition,
            "import json",
            "from infrastructure.tasks.registry import TaskRegistry",
            "registry = TaskRegistry()",
            "catalog = {}",
            "for task_type in sorted(registry.registered_types):",
            "    definition = registry.get_definition(task_type)",
            "    catalog[task_type] = {",
            "        'recovery_policy': definition.recovery_policy,",
            "        'max_attempts': definition.max_attempts,",
            "        'owner_scope': definition.owner_scope,",
            "    }",
            "print(json.dumps(catalog, sort_keys=True))",
        )
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        cwd=BACKEND_ROOT,
        env=os.environ.copy(),
        text=True,
    )
    return json.loads(completed.stdout)


def test_runtime_manifest_matches_direct_task_handler_modules() -> None:
    """Test-only static discovery prevents the explicit manifest from drifting."""
    discovered = {
        ".".join(task_file.relative_to(BACKEND_ROOT).with_suffix("").parts)
        for task_file in (BACKEND_ROOT / "modules").glob("**/*tasks.py")
        if "@task_handler" in task_file.read_text(encoding="utf-8")
    }

    assert discovered == set(task_runtime._TASK_HANDLER_MODULES)


def test_register_task_handlers_imports_manifest_once_in_order() -> None:
    with patch(
        "app.task_runtime.importlib.import_module",
        autospec=True,
    ) as import_module:
        task_runtime.register_task_handlers()

    assert import_module.call_args_list == [
        call(module_name) for module_name in task_runtime._TASK_HANDLER_MODULES
    ]


def test_register_task_handlers_propagates_import_failure_without_continuing() -> None:
    failing_module = task_runtime._TASK_HANDLER_MODULES[2]

    def import_module(module_name: str) -> None:
        if module_name == failing_module:
            raise RuntimeError("handler import failed")

    with (
        patch(
            "app.task_runtime.importlib.import_module",
            autospec=True,
            side_effect=import_module,
        ) as mocked_import,
        pytest.raises(RuntimeError, match="handler import failed"),
    ):
        task_runtime.register_task_handlers()

    assert mocked_import.call_args_list == [
        call(module_name) for module_name in task_runtime._TASK_HANDLER_MODULES[:3]
    ]


def test_api_and_worker_compose_the_same_complete_task_catalog() -> None:
    api_catalog = _registered_catalog("import app.main")
    worker_catalog = _registered_catalog(
        "from run_worker import _configure_worker_process\n_configure_worker_process()"
    )

    assert api_catalog
    assert api_catalog == worker_catalog
    assert {item["owner_scope"] for item in api_catalog.values()} == {
        "global",
        "project",
    }
    assert api_catalog["deep_import"] == {
        "recovery_policy": "manual_resume",
        "max_attempts": 1,
        "owner_scope": "project",
    }
    assert api_catalog["rag_index_chapter"] == {
        "recovery_policy": "auto_requeue",
        "max_attempts": 2,
        "owner_scope": "project",
    }
    assert api_catalog["writing_generate"] == {
        "recovery_policy": "restart_origin",
        "max_attempts": 1,
        "owner_scope": "project",
    }
