"""Keep author-started LLM paths behind the shared Context confirmation gate."""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]

GATED_FUNCTIONS = {
    "modules/writing/api.py": {
        "generate_writing_candidate": ("context_confirmation_id",),
        "run_conflict_check_ai_review": ("run_ai_review",),
        "enqueue_conflict_check_ai_review": ("context_confirmation_id",),
        "create_conflict_item_ai_suggestion": ("generate_ai_suggestion",),
        "enqueue_conflict_item_ai_suggestion": ("validate_ai_suggestion_request",),
    },
    "modules/story/api.py": {
        "_enqueue_confirmed_task": ("require_fresh_confirmation",),
        "_enqueue_one_click_task": ("require_fresh_confirmation",),
    },
    "modules/story/outline_state/api.py": {
        "_enqueue_confirmed_outline_task": ("require_fresh_confirmation",),
        "_enqueue_outline_layer_task": ("require_fresh_confirmation",),
        "api_generate_story_outline": ("context_confirmation_id", "prepare"),
        "api_preview_scene_fusion": ("_require_scene_fusion_confirmation",),
        "api_preview_scene_fusion_task": ("_require_scene_fusion_confirmation",),
    },
    "modules/world/api.py": {
        "chat_world_generation_center": ("_require_generation_confirmation",),
        "converge_world_generation_center": ("_require_generation_confirmation",),
        "explore_world_generation_center": ("_require_generation_confirmation",),
        "inspect_world_generation_center_page": (
            "_require_generation_confirmation",
        ),
        "ask_world": ("_require_generation_confirmation",),
        "generate_world_suggestion": ("_require_generation_confirmation",),
        "enqueue_world_suggestion": ("_require_generation_confirmation",),
        "create_world_validation_run": ("require_fresh_confirmation",),
        "refresh_bible_synopsis": ("require_fresh_confirmation",),
        "create_entity_fusion_suggestions": ("require_fresh_confirmation",),
    },
    "modules/world/map_atlas_api.py": {
        "create_run": ("require_fresh_confirmation",),
    },
}


def _function_sources(relative_path: str) -> dict[str, str]:
    source = (BACKEND_ROOT / relative_path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    return {
        node.name: ast.get_source_segment(source, node) or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
    }


def test_author_started_llm_api_inventory_consumes_confirmation() -> None:
    missing: list[str] = []
    for relative_path, functions in GATED_FUNCTIONS.items():
        sources = _function_sources(relative_path)
        for function_name, markers in functions.items():
            function_source = sources.get(function_name, "")
            if not function_source or not all(
                marker in function_source for marker in markers
            ):
                missing.append(f"{relative_path}:{function_name}")
    assert missing == []


def test_domain_overlays_preserve_confirmed_selection() -> None:
    required_markers = {
        "modules/evidence/compilation/services/generation_background.py": (
            "ConfirmedAIActionService",
            "prepared.compiled",
        ),
        "modules/story/tasks.py": (
            'selection_options.get("excluded_asset_ids")',
            'selection_options.get("excluded_refs")',
        ),
        "modules/story/outline_state/tasks.py": (
            "confirmed_context=confirmed_context",
        ),
        "modules/world/services/worldbuilding/ask_world_service.py": (
            "_confirmed_candidates",
            "selected_asset_ids",
        ),
        "modules/world/tasks.py": (
            "allowed_entity_ids",
            "prepare_confirmed_ai_action",
            "confirmed_context=confirmed_context",
        ),
        "modules/world/map_atlas_workflow.py": ("context_confirmation_id",),
        "modules/story/outline_state/scene_fusion_draft.py": (
            "confirmed_context.rendered_markdown",
        ),
        "modules/world/services/worldbuilding/world_validation_service.py": (
            "_confirmed_semantic_manifest",
        ),
        "modules/world/services/worldbuilding/world_bible_synopsis_service.py": (
            "_confirmed_source_manifest",
        ),
    }
    missing = [
        f"{relative_path}:{marker}"
        for relative_path, markers in required_markers.items()
        for marker in markers
        if marker
        not in (BACKEND_ROOT / relative_path).read_text(encoding="utf-8")
    ]
    assert missing == []
