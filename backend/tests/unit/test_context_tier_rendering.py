from modules.context.markdown_renderer import render_compiled_context
from modules.context.services.compiled_context import (
    CompiledContext,
    ContextSection,
    Tier,
)


def test_render_compiled_context_respects_tier_order():
    ctx = CompiledContext(
        sections=[
            ContextSection(
                key="warn", tier=Tier.P4, content="Warning", token_count=10
            ),
            ContextSection(
                key="obj", tier=Tier.P0, content="Objective", token_count=10
            ),
            ContextSection(
                key="style", tier=Tier.P3, content="Style", token_count=10
            ),
        ],
        total_tokens=30,
        budget_tokens=100,
    )
    result = render_compiled_context(ctx)
    lines = result.split("\n")
    obj_idx = next(
        i
        for i, line in enumerate(lines)
        if "创作目标" in line or "Objective" in line
    )
    style_idx = next(
        i
        for i, line in enumerate(lines)
        if "风格" in line or "Style" in line
    )
    warn_idx = next(
        i
        for i, line in enumerate(lines)
        if "警告" in line or "Warning" in line
    )
    assert obj_idx < style_idx < warn_idx


def test_render_compiled_context_with_known_keys():
    ctx = CompiledContext(
        sections=[
            ContextSection(
                key="writing_objective",
                tier=Tier.P0,
                content="Write a scene",
                token_count=10,
            ),
            ContextSection(
                key="hard_constraints",
                tier=Tier.P0,
                content="No spoilers",
                token_count=10,
            ),
        ],
        total_tokens=20,
        budget_tokens=100,
    )
    result = render_compiled_context(ctx)
    assert "创作目标" in result
    assert "硬约束" in result


def test_render_compiled_context_empty():
    ctx = CompiledContext(sections=[], total_tokens=0, budget_tokens=100)
    result = render_compiled_context(ctx)
    assert result == ""
