"""Tests for tiktoken-based token estimates."""

from __future__ import annotations

import tiktoken

from infrastructure.llm.agent_step_harness import (
    ContextBudget,
    ContextBudgetGuard,
)
from infrastructure.llm.token_estimation import estimate_token_count
from modules.imports.context_snapshot_helpers import (
    build_phase2_snapshot_payload,
    estimate_tokens,
)


def test_estimate_token_count_handles_empty_text() -> None:
    assert estimate_token_count(None) == 0
    assert estimate_token_count("") == 0


def test_estimate_token_count_uses_known_openai_model_mapping() -> None:
    text = "antidisestablishmentarianism 今天天气很好。"

    assert estimate_token_count(text, model="gpt-4") == len(
        tiktoken.encoding_for_model("gpt-4").encode(text)
    )


def test_estimate_token_count_falls_back_to_cl100k_for_unknown_model() -> None:
    text = "unknown OpenAI-compatible model should still use cl100k_base"

    assert estimate_token_count(text, model="not-a-real-openai-model") == len(
        tiktoken.get_encoding("cl100k_base").encode(text)
    )


def test_import_snapshot_helper_uses_model_aware_token_estimate() -> None:
    scene = {
        "id": "scene-1",
        "scene_index": 7,
        "chapter_ids": ["chapter-1"],
    }
    sections = {
        "existing_entities_context": "- 灯塔\n- 海湾",
        "memory_context": "上一场景：主角看到雾中灯火。",
        "scene_text": "今天天气很好。" * 12,
    }

    payload = build_phase2_snapshot_payload(
        scene=scene,
        source_chapter_index=3,
        existing_context=sections["existing_entities_context"],
        memory_context=sections["memory_context"],
        chapters_text=sections["scene_text"],
        accumulated_memory=[{"summary": "seen"}],
        model="not-a-real-openai-model",
        max_tokens=4096,
        temperature=0.2,
    )

    expected_sections = {
        key: estimate_token_count(value, model="not-a-real-openai-model")
        for key, value in sections.items()
    }
    assert payload["token_metadata"]["sections"] == expected_sections
    assert payload["token_metadata"]["total_tokens"] == sum(expected_sections.values())
    assert estimate_tokens(sections["scene_text"]) == estimate_token_count(
        sections["scene_text"]
    )


def test_agent_step_autocompact_uses_tiktoken_estimate() -> None:
    text = "今天天气很好。" * 20
    guard = ContextBudgetGuard(ContextBudget(context_limit_tokens=10, trigger_ratio=0.5))

    result = guard.autocompact_fallback(text)

    assert result.degraded is True
    assert result.content["estimated_tokens"] == estimate_token_count(text)
    assert result.events[0].details["estimated_tokens"] == estimate_token_count(text)
