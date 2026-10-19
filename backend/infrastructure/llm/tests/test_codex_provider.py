"""Codex text isolation and format contracts, without real model requests."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import BaseModel, ConfigDict

from infrastructure.llm.cli_agent import CLIAgentError, CLISpec, _command, run_cli_agent
from infrastructure.llm.codex_provider import CodexProvider, native_schema
from infrastructure.llm.errors import LLMError, LLMInvalidResponseError
from infrastructure.llm.retry import is_retryable_llm_error, is_retryable_transport_error
from infrastructure.llm.schemas import LLMCallRequest, LLMToolDefinition


@pytest.fixture(autouse=True)
def isolated_account_admission(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "infrastructure.llm.codex_identity.codex_login_identity",
        lambda: "synthetic-account",
    )
    monkeypatch.setattr(
        "infrastructure.llm.model_admission._admission_directory", lambda: tmp_path
    )


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str


class Open(BaseModel):
    fields: dict[str, str]


def test_native_schema_preserves_open_maps_and_input():
    original = Closed.model_json_schema()
    expected = json.loads(json.dumps(original))
    native = native_schema(original)
    assert native["additionalProperties"] is False
    assert original == expected
    assert native_schema(Open.model_json_schema()) is None


def spec(tmp_path, executable):
    return CLISpec(
        kind="codex",
        command=str(executable),
        workspace=tmp_path,
        prompt="synthetic",
        model="gpt-6-luna",
        max_tool_attempts=0,
        text_only=True,
        output_schema=Closed.model_json_schema(),
    )


def fake_cli(tmp_path: Path, events, prefix=""):
    executable = tmp_path / "fake-cli"
    executable.write_text(
        "#!/usr/bin/env python3\nimport json, os, sys\n"
        + prefix
        + "\n"
        + "\n".join(f"print({json.dumps(e)!r})" for e in events)
        + "\n"
    )
    executable.chmod(0o700)
    return executable


def completed(answer='{"value":"ok"}'):
    return [
        {"type": "item.completed", "item": {"type": "agent_message", "text": answer}},
        {"type": "turn.completed", "usage": {"input_tokens": 4, "output_tokens": 2}},
    ]


def test_text_command_disables_native_tools_and_user_rules(tmp_path):
    executable = fake_cli(tmp_path, completed())
    args, stdin = _command(spec(tmp_path, executable))
    assert "danger-full-access" not in args
    assert args[args.index("--sandbox") + 1] == "read-only"
    assert "--ignore-user-config" in args and "--ignore-rules" in args
    assert "mcp_servers={}" in args and 'web_search="disabled"' in args
    assert 'model_reasoning_effort="max"' in args
    for feature in (
        "plugins",
        "image_generation",
        "shell_tool",
        "multi_agent",
        "view_image",
    ):
        assert args[args.index(feature) - 1] == "--disable"
    assert "project_doc_max_bytes=0" in args
    assert "skip_host_skill_discovery" in args
    for feature in ("hooks", "apps", "code_mode_host", "unbounded_connection_retries"):
        assert args[args.index(feature) - 1] == "--disable"
    assert (
        (tmp_path / "text-instructions.md").read_text().startswith("Complete exactly one")
    )
    assert stdin == b"synthetic"


@pytest.mark.asyncio
async def test_cli_strips_app_secrets_and_accepts_large_json_line(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-child")
    monkeypatch.setenv("LLM_SETTINGS_ENCRYPTION_KEY", "must-not-reach-child")
    payload = "x" * 70000
    executable = fake_cli(
        tmp_path,
        completed(payload),
        "assert 'OPENAI_API_KEY' not in os.environ; "
        "assert 'LLM_SETTINGS_ENCRYPTION_KEY' not in os.environ",
    )
    result = await run_cli_agent(spec(tmp_path, executable))
    assert result.answer == payload
    assert result.tool_attempts == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "native_tool",
    [
        "command_execution",
        "mcp_tool_call",
        "file_change",
        "web_search",
        "image_generation",
        "future_native_tool",
    ],
)
async def test_cli_completed_native_tool_is_rejected(tmp_path, native_tool):
    executable = fake_cli(
        tmp_path,
        [{"type": "item.completed", "item": {"type": native_tool}}, *completed()],
    )
    with pytest.raises(CLIAgentError, match="原生工具或未知事件"):
        await run_cli_agent(spec(tmp_path, executable))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason", ["stream disconnected", "output schema", "private raw error"]
)
async def test_cli_error_item_preserves_safe_failure_reason(tmp_path, reason):
    executable = fake_cli(
        tmp_path,
        [
            {"type": "item.completed", "item": {"type": "error", "message": reason}},
            *completed(),
        ],
    )
    expected = {
        "stream disconnected": "stream_disconnected",
        "output schema": "output_schema",
    }.get(reason, "unknown")
    with pytest.raises(CLIAgentError, match=expected) as failure:
        await run_cli_agent(spec(tmp_path, executable))
    assert reason not in str(failure.value)


@pytest.mark.asyncio
async def test_cli_incomplete_result_is_not_success(tmp_path):
    executable = fake_cli(tmp_path, completed()[:-1])
    with pytest.raises(CLIAgentError, match="结果不完整"):
        await run_cli_agent(spec(tmp_path, executable))


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(
        "infrastructure.llm.codex_provider.codex_connection_fingerprint",
        lambda: "synthetic-fingerprint",
    )
    return CodexProvider()


@pytest.mark.asyncio
async def test_open_schema_envelope_keeps_dynamic_fields(provider):
    request = LLMCallRequest(
        model="gpt-6-luna",
        response_format={
            "type": "json_schema",
            "json_schema": {"schema": Open.model_json_schema()},
        },
    )
    result = SimpleNamespace(
        answer=json.dumps({"content": json.dumps({"fields": {"arbitrary": "kept"}})}),
        usage={"input_tokens": 1, "output_tokens": 1},
        tool_attempts=0,
    )
    with patch(
        "infrastructure.llm.codex_provider.run_cli_agent",
        autospec=True,
        return_value=result,
    ) as run:
        response = await provider.generate(request)
    assert json.loads(response.content)["fields"] == {"arbitrary": "kept"}
    assert "content" in run.call_args.args[0].output_schema["properties"]
    assert response.raw["output_token_limit_enforced"] is False


@pytest.mark.asyncio
async def test_unknown_cli_completion_is_not_retryable(provider):
    with patch(
        "infrastructure.llm.codex_provider.run_cli_agent",
        autospec=True,
        side_effect=CLIAgentError("unknown"),
    ) as run:
        with pytest.raises(LLMError) as caught:
            await provider.generate(LLMCallRequest(model="gpt-6-luna"))
    assert not is_retryable_llm_error(caught.value)
    assert not is_retryable_transport_error(caught.value)
    assert run.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("setting", ["model", "effort", "wrapper"])
async def test_wrong_native_configuration_stops_before_reservation_or_io(
    provider, stream, setting
):
    from infrastructure.llm.client import LLMClient

    client = LLMClient(
        provider_name="codex",
        default_model="gpt-6-luna",
        api_key="",
        base_url="codex://local",
    )
    with (
        patch(
            "infrastructure.llm.client._reserve_ai_run_request", autospec=True
        ) as reserve,
        patch("infrastructure.llm.codex_provider.run_cli_agent", autospec=True) as native,
    ):
        with pytest.raises(LLMError) as caught:
            request = LLMCallRequest(
                model="gpt-6.1-sol" if setting == "model" else "gpt-6-luna",
                extra=(
                    {"reasoning_effort": "high"}
                    if setting == "effort"
                    else {"codex_text_adapter_version": "codex-text-v2"}
                    if setting == "wrapper"
                    else {}
                ),
            )
            if stream:
                _ = [chunk async for chunk in client.generate_stream(request)]
            else:
                await client.generate(request)
        assert caught.value.error_kind == "codex_configuration"
        reserve.assert_not_called()
        native.assert_not_called()
    await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "answer",
    [
        '{"content":"","tool_calls":[{"name":"shell","arguments":"{}"}]}',
        '{"content":"","tool_calls":[{"name":"lookup","arguments":"[]"}]}',
        '{"content":"","tool_calls":[]}',
    ],
)
async def test_tool_proposals_require_registered_name_object_and_required_choice(
    provider, answer
):
    request = LLMCallRequest(
        model="gpt-6-luna",
        tools=[LLMToolDefinition(name="lookup", parameters={"type": "object"})],
        tool_choice="required",
    )
    result = SimpleNamespace(answer=answer, usage={}, tool_attempts=0)
    with patch(
        "infrastructure.llm.codex_provider.run_cli_agent",
        autospec=True,
        return_value=result,
    ):
        with pytest.raises(LLMInvalidResponseError):
            await provider.generate(request)


@pytest.mark.asyncio
async def test_stream_has_final_usage_and_delayed_content(provider):
    result = SimpleNamespace(
        answer='{"content":"answer"}',
        usage={"input_tokens": 2, "output_tokens": 1},
        tool_attempts=0,
    )
    with patch(
        "infrastructure.llm.codex_provider.run_cli_agent",
        autospec=True,
        return_value=result,
    ):
        chunks = [
            c
            async for c in await provider.generate_stream(
                LLMCallRequest(model="gpt-6-luna")
            )
        ]
    assert chunks[0].content == "answer"
    assert chunks[-1].finish_reason == "stop" and chunks[-1].usage.total_tokens == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_client_outer_timeout_is_unknown_and_never_retried(provider, stream):
    import asyncio

    from infrastructure.llm.client import LLMClient
    from infrastructure.llm.profiles import ResolvedLLMProfile

    profile = ResolvedLLMProfile(
        provider_id="codex",
        label="Codex",
        api_key="",
        base_url="codex://local",
        model="gpt-6-luna",
        timeout=900,
        max_tokens=32768,
        temperature=None,
        top_p=None,
        extra={"reasoning_effort": "max"},
        sources={},
    )
    client = LLMClient.from_resolved_profile(profile)
    client._provider.request_timeout = 0.01

    async def pending(*args, **kwargs):
        await asyncio.sleep(1)

    target = "generate_stream" if stream else "generate"
    with patch.object(
        client._provider, target, autospec=True, side_effect=pending
    ) as run:
        with pytest.raises(LLMError) as caught:
            if stream:
                _ = [c async for c in client.generate_stream(LLMCallRequest())]
            else:
                await client.generate(LLMCallRequest())
    assert caught.value.error_kind == "codex_result_unknown"
    assert not is_retryable_llm_error(caught.value)
    assert not is_retryable_transport_error(caught.value)
    assert run.await_count == 1
    await client.close()


@pytest.mark.asyncio
async def test_gateway_agent_preserves_unset_profile_model_and_executes_product_tool(
    provider,
):
    from pydantic_ai import Tool

    from infrastructure.llm.agent_runtime import AgentRunBudget, run_project_agent
    from infrastructure.llm.client import LLMClient
    from infrastructure.llm.profiles import ResolvedLLMProfile
    from infrastructure.llm.schemas import LLMMessage

    profile = ResolvedLLMProfile(
        provider_id="codex",
        label="Codex",
        api_key="",
        base_url="codex://local",
        model="gpt-6-luna",
        timeout=900,
        max_tokens=32768,
        temperature=None,
        top_p=None,
        extra={"reasoning_effort": "max"},
        sources={},
    )
    client = LLMClient.from_resolved_profile(profile)
    called = []

    async def lookup() -> str:
        """Return a source value."""
        called.append(True)
        return "source-value"

    results = [
        SimpleNamespace(
            answer=json.dumps(
                {"content": "", "tool_calls": [{"name": "lookup", "arguments": "{}"}]}
            ),
            usage={"input_tokens": 1, "output_tokens": 1},
            tool_attempts=0,
        ),
        SimpleNamespace(
            answer=json.dumps({"content": "source-value", "tool_calls": []}),
            usage={"input_tokens": 1, "output_tokens": 1},
            tool_attempts=0,
        ),
    ]
    with patch(
        "infrastructure.llm.codex_provider.run_cli_agent",
        autospec=True,
        side_effect=results,
    ) as run:
        result = await run_project_agent(
            client,
            LLMCallRequest(messages=[LLMMessage(content="lookup")]),
            tools=[Tool(lookup)],
            deps=None,
            budget=AgentRunBudget(),
            input_limit=12000,
        )
    assert result.output == "source-value" and called == [True]
    assert run.await_count == 2
    await client.close()


@pytest.mark.asyncio
async def test_native_failure_diagnostic_never_exposes_message(tmp_path):
    executable = fake_cli(
        tmp_path,
        [
            {
                "type": "turn.failed",
                "error": {"message": "stream disconnected; private-text secret-content"},
            }
        ],
    )
    with pytest.raises(CLIAgentError) as caught:
        await run_cli_agent(spec(tmp_path, executable))
    assert "stream_disconnected" in str(caught.value)
    assert "private-text" not in str(caught.value) and "secret-content" not in str(
        caught.value
    )
    diagnostic = caught.value.diagnostic
    assert diagnostic["turn_failed"] is True
    assert diagnostic["failure_label"] == "stream_disconnected"
    assert "private-text" not in json.dumps(diagnostic)


@pytest.mark.asyncio
async def test_native_exit_code_and_turn_state_are_observable(tmp_path):
    executable = fake_cli(
        tmp_path, [], "sys.stderr.write('private raw text'); sys.exit(17)"
    )
    with pytest.raises(CLIAgentError) as caught:
        await run_cli_agent(spec(tmp_path, executable))
    diagnostic = caught.value.diagnostic
    assert diagnostic["exit_code"] == 17
    assert diagnostic["event_seen"] is False
    assert diagnostic["stopped_by_adapter"] is False
    assert "private raw" not in json.dumps(diagnostic)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_timeout_and_cancel_stop_process_and_record_metadata(tmp_path, cancel):
    import asyncio
    from dataclasses import replace

    executable = fake_cli(tmp_path, [], "import time; time.sleep(30)")
    task = asyncio.create_task(
        run_cli_agent(
            replace(
                spec(tmp_path, executable),
                timeout_seconds=30 if cancel else 0.05,
            )
        )
    )
    if cancel:
        await asyncio.sleep(0.05)
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else CLIAgentError) as caught:
        await task
    diagnostic = caught.value.diagnostic
    assert diagnostic["failure_label"] == ("cancelled" if cancel else "timeout")
    assert diagnostic["stopped_by_adapter"] is True
    assert diagnostic["exit_code"] is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("cap", [2, 3, 4, 6, 8])
async def test_codex_admission_is_shared_across_projects_and_precedes_provider_io(
    monkeypatch, cap
):
    import asyncio

    from infrastructure.llm.limits import LLMLimiterScope, LLMProcessLimiter

    monkeypatch.setenv(
        "LLM_MODEL_LIMITS_JSON",
        json.dumps({"subscription/codex/legacy": {"concurrency": cap}}),
    )
    from core.config import get_settings

    get_settings.cache_clear()
    limiter = LLMProcessLimiter()
    active = 0
    peak = 0

    async def one(index):
        nonlocal active, peak
        scope = LLMLimiterScope.for_call(
            novel_id=str(index),
            operation_kind="chat",
            base_url="codex://local",
            provider_id="codex",
        )
        async with limiter.scope(limiter_scope=scope):
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.02)
            active -= 1

    await asyncio.gather(*(one(i) for i in range(8)))
    assert peak == cap
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_cancelled_codex_waiter_does_not_leak_admission(monkeypatch):
    from core.config import get_settings

    monkeypatch.setenv(
        "LLM_MODEL_LIMITS_JSON", '{"subscription/codex/legacy":{"concurrency":2}}'
    )
    get_settings.cache_clear()
    import asyncio

    from infrastructure.llm.limits import LLMLimiterScope, LLMProcessLimiter

    limiter = LLMProcessLimiter()
    scope = LLMLimiterScope.for_call(
        novel_id="one",
        operation_kind="chat",
        base_url="codex://local",
        provider_id="codex",
    )
    release = asyncio.Event()
    ready = asyncio.Event()
    entered = 0

    async def hold():
        nonlocal entered
        async with limiter.scope(limiter_scope=scope):
            entered += 1
            if entered == 2:
                ready.set()
            await release.wait()

    first = [asyncio.create_task(hold()) for _ in range(2)]
    await ready.wait()
    waiter = asyncio.create_task(hold())
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    release.set()
    await asyncio.gather(*first)
    await asyncio.gather(hold(), hold())
    assert entered == 4


@pytest.mark.asyncio
async def test_known_disabled_feature_notices_are_not_native_tool_attempts(tmp_path):
    notices = [
        {
            "type": "item.completed",
            "item": {
                "type": "error",
                "message": (
                    "Under-development features enabled: "
                    "skip_host_skill_discovery. Notice only."
                ),
            },
        },
        {
            "type": "item.completed",
            "item": {
                "type": "error",
                "message": (
                    "Code Mode is unavailable because code-mode host is disabled. "
                    "Code mode will fail closed; enable `features.code_mode_host` "
                    "and install `codex-code-mode-host`."
                ),
            },
        },
    ]
    executable = fake_cli(tmp_path, [*notices, *completed()])
    result = await run_cli_agent(spec(tmp_path, executable))
    assert result.tool_attempts == 0
    assert result.answer == '{"value":"ok"}'


def test_text_instructions_continue_after_product_tool_result():
    from infrastructure.llm.cli_agent import CODEX_TEXT_INSTRUCTIONS

    assert "chronological conversation" in CODEX_TEXT_INSTRUCTIONS
    assert "tool_calls=[]" in CODEX_TEXT_INSTRUCTIONS


def test_uncapped_codex_output_does_not_imply_truncation():
    from infrastructure.llm.client import _looks_truncated_response

    assert not _looks_truncated_response(
        finish_reason="stop",
        completion_tokens=4096,
        max_tokens=2048,
        output_token_limit_enforced=False,
    )
    assert _looks_truncated_response(
        finish_reason="length",
        completion_tokens=4096,
        max_tokens=2048,
        output_token_limit_enforced=False,
    )


@pytest.mark.asyncio
async def test_completed_invalid_envelope_retains_known_receipt_usage(provider):
    from unittest.mock import create_autospec

    from infrastructure.llm.client import _settle_ai_run_request
    from infrastructure.llm.workflow_budget import AIRequestOutcome, AIRunEnvelope

    result = SimpleNamespace(
        answer='{"content":"not JSON"}',
        usage={"input_tokens": 4, "output_tokens": 2},
        tool_attempts=0,
    )
    with patch(
        "infrastructure.llm.codex_provider.run_cli_agent",
        autospec=True,
        return_value=result,
    ):
        with pytest.raises(LLMInvalidResponseError) as caught:
            await provider.generate(
                LLMCallRequest(
                    model="gpt-6-luna", response_format={"type": "json_object"}
                )
            )
    assert caught.value.usage.total_tokens == 6
    ledger = create_autospec(AIRunEnvelope, instance=True)
    reservation = object()
    await _settle_ai_run_request(ledger, reservation, usage=None, error=caught.value)
    assert ledger.settle.await_args.kwargs["usage"] == caught.value.usage
    assert ledger.settle.await_args.kwargs["outcome"] == AIRequestOutcome.failed


@pytest.mark.asyncio
async def test_known_codex_format_failure_closes_agent_pending_request(provider):
    from infrastructure.llm.agent_runtime import AgentRunBudget, run_project_agent
    from infrastructure.llm.client import LLMClient
    from infrastructure.llm.profiles import ResolvedLLMProfile
    from infrastructure.llm.schemas import LLMMessage

    profile = ResolvedLLMProfile(
        provider_id="codex",
        label="Codex",
        api_key="",
        base_url="codex://local",
        model="gpt-6-luna",
        timeout=900,
        max_tokens=32768,
        temperature=None,
        top_p=None,
        extra={"reasoning_effort": "max"},
        sources={},
    )
    client = LLMClient.from_resolved_profile(profile)
    budget = AgentRunBudget()
    result = SimpleNamespace(
        answer='{"content":123}',
        usage={"input_tokens": 4, "output_tokens": 2},
        tool_attempts=0,
    )
    with patch(
        "infrastructure.llm.codex_provider.run_cli_agent",
        autospec=True,
        return_value=result,
    ):
        with pytest.raises(LLMInvalidResponseError):
            await run_project_agent(
                client,
                LLMCallRequest(messages=[LLMMessage(content="return an answer")]),
                tools=[],
                deps=None,
                budget=budget,
                input_limit=12000,
            )
    assert budget.requests == 1
    assert budget.pending_usage == 0 and budget.usage_complete
    assert budget.prompt_tokens == 4 and budget.completion_tokens == 2
    await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message, expected",
    [
        ("Invalid schema: private manuscript sk-secret", "output_schema"),
        ("unexpected argument --private-flag secret-content", "cli_configuration"),
        ("stream disconnected; private-novel", "stream_disconnected"),
        ("Unauthorized: sk-sensitive-value", "authentication"),
        ("unrecognized private error with secret-content", "unknown"),
    ],
)
async def test_native_stderr_exit_diagnostic_is_label_only(tmp_path, message, expected):
    executable = fake_cli(tmp_path, [], f"sys.stderr.write({message!r}); sys.exit(1)")
    with pytest.raises(CLIAgentError) as caught:
        await run_cli_agent(spec(tmp_path, executable))
    assert f"（{expected}）" in str(caught.value)
    assert "private" not in str(caught.value) and "sk-" not in str(caught.value)
    assert "secret" not in str(caught.value)


@pytest.mark.asyncio
async def test_split_stderr_keyword_is_classified_without_exposing_tail(tmp_path):
    executable = fake_cli(
        tmp_path,
        [],
        "import time; sys.stderr.write('private-novel stream dis'); sys.stderr.flush(); "
        "time.sleep(0.05); sys.stderr.write('connected sk-secret'); sys.exit(1)",
    )
    with pytest.raises(CLIAgentError, match="stream_disconnected") as caught:
        await run_cli_agent(spec(tmp_path, executable))
    assert "private-novel" not in str(caught.value) and "sk-secret" not in str(
        caught.value
    )


@pytest.mark.asyncio
async def test_stderr_notice_does_not_turn_completed_result_into_failure(tmp_path):
    executable = fake_cli(
        tmp_path,
        completed(),
        "sys.stderr.write('previous stream disconnected; private-notice')",
    )
    result = await run_cli_agent(spec(tmp_path, executable))
    assert result.answer == '{"value":"ok"}'


@pytest.mark.asyncio
async def test_approval_client_alone_allows_low_and_emits_low_native_config(
    provider, tmp_path
):
    from dataclasses import replace

    from infrastructure.llm.client import LLMClient

    request = LLMCallRequest(
        model="gpt-6-luna",
        extra={"reasoning_effort": "low"},
        response_format={
            "type": "json_schema",
            "json_schema": {"schema": Closed.model_json_schema()},
        },
    )
    with pytest.raises(LLMError):
        provider.validate_request(request)
    approval = CodexProvider(approval_judgment=True)
    approval.validate_request(request)
    result = SimpleNamespace(
        answer=json.dumps({"data": {"value": "allow"}}),
        usage={"input_tokens": 1, "output_tokens": 1},
        tool_attempts=0,
    )
    with patch(
        "infrastructure.llm.codex_provider.run_cli_agent",
        autospec=True,
        return_value=result,
    ) as run:
        response = await approval.generate(request)
    assert run.call_args.args[0].approval_judgment is True
    assert response.raw["reasoning_effort"] == "low"
    executable = fake_cli(tmp_path, completed())
    args, _ = _command(replace(spec(tmp_path, executable), approval_judgment=True))
    assert 'model_reasoning_effort="low"' in args
    assert 'model_reasoning_effort="max"' not in args
    with pytest.raises(LLMError):
        approval.validate_request(
            LLMCallRequest(model="gpt-6-luna", extra={"reasoning_effort": "max"})
        )
    with pytest.raises(LLMError, match="无工具"):
        approval.validate_request(
            LLMCallRequest(model="gpt-6-luna", extra={"reasoning_effort": "low"})
        )
    with pytest.raises(ValueError, match="生成质量覆盖"):
        LLMClient(provider_name="codex", high_quality=True, approval_judgment=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "input_tokens,cached,accepted",
    [
        (4, None, False),
        (4, 0, True),
        (4, 3, True),
        (4, -1, False),
        (4, True, False),
        (4, 5, False),
        (None, 0, False),
        (True, 0, False),
        (-1, 0, False),
    ],
)
async def test_native_cached_input_usage_reaches_safe_structured_diagnostic(
    provider, input_tokens, cached, accepted
):
    from infrastructure.llm.client import _cache_usage_diagnostic

    usage = {"output_tokens": 2}
    if input_tokens is not None:
        usage["input_tokens"] = input_tokens
    if cached is not None:
        usage["cached_input_tokens"] = cached
    with patch(
        "infrastructure.llm.codex_provider.run_cli_agent",
        autospec=True,
        return_value=SimpleNamespace(
            answer='{"content":"private output"}', usage=usage, tool_attempts=0
        ),
    ):
        response = await provider.generate(LLMCallRequest(model="gpt-6-luna"))
    diagnostic = _cache_usage_diagnostic(response)
    assert diagnostic["prompt_tokens"] == (input_tokens or 0)
    if not accepted:
        assert "cache_hit_tokens" not in diagnostic
        assert "cache_miss_tokens" not in diagnostic
    else:
        assert diagnostic["cache_hit_tokens"] == cached
        assert diagnostic["cache_miss_tokens"] == input_tokens - cached
    assert "private output" not in repr(diagnostic)


@pytest.mark.asyncio
@pytest.mark.parametrize("cached", [None, 0, 3, 5, -1, True])
async def test_native_event_cache_survives_cli_decoder(provider, tmp_path, cached):
    from infrastructure.llm.client import _cache_usage_diagnostic

    events = completed('{"content":"private output"}')
    if cached is not None:
        events[-1]["usage"]["cached_input_tokens"] = cached
    provider.command = str(fake_cli(tmp_path, events))
    response = await provider.generate(LLMCallRequest(model="gpt-6-luna"))
    diagnostic = _cache_usage_diagnostic(response)
    assert diagnostic["prompt_tokens"] == 4
    assert response.usage.completion_tokens == 2
    if type(cached) is int and 0 <= cached <= 4:
        assert diagnostic["cache_hit_tokens"] == cached
        assert diagnostic["cache_miss_tokens"] == 4 - cached
    else:
        assert "cache_hit_tokens" not in diagnostic
        assert "cache_miss_tokens" not in diagnostic
    assert "private output" not in repr(diagnostic)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "usage",
    [
        {"cached_input_tokens": 3},
        {"input_tokens": True, "output_tokens": -1, "cached_input_tokens": 0},
    ],
)
async def test_cache_alone_cannot_settle_unknown_native_usage(provider, tmp_path, usage):
    events = completed('{"content":"private output"}')
    events[-1]["usage"] = usage
    provider.command = str(fake_cli(tmp_path, events))
    with pytest.raises(LLMError) as caught:
        await provider.generate(LLMCallRequest(model="gpt-6-luna"))
    assert caught.value.error_kind == "codex_result_unknown"
