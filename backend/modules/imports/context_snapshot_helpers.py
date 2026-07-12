"""Helpers for deep-import context snapshot metadata."""

from __future__ import annotations

import hashlib
from typing import Any

from infrastructure.llm.token_estimation import estimate_token_count


def text_hash(value: str) -> str:
    """Stable SHA-256 hash for prompt/context text."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def estimate_tokens(value: str) -> int:
    """Tiktoken-based token estimate used for audit metadata."""
    return estimate_token_count(value)


def build_phase2_snapshot_payload(
    *,
    scene: dict[str, Any],
    source_chapter_index: int,
    existing_context: str,
    memory_context: str,
    chapters_text: str,
    accumulated_memory: list[dict],
    model: str,
    max_tokens: int,
    temperature: float,
    activation: dict[str, Any] | None = None,
    profile_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build compact snapshot payload for Phase 2 handcrafted context."""
    scene_id = str(scene.get("id")) if scene.get("id") else None
    chapter_ids = [str(ch) for ch in (scene.get("chapter_ids") or [])]
    existing_terms = [
        line[2:].strip()
        for line in existing_context.splitlines()
        if line.startswith("- ")
    ]
    sections = {
        "existing_entities_context": existing_context,
        "memory_context": memory_context,
        "scene_text": chapters_text,
    }
    section_items = [
        {
            "key": key,
            "char_count": len(content),
            "token_estimate": estimate_token_count(content, model=model),
            "hash": text_hash(content),
        }
        for key, content in sections.items()
    ]
    per_section_tokens = {item["key"]: item["token_estimate"] for item in section_items}

    activation = activation or {}
    return {
        "scene_id": scene_id,
        "scene_index": scene.get("scene_index"),
        "chapter_index": source_chapter_index,
        "compile_options": {
            "source": "deep_import_phase2_handcrafted_context",
            "model": model,
            "scene_index": scene.get("scene_index"),
            "chapter_ids": chapter_ids,
            "activation_version": activation.get("activation_version"),
            "llm_runtime": profile_summary or {},
        },
        "included_asset_ids": {
            "scenes": [scene_id] if scene_id else [],
            "chapters": chapter_ids,
            "existing_entities": [],
            "pending_entities": [],
        },
        "context_summary": {
            "scene_index": scene.get("scene_index"),
            "source_chapters": chapter_ids,
            "existing_entity_count": len(existing_terms),
            "recent_memory": accumulated_memory[-5:],
            "scene_text_char_count": len(chapters_text),
            "include_pending_objects": True,
            "activation_source_count": len(activation.get("sources") or []),
        },
        "section_metadata": {
            "sections": section_items,
            "existing_entity_terms": existing_terms,
            "activation": activation,
        },
        "token_metadata": {
            "total_tokens": sum(per_section_tokens.values()),
            "sections": per_section_tokens,
            "max_tokens": max_tokens,
            "temperature": temperature,
        },
        "rendered_context": (
            f"{existing_context}\n\n{memory_context}\n\n"
            f"请从以下正文中提取世界对象。\n\n{chapters_text}"
        ),
    }


def build_result_ref(result_type: str, result_id: Any) -> dict[str, str]:
    """Create a stable result ref dict."""
    return {"type": result_type, "id": str(result_id)}
