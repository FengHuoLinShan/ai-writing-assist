"""Tests for imports agent harness primitives."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from modules.imports.agent_step_harness import (
    AgentPermissionLevel,
    ContextBudget,
    ContextBudgetGuard,
    ManagedLLMStep,
    OutputGuard,
    StepExecutionStatus,
    StepToolEnvelope,
)


class _ItemsPayload(BaseModel):
    items: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


@pytest.mark.asyncio
async def test_managed_step_records_journal_and_elapsed() -> None:
    step = ManagedLLMStep(
        StepToolEnvelope(
            name="phase1a_reinforce",
            permission_level=AgentPermissionLevel.draft,
            read_only=False,
        )
    )

    result = await step.run(lambda: {"ok": True})

    assert result.status == StepExecutionStatus.succeeded
    assert result.output == {"ok": True}
    assert [event["event"] for event in result.journal_events] == ["started", "ended"]
    assert result.journal_events[-1]["step_name"] == "phase1a_reinforce"
    assert result.elapsed_ms >= 0


def test_managed_step_rejects_autonomous_permission() -> None:
    with pytest.raises(ValueError, match="Autonomous"):
        ManagedLLMStep(
            StepToolEnvelope(
                name="forbidden",
                permission_level=AgentPermissionLevel.autonomous,
            )
        )


def test_step_envelope_rejects_autonomous_permission() -> None:
    with pytest.raises(ValueError, match="Autonomous"):
        StepToolEnvelope(
            name="forbidden",
            permission_level=AgentPermissionLevel.autonomous,
        )


@pytest.mark.asyncio
async def test_output_guard_accepts_valid_json_and_fills_missing_lists() -> None:
    result = await OutputGuard(_ItemsPayload).validate('{"items":["a"]}')

    assert result.status == StepExecutionStatus.succeeded
    assert result.output.items == ["a"]
    assert result.output.warnings == []


@pytest.mark.asyncio
async def test_output_guard_normalizes_bare_list_for_single_list_schema() -> None:
    class OneListPayload(BaseModel):
        items: list[str]

    result = await OutputGuard(OneListPayload).validate('["a", "b"]')

    assert result.status == StepExecutionStatus.succeeded
    assert result.output.items == ["a", "b"]


@pytest.mark.asyncio
async def test_output_guard_repairs_once() -> None:
    async def repairer(payload):
        assert payload["raw_output_hash"]
        assert payload["validation_errors"]
        return {"items": ["fixed"]}

    result = await OutputGuard(_ItemsPayload, repairer=repairer).validate(
        '{"items":"bad"}'
    )

    assert result.status == StepExecutionStatus.succeeded
    assert result.output.items == ["fixed"]
    assert result.repair_attempts == 1


@pytest.mark.asyncio
async def test_output_guard_repair_failure_degrades() -> None:
    def repairer(_payload):
        return {"items": "still-bad"}

    result = await OutputGuard(_ItemsPayload, repairer=repairer).validate(
        '{"items":"bad"}'
    )

    assert result.status == StepExecutionStatus.degraded
    assert result.degraded is True
    assert result.error_kind == "repair_failed"
    assert result.repair_attempts == 1


@pytest.mark.asyncio
async def test_managed_step_applies_output_schema_guard() -> None:
    step = ManagedLLMStep(
        StepToolEnvelope(
            name="guarded",
            output_schema=_ItemsPayload,
            permission_level=AgentPermissionLevel.draft,
        )
    )

    result = await step.run(lambda: '{"items":"bad"}')

    assert result.status == StepExecutionStatus.degraded
    assert result.degraded is True
    assert result.error_kind == "schema_validation"
    assert result.journal_events[-1]["details"]["output_guard"][
        "validation_error_count"
    ]


@pytest.mark.asyncio
async def test_managed_step_propagates_budget_degradation() -> None:
    step = ManagedLLMStep(StepToolEnvelope(name="budgeted"))
    guard = ContextBudgetGuard(ContextBudget(max_input_chars=4))
    budget_result = guard.enforce_step_input("abcdef")

    result = await step.run(lambda: budget_result)

    assert result.status == StepExecutionStatus.degraded
    assert result.degraded is True
    assert result.error_kind == "context_overflow"
    assert result.output == "abcd"
    assert result.journal_events[-1]["details"]["budget_events"][0]["level"] == (
        "step_input"
    )


@pytest.mark.asyncio
async def test_managed_step_records_token_usage_and_quality_stats_in_journal() -> None:
    step = ManagedLLMStep(StepToolEnvelope(name="metered"))

    result = await step.run(
        lambda: {"ok": True},
        token_usage={"input": 10},
        quality_stats={"scene_count": 2},
    )

    details = result.journal_events[-1]["details"]
    assert details["token_usage"] == {"input": 10}
    assert details["quality_stats"] == {"scene_count": 2}


def test_context_budget_guard_caps_step_input() -> None:
    guard = ContextBudgetGuard(ContextBudget(max_input_chars=12))

    result = guard.enforce_step_input("x" * 20)

    assert result.degraded is True
    assert result.error_kind == "context_overflow"
    assert result.content == "x" * 12
    assert result.events[0].level == "step_input"
    assert result.events[0].reason == "step_input_budget"


def test_context_budget_guard_caps_tool_output() -> None:
    guard = ContextBudgetGuard(ContextBudget(max_output_chars=8))

    result = guard.enforce_tool_output({"content": "abcdefghijklmnop"})

    assert result.degraded is True
    assert len(result.content) == 8
    assert result.events[0].level == "tool_output"


def test_context_budget_guard_snips_old_tool_results_and_preserves_recent() -> None:
    guard = ContextBudgetGuard(ContextBudget(max_input_chars=500))
    results = [
        {"tool": "search", "output": "old-a" * 40},
        {"tool": "read", "output": "old-b" * 40},
        {"tool": "read", "output": "recent"},
    ]

    result = guard.snip_old_tool_results(results, protect_recent=1)

    assert result.degraded is True
    assert result.content[0]["snipped"] is True
    assert result.content[1]["snipped"] is True
    assert result.content[2]["output"] == "recent"
    assert result.events[0].reason == "old_tool_results_snipped"


def test_context_budget_guard_microcompacts_working_context() -> None:
    guard = ContextBudgetGuard(ContextBudget(max_input_chars=180))
    sections = [
        {
            "key": "draft",
            "content": "HEAD" + ("x" * 400) + "TAIL",
        }
    ]

    result = guard.microcompact_context(
        sections,
        head_chars=16,
        tail_chars=16,
    )

    assert result.degraded is True
    assert result.content[0]["microcompacted"] is True
    assert "context microcompacted" in result.content[0]["content"]
    assert result.events[0].level == "working_context"


def test_context_budget_guard_autocompact_fallback_marks_overflow() -> None:
    guard = ContextBudgetGuard(
        ContextBudget(context_limit_tokens=10, trigger_ratio=0.5)
    )

    result = guard.autocompact_fallback("x" * 80)

    assert result.degraded is True
    assert result.error_kind == "context_overflow"
    assert result.content["autocompact_required"] is True
    assert result.events[0].event_type == "autocompact_fallback"
