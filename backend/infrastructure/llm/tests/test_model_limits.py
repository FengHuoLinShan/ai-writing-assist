import asyncio
import json
from types import SimpleNamespace

import pytest

from infrastructure.llm.limits import LLMLimiterScope, LLMProcessLimiter
from infrastructure.llm.model_limits import get_model_limits


def test_limits_are_exact_source_model_defaults():
    settings = SimpleNamespace(
        llm_model_limits_json=json.dumps(
            {
                "subscription/codex/gpt-6-luna": {
                    "concurrency": 16,
                    "input_budget_tokens": 500000,
                },
                "api/deepseek/deepseek-flash": {"concurrency": 3, "rpm": 60},
            }
        )
    )
    assert get_model_limits("codex", "gpt-6-luna", settings=settings).concurrency == 16
    assert (
        get_model_limits("deepseek", "deepseek-flash", settings=settings).concurrency == 3
    )
    assert get_model_limits("deepseek", "other", settings=settings).concurrency == 8


@pytest.mark.parametrize(
    "value", ["[]", "{", '{"api/ds/m":{"concurrency":0}}', '{"api/ds/m":{"rpm":true}}']
)
def test_invalid_limits_fail_before_admission(value):
    with pytest.raises(ValueError, match="LLM_MODEL_LIMITS_JSON"):
        get_model_limits("ds", "m", settings=SimpleNamespace(llm_model_limits_json=value))


async def test_subscription_and_api_each_fill_eight_slots(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "infrastructure.llm.model_admission._admission_directory", lambda: tmp_path
    )
    monkeypatch.setattr(
        "infrastructure.llm.codex_identity.codex_login_identity", lambda: "synthetic"
    )
    monkeypatch.setattr(
        "infrastructure.llm.limits.get_settings",
        lambda: SimpleNamespace(
            llm_model_limits_json="{}",
            llm_circuit_breaker_failure_threshold=5,
            llm_circuit_breaker_reset_seconds=60,
        ),
    )
    limiter = LLMProcessLimiter()
    entered, release = asyncio.Event(), asyncio.Event()
    active = {"codex": 0, "deepseek": 0}

    async def call(provider):
        active[provider] += 1
        if sum(active.values()) == 16:
            entered.set()
        await release.wait()
        active[provider] -= 1

    jobs = [
        asyncio.create_task(
            limiter.run(
                lambda p=provider: call(p),
                limiter_scope=LLMLimiterScope.for_call(
                    novel_id=f"project-{i}",
                    operation_kind="chat",
                    provider_id=provider,
                    base_url="codex://local"
                    if provider == "codex"
                    else "https://api.deepseek.com",
                    model="gpt-6-luna" if provider == "codex" else "deepseek-flash",
                ),
            )
        )
        for provider in active
        for i in range(9)
    ]
    try:
        await asyncio.wait_for(entered.wait(), 3)
        assert active == {"codex": 8, "deepseek": 8}
    finally:
        release.set()
        await asyncio.gather(*jobs)


async def test_model_reconfiguration_waits_only_for_its_own_pool(monkeypatch, tmp_path):
    settings = SimpleNamespace(
        llm_model_limits_json="{}",
        llm_circuit_breaker_failure_threshold=0,
        llm_circuit_breaker_reset_seconds=60,
    )
    monkeypatch.setattr("infrastructure.llm.limits.get_settings", lambda: settings)
    monkeypatch.setattr(
        "infrastructure.llm.model_admission._admission_directory", lambda: tmp_path
    )
    limiter = LLMProcessLimiter()
    a = LLMLimiterScope.for_call(
        novel_id="p",
        operation_kind="chat",
        base_url="https://unit.invalid",
        provider_id="deepseek",
        model="a",
    )
    b = LLMLimiterScope.for_call(
        novel_id="p",
        operation_kind="chat",
        base_url="https://unit.invalid",
        provider_id="deepseek",
        model="b",
    )
    entered, release, changed = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def held():
        async with limiter.scope(limiter_scope=a):
            entered.set()
            await release.wait()

    task = asyncio.create_task(held())
    await entered.wait()
    settings.llm_model_limits_json = '{"api/deepseek/a":{"concurrency":1}}'

    async def new():
        async with limiter.scope(limiter_scope=a):
            changed.set()

    waiting = asyncio.create_task(new())
    await asyncio.sleep(0)
    async with limiter.scope(limiter_scope=b):
        assert not changed.is_set()
    release.set()
    await asyncio.gather(task, waiting)
    assert changed.is_set()


@pytest.mark.parametrize(
    "selector",
    [
        "typo",
        "api/codex/gpt-6-luna",
        "subscription/deepseek/m",
        "api//m",
        "api/ds/",
        "api/ds/m*",
        "api/ ds/m",
    ],
)
def test_invalid_pool_selector_fails_closed(selector):
    with pytest.raises(ValueError, match="LLM_MODEL_LIMITS_JSON"):
        get_model_limits(
            "ds",
            "m",
            settings=SimpleNamespace(
                llm_model_limits_json=json.dumps({selector: {"concurrency": 1}})
            ),
        )
