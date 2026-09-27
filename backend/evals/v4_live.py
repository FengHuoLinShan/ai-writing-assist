"""Opt-in V4 handler probe using the existing verified default and spend ledger."""

import argparse
import asyncio
import fcntl
import hashlib
import json
import math
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import delete, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.config import Settings, get_settings
from infrastructure.llm.providers import OpenAIProvider

FLASH_MODELS = {"deepseek-flash", "deepseek-v4-flash", "deepseek-v4-flash-vision-exp"}


def save(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str))
    temporary.replace(path)


def peak(when):
    return when.weekday() < 5 and (1 <= when.hour < 4 or 6 <= when.hour < 10)


class Meter:
    """Reserve peak-price cost before each transport attempt, including retries."""

    def __init__(self, path):
        self.path = path
        self.ledger = (
            json.loads(path.read_text())
            if path.exists()
            else {
                "cap_usd": 5,
                "provider": "deepseek",
                "model": "deepseek-flash",
                "pricing_source": "https://api-docs.deepseek.com/quick_start/pricing/",
                "pricing_verified_at": "2026-09-22",
                "calls": [],
            }
        )
        cap = self.ledger["cap_usd"]
        if (
            cap is not None
            and (type(cap) not in (int, float) or not math.isfinite(cap) or cap <= 0)
            or self.ledger["model"] != "deepseek-flash"
        ):
            raise RuntimeError("Ledger does not match this authorization")
        self.blocked = any(self._unresolved(call) for call in self.ledger["calls"])

    @staticmethod
    def _unresolved(call):
        if call["status"] == "settled":
            return False
        resolution = call.get("budget_resolution") or {}
        return not (
            call["status"] == "usage_unknown"
            and resolution.get("kind") == "authorized_reserved_cap"
            and resolution.get("amount_usd") == call["cost_upper_usd"]
            and call["cost_upper_usd"] > 0
            and resolution.get("authorization")
        )

    def account_unknown_at_reserved_cap(self, sequence, *, request_hash, authorization):
        """Record explicit budget authorization; actual usage stays unknown forever."""
        call = next(c for c in self.ledger["calls"] if c["sequence"] == sequence)
        if (
            call["status"] != "usage_unknown"
            or call["request_hash"] != request_hash
            or not authorization.strip()
            or call["cost_upper_usd"] <= 0
        ):
            raise ValueError("Expected the explicitly authorized unknown request")
        if not call.get("budget_resolution"):
            call["budget_resolution"] = {
                "kind": "authorized_reserved_cap",
                "amount_usd": call["cost_upper_usd"],
                "authorization": authorization,
                "recorded_at": datetime.now(UTC).isoformat(),
                "retry_original": False,
            }
            save(self.path, self.ledger)
        self.blocked = any(self._unresolved(c) for c in self.ledger["calls"])

    def _reserve(self, provider, request):
        calls = self.ledger["calls"]
        if self.blocked:
            raise RuntimeError("Unreconciled request: all further paid calls are blocked")
        if (
            provider._base_url.rstrip("/") != "https://api.deepseek.com"
            or request.model not in FLASH_MODELS
        ):
            raise RuntimeError("The verified default does not match this price schedule")
        if not request.max_tokens or request.max_tokens < 1:
            raise RuntimeError("A finite output limit is required before spending")
        payload = request.model_dump(mode="json")
        encoded = json.dumps(payload, ensure_ascii=False).encode()
        request_hash = hashlib.sha256(encoded).hexdigest()
        if any(
            call.get("budget_resolution") and call.get("request_hash") == request_hash
            for call in calls
        ):
            raise RuntimeError("The unknown original request must not be retried")
        reserve = ((len(encoded) + 4096) * 0.30 + request.max_tokens * 1.20) / 1_000_000
        spent = sum(call["cost_upper_usd"] for call in calls)
        cap = self.ledger["cap_usd"]
        if cap is not None and spent + reserve > cap:
            raise RuntimeError(
                f"USD {cap:g} cap reached before the next provider request"
            )
        started = datetime.now(UTC)
        call = {
            "sequence": len(calls) + 1,
            "status": "pending",
            "started_at": started.isoformat(),
            "cost_upper_usd": reserve,
            "request_hash": request_hash,
            "request": payload,
        }
        calls.append(call)
        save(self.path, self.ledger)
        return call, started, reserve

    def _settle(self, call, started, reserve, response):
        usage = response.usage
        if (
            not usage
            or usage.total_tokens <= 0
            or usage.prompt_tokens < 0
            or usage.completion_tokens < 0
        ):
            raise RuntimeError(
                "Usage unknown; reservation retained and paid calls stopped"
            )
        ended = datetime.now(UTC)
        raw_usage = response.raw.get("usage") or {}
        hits = raw_usage.get("prompt_cache_hit_tokens", 0)
        if type(hits) is not int or not 0 <= hits <= usage.prompt_tokens:
            hits = 0
        factor = 1 if peak(started) or peak(ended) else 0.5
        upper = (usage.prompt_tokens * 0.30 + usage.completion_tokens * 1.20) / 1_000_000
        actual = (
            (
                (usage.prompt_tokens - hits) * 0.30
                + hits * 0.006
                + usage.completion_tokens * 1.20
            )
            * factor
            / 1_000_000
        )
        call.update(
            status="settled",
            ended_at=ended.isoformat(),
            cost_upper_usd=upper,
            estimated_cost_usd=actual,
            usage=usage.model_dump(),
            cache_hit_tokens=hits,
            price_band="peak" if factor == 1 else "off_peak",
            provider_call_id=response.raw.get("id"),
            model=response.model,
            finish_reason=response.finish_reason,
            content=response.content,
        )
        if upper > reserve:
            call["status"] = "reservation_exceeded"
            raise RuntimeError("Token reservation exceeded; further paid calls stopped")
        save(self.path, self.ledger)

    def _failed(self, call, error):
        self.blocked = True
        if call["status"] == "pending":
            call.update(status="usage_unknown", error_type=type(error).__name__)
        save(self.path, self.ledger)

    def wrap(self, original):
        async def metered(provider, request):
            call, started, reserve = self._reserve(provider, request)
            try:
                response = await original(provider, request)
                self._settle(call, started, reserve, response)
                return response
            except BaseException as error:
                self._failed(call, error)
                raise

        return metered

    def wrap_stream(self, original):
        """Meter actual streamed chunks; cancellation retains the full reservation."""

        async def metered(provider, request):
            call, started, reserve = self._reserve(provider, request)
            try:
                stream = await original(provider, request)
            except BaseException as error:
                self._failed(call, error)
                raise

            async def observed():
                usage, finish = None, None
                content = []
                try:
                    async for chunk in stream:
                        if chunk.usage is not None:
                            usage = chunk.usage
                        if chunk.finish_reason is not None:
                            finish = chunk.finish_reason
                        content.append(chunk.content or "")
                        yield chunk
                    call["streamed"] = True
                    call["cache_usage_available"] = False
                    self._settle(
                        call,
                        started,
                        reserve,
                        SimpleNamespace(
                            usage=usage,
                            raw={},
                            model=request.model,
                            finish_reason=finish,
                            content="".join(content),
                        ),
                    )
                except BaseException as error:
                    self._failed(call, error)
                    raise
                finally:
                    await stream.aclose()

            return observed()

        return metered


async def run(output, preflight, scenario="vertical"):
    from app.bootstrap import register_container_services
    from app.task_runtime import register_task_handlers
    from evals.v4_vertical_slice import (
        engineering_checks,
        run_preparation_slice,
        run_reading_slice,
        run_slice,
        run_world_slice,
    )
    from infrastructure.tasks.models import AsyncTask
    from infrastructure.tasks.worker import TaskWorker
    from modules.account.context import bind_principal, reset_principal
    from modules.account.contracts import AccountPrincipal
    from modules.account.models import Account
    from modules.account.settings_models import AccountLLMCredential, GlobalLLMDefaults
    from modules.project.models import Project
    from run_worker import (
        _guard_active_task_project_finalize,
        _require_active_task_project,
    )

    # The source connection is explicitly read-only. Only account configuration is read.
    source_url = make_url(Settings().database_url)
    source = create_async_engine(source_url)
    source_sessions = async_sessionmaker(source, expire_on_commit=False)
    async with source_sessions() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        defaults = await db.scalar(
            select(GlobalLLMDefaults).where(GlobalLLMDefaults.owner_id == UUID(int=0))
        )
        if (
            defaults is None
            or defaults.provider_id != "deepseek"
            or defaults.model not in FLASH_MODELS
        ):
            raise RuntimeError(
                "Current default changed; no priced call is authorized by this probe"
            )
        credential = await db.scalar(
            select(AccountLLMCredential).where(
                AccountLLMCredential.owner_id == defaults.owner_id,
                AccountLLMCredential.provider_id == defaults.provider_id,
            )
        )
        if not credential or not credential.verified_at:
            raise RuntimeError("The default provider connection is not verified")
        profile = {
            key: getattr(defaults, key)
            for key in (
                "provider_id",
                "label",
                "base_url",
                "model",
                "timeout",
                "max_tokens",
                "temperature",
                "top_p",
                "extra",
                "creative_mode",
            )
        }
        secret = {
            key: getattr(credential, key)
            for key in (
                "provider_id",
                "encrypted_api_key",
                "key_fingerprint",
                "verified_at",
            )
        }
    await source.dispose()
    name = "ai_novel_agent_e2e_v4_live_20260922"
    target_url = source_url.set(database=name)
    assert target_url.database != source_url.database
    admin = create_async_engine(
        source_url.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    async with admin.connect() as connection:
        exists = await connection.scalar(
            text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": name}
        )
        if not exists:
            await connection.execute(
                text('CREATE DATABASE "ai_novel_agent_e2e_v4_live_20260922"')
            )
    await admin.dispose()
    os.environ.update(
        DATABASE_URL=target_url.render_as_string(hide_password=False),
        E2E_DATABASE_URL=target_url.render_as_string(hide_password=False),
        ASSISTANT_ENABLED="true",
        COLLABORATION_V2_ENABLED="true",
        ASSISTANT_FORECAST_ENABLED="true",
        ASSISTANT_FORECAST_SEMANTIC_ENABLED="true",
        RERANKER_ENABLED="false",
        RAG_QUERY_PLANNER_ENABLED="false",
    )
    get_settings.cache_clear()
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    register_container_services(ignore_existing=True)
    register_task_handlers()
    engine = create_async_engine(target_url, pool_size=6, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owner, nid = uuid4(), uuid4()
    principal = AccountPrincipal(
        account_id=owner,
        status="active",
        identity_type="email",
        support_code="v4-probe-" + owner.hex[:10],
    )
    token = bind_principal(principal)
    original = OpenAIProvider.generate
    report = {
        "mode": "synthetic_native_preflight" if preflight else "paid_default",
        "started_at": datetime.now(UTC).isoformat(),
        "novel_id": str(nid),
        "database": name,
        "provider": profile["provider_id"],
        "model": profile["model"],
        "scenario": scenario,
    }

    def checkpoint(stage):
        report["stage"] = stage
        save(output, report)

    try:
        async with sessions.begin() as db:
            db.add(
                Account(id=owner, status="active", support_code=principal.support_code)
            )
            db.add(
                Project(id=nid, owner_id=owner, title="V4 纵切验收 · " + report["mode"])
            )
            db.add(AccountLLMCredential(owner_id=owner, **secret))
            db.add(GlobalLLMDefaults(owner_id=owner, **profile))
        checkpoint("dedicated_project_created")
        if preflight and scenario == "vertical":
            from pytest import MonkeyPatch

            from modules.evolution.tests.test_g2_consumers import (
                test_real_handlers_connect_understanding_cases_forecast_and_map,
            )

            with MonkeyPatch.context() as patch:
                async with sessions() as db:
                    await test_real_handlers_connect_understanding_cases_forecast_and_map(
                        db, str(nid), None, patch
                    )
            report["preflight_passed"] = True
        else:
            meter = None if preflight else Meter(output.parent / "paid-calls.json")
            first_call = len(meter.ledger["calls"]) if meter else 0
            synthetic_calls = 0
            if preflight:
                from runpy import run_path

                from infrastructure.llm.schemas import LLMCallResponse, LLMUsage

                synthetic_reply = run_path(
                    str(
                        Path(__file__).resolve().parents[1]
                        / "tests/support/creative_browser_provider.py"
                    )
                )["structured_reply"]

                async def synthetic(provider, request):
                    nonlocal synthetic_calls
                    synthetic_calls += 1
                    if scenario in {"preparation", "world"}:
                        return synthetic_reply(request)
                    return LLMCallResponse(
                        content='{"observations":[],"scene_events":[]}',
                        finish_reason="stop",
                        usage=LLMUsage(
                            prompt_tokens=10, completion_tokens=8, total_tokens=18
                        ),
                    )

                OpenAIProvider.generate = synthetic
            else:
                OpenAIProvider.generate = meter.wrap(original)
            worker = TaskWorker(
                db_manager=SimpleNamespace(engine=engine, session_factory=sessions),
                task_preflight=_require_active_task_project,
                task_commit_guard=_guard_active_task_project_finalize,
                heartbeat_interval=30,
            )

            async def execute(task_id, expected="done"):
                await worker.run_once(task_id=task_id, novel_id=str(nid))
                async with sessions() as check:
                    row = await check.get(AsyncTask, UUID(task_id))
                    report.setdefault("worker_tasks", []).append(
                        {
                            "task_id": task_id,
                            "type": row.task_type,
                            "status": row.status,
                            "result": row.result,
                        }
                    )
                    checkpoint("worker_task_finished")
                    if row.status != expected:
                        raise RuntimeError(
                            "Production task did not complete; inspect preserved result"
                        )

            async with sessions() as db:
                await {
                    "reading": run_reading_slice,
                    "preparation": run_preparation_slice,
                    "vertical": run_slice,
                    "world": run_world_slice,
                }[scenario](db, nid, execute, report, checkpoint)
            if scenario == "vertical":
                report["engineering_checks"] = engineering_checks(report)
            else:
                report["transport_calls"] = (
                    len(meter.ledger["calls"]) - first_call if meter else synthetic_calls
                )
                assert report["transport_calls"] == report.get(
                    "expected_transport_calls", 3
                )
            if meter:
                report["estimated_cost_usd"] = sum(
                    call.get("estimated_cost_usd", 0) for call in meter.ledger["calls"]
                )
                report["cost_upper_usd"] = sum(
                    call["cost_upper_usd"] for call in meter.ledger["calls"]
                )
            else:
                report["preflight_passed"] = True
        checkpoint("finished")
    except BaseException as error:
        report["error_type"] = type(error).__name__
        checkpoint("failed")
        raise
    finally:
        OpenAIProvider.generate = original
        async with sessions.begin() as db:
            await db.execute(
                delete(AccountLLMCredential).where(AccountLLMCredential.owner_id == owner)
            )
        reset_principal(token)
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument(
        "--scenario",
        choices=("vertical", "reading", "preparation", "world"),
        default="vertical",
    )
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # One ledger covers all retries/reruns; another process cannot spend concurrently.
    with (args.output.parent / "paid-calls.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        asyncio.run(run(args.output, args.preflight, args.scenario))
