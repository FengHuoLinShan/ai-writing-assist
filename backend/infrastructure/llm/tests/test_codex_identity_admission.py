"""Synthetic login and real OS locks; never dispatch a model request."""

from __future__ import annotations

import asyncio
import json
import multiprocessing
import os
from pathlib import Path

import pytest

from infrastructure.llm import codex_admission
from infrastructure.llm.codex_identity import codex_login_identity
from infrastructure.llm.errors import LLMError


def write_identity(directory, *, account="synthetic-a", mode="chatgpt", token="token-a"):
    path = directory / "auth.json"
    path.write_text(
        json.dumps(
            {
                "auth_mode": mode,
                "tokens": {
                    "account_id": account,
                    "access_token": token,
                },
            }
        )
    )
    path.chmod(0o600)
    return path


def test_identity_ignores_token_refresh_but_binds_account(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    write_identity(tmp_path)
    first = codex_login_identity()
    write_identity(tmp_path, token="new-token")
    assert codex_login_identity() == first
    write_identity(tmp_path, account="synthetic-b")
    assert codex_login_identity() != first
    assert "synthetic" not in first and "token" not in first


@pytest.mark.parametrize(
    "failure", ["missing", "api", "malformed", "symlink", "writable"]
)
def test_invalid_login_is_closed(monkeypatch, tmp_path, failure):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    if failure != "missing":
        path = write_identity(tmp_path, mode="apikey" if failure == "api" else "chatgpt")
        if failure == "malformed":
            path.write_text("private token: not-json")
        elif failure == "symlink":
            path.rename(tmp_path / "target")
            path.symlink_to(tmp_path / "target")
        elif failure == "writable":
            path.chmod(0o666)
    with pytest.raises(ValueError, match="ChatGPT") as caught:
        codex_login_identity()
    assert "private token" not in str(caught.value)


def test_platform_read_only_identity_mode_is_compatible(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    path = write_identity(tmp_path)
    path.chmod(0o644)
    assert codex_login_identity()


def _worker(directory, active, peak, ready, hold, cap, crash=False):
    # Spawned workers run the production limiter with separate project scopes.
    from core.config import get_settings
    from infrastructure.llm.limits import LLMLimiterScope, LLMProcessLimiter

    os.environ["CODEX_HOME"] = directory
    os.environ["CODEX_TEXT_MAX_CONCURRENT_REQUESTS"] = str(cap)
    get_settings.cache_clear()
    codex_admission._admission_directory = lambda: Path(directory)

    async def run():
        scope = LLMLimiterScope.for_call(
            novel_id=str(os.getpid()),
            operation_kind="chat",
            base_url="codex://local",
            provider_id="codex",
        )
        async with LLMProcessLimiter().scope(limiter_scope=scope):
            with active.get_lock():
                active.value += 1
                peak.value = max(peak.value, active.value)
            ready.set()
            if crash:
                os._exit(7)
            while not hold.is_set():
                await asyncio.sleep(0.01)
            with active.get_lock():
                active.value -= 1

    asyncio.run(run())


@pytest.mark.parametrize("cap", [2, 6, 8])
def test_account_cap_is_shared_by_spawned_workers(tmp_path, cap):
    write_identity(tmp_path)
    ctx = multiprocessing.get_context("spawn")
    active, peak = ctx.Value("i", 0), ctx.Value("i", 0)
    ready, hold = ctx.Event(), ctx.Event()
    workers = [
        ctx.Process(target=_worker, args=(str(tmp_path), active, peak, ready, hold, cap))
        for _ in range(10)
    ]
    try:
        for worker in workers:
            worker.start()
        import time

        deadline = time.monotonic() + 20
        while peak.value < cap and time.monotonic() < deadline:
            time.sleep(0.02)
        assert peak.value == cap
        hold.set()
        for worker in workers:
            worker.join(timeout=20)
            assert worker.exitcode == 0
        assert active.value == 0 and peak.value == cap
    finally:
        hold.set()
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=5)


@pytest.mark.asyncio
async def test_cancel_waiter_crash_release_and_capacity_mismatch(monkeypatch, tmp_path):
    write_identity(tmp_path)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setattr(codex_admission, "_admission_directory", lambda: tmp_path)
    ctx = multiprocessing.get_context("spawn")
    active, peak = ctx.Value("i", 0), ctx.Value("i", 0)
    ready, hold = ctx.Event(), ctx.Event()
    worker = ctx.Process(
        target=_worker, args=(str(tmp_path), active, peak, ready, hold, 1)
    )
    worker.start()
    try:
        assert await asyncio.to_thread(ready.wait, 20)
        with pytest.raises(LLMError, match="配置不一致"):
            async with codex_admission.codex_account_admission(2):
                pytest.fail("mismatched workers must fail before IO")

        async def wait():
            async with codex_admission.codex_account_admission(1):
                pytest.fail("held account slot must block waiter")

        waiter = asyncio.create_task(wait())
        await asyncio.sleep(0.03)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        worker.terminate()
        await asyncio.to_thread(worker.join, 5)
        # OS process termination releases the slot; no cleanup or forged settlement.
        async with asyncio.timeout(2):
            async with codex_admission.codex_account_admission(2):
                pass
    finally:
        if worker.is_alive():
            worker.terminate()
            worker.join(timeout=5)


@pytest.mark.asyncio
async def test_admission_wait_obeys_run_deadline(monkeypatch, tmp_path):
    from infrastructure.llm import limits
    from infrastructure.llm.workflow_budget import AIRunDeadlineExceededError

    write_identity(tmp_path)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setattr(codex_admission, "_admission_directory", lambda: tmp_path)
    async with codex_admission.codex_account_admission(1):
        monkeypatch.setattr(limits, "_ai_run_remaining_seconds", lambda: 0)
        with pytest.raises(AIRunDeadlineExceededError):
            async with codex_admission.codex_account_admission(1):
                pytest.fail("deadline must prevent IO")
