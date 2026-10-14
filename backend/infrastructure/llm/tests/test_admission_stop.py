"""Queued requests never become sent peers after a wave stops."""

import asyncio
from types import SimpleNamespace

import pytest

from infrastructure.llm.agent_runtime import AgentRunBudget
from infrastructure.llm.client import LLMClient
from infrastructure.llm.errors import (
    LLMAdmissionStoppedError,
    LLMError,
    LLMInvalidResponseError,
)
from infrastructure.llm.limits import (
    get_llm_limiter,
    request_admission_scope,
    reset_llm_limiter_for_tests,
)
from infrastructure.llm.schemas import (
    AIStepCallKind,
    LLMCallRequest,
    LLMCallResponse,
    LLMMessage,
    LLMUsage,
)
from infrastructure.llm.workflow_budget import (
    AIManagedStepContext,
    AIRunEnvelope,
    ai_run_scope,
    managed_step_scope,
    new_ai_run_envelope,
    workflow_budget,
)
from modules.evolution.ready import drain_ready


@pytest.mark.parametrize("outcome", ["unknown", "cancel", "known_format"])
async def test_shared_pool_waiters_stop_before_io_and_sent_peer_settles(
    monkeypatch, tmp_path, outcome
):
    reset_llm_limiter_for_tests()
    monkeypatch.setattr(
        "infrastructure.llm.model_admission._admission_directory", lambda: tmp_path
    )
    monkeypatch.setattr(
        "infrastructure.llm.codex_identity.codex_login_identity", lambda: "stop-test"
    )
    held, release_holders, sent, release_peer, queued = (
        asyncio.Event() for _ in range(5)
    )
    holders_entered, jobs_entered, calls = 0, 0, []
    usage = LLMUsage(prompt_tokens=2, completion_tokens=1, total_tokens=3)

    class Provider:
        name = "fake"

        async def generate(self, request):
            index = int(request.messages[0].content)
            calls.append(index)
            if index == 0:
                sent.set()
                await release_peer.wait()
                if outcome == "unknown":
                    raise LLMError("result unknown", error_kind="codex_result_unknown")
                if outcome == "known_format":
                    raise LLMInvalidResponseError("complete format failure", usage=usage)
            return LLMCallResponse(content="ok", usage=usage)

        async def close(self):
            pass

    client = LLMClient()
    original = client._provider
    client._provider = Provider()
    client._limiter_provider_id = "codex"
    client._limiter_base_url = "codex://local"
    client._default_model = "gpt-6-luna"
    limiter = get_llm_limiter()
    scope = client._limiter_scope("chat", "gpt-6-luna")

    async def holder():
        nonlocal holders_entered
        async with limiter.scope(limiter_scope=scope):
            holders_entered += 1
            if holders_entered == 7:
                held.set()
            await release_holders.wait()

    holders = [asyncio.create_task(holder()) for _ in range(7)]
    ledger = new_ai_run_envelope(
        operation_id="stop",
        run_id="stop",
        root_capability_id="evolution.reading",
        novel_id="n",
        request_limit=None,
        budget_mode="confirmed_scope",
        scope_fingerprint="a" * 64,
    )
    context = AIManagedStepContext(
        step_name="delivery",
        call_kind=AIStepCallKind.generate,
        profile_summary={"provider_id": "codex", "model": "gpt-6-luna"},
    )

    async def job(index):
        nonlocal jobs_entered
        jobs_entered += 1
        if jobs_entered == 8:
            queued.set()
        try:
            await client.generate(
                LLMCallRequest(
                    model="gpt-6-luna",
                    messages=[LLMMessage(role="user", content=str(index))],
                ),
                transport_retries=False,
            )
        except LLMInvalidResponseError:
            if outcome != "known_format":
                raise

    task = None
    try:
        await asyncio.wait_for(held.wait(), 2)
        with ai_run_scope(ledger), managed_step_scope(context):
            task = asyncio.create_task(
                drain_ready([lambda i=i: job(i) for i in range(8)], 8)
            )
            await asyncio.wait_for(queued.wait(), 2)
            await asyncio.wait_for(sent.wait(), 2)
            if outcome == "cancel":
                task.cancel()
                await asyncio.sleep(0)
            release_peer.set()
            if outcome == "known_format":
                release_holders.set()
                await asyncio.wait_for(task, 2)
                assert sorted(calls) == list(range(8))
                assert ledger.snapshot().requests_started == 8
            else:
                with pytest.raises(
                    asyncio.CancelledError if outcome == "cancel" else LLMError
                ):
                    await asyncio.wait_for(task, 2)
                # Other roots still hold their slots: unissued peers must settle promptly.
                assert not release_holders.is_set()
                assert calls == [0]
                assert ledger.snapshot().requests_started == 1
                assert ledger.snapshot().requests_unknown == (outcome == "unknown")
                assert ledger.snapshot().requests_settled == (outcome == "cancel")
    finally:
        release_peer.set()
        release_holders.set()
        await asyncio.gather(*holders, return_exceptions=True)
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        await original.close()
        reset_llm_limiter_for_tests()


@pytest.mark.parametrize(
    "path, blocked_checkpoint",
    [
        ("generate", "ledger"),
        ("complete_stream", "ledger"),
        ("stream", "ledger"),
        ("embedding", "ledger"),
        ("generate", "workflow"),
    ],
)
async def test_stop_during_checkpoint_discards_before_provider_task(
    monkeypatch, tmp_path, path, blocked_checkpoint
):
    reset_llm_limiter_for_tests()
    monkeypatch.setattr(
        "infrastructure.llm.model_admission._admission_directory", lambda: tmp_path
    )
    waiting, release, stop = (asyncio.Event() for _ in range(3))
    calls = []

    class Provider:
        name = "fake"

        async def generate(self, request, **kwargs):
            calls.append("generate")

        async def generate_stream(self, request):
            calls.append("stream")

        async def generate_embedding(self, **kwargs):
            calls.append("embedding")

    client = LLMClient()
    original, client._provider = client._provider, Provider()
    monkeypatch.setattr(
        "infrastructure.llm.client.get_settings",
        lambda: SimpleNamespace(
            embedding_provider="openai", embedding_model="embedding-model"
        ),
    )

    async def checkpoint_ledger(snapshot):
        if blocked_checkpoint == "ledger" and snapshot.requests_started == 1:
            waiting.set()
            await release.wait()

    async def checkpoint_workflow(snapshot):
        if blocked_checkpoint == "workflow" and snapshot["requests"] == 1:
            waiting.set()
            await release.wait()

    ledger = AIRunEnvelope(
        new_ai_run_envelope(
            operation_id="checkpoint",
            run_id="checkpoint",
            root_capability_id="writing.generate",
            novel_id="n",
            request_limit=8,
            budget_mode="bounded",
        ).snapshot(),
        on_change=checkpoint_ledger,
    )
    budget = AgentRunBudget()

    async def invoke():
        request = LLMCallRequest(messages=[LLMMessage(role="user", content="合成资料")])
        if path == "stream":
            async for _ in client.generate_stream(request, transport_retries=False):
                pass
        elif path == "embedding":
            await client.generate_embedding("合成资料")
        else:
            await client.generate(
                request,
                transport_retries=False,
                complete_stream=path == "complete_stream",
            )

    task = None
    try:
        with (
            request_admission_scope(stop),
            ai_run_scope(ledger),
            managed_step_scope(
                AIManagedStepContext(
                    step_name="checkpoint", call_kind=AIStepCallKind.generate
                )
            ),
            workflow_budget(budget, checkpoint_workflow),
        ):
            task = asyncio.create_task(invoke())
            await asyncio.wait_for(waiting.wait(), 2)
            stop.set()
            release.set()
            with pytest.raises(LLMAdmissionStoppedError):
                await asyncio.wait_for(task, 2)
        assert calls == []
        assert ledger.snapshot().requests_started == 0
        assert ledger.snapshot().requests_unknown == 0
        assert budget.requests == 0 and budget.usage_complete
    finally:
        release.set()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        await original.close()
        reset_llm_limiter_for_tests()
