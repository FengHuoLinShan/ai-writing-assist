"""Tests for tiktoken-based token estimates."""

from __future__ import annotations

import pytest

from infrastructure.llm import token_estimation
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


class _FakeEncoding:
    def encode(self, text: str) -> list[str]:
        return text.split()


@pytest.fixture(autouse=True)
def _clear_tokenizer_caches() -> None:
    token_estimation._encoding_for_model.cache_clear()
    token_estimation._encoding_by_name.cache_clear()
    yield
    token_estimation._encoding_for_model.cache_clear()
    token_estimation._encoding_by_name.cache_clear()


def test_estimate_token_count_uses_known_openai_model_mapping(monkeypatch) -> None:
    text = "antidisestablishmentarianism 今天天气很好。"
    requested: list[str] = []

    monkeypatch.setattr(
        token_estimation.tiktoken,
        "encoding_name_for_model",
        lambda model: "known-encoding" if model == "gpt-4" else "unexpected",
    )
    monkeypatch.setattr(
        token_estimation.tiktoken,
        "get_encoding",
        lambda name: requested.append(name) or _FakeEncoding(),
    )

    assert estimate_token_count(text, model="gpt-4") == 2
    assert requested == ["known-encoding"]


def test_estimate_token_count_falls_back_to_cl100k_for_unknown_model(
    monkeypatch,
) -> None:
    text = "unknown OpenAI-compatible model should still use cl100k_base"
    requested: list[str] = []

    def unknown_model(_model: str) -> str:
        raise KeyError("unknown model")

    monkeypatch.setattr(
        token_estimation.tiktoken,
        "encoding_name_for_model",
        unknown_model,
    )
    monkeypatch.setattr(
        token_estimation.tiktoken,
        "get_encoding",
        lambda name: requested.append(name) or _FakeEncoding(),
    )

    assert estimate_token_count(text, model="not-a-real-openai-model") == 7
    assert requested == ["cl100k_base"]


def test_estimate_token_count_uses_cached_byte_bound_when_asset_load_fails(
    monkeypatch,
) -> None:
    attempts = 0

    def unavailable(_name: str):
        nonlocal attempts
        attempts += 1
        raise OSError("offline tokenizer asset")

    monkeypatch.setattr(
        token_estimation.tiktoken,
        "get_encoding",
        unavailable,
    )

    text = "离线 token budget"
    expected = len(text.encode("utf-8"))
    assert estimate_token_count(text) == expected
    assert estimate_token_count(text) == expected
    assert attempts == 1


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


def test_phase2_v2_snapshot_covers_actual_structured_prompt_context() -> None:
    activation = {
        "activation_version": "import-context-v2",
        "prompt_contract_version": "scene-entity-extraction-v2",
        "context_fingerprint": "fingerprint",
        "scene_card": {"title": "锁定 Scene"},
        "outline_context": {"plot_threads": [{"name": "主线"}]},
        "identity_candidates": [{"prompt_ref": "entity-001", "name": "沈砚"}],
        "previous_scene_briefs": [{"prompt_ref": "previous-scene-001"}],
        "previous_scene_evidence": [{"text": "前序逐字证据"}],
        "sources": [{"type": "world_entity", "id": "audit-only-id"}],
    }

    payload = build_phase2_snapshot_payload(
        scene={"id": "scene-1", "scene_index": 1, "chapter_ids": ["1"]},
        source_chapter_index=1,
        existing_context="legacy world",
        memory_context="legacy memory",
        chapters_text="当前 Scene 完整正文",
        accumulated_memory=[],
        model="not-a-real-openai-model",
        max_tokens=1024,
        temperature=0.3,
        activation=activation,
    )

    rendered = payload["rendered_context"]
    assert "前序逐字证据" in rendered
    assert "当前 Scene 完整正文" in rendered
    assert "scene-entity-extraction-v2" in rendered
    assert "audit-only-id" not in rendered
    section_keys = {
        item["key"] for item in payload["section_metadata"]["sections"]
    }
    assert "previous_scene_evidence" in section_keys
    assert "outline_context" in section_keys


def test_agent_step_autocompact_uses_tiktoken_estimate() -> None:
    text = "今天天气很好。" * 20
    guard = ContextBudgetGuard(ContextBudget(context_limit_tokens=10, trigger_ratio=0.5))

    result = guard.autocompact_fallback(text)

    assert result.degraded is True
    assert result.content["estimated_tokens"] == estimate_token_count(text)
    assert result.events[0].details["estimated_tokens"] == estimate_token_count(text)
