"""Physical-fusion guard: consumers use the Evidence owner seam."""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def test_business_consumers_use_only_evidence_facade_or_contracts() -> None:
    violations: list[str] = []
    modules_root = BACKEND_ROOT / "modules"
    excluded = {"evidence"}
    for path in modules_root.rglob("*.py"):
        relative = path.relative_to(modules_root)
        if relative.parts[0] in excluded or "tests" in relative.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
            for name in names:
                if name.startswith(("modules.rag", "modules.context")):
                    violations.append(f"{relative}:{node.lineno}:{name}")
                if name.startswith(
                    ("modules.evidence.indexing", "modules.evidence.compilation")
                ):
                    violations.append(f"{relative}:{node.lineno}:{name}")

    assert violations == []
