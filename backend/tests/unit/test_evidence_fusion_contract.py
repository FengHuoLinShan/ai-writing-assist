"""Physical-fusion guard: consumers use the Evidence owner seam."""

from __future__ import annotations

import ast

from tests.support.inventory import MODULES_ROOT, module_python_files, python_ast


def test_business_consumers_use_only_evidence_facade_or_contracts() -> None:
    violations: list[str] = []
    excluded = {"evidence"}
    for path in module_python_files():
        relative = path.relative_to(MODULES_ROOT)
        if relative.parts[0] in excluded:
            continue
        tree = python_ast(path)
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
