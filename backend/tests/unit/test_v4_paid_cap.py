"""Durable spend cap across concurrent requests, failures and process restarts."""

import asyncio
from types import SimpleNamespace

import pytest

from evals.v4_live import Meter, save
from infrastructure.llm.schemas import (
    LLMCallRequest,
    LLMCallResponse,
    LLMStreamChunk,
    LLMUsage,
)


async def test_paid_cap_reserves_before_transport_and_blocks_unknown_usage(tmp_path):
    path = tmp_path / "calls.json"
    meter = Meter(path)
    meter.ledger["calls"] = [{"status": "settled", "cost_upper_usd": 4.97}]
    request = LLMCallRequest(max_tokens=12000)
    provider = SimpleNamespace(_base_url="https://api.deepseek.com")
    called, waiting = [], asyncio.Event()

    async def transport(provider, request):
        called.append(1)
        await waiting.wait()
        return LLMCallResponse(
            usage=LLMUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20)
        )

    charged = meter.wrap(transport)
    first = asyncio.create_task(charged(provider, request))
    await asyncio.sleep(0)
    assert len(called) == 1
    with pytest.raises(RuntimeError, match="cap reached"):
        await charged(provider, request)
    assert len(called) == 1
    assert Meter(path).blocked  # A process interrupted mid-call cannot spend again.
    waiting.set()
    await first
    assert not Meter(path).blocked

    async def failed(provider, request):
        called.append(1)
        raise ConnectionError("usage unknown")

    with pytest.raises(ConnectionError):
        await meter.wrap(failed)(provider, request)
    with pytest.raises(RuntimeError, match="Unreconciled"):
        await Meter(path).wrap(transport)(provider, request)
    assert len(called) == 2


async def test_authorized_unknown_cap_keeps_cost_and_blocks_original_retry(tmp_path):
    path = tmp_path / "calls.json"
    meter = Meter(path)
    provider = SimpleNamespace(_base_url="https://api.deepseek.com")
    request = LLMCallRequest(max_tokens=12000)

    async def failed(provider, request):
        raise ConnectionError("usage unknown")

    with pytest.raises(ConnectionError):
        await meter.wrap(failed)(provider, request)
    before = dict(meter.ledger["calls"][0])
    with pytest.raises(ValueError):
        meter.account_unknown_at_reserved_cap(
            1, request_hash="wrong", authorization="User approved the reserved cap"
        )
    meter.account_unknown_at_reserved_cap(
        1,
        request_hash=before["request_hash"],
        authorization="User approved the reserved cap; do not retry original",
    )
    restored = Meter(path)
    assert not restored.blocked
    call = restored.ledger["calls"][0]
    assert all(call[key] == value for key, value in before.items())
    assert call["status"] == "usage_unknown"
    assert "estimated_cost_usd" not in call
    assert call["budget_resolution"]["amount_usd"] == before["cost_upper_usd"]
    with pytest.raises(RuntimeError, match="must not be retried"):
        await restored.wrap(failed)(provider, request)

    async def succeeded(provider, request):
        return LLMCallResponse(
            usage=LLMUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20)
        )

    await restored.wrap(succeeded)(
        provider, request.model_copy(update={"max_tokens": 100})
    )
    assert len(restored.ledger["calls"]) == 2
    assert restored.ledger["calls"][0]["cost_upper_usd"] == before["cost_upper_usd"]


async def test_explicit_uncapped_ledger_still_blocks_unknown_and_original_retry(tmp_path):
    path = tmp_path / "calls.json"
    meter = Meter(path)
    meter.ledger["cap_usd"] = None
    meter.ledger["calls"] = [{"sequence": 1, "status": "settled", "cost_upper_usd": 5.1}]
    save(path, meter.ledger)
    meter = Meter(path)
    provider = SimpleNamespace(_base_url="https://api.deepseek.com")
    request = LLMCallRequest(max_tokens=100)

    async def failed(provider, request):
        raise ConnectionError("usage unknown")

    with pytest.raises(ConnectionError):
        await meter.wrap(failed)(provider, request)
    assert Meter(path).blocked
    call = meter.ledger["calls"][-1]
    meter.account_unknown_at_reserved_cap(
        call["sequence"],
        request_hash=call["request_hash"],
        authorization="User authorized counting the full reservation",
    )
    assert not Meter(path).blocked
    with pytest.raises(RuntimeError, match="must not be retried"):
        await Meter(path).wrap(failed)(provider, request)


@pytest.mark.parametrize("interrupt", [False, True])
async def test_paid_stream_settles_final_usage_or_retains_cancelled_reservation(
    tmp_path, interrupt
):
    meter = Meter(tmp_path / "calls.json")
    request = LLMCallRequest(max_tokens=100)
    provider = SimpleNamespace(_base_url="https://api.deepseek.com")
    closed = []

    async def transport(provider, request):
        assert meter.ledger["calls"][-1]["status"] == "pending"

        async def chunks():
            try:
                yield LLMStreamChunk(content="新的故事")
                yield LLMStreamChunk(
                    finish_reason="stop",
                    usage=LLMUsage(
                        prompt_tokens=10, completion_tokens=10, total_tokens=20
                    ),
                )
            finally:
                closed.append(True)

        return chunks()

    stream = await meter.wrap_stream(transport)(provider, request)
    reserve = meter.ledger["calls"][0]["cost_upper_usd"]
    assert (await anext(stream)).content == "新的故事"
    if interrupt:
        await stream.aclose()
        assert meter.ledger["calls"][0]["cost_upper_usd"] == reserve
        assert Meter(meter.path).blocked
        assert meter.ledger["calls"][0]["status"] == "usage_unknown"
    else:
        assert len([chunk async for chunk in stream]) == 1
        assert meter.ledger["calls"][0]["status"] == "settled"
        assert meter.ledger["calls"][0]["content"] == "新的故事"
        assert meter.ledger["calls"][0]["usage"]["total_tokens"] == 20
    assert closed == [True]
