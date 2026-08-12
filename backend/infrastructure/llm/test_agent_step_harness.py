"""Tests for shared LLM step harness primitives."""

from __future__ import annotations

import asyncio
import json

import pytest
from pydantic import BaseModel, Field

from infrastructure.llm.agent_step_harness import (
    MANAGED_LLM_PROVENANCE_KEY,
    AgentPermissionLevel,
    AgentRunJournal,
    ContextBudget,
    ContextBudgetGuard,
    ManagedLLMStep,
    OutputGuard,
    StepExecutionStatus,
    StepToolEnvelope,
    build_managed_llm_provenance,
    managed_llm_provenance_scope,
    merge_managed_llm_provenance,
    run_managed_generate,
    run_managed_structured,
)
from infrastructure.llm.errors import LLMInvalidResponseError
from infrastructure.llm.schemas import LLMCallRequest, LLMCallResponse


class _ItemsPayload(BaseModel):
    items: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class _FakeLLMClient:
    def __init__(self, result=None, exc: Exception | None = None) -> None:
        self.result = result
        self.exc = exc
        self.calls: list[dict] = []
        self.profile_summary = {
            "model": "test-model",
            "max_tokens": 12_000,
            "api_key_configured": True,
        }
        self.runtime_scope = {
            "novel_id": "novel-1",
            "profile_source": "project",
        }

    async def generate(self, request: LLMCallRequest) -> LLMCallResponse:
        self.calls.append({"method": "generate", "request": request})
        if self.exc is not None:
            raise self.exc
        return self.result

    async def generate_structured(
        self,
        request: LLMCallRequest,
        schema: type[BaseModel],
        *,
        max_fix_attempts: int = 2,
        fix_prompt: str | None = None,
        transport_retries: bool = True,
        partial_list_fields: set[str] | None = None,
        diagnostics: list[dict] | None = None,
        format_repair_attempts: int = 0,
    ) -> BaseModel:
        self.calls.append(
            {
                "method": "generate_structured",
                "request": request,
                "schema": schema,
                "max_fix_attempts": max_fix_attempts,
                "fix_prompt": fix_prompt,
                "transport_retries": transport_retries,
                "partial_list_fields": partial_list_fields,
                "diagnostics": diagnostics,
                "format_repair_attempts": format_repair_attempts,
            }
        )
        if diagnostics is not None:
            diagnostics.append({"kind": "fake"})
        if self.exc is not None:
            raise self.exc
        return self.result


@pytest.mark.asyncio
async def test_run_managed_generate_returns_response_without_wrapping() -> None:
    request = LLMCallRequest(model="test-model", messages=[])
    response = LLMCallResponse(content="ok", model="test-model")
    client = _FakeLLMClient(result=response)

    result = await run_managed_generate(
        client,
        request,
        step_name="test.generate",
    )

    assert result is response
    assert client.calls[0]["method"] == "generate"
    assert client.calls[0]["request"] is request


@pytest.mark.asyncio
async def test_managed_generate_records_secret_free_runtime_scope() -> None:
    request = LLMCallRequest(model="phase-model-override", messages=[])
    client = _FakeLLMClient(result=LLMCallResponse(content="ok", model="test-model"))
    journal = AgentRunJournal()
    await run_managed_generate(
        client,
        request,
        step_name="test.runtime",
        journal=journal,
    )

    runtime = journal.model_dump()[-1]["details"]["quality_stats"]["llm_runtime"]
    assert runtime["novel_id"] == "novel-1"
    assert runtime["profile_source"] == "project"
    assert runtime["profile_summary"]["model"] == "phase-model-override"
    assert runtime["profile_summary"]["default_model"] == "test-model"
    assert runtime["profile_summary"]["max_tokens"] == 12_000
    assert "api_key" not in runtime["profile_summary"]


def test_managed_provenance_preserves_account_profile_source() -> None:
    client = _FakeLLMClient()
    client.runtime_scope["profile_source"] = "account"
    client.profile_summary["sources"] = {"model": "account"}

    provenance = build_managed_llm_provenance(
        client,
        step_name="test.account-runtime",
        request=LLMCallRequest(model="test-model", messages=[]),
    )

    assert provenance["profile_source"] == "account"
    assert provenance["profile_summary"]["sources"]["model"] == "account"


@pytest.mark.asyncio
async def test_managed_provenance_is_secret_safe_stable_and_deduplicated() -> None:
    response = LLMCallResponse(content="ok", model="phase-model-override")
    client = _FakeLLMClient(result=response)
    client.profile_summary.update(
        {
            "provider_id": "compatible",
            "base_url_host": (
                "https://writer:password@api.example.test/v1?api_key=query-secret"
            ),
            "api_key": "sk-profile-secret",
            "base_url": "https://api.example.test/v1?token=base-secret",
            "prompt": "private prompt",
            "content": "private novel body",
        }
    )
    request = LLMCallRequest(model="phase-model-override", messages=[])

    with managed_llm_provenance_scope() as records:
        await run_managed_generate(client, request, step_name="test.phase")
        await run_managed_generate(client, request, step_name="test.phase")
        await run_managed_generate(client, request, step_name="test.other_phase")

    assert len(records) == 2
    first = records[0]
    assert set(first) == {
        "step_name",
        "novel_id",
        "profile_source",
        "profile_summary",
        "profile_hash",
    }
    assert first["profile_summary"]["model"] == "phase-model-override"
    assert first["profile_summary"]["default_model"] == "test-model"
    assert first["profile_summary"]["base_url_host"] == "api.example.test"
    assert (
        first["profile_hash"]
        == build_managed_llm_provenance(
            client,
            step_name="test.phase",
            request=request,
        )["profile_hash"]
    )
    assert len(first["profile_hash"]) == 64

    serialized = json.dumps(records, ensure_ascii=False, sort_keys=True)
    for secret in (
        "password",
        "query-secret",
        "sk-profile-secret",
        "base-secret",
        "private prompt",
        "private novel body",
    ):
        assert secret not in serialized

    merged = merge_managed_llm_provenance(
        {MANAGED_LLM_PROVENANCE_KEY: [records[0]]},
        records,
    )
    assert len(merged[MANAGED_LLM_PROVENANCE_KEY]) == 2


@pytest.mark.asyncio
async def test_managed_provenance_scopes_are_isolated_between_async_tasks() -> None:
    async def collect(novel_id: str) -> list[dict]:
        client = _FakeLLMClient(result=LLMCallResponse(content="ok", model="phase-model"))
        client.runtime_scope["novel_id"] = novel_id
        with managed_llm_provenance_scope() as records:
            await asyncio.sleep(0)
            await run_managed_generate(
                client,
                LLMCallRequest(model="phase-model", messages=[]),
                step_name="test.isolated",
            )
            await asyncio.sleep(0)
            return list(records)

    first, second = await asyncio.gather(collect("novel-a"), collect("novel-b"))

    assert [item["novel_id"] for item in first] == ["novel-a"]
    assert [item["novel_id"] for item in second] == ["novel-b"]


@pytest.mark.asyncio
async def test_managed_provenance_records_failed_calls() -> None:
    client = _FakeLLMClient(exc=LLMInvalidResponseError("bad response"))

    with managed_llm_provenance_scope() as records:
        with pytest.raises(LLMInvalidResponseError):
            await run_managed_generate(
                client,
                LLMCallRequest(model="failed-model", messages=[]),
                step_name="test.failed",
            )

    assert len(records) == 1
    assert records[0]["step_name"] == "test.failed"
    assert records[0]["profile_summary"]["model"] == "failed-model"


@pytest.mark.asyncio
async def test_run_managed_generate_rethrows_original_exception() -> None:
    request = LLMCallRequest(model="test-model", messages=[])
    exc = LLMInvalidResponseError("bad")
    client = _FakeLLMClient(exc=exc)

    with pytest.raises(LLMInvalidResponseError) as raised:
        await run_managed_generate(client, request, step_name="test.generate")

    assert raised.value is exc


@pytest.mark.asyncio
async def test_run_managed_structured_forwards_structured_options() -> None:
    request = LLMCallRequest(model="test-model", messages=[])
    output = _ItemsPayload(items=["a"])
    diagnostics: list[dict] = []
    client = _FakeLLMClient(result=output)

    result = await run_managed_structured(
        client,
        request,
        _ItemsPayload,
        step_name="test.structured",
        max_fix_attempts=3,
        fix_prompt="fix it",
        transport_retries=False,
        partial_list_fields={"items"},
        diagnostics=diagnostics,
        format_repair_attempts=1,
    )

    call = client.calls[0]
    assert result is output
    assert call["schema"] is _ItemsPayload
    assert call["max_fix_attempts"] == 3
    assert call["fix_prompt"] == "fix it"
    assert call["transport_retries"] is False
    assert call["partial_list_fields"] == {"items"}
    assert call["diagnostics"] is diagnostics
    assert call["format_repair_attempts"] == 1
    assert diagnostics == [{"kind": "fake"}]


@pytest.mark.asyncio
async def test_run_managed_structured_keeps_duck_typed_request_compatibility() -> None:
    request = object()
    output = _ItemsPayload(items=["a"])
    client = _FakeLLMClient(result=output)

    result = await run_managed_structured(  # type: ignore[arg-type]
        client,
        request,
        _ItemsPayload,
        step_name="test.duck_typed_request",
    )

    assert result is output
    assert client.calls[0]["request"] is request


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
async def test_low_level_output_guard_accepts_valid_json() -> None:
    result = await OutputGuard(_ItemsPayload).validate('{"items":["a"]}')

    assert result.status == StepExecutionStatus.succeeded
    assert result.output.items == ["a"]
    assert result.output.warnings == []


@pytest.mark.asyncio
async def test_low_level_output_guard_normalizes_bare_list() -> None:
    class OneListPayload(BaseModel):
        items: list[str]

    result = await OutputGuard(OneListPayload).validate('["a", "b"]')

    assert result.status == StepExecutionStatus.succeeded
    assert result.output.items == ["a", "b"]


@pytest.mark.asyncio
async def test_low_level_output_guard_repairs_once() -> None:
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
async def test_low_level_output_guard_repair_failure_degrades() -> None:
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
async def test_managed_step_applies_low_level_output_schema_guard() -> None:
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
    assert result.journal_events[-1]["details"]["output_guard"]["validation_error_count"]


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
    guard = ContextBudgetGuard(ContextBudget(context_limit_tokens=10, trigger_ratio=0.5))

    result = guard.autocompact_fallback("x" * 80)

    assert result.degraded is True
    assert result.error_kind == "context_overflow"
    assert result.content["autocompact_required"] is True
    assert result.events[0].event_type == "autocompact_fallback"
