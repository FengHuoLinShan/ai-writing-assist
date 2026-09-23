"""Durable spend cap across concurrent requests, failures and process restarts."""

import asyncio
from types import SimpleNamespace

import pytest

from evals.v4_live import Meter
from infrastructure.llm.schemas import LLMCallRequest, LLMCallResponse, LLMUsage


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
