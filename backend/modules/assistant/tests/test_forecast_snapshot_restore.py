"""Forecast runs restore their frozen snapshot through the Project gateway.

G3③c：`open_task_snapshot_client`（local_agent）退役后，语义前瞻的执行客户端
改经 `modules.project.facade.open_project_snapshot_llm_client` 恢复——快照不含
secret，账户 Key 轮换后仍按当前 Key 重建并完成本轮分析。
"""

from dataclasses import replace
from uuid import UUID

from core.config import get_settings
from infrastructure.llm.providers import OpenAIProvider
from infrastructure.llm.schemas import LLMCallResponse, LLMUsage
from infrastructure.tasks.models import AsyncTask
from modules.assistant.forecast import runtime, service
from modules.assistant.forecast.contracts import (
    EvaluateRequest,
    FocusRequest,
)
from modules.assistant.models import AssistantRun
from modules.writing.facade import create_draft_only


async def test_semantic_run_restores_snapshot_after_account_key_rotation(
    db_session, test_project_id, account_llm_connection, monkeypatch
):
    import json

    db, nid = db_session, test_project_id
    settings = replace(
        get_settings(),
        assistant_enabled=True,
        assistant_forecast_enabled=True,
        assistant_forecast_semantic_enabled=True,
    )
    for module in (runtime, service):
        monkeypatch.setattr(module, "get_settings", lambda: settings)
    draft = await create_draft_only(db, nid, 1, "开场", "她接受了旧敌的帮助。")
    await db.flush()
    provider_keys = []

    async def provider(self, request):
        assert not db.in_transaction()
        provider_keys.append(self._api_key)
        schema = json.loads(request.messages[-1].content.split("schema: ", 1)[1])
        if schema["title"] == "ForecastOutput":
            result = {"items": []}
        elif schema["title"] == "AuditVerdictOutput":
            result = {
                "verdict": "pass",
                "findings": [],
                "dimensions": [
                    {"dimension": value, "checked": True}
                    for value in ("prior_prose", "world_rules", "outline")
                ],
            }
        else:
            raise AssertionError(schema["title"])
        return LLMCallResponse(
            content=json.dumps(result, ensure_ascii=False),
            usage=LLMUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
            finish_reason="stop",
        )

    monkeypatch.setattr(OpenAIProvider, "generate", provider)
    monkeypatch.setattr(db, "task_checkpoint_enabled", True, raising=False)
    submission = await runtime.submit(
        db,
        nid,
        EvaluateRequest(
            operation_id=UUID("40000000-0000-4000-8000-000000000001"),
            context=FocusRequest(
                client_context_id=UUID("40000000-0000-4000-8000-000000000002"),
                focus_seq=1,
                page="writing",
                draft_id=draft.id,
            ),
            horizon={"unit": "decision"},
            requested_capabilities=["writing.next_beat.v1"],
        ),
    )
    await db.commit()

    from datetime import UTC, datetime

    from infrastructure.llm.secret_store import encrypt_secret, fingerprint_secret
    from modules.account.settings_repositories import AccountLLMCredentialRepository

    await AccountLLMCredentialRepository().upsert(
        db,
        {
            "owner_id": account_llm_connection["owner_id"],
            "provider_id": "deepseek",
            "encrypted_api_key": encrypt_secret("rotated-account-key"),
            "key_fingerprint": fingerprint_secret(
                "rotated-account-key", purpose="account-llm-api-key"
            ),
            "verified_at": datetime.now(UTC),
        },
    )
    await db.commit()

    run_row = await db.get(AssistantRun, submission.run_id)
    task = await db.get(AsyncTask, run_row.task_id)
    assert task is not None, "forecast task was not enqueued"
    result = await runtime.execute(db, task)
    assert str(result["run_id"]) == str(submission.run_id) and not result.get("cached")
    run = await db.get(AssistantRun, submission.run_id)
    assert run.status == "completed"
    assert run.result_json["completion"] == "complete"
    assert provider_keys, "semantic forecast must reach the provider"
    assert set(provider_keys) == {"rotated-account-key"}
