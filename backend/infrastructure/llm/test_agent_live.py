"""Opt-in, bounded DeepSeek protocol acceptance using an isolated test project."""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import BaseModel
from pydantic_ai import Tool

from infrastructure.llm.agent_runtime import AgentRunBudget, run_project_agent
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from infrastructure.llm.secret_store import encrypt_secret, fingerprint_secret
from modules.account.settings_constants import (
    ACCOUNT_LLM_PROVIDER_TEMPLATES,
    LOCAL_OWNER_ID,
)
from modules.account.settings_repositories import (
    AccountLLMCredentialRepository,
    GlobalLLMDefaultsRepository,
)
from modules.assistant.models import AssistantRun
from modules.project.facade import open_project_llm_client

pytestmark = [
    pytest.mark.real_llm,
    pytest.mark.skipif(
        os.getenv("RUN_ASSISTANT_REAL_LLM") != "1",
        reason="explicit paid assistant protocol gate",
    ),
]


class VerifiedAnswer(BaseModel):
    answer: str


@pytest.mark.asyncio
async def test_deepseek_agent_tool_native_search_and_stream_stop(
    db_session, test_project_id
):
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        pytest.fail("DEEPSEEK_API_KEY is required", pytrace=False)
    await AccountLLMCredentialRepository().upsert(
        db_session,
        {
            "owner_id": LOCAL_OWNER_ID,
            "provider_id": "deepseek",
            "encrypted_api_key": encrypt_secret(key),
            "key_fingerprint": fingerprint_secret(key, purpose="account-llm-api-key"),
            "verified_at": datetime.now(UTC),
        },
    )
    await GlobalLLMDefaultsRepository().upsert(
        db_session,
        {
            "owner_id": LOCAL_OWNER_ID,
            **ACCOUNT_LLM_PROVIDER_TEMPLATES["deepseek"],
            "model": os.getenv("ASSISTANT_REAL_LLM_MODEL")
            or ACCOUNT_LLM_PROVIDER_TEMPLATES["deepseek"]["model"],
        },
    )
    called = []

    async def lookup() -> str:
        """Return the exact code required to answer the user's question."""
        called.append(True)
        return "source-verified-4729"

    # At most six reservations, including one deliberately interrupted request.
    budget = AgentRunBudget(requests=6)
    receipt = AssistantRun(
        novel_id=uuid.UUID(test_project_id),
        owner_id=LOCAL_OWNER_ID,
        request_hash="a" * 64,
    )
    db_session.add(receipt)
    await db_session.flush()
    receipt_id = receipt.id
    started = time.perf_counter()
    gateway_calls = 0

    async def save_budget(value):
        row = await db_session.get(AssistantRun, receipt_id)
        row.budget_json = value
        await db_session.commit()

    async def save_state(value):
        row = await db_session.get(AssistantRun, receipt_id)
        row.checkpoint_json = value
        await db_session.commit()

    class SimulatedInterruptionError(Exception):
        pass

    stage = "tool_loop"
    try:
        async with asyncio.timeout(240):
            async with open_project_llm_client(
                db_session, test_project_id, timeout_override=120
            ) as client:
                generate = client.generate

                async def interrupted_generate(request, *, transport_retries):
                    nonlocal gateway_calls
                    if called:
                        raise SimulatedInterruptionError()
                    gateway_calls += 1
                    return await generate(request, transport_retries=transport_retries)

                client.generate = interrupted_generate
                request = LLMCallRequest(
                    model=client.model_name,
                    max_tokens=4096,
                    messages=[
                        LLMMessage(
                            content=(
                                "先调用 lookup 工具，answer 只填写"
                                "工具给出的完整代码，不得猜测。"
                            )
                        )
                    ],
                )
                with pytest.raises(SimulatedInterruptionError):
                    await run_project_agent(
                        client,
                        request,
                        tools=[Tool(lookup)],
                        deps=None,
                        output_type=VerifiedAnswer,
                        budget=budget,
                        input_limit=8000,
                        checkpoint=save_budget,
                        state_checkpoint=save_state,
                    )
                db_session.expire_all()
                row = await db_session.get(AssistantRun, receipt_id)
                budget = AgentRunBudget.model_validate(row.budget_json)
                saved_state = json.loads(json.dumps(row.checkpoint_json))

                async def resumed_generate(request, *, transport_retries):
                    nonlocal gateway_calls
                    gateway_calls += 1
                    return await generate(request, transport_retries=transport_retries)

                client.generate = resumed_generate
                stage = "persisted_tool_resume"
                result = await run_project_agent(
                    client,
                    LLMCallRequest(
                        model=client.model_name,
                        max_tokens=4096,
                        messages=[
                            LLMMessage(
                                content=(
                                    "先调用 lookup 工具，answer 只填写"
                                    "工具给出的完整代码，不得猜测。"
                                )
                            )
                        ],
                    ),
                    tools=[Tool(lookup)],
                    deps=None,
                    output_type=VerifiedAnswer,
                    budget=budget,
                    input_limit=8000,
                    checkpoint=save_budget,
                    state=saved_state,
                )
                assert len(called) == 1 and result.output.answer == "source-verified-4729"

                async def reserve():
                    budget.reserve(requests=1, web=1)
                    await save_budget(budget.model_dump(mode="json"))

                stage = "native_search"
                # The opt-in acceptance probe tests the adapter before runtime
                # registration. Production clients still require a verified entry.
                web = await client._provider.research(
                    provider_id="deepseek",
                    model=client.model_name,
                    question=(
                        "IANA 的 example.com 示例域名用途是什么？引用 IANA 官方来源。"
                    ),
                    before_request=reserve,
                )
                assert web.sources and web.source_coverage == "cited"
                budget.add_usage(web.usage, requests=web.requests)
                stage = "stream_stop"
                budget.reserve(requests=1)
                stream = client.generate_stream(
                    LLMCallRequest(
                        model=client.model_name,
                        max_tokens=256,
                        messages=[LLMMessage(content="只输出 OK。")],
                    ),
                    transport_retries=False,
                )
                observed = False
                stream_started = time.perf_counter()
                stream_usage = None
                try:
                    async for chunk in stream:
                        stream_usage = chunk.usage or stream_usage
                        if chunk.content:
                            observed = True
                            break
                finally:
                    await stream.aclose()
                    budget.add_usage(stream_usage)
                assert observed
                report = {
                    "provider": "deepseek",
                    "model": client.model_name,
                    "runtime": "pydantic-ai-2.42.0",
                    "observed_at": datetime.now(UTC).isoformat(),
                    "passed": [
                        "tool_call",
                        "persisted_history_resume",
                        "native_web_search",
                        "stream_close",
                    ],
                    "gateway_model_requests": gateway_calls + 1,
                    "native_web_requests": web.requests,
                    "reserved_requests": budget.requests - 6,
                    "tool_executions": len(called),
                    "sources": len(web.sources),
                    "known_input_tokens": budget.prompt_tokens,
                    "known_output_tokens": budget.completion_tokens,
                    "usage_complete": budget.usage_complete,
                    "cost": None,
                    "cost_status": "unknown",
                    "first_stream_text_seconds": time.perf_counter() - stream_started,
                    "total_seconds": time.perf_counter() - started,
                }
                directory = Path(__file__).resolve().parents[2] / ".test-artifacts"
                directory.mkdir(exist_ok=True)
                (directory / "assistant-live-core.json").write_text(
                    json.dumps(report, ensure_ascii=False, indent=2) + "\n"
                )
    except Exception as error:
        # Never include provider payloads, environment values, or connection repr.
        from infrastructure.llm.native_search import NativeSearchUnavailableError

        if isinstance(error, NativeSearchUnavailableError) and error.requests:
            budget.add_usage(error.usage, requests=error.requests)
        directory = Path(__file__).resolve().parents[2] / ".test-artifacts"
        directory.mkdir(exist_ok=True)
        with (directory / "assistant-live-failures.jsonl").open("a") as output:
            output.write(
                json.dumps(
                    {
                        "observed_at": datetime.now(UTC).isoformat(),
                        "stage": stage,
                        "error_class": type(error).__name__,
                        "protocol_diagnostics": getattr(error, "diagnostics", {}),
                        "reserved_requests": budget.requests - 6,
                        "budget": budget.model_dump(mode="json"),
                        "total_seconds": time.perf_counter() - started,
                    }
                )
                + "\n"
            )
        pytest.fail(
            f"Assistant live protocol gate failed at {stage} ({type(error).__name__})",
            pytrace=False,
        )
