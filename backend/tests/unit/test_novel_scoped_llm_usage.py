"""Guard novel-scoped business LLM calls against default client drift."""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
MODULES_ROOT = BACKEND_ROOT / "modules"

# These are deliberately narrow legacy/project-snapshot/embedding adapters.
# Any new entry requires a reason and a migration decision.
ALLOWED_DIRECT_CLIENT_CALLS: dict[tuple[str, str], str] = {
    ("modules/rag/embedding_writer.py", "constructor"): (
        "embedding-only adapter governed by EMBEDDING_* settings"
    ),
    ("modules/rag/retrieval.py", "constructor"): (
        "embedding-only adapter governed by EMBEDDING_* settings"
    ),
    ("modules/rag/tuning.py", "constructor"): (
        "offline embedding tuning governed by EMBEDDING_* settings"
    ),
    (
        "modules/world/services/core/extraction_service.py",
        "project_settings",
    ): "unit-test-only Mock session compatibility; production uses runtime seam",
}


def _call_kind(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name) and node.func.id == "LLMClient":
        return "constructor"
    if (
        isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "LLMClient"
        and node.func.attr == "from_project_settings"
    ):
        return "project_settings"
    return None


def test_business_modules_have_no_unclassified_direct_llm_clients() -> None:
    discovered: set[tuple[str, str]] = set()
    for path in MODULES_ROOT.rglob("*.py"):
        if "tests" in path.relative_to(MODULES_ROOT).parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            kind = _call_kind(node)
            if kind is not None:
                discovered.add((str(path.relative_to(BACKEND_ROOT)), kind))

    assert discovered == set(ALLOWED_DIRECT_CLIENT_CALLS)


def test_novel_scoped_generation_modules_use_project_runtime_seam() -> None:
    managed_modules = (
        "modules/writing/services.py",
        "modules/writing/conflict_ai.py",
        "modules/outline/ai_workflow_service.py",
        "modules/outline/generator.py",
        "modules/outline/cross_chapter_detection.py",
        "modules/outline/structure_dedup.py",
        "modules/world/entity_fusion.py",
        "modules/world/services/core/extraction_service.py",
        "modules/world/services/worldbuilding/object_draft_generation_service.py",
        "modules/world/services/worldbuilding/world_bible_ai_generation_service.py",
        "modules/rag/retrieval.py",
    )

    for relative_path in managed_modules:
        source = (BACKEND_ROOT / relative_path).read_text(encoding="utf-8")
        assert "open_project_llm_client" in source, relative_path


def test_every_db_backed_workflow_passes_its_novel_id_to_runtime_seam() -> None:
    expected_call_counts = {
        "modules/writing/services.py": 1,
        "modules/writing/conflict_ai.py": 2,
        "modules/outline/ai_workflow_service.py": 1,
        "modules/outline/generator.py": 1,
        "modules/outline/cross_chapter_detection.py": 1,
        "modules/outline/structure_dedup.py": 1,
        "modules/world/entity_fusion.py": 1,
        "modules/world/services/core/extraction_service.py": 1,
        "modules/world/services/worldbuilding/object_draft_generation_service.py": 1,
        "modules/world/services/worldbuilding/world_bible_ai_generation_service.py": 1,
        "modules/rag/retrieval.py": 1,
    }
    actual_counts: dict[str, int] = {}
    violations: list[str] = []
    for relative_path in expected_call_counts:
        path = BACKEND_ROOT / relative_path
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else None
            )
            if name != "open_project_llm_client":
                continue
            actual_counts[relative_path] = actual_counts.get(relative_path, 0) + 1
            args = [ast.unparse(item) for item in node.args]
            if (
                len(args) < 2
                or args[0] != "db"
                or args[1]
                not in {
                    "novel_id",
                    "str(novel_id)",
                }
            ):
                violations.append(f"{relative_path}:{node.lineno}:{args}")

    assert violations == []
    assert actual_counts == expected_call_counts


def test_import_workflows_use_project_owned_snapshot_runtime_seam() -> None:
    expected = {
        "modules/imports/workflow_llm_adapters.py": 1,
        "modules/imports/entity_extraction/scene_entity_llm_adapters.py": 2,
    }
    actual: dict[str, int] = {}
    missing_scope: list[str] = []
    for relative_path in expected:
        path = BACKEND_ROOT / relative_path
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else None
            )
            if name == "create_project_snapshot_llm_client":
                actual[relative_path] = actual.get(relative_path, 0) + 1
                keywords = {item.arg: ast.unparse(item.value) for item in node.keywords}
                if "novel_id" not in keywords:
                    missing_scope.append(f"{relative_path}:{node.lineno}")

    assert actual == expected
    assert missing_scope == []


def test_active_import_phases_bind_novel_id_to_snapshot_runtime() -> None:
    path = BACKEND_ROOT / "modules/imports/workflow.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    expected = {
        "_Phase1aSceneSlicingLLM": 1,
        "_Phase1bSceneEnrichmentLLM": 1,
        "phase2_project_settings_context": 1,
    }
    actual: dict[str, int] = {}
    invalid_scope: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = (
            node.func.id
            if isinstance(node.func, ast.Name)
            else node.func.attr
            if isinstance(node.func, ast.Attribute)
            else None
        )
        if name not in expected:
            continue
        actual[name] = actual.get(name, 0) + 1
        keywords = {item.arg: ast.unparse(item.value) for item in node.keywords}
        if keywords.get("novel_id") != "novel_id":
            invalid_scope.append(f"{name}:{node.lineno}:{keywords}")

    assert actual == expected
    assert invalid_scope == []


def test_legacy_scene_segmentation_entrypoint_has_no_production_caller() -> None:
    callers: list[str] = []
    for path in MODULES_ROOT.rglob("*.py"):
        relative = path.relative_to(BACKEND_ROOT)
        if "tests" in relative.parts or str(relative) == (
            "modules/imports/scene_segmentation.py"
        ):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "segment_chapters"
            ):
                callers.append(f"{relative}:{node.lineno}")

    assert callers == []
