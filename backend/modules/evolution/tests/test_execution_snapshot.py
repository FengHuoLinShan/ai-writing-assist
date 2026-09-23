"""Queued model identity and a failed response share the actual run budget."""

import json
from uuid import UUID

import pytest
from sqlalchemy import select

from infrastructure.llm.errors import LLMInvalidResponseError
from infrastructure.llm.providers import OpenAIProvider
from infrastructure.llm.schemas import LLMCallResponse, LLMUsage
from infrastructure.tasks.models import AsyncTask
from modules.account.settings_models import GlobalLLMDefaults
from modules.evolution.models import EvolutionFrozenAttempt
from modules.evolution.pipeline import SamplePendingReconciliationError
from modules.evolution.store import PostgresAttemptStore
from modules.evolution.tasks import (
    EvolutionSceneStepRequest,
    enqueue_evolution_scene_step,
    handle_evolution_scene_step,
)
from modules.evolution.tests.test_source_integrity import seed


@pytest.mark.parametrize("invalid", [False, True])
async def test_queued_snapshot_survives_default_change_and_does_not_retry(
    db_session,
    evolution_project_id,
    account_llm_connection,
    monkeypatch,
    invalid,
):
    db, nid = db_session, evolution_project_id
    scene_id = await seed(db, nid, {1: "天亮了。"})
    request = EvolutionSceneStepRequest(
        novel_id=nid,
        run_key="snapshot-test",
        scene_index=0,
        scene_id=scene_id,
        chapter_index=1,
        scene_text="天亮了。",
        budget_total=1,
    )
    queued = await enqueue_evolution_scene_step(db, request)
    defaults = await db.scalar(
        select(GlobalLLMDefaults).where(
            GlobalLLMDefaults.owner_id == account_llm_connection["owner_id"]
        )
    )
    original_model = defaults.model
    defaults.model = "deepseek-pro"
    await db.commit()
    # Even another Scene enqueue uses this run's original profile.
    assert (await enqueue_evolution_scene_step(db, request))["task_id"] == queued[
        "task_id"
    ]
    calls = []

    async def provider(self, prompt):
        assert not db.in_transaction()
        calls.append(prompt.model)
        return LLMCallResponse(
            content="invalid json"
            if invalid
            else json.dumps({"observations": [], "scene_events": []}),
            finish_reason="stop",
            usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

    monkeypatch.setattr(OpenAIProvider, "generate", provider)
    task = await db.get(AsyncTask, UUID(queued["task_id"]))
    if invalid:
        with pytest.raises(LLMInvalidResponseError):
            await handle_evolution_scene_step(db, task)
        with pytest.raises(SamplePendingReconciliationError):
            await handle_evolution_scene_step(db, task)
    else:
        await handle_evolution_scene_step(db, task)
        assert (await handle_evolution_scene_step(db, task))["recovered"] is True
    assert calls == [original_model]
    run = await PostgresAttemptStore(db, nid).load_run(request.run_key)
    assert run.llm_snapshot_json["profile"]["model"] == original_model
    assert account_llm_connection["api_key"] not in json.dumps(run.llm_snapshot_json)
    assert run.budget_remaining == 0
    assert run.committed_scene_index == (-1 if invalid else 0)
    frozen = await db.scalar(
        select(EvolutionFrozenAttempt).where(
            EvolutionFrozenAttempt.novel_id == UUID(nid),
            EvolutionFrozenAttempt.run_key == request.run_key,
        )
    )
    assert frozen.payload_json["paid_call_receipt"]["model"] == original_model
    assert frozen.payload_json["paid_call_receipt"]["provider"] == "deepseek"
