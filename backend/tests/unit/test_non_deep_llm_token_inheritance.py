from __future__ import annotations

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
MODULES_ROOT = BACKEND_ROOT / "modules"

_EXPLICIT_BUDGET_ALLOWLIST = {
    "modules/outline/generation/parser.py",
}


def _llm_request_calls(path: Path) -> list[tuple[int, bool]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
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


def test_only_deep_import_requests_set_explicit_max_tokens() -> None:
    violations: list[str] = []
    for path in MODULES_ROOT.rglob("*.py"):
        relative = path.relative_to(BACKEND_ROOT).as_posix()
        if "/tests/" in f"/{relative}/":
            continue
        if relative.startswith("modules/imports/"):
            continue
        if relative in _EXPLICIT_BUDGET_ALLOWLIST:
            continue
        for lineno, has_explicit_budget in _llm_request_calls(path):
            if has_explicit_budget:
                violations.append(f"{relative}:{lineno}")

    assert violations == []


def test_every_deep_import_request_keeps_an_explicit_stage_budget() -> None:
    deep_import_paths = [
        path
        for path in (MODULES_ROOT / "imports").rglob("*.py")
        if "/tests/" not in f"/{path.as_posix()}/"
    ]
    deep_import_paths.extend(BACKEND_ROOT / path for path in _EXPLICIT_BUDGET_ALLOWLIST)

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
