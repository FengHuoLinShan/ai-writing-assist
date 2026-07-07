"""Unit tests for CompiledContext IR and Tier-based budget enforcement."""

from __future__ import annotations

from infrastructure.llm.token_estimation import estimate_token_count
from modules.context.services.compiled_context import (
    CompiledContext,
    ContextSection,
    Tier,
)


def test_tier_ordering():
    assert Tier.P0 < Tier.P1
    assert Tier.P1 < Tier.P2
    assert Tier.P2 < Tier.P3
    assert Tier.P3 < Tier.P4


def test_enforce_budget_no_overage():
    sections = [
        ContextSection(key="a", tier=Tier.P0, content="hello", token_count=5),
        ContextSection(key="b", tier=Tier.P1, content="world", token_count=5),
    ]
    ctx = CompiledContext(sections=sections, total_tokens=10, budget_tokens=20)
    result = ctx.enforce_budget()
    assert len(result.sections) == 2
    assert result.total_tokens == 10


def test_enforce_budget_evicts_p4_first():
    sections = [
        ContextSection(key="core", tier=Tier.P0, content="c", token_count=50),
        ContextSection(key="filler", tier=Tier.P4, content="f", token_count=100),
    ]
    ctx = CompiledContext(sections=sections, total_tokens=150, budget_tokens=80)
    result = ctx.enforce_budget()
    assert len(result.sections) == 1
    assert result.sections[0].key == "core"
    assert result.total_tokens == 50


def test_enforce_budget_evicts_p3_then_p4():
    sections = [
        ContextSection(key="core", tier=Tier.P0, content="c", token_count=50),
        ContextSection(key="low", tier=Tier.P3, content="l", token_count=60),
        ContextSection(key="filler", tier=Tier.P4, content="f", token_count=40),
    ]
    ctx = CompiledContext(sections=sections, total_tokens=150, budget_tokens=60)
    result = ctx.enforce_budget()
    assert len(result.sections) == 1
    assert result.sections[0].key == "core"
    assert result.total_tokens == 50


def test_enforce_budget_p2_per_item_truncation():
    items = [
        "alpha_x" * 20,
        "beta_x" * 20,
        "gamma_x" * 20,
        "delta_x" * 20,
    ]
    content = "\n".join(items)
    sections = [
        ContextSection(key="core", tier=Tier.P0, content="c", token_count=10),
        ContextSection(
            key="events",
            tier=Tier.P2,
            content=content,
            token_count=200,
            truncatable_per_item=True,
        ),
    ]
    ctx = CompiledContext(sections=sections, total_tokens=210, budget_tokens=115)
    result = ctx.enforce_budget()
    p2_sections = [s for s in result.sections if s.tier == Tier.P2]
    assert len(p2_sections) == 1
    p2 = p2_sections[0]
    assert p2.content != content
    kept_items = p2.content.split("\n")
    assert len(kept_items) < len(items)
    assert result.total_tokens <= ctx.budget_tokens


def test_enforce_budget_p2_truncation_counts_tokens_with_tokenizer():
    core_content = "core"
    items = [
        "今天天气很好。" * 5,
        "alpha beta gamma delta " * 10,
        "结尾线索。" * 8,
    ]
    content = "\n".join(items)
    first_item_tokens = estimate_token_count(items[0])
    core_tokens = estimate_token_count(core_content)
    budget = core_tokens + first_item_tokens
    sections = [
        ContextSection(
            key="core",
            tier=Tier.P0,
            content=core_content,
            token_count=core_tokens,
        ),
        ContextSection(
            key="events",
            tier=Tier.P2,
            content=content,
            token_count=estimate_token_count(content),
            truncatable_per_item=True,
        ),
    ]
    ctx = CompiledContext(
        sections=sections,
        total_tokens=sum(s.token_count for s in sections),
        budget_tokens=budget,
    )

    result = ctx.enforce_budget()

    assert result.total_tokens <= budget
    events_section = next(s for s in result.sections if s.key == "events")
    assert events_section.content == items[0]
    assert events_section.token_count == first_item_tokens


def test_enforce_budget_never_evicts_p0():
    sections = [
        ContextSection(
            key="core",
            tier=Tier.P0,
            content="c" * 200,
            token_count=200,
        ),
    ]
    ctx = CompiledContext(sections=sections, total_tokens=200, budget_tokens=50)
    result = ctx.enforce_budget()
    assert len(result.sections) == 1
    assert result.sections[0].key == "core"
    assert result.sections[0].tier == Tier.P0
