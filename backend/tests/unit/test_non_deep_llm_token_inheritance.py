from __future__ import annotations

import ast
from pathlib import Path

from tests.support.inventory import module_python_files, python_ast

BACKEND_ROOT = Path(__file__).resolve().parents[2]
MODULES_ROOT = BACKEND_ROOT / "modules"

_DEEP_IMPORT_BUDGET_ALLOWLIST = {
    "modules/story/outline_state/generation/parser.py",
}
_EXPLICIT_OUTPUT_BUDGET_ALLOWLIST = {
    *_DEEP_IMPORT_BUDGET_ALLOWLIST,
    "modules/evidence/compilation/services/retrieval_query_planner.py",
    # Focused one-hop nominations have a schema-bound budget to avoid truncated JSON.
    "modules/evidence/compilation/services/focused_evidence.py",
    "modules/interaction/generation.py",
    # ADR-0023 continuity review and typed World iteration bound their JSON replies.
    "modules/interaction/proactive.py",
    # Scene extraction has a bounded typed response and needs room for the
    # observations plus their evidence-linked scene events.
    "modules/evolution/llm_sampler.py",
    # 世界设计迭代的多轮审查/修复绑定 JSON 输出预算（AO-6 拆分后单文件）。
    "modules/world/services/worldbuilding/generation_center/design_iteration.py",
    "modules/world/map_atlas_workflow.py",
    # Five-location spatial extraction shares the atlas's bounded JSON output budget.
    "modules/world/map_structure_workflow.py",
    "modules/world/services/worldbuilding/world_validation_service.py",
}
_GOAL_SERVICE = "modules/assistant/goal_runs/service.py"
_APPROVAL_REPLY_FILES = {
    "modules/assistant/approval.py",
    "modules/assistant/approval_calibration.py",
}


def _approval_bounded_call_lines(path: Path) -> set[int]:
    # The task-authorized three-field judgment and its calibration share 1024 tokens.
    return {
        node.lineno
        for node in ast.walk(python_ast(path))
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", None) == "LLMCallRequest"
        and any(
            item.arg == "max_tokens"
            and isinstance(item.value, ast.Constant)
            and item.value.value == 1024
            for item in node.keywords
        )
    }


def _llm_request_calls(path: Path) -> list[tuple[int, bool]]:
    tree = python_ast(path)
    calls: list[tuple[int, bool]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call_name = getattr(node.func, "id", None) or getattr(
            node.func,
            "attr",
            None,
        )
        if call_name != "LLMCallRequest":
            continue
        calls.append(
            (
                node.lineno,
                any(keyword.arg == "max_tokens" for keyword in node.keywords),
            )
        )
    return calls


def _goal_frozen_budget_call_lines(path: Path) -> set[int]:
    """Only the Goal preflight may override the frozen Project model default."""
    lines: set[int] = set()
    for node in ast.walk(python_ast(path)):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "id", None) != "LLMCallRequest":
            continue
        output = next(
            (item.value for item in node.keywords if item.arg == "max_tokens"),
            None,
        )
        if (
            isinstance(output, ast.Call)
            and isinstance(output.func, ast.Name)
            and output.func.id == "_goal_prompt_token_limit"
        ):
            lines.add(node.lineno)
    return lines


def test_only_approved_workflows_set_explicit_max_tokens() -> None:
    violations: list[str] = []
    for path in module_python_files():
        relative = path.relative_to(BACKEND_ROOT).as_posix()
        if "/tests/" in f"/{relative}/":
            continue
        if relative.startswith("modules/imports/"):
            continue
        if relative in _EXPLICIT_OUTPUT_BUDGET_ALLOWLIST:
            continue
        goal_bounded = (
            _goal_frozen_budget_call_lines(path) if relative == _GOAL_SERVICE else set()
        )
        approval_bounded = (
            _approval_bounded_call_lines(path)
            if relative in _APPROVAL_REPLY_FILES
            else set()
        )
        for lineno, has_explicit_budget in _llm_request_calls(path):
            if has_explicit_budget and lineno not in goal_bounded | approval_bounded:
                violations.append(f"{relative}:{lineno}")

    assert violations == []


def test_every_deep_import_request_keeps_an_explicit_stage_budget() -> None:
    deep_import_paths = [
        path
        for path in module_python_files()
        if path.is_relative_to(MODULES_ROOT / "imports")
    ]
    deep_import_paths.extend(
        BACKEND_ROOT / path for path in _DEEP_IMPORT_BUDGET_ALLOWLIST
    )

    requests: list[str] = []
    missing_budgets: list[str] = []
    for path in deep_import_paths:
        relative = path.relative_to(BACKEND_ROOT).as_posix()
        for lineno, has_explicit_budget in _llm_request_calls(path):
            location = f"{relative}:{lineno}"
            requests.append(location)
            if not has_explicit_budget:
                missing_budgets.append(location)

    assert requests
    assert missing_budgets == []
