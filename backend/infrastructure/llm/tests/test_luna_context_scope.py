"""Frozen native input and explicit range authorization without provider I/O."""

from dataclasses import replace

import pytest
from pydantic import ValidationError

from infrastructure.llm.capabilities import (
    capability_from_execution_snapshot,
    legacy_capability_snapshot,
    resolve_llm_capability_profile,
)
from infrastructure.llm.cli_agent import CLISpec, _command
from infrastructure.llm.codex_provider import CodexProvider, codex_input_tokens
from infrastructure.llm.errors import LLMError
from infrastructure.llm.schemas import (
    AIRunEnvelopeV2,
    AIStepCallKind,
    LLMCallRequest,
    LLMMessage,
    LLMUsage,
    read_ai_run_envelope,
)
from infrastructure.llm.token_estimation import (
    estimate_token_count,
    token_estimation_method,
)
from infrastructure.llm.workflow_budget import (
    AIManagedStepContext,
    AIRunIdentityError,
    managed_step_scope,
    new_ai_run_envelope,
)


def luna_snapshot():
    return {
        "profile": {
            "provider_id": "codex",
            "model": "gpt-6-luna",
            "connection_verified": True,
        },
        "llm_capability_profile": resolve_llm_capability_profile(
            "codex", "gpt-6-luna"
        ).to_snapshot(),
    }


def test_luna_capability_is_explicit_unverified_and_legacy_unchanged():
    profile = resolve_llm_capability_profile("codex", "gpt-6-luna")
    assert (
        profile.context_limit_tokens,
        profile.default_input_budget_tokens,
        profile.story_output_tokens,
        profile.safety_margin_tokens,
        profile.native_auto_compact_tokens,
    ) == (1050000, 500000, 128000, 32000, 800000)
    assert profile.verified_input_ceiling_tokens == 0
    assert profile.calibration_status == "official_spec_runtime_unverified"
    assert (
        resolve_llm_capability_profile(
            "codex", "gpt-5.6-luna"
        ).default_input_budget_tokens
        is None
    )
    old = {
        "profile": {"provider_id": "codex", "model": "gpt-6-luna"},
        "llm_capability_profile": legacy_capability_snapshot("codex", "gpt-6-luna"),
    }
    assert capability_from_execution_snapshot(old).default_input_budget_tokens is None
    assert (
        capability_from_execution_snapshot(old).to_snapshot()
        == old["llm_capability_profile"]
    )


def test_unmapped_luna_uses_byte_upper_bound():
    assert token_estimation_method("gpt-6-luna") == "utf8_byte_upper_bound"
    text = "甲😀abc"
    assert estimate_token_count(text, model="gpt-6-luna") == len(text.encode())


def test_full_input_boundary_checks_envelope_and_schema(monkeypatch):
    provider = CodexProvider.__new__(CodexProvider)
    provider._effort = "max"
    provider._approval_judgment = False
    monkeypatch.setattr(CodexProvider, "validate_connection", lambda self: None)
    capability = resolve_llm_capability_profile("codex", "gpt-6-luna")
    request = LLMCallRequest(
        model="gpt-6-luna",
        messages=[LLMMessage(role="user", content="x" * 150000)],
        max_tokens=128000,
    )
    count = codex_input_tokens(request)
    assert count > 150000  # CLI framing, instructions and envelope are input too.
    provider._execution_capability = replace(
        capability, default_input_budget_tokens=count
    )
    provider.validate_request(request)
    provider._execution_capability = replace(
        capability, default_input_budget_tokens=count - 1
    )
    with pytest.raises(LLMError, match="完整请求"):
        provider.validate_request(request)
    request.response_format = {
        "type": "json_schema",
        "json_schema": {
            "schema": {
                "type": "object",
                "properties": {
                    "evidence": {"type": "string", "description": "证据" * 1000}
                },
            }
        },
    }
    assert codex_input_tokens(request) > count


def test_cli_passes_frozen_window_without_user_catalog(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "infrastructure.llm.cli_agent.shutil.which", lambda command: command
    )
    spec = CLISpec(
        kind="codex",
        command="/synthetic/codex",
        model="gpt-6-luna",
        prompt="{}",
        workspace=tmp_path,
        text_only=True,
        output_schema={"type": "object"},
        max_tool_attempts=0,
        context_window_tokens=1050000,
        auto_compact_token_limit=800000,
    )
    args, _ = _command(spec)
    assert "--ignore-user-config" in args
    assert "model_context_window=1050000" in args
    assert "model_auto_compact_token_limit=800000" in args
    old = replace(spec, context_window_tokens=None, auto_compact_token_limit=None)
    args, _ = _command(old)
    assert not any(arg.startswith("model_context_window=") for arg in args)


async def test_scope_runs_past_old_limit_and_rejects_ds():
    ledger = new_ai_run_envelope(
        operation_id="scope",
        run_id="scope",
        root_capability_id="evolution.reading",
        novel_id="project",
        request_limit=None,
        budget_mode="confirmed_scope",
        scope_fingerprint="a" * 64,
    )
    context = AIManagedStepContext(
        step_name="evolution.discovery",
        call_kind=AIStepCallKind.structured,
        profile_summary={"provider_id": "codex", "model": "gpt-6-luna"},
    )
    with managed_step_scope(context):
        for _ in range(161):
            reservation = await ledger.reserve()
            await ledger.settle(
                reservation,
                usage=LLMUsage(
                    prompt_tokens=100000, completion_tokens=100, total_tokens=100100
                ),
            )
    assert ledger.snapshot().requests_started == 161
    restored = read_ai_run_envelope(ledger.snapshot().model_dump(mode="json"))
    assert isinstance(restored, AIRunEnvelopeV2) and restored.request_limit is None
    with managed_step_scope(
        replace(
            context,
            profile_summary={"provider_id": "deepseek", "model": "deepseek-flash"},
        )
    ):
        with pytest.raises(AIRunIdentityError):
            await ledger.reserve()
    assert ledger.snapshot().requests_started == 161


def test_null_quota_needs_explicit_scope_and_agent_cannot_use_it():
    common = dict(operation_id="x", run_id="x", novel_id="x", request_limit=None)
    with pytest.raises(ValidationError):
        new_ai_run_envelope(
            **common, root_capability_id="evolution.reading", budget_mode="bounded"
        )
    with pytest.raises(ValidationError):
        new_ai_run_envelope(
            **common,
            root_capability_id="assistant.agent",
            budget_mode="confirmed_scope",
            scope_fingerprint="b" * 64,
        )
    with pytest.raises(ValidationError):
        new_ai_run_envelope(
            **common,
            root_capability_id="evolution.reading",
            budget_mode="confirmed_scope",
        )


def test_five_hundred_k_full_input_includes_host_framing(monkeypatch):
    monkeypatch.setattr(CodexProvider, "validate_connection", lambda self: None)
    request = LLMCallRequest(
        model="gpt-6-luna",
        max_tokens=128000,
        messages=[LLMMessage(role="user", content="")],
    )
    overhead = codex_input_tokens(request)
    request.messages[0].content = "x" * (500000 - overhead)
    assert codex_input_tokens(request) == 500000
    provider = CodexProvider.__new__(CodexProvider)
    provider._effort = "max"
    provider._approval_judgment = False
    provider._execution_capability = resolve_llm_capability_profile("codex", "gpt-6-luna")
    provider.validate_request(request)
    request.messages[0].content += "x"
    with pytest.raises(LLMError):
        provider.validate_request(request)


def test_tokenizer_drift_cannot_relax_a_frozen_input_budget(monkeypatch):
    from infrastructure.llm.retry import is_retryable_transport_error
    from modules.evolution.input_budget import fits

    snapshot = luna_snapshot()
    capability = capability_from_execution_snapshot(snapshot)
    request = LLMCallRequest(
        model="gpt-6-luna", messages=[LLMMessage(role="user", content="x" * 510000)]
    )
    assert codex_input_tokens(request) > 500000
    monkeypatch.setattr(
        "infrastructure.llm.token_estimation.token_estimation_method",
        lambda model: "known_model_tokenizer",
    )
    monkeypatch.setattr(CodexProvider, "validate_connection", lambda self: None)
    provider = CodexProvider.__new__(CodexProvider)
    provider._effort = "max"
    provider._approval_judgment = False
    provider._execution_capability = capability
    with pytest.raises(LLMError) as caught:
        provider.validate_request(request)
    assert caught.value.error_kind == "context_policy_changed"
    assert not is_retryable_transport_error(caught.value)
    with pytest.raises(LLMError, match="计量策略"):
        fits(
            snapshot,
            "scene_sample",
            {"messages": [LLMMessage(role="user", content="text")]},
        )


def test_v2_requires_a_declared_budget_policy():
    with pytest.raises(ValidationError):
        AIRunEnvelopeV2(
            operation_id="x",
            run_id="x",
            root_capability_id="evolution.reading",
            novel_id="x",
            request_limit=20,
        )


def test_routed_model_uses_its_frozen_input_budget_and_legacy_route_is_unchanged(
    monkeypatch,
):
    from types import SimpleNamespace

    from infrastructure.llm.client import LLMClient

    client = LLMClient.__new__(LLMClient)
    client._approval_judgment = False
    client._provider = SimpleNamespace(name="openai")
    client._limiter_provider_id = "deepseek"
    client._execution_capability = resolve_llm_capability_profile(
        "deepseek", "deepseek-flash"
    )
    secondary = resolve_llm_capability_profile("deepseek", "deepseek-v4-flash")
    secondary = replace(
        secondary,
        default_input_budget_tokens=10,
        token_estimation_method=token_estimation_method(secondary.model),
    )
    client.cost_routing = {
        "cheap_model": secondary.model,
        "llm_capability_profile": secondary.to_snapshot(),
    }
    request = LLMCallRequest(
        model=secondary.model, messages=[LLMMessage(role="user", content="x" * 4000)]
    )
    with pytest.raises(LLMError, match="冻结输入预算"):
        client._validate_input_budget(request)
    client.cost_routing = {"cheap_model": secondary.model}

    def forbid_current_resolution(*args, **kwargs):
        raise AssertionError("old routed request must not refreeze from current settings")

    monkeypatch.setattr(
        "infrastructure.llm.capabilities.resolve_llm_capability_profile",
        forbid_current_resolution,
    )
    client._validate_input_budget(request)
