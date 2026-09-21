"""Opt-in real-provider probe of one frozen creative prefix through the worker."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from cryptography.fernet import Fernet
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.bootstrap import register_container_services
from app.task_runtime import register_task_handlers
from core.config import get_settings
from evals.creative_forecast import corpus
from infrastructure.llm.providers import OpenAIProvider
from infrastructure.llm.secret_store import encrypt_secret, fingerprint_secret
from infrastructure.tasks.worker import TaskWorker
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.account.models import Account
from modules.account.settings_constants import ACCOUNT_LLM_PROVIDER_TEMPLATES
from modules.account.settings_models import AccountLLMCredential, GlobalLLMDefaults
from modules.assistant.forecast import runtime as forecast_runtime
from modules.assistant.forecast.contracts import EvaluateRequest
from modules.assistant.forecast.models import ForecastCandidate
from modules.assistant.models import AssistantRun
from modules.collaboration import cases, views
from modules.collaboration.contracts import CaseCreate, Grant, RunCreate
from modules.project.models import Project
from modules.writing.facade import create_draft_only
from run_worker import _guard_active_task_project_finalize, _require_active_task_project
from tests.e2e.config import require_e2e_database_url

PEAK_INPUT_PER_MILLION = 0.30
PEAK_OUTPUT_PER_MILLION = 1.20


async def run(case_id: str, output: Path, cap_usd: float, suite: str) -> None:
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise RuntimeError("DEEPSEEK_API_KEY is required")
    # This dedicated test account must not use a shared repository test key.
    os.environ["LLM_SETTINGS_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    if not (get_settings().assistant_enabled and get_settings().collaboration_v2_enabled):
        raise RuntimeError("Enable the two opt-in creative switches for this process")
    if suite == "forecast" and not (
        get_settings().assistant_forecast_enabled
        and get_settings().assistant_forecast_semantic_enabled
    ):
        raise RuntimeError("Enable the two opt-in forecast switches for this process")
    chosen = next((item for item in corpus() if item["id"] == case_id), None)
    if chosen is None:
        raise ValueError("Unknown frozen prefix")
    db_url = require_e2e_database_url()
    register_container_services(ignore_existing=True)
    register_task_handlers()
    output.parent.mkdir(parents=True, exist_ok=True)
    spent, calls = 0.0, []
    original = OpenAIProvider.generate

    async def metered(self, request):
        nonlocal spent
        if self._base_url.rstrip("/") != "https://api.deepseek.com":
            raise RuntimeError("Unexpected provider endpoint")
        if request.model != "deepseek-flash":
            raise RuntimeError("This probe is priced only for deepseek-flash")
        input_bound = (
            sum(len(message.content.encode()) for message in request.messages) + 4096
        )
        output_bound = request.max_tokens or 12000
        reserve = (
            input_bound * PEAK_INPUT_PER_MILLION + output_bound * PEAK_OUTPUT_PER_MILLION
        ) / 1_000_000
        if spent + reserve > cap_usd:
            raise RuntimeError("USD cap reached before the next provider request")
        request_hash = hashlib.sha256(request.model_dump_json().encode()).hexdigest()
        try:
            response = await original(self, request)
            usage = response.usage
            if not usage or not usage.total_tokens:
                raise RuntimeError("Provider usage unknown; stopped paid calls")
            actual = (
                usage.prompt_tokens * PEAK_INPUT_PER_MILLION
                + usage.completion_tokens * PEAK_OUTPUT_PER_MILLION
            ) / 1_000_000
            spent += actual
            calls.append(
                {
                    "request_hash": request_hash,
                    "provider_call_id": response.raw.get("id"),
                    "model": response.model,
                    "input_tokens": usage.prompt_tokens,
                    "output_tokens": usage.completion_tokens,
                    "finish_reason": response.finish_reason,
                    "peak_cost_usd": actual,
                }
            )
            output.with_suffix(".calls.json").write_text(
                json.dumps({"spent_peak_usd": spent, "calls": calls}, indent=2)
            )
            return response
        except Exception:
            if not calls or calls[-1]["request_hash"] != request_hash:
                spent += reserve
                calls.append({"request_hash": request_hash, "usage_unknown": True})
                output.with_suffix(".calls.json").write_text(
                    json.dumps({"spent_peak_usd": spent, "calls": calls}, indent=2)
                )
            raise

    OpenAIProvider.generate = metered
    engine = create_async_engine(db_url, pool_size=6, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    owner, novel_id = uuid4(), uuid4()
    principal = AccountPrincipal(
        account_id=owner,
        status="active",
        identity_type="email",
        support_code="creative-live-" + owner.hex[:10],
    )
    token = bind_principal(principal)
    try:
        async with sessions.begin() as db:
            db.add(
                Account(id=owner, status="active", support_code=principal.support_code)
            )
            db.add(
                Project(
                    id=novel_id,
                    owner_id=owner,
                    title="Frozen creative eval " + case_id,
                )
            )
            db.add(
                AccountLLMCredential(
                    owner_id=owner,
                    provider_id="deepseek",
                    encrypted_api_key=encrypt_secret(os.environ["DEEPSEEK_API_KEY"]),
                    key_fingerprint=fingerprint_secret(
                        os.environ["DEEPSEEK_API_KEY"], purpose="account-llm-api-key"
                    ),
                    verified_at=datetime.now(UTC),
                )
            )
            db.add(
                GlobalLLMDefaults(
                    owner_id=owner,
                    **{
                        **ACCOUNT_LLM_PROVIDER_TEMPLATES["deepseek"],
                        "extra": {"thinking": {"type": "disabled"}},
                    },
                )
            )
            await db.flush()
            draft = await create_draft_only(
                db, str(novel_id), 1, case_id, chosen["prefix"]
            )
            if suite == "creative":
                created = await cases.create_case(
                    db,
                    str(novel_id),
                    CaseCreate(
                        operation_id=uuid4(),
                        goal="仅依据当前前缀，提出局部改进并比较两种不同试改；有意留白可保留。",
                        constraints=[chosen["instruction"], "不使用当前前缀之后的情节"],
                        grant=Grant(
                            resources=[{"kind": "writing_draft", "id": draft.id}],
                            expires_at=datetime.now(UTC) + timedelta(hours=4),
                            request_limit=30,
                        ),
                    ),
                )
                submitted = await cases.submit_run(
                    db,
                    str(novel_id),
                    created["id"],
                    RunCreate(operation_id=uuid4(), expected_goal_version=1),
                )
                run_id, task_id = submitted["run_id"], submitted["task_id"]
            else:
                submitted = await forecast_runtime.submit(
                    db,
                    str(novel_id),
                    EvaluateRequest.model_validate(
                        {
                            "operation_id": str(uuid4()),
                            "context": {
                                "client_context_id": str(uuid4()),
                                "focus_seq": 1,
                                "page": "writing",
                                "draft_id": draft.id,
                                "expected_source_hash": draft.content_hash,
                                "editor_state": "saved",
                                "explicit_instruction": chosen["instruction"],
                            },
                            "horizon": {"unit": "scene"},
                            "requested_capabilities": ["writing.next_beat.v1"],
                        }
                    ),
                )
                run_id = str(submitted.run_id)
                task_id = str((await db.get(AssistantRun, submitted.run_id)).task_id)
        worker = TaskWorker(
            db_manager=SimpleNamespace(engine=engine, session_factory=sessions),
            task_preflight=_require_active_task_project,
            task_commit_guard=_guard_active_task_project_finalize,
            heartbeat_interval=60,
        )
        await worker.run_once(task_id=task_id, novel_id=str(novel_id))
        async with sessions() as db:
            if suite == "creative":
                result = await views.run_view(db, str(novel_id), run_id)
            else:
                forecast_view = await forecast_runtime.view(db, str(novel_id), run_id)
                result = forecast_view.model_dump(mode="json")
                result["candidates"] = [
                    row.payload_json
                    for row in (
                        await db.scalars(
                            select(ForecastCandidate).where(
                                ForecastCandidate.run_id == submitted.run_id
                            )
                        )
                    ).all()
                ]
        output.write_text(
            json.dumps(
                {
                    "case_id": case_id,
                    "suite": suite,
                    "novel_id": str(novel_id),
                    "run_id": run_id,
                    "provider": "deepseek",
                    "model": "deepseek-flash",
                    "thinking": "disabled",
                    "spent_peak_usd": spent,
                    "result": result,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        print(
            json.dumps(
                {"status": result["status"], "calls": len(calls), "peak_cost_usd": spent}
            )
        )
    finally:
        reset_principal(token)
        OpenAIProvider.generate = original
        async with sessions.begin() as db:
            await db.execute(
                delete(AccountLLMCredential).where(
                    AccountLLMCredential.owner_id == owner,
                    AccountLLMCredential.provider_id == "deepseek",
                )
            )
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("case_id")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cap-usd", type=float, required=True)
    parser.add_argument("--suite", choices=["creative", "forecast"], default="creative")
    args = parser.parse_args()
    asyncio.run(run(args.case_id, args.output, args.cap_usd, args.suite))


if __name__ == "__main__":
    main()
