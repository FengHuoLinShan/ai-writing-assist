"""Physical-fusion guards: one implementation with one-release aliases."""

from __future__ import annotations

import ast
from pathlib import Path

from modules.context import contracts as legacy_context_contracts
from modules.context import facade as legacy_context_facade
from modules.context import models as legacy_context_models
from modules.evidence import contracts, facade
from modules.evidence.compilation import models as compilation_models
from modules.evidence.indexing import models as indexing_models
from modules.rag import contracts as legacy_rag_contracts
from modules.rag import facade as legacy_rag_facade
from modules.rag import models as legacy_rag_models

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def test_legacy_imports_reexport_the_evidence_implementation() -> None:
    assert legacy_rag_facade.retrieve is facade.retrieve
    assert legacy_context_facade.confirm_context is facade.confirm_context
    assert legacy_rag_contracts.RagChunkContract is contracts.RagChunkContract
    assert (
        legacy_context_contracts.ContextSnapshotRequest
        is contracts.ContextSnapshotRequest
    )
    assert legacy_rag_models.RagChunk is indexing_models.RagChunk
    assert (
        legacy_context_models.ContextConfirmation
        is compilation_models.ContextConfirmation
    )


def test_business_consumers_use_only_evidence_facade_or_contracts() -> None:
    violations: list[str] = []
    modules_root = BACKEND_ROOT / "modules"
    excluded = {"evidence", "rag", "context"}
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

