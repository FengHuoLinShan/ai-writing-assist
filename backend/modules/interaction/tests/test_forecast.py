"""Journey-only, selected-path projection and provider-only finite analysis."""

import json
from dataclasses import replace
from uuid import UUID, uuid4

from sqlalchemy import func, select

from core.config import get_settings
from infrastructure.llm.providers import OpenAIProvider
from infrastructure.llm.schemas import LLMCallResponse, LLMUsage
from infrastructure.llm.workflow_budget import ai_run_scope, new_ai_run_envelope
from infrastructure.tasks.models import AsyncTask
from modules.assistant.forecast import runtime
from modules.assistant.models import AssistantRun
from modules.interaction.models import (
    InteractionGenerationAttempt,
    InteractionJourney,
    InteractionMessageNode,
)
from modules.interaction.schemas import JourneyCreateRequest
from modules.interaction.services import InteractionService


async def test_rp_forecast_has_no_siblings_or_automatic_story_write(
    db_session, async_client, account_llm_connection, monkeypatch
):
    settings = replace(
        get_settings(),
        assistant_enabled=True,
        assistant_forecast_enabled=True,
        assistant_forecast_semantic_enabled=True,
        interaction_forecast_enabled=True,
    )
    monkeypatch.setattr(runtime, "get_settings", lambda: settings)
    monkeypatch.setattr("modules.interaction.forecast_api.get_settings", lambda: settings)
    service, db = InteractionService(), db_session
    created = await service.create_journey(
        db,
        JourneyCreateRequest(
            opening_text="我来到车站。", idempotency_key="forecast-fixture"
        ),
    )
    journey = await db.get(InteractionJourney, UUID(created.journey.id))
    attempt = await db.get(InteractionGenerationAttempt, UUID(created.attempt.id))
    attempt.status = "completed"
    selected = InteractionMessageNode(
        novel_id=journey.novel_id,
        journey_id=journey.id,
        parent_node_id=journey.selected_leaf_node_id,
        role="assistant",
        message_kind="story",
        content="站员还在等你的回答。",
        completion_state="complete",
    )
    sibling = InteractionMessageNode(
        novel_id=journey.novel_id,
        journey_id=journey.id,
        parent_node_id=journey.selected_leaf_node_id,
        role="assistant",
        message_kind="story",
        content="未选分支的凶手暗号。",
        completion_state="complete",
    )
    db.add_all([selected, sibling])
    await db.flush()
    await service._repo.set_selected_child(
        db,
        journey=journey,
        parent_node_id=journey.selected_leaf_node_id,
        child_node_id=selected.id,
    )
    journey.selected_leaf_node_id = selected.id
    await db.commit()
    jid, nid = str(journey.id), str(journey.novel_id)
    context = dict(
        client_context_id=str(uuid4()),
        focus_seq=1,
        selected_leaf_node_id=str(selected.id),
        selection_epoch=journey.selection_epoch,
        source_context_epoch=journey.source_context_epoch,
        overview_epoch=journey.overview_epoch,
    )
    url = f"/api/interactions/journeys/{jid}/forecasts"
    count = await db.scalar(select(func.count()).select_from(AsyncTask))
    response = await async_client.post(f"{url}/feed", json={"context": context})
    assert response.status_code == 200, response.text
    assert str(sibling.id) not in response.text
    assert await db.scalar(select(func.count()).select_from(AsyncTask)) == count
    denied = await async_client.post(
        "/api/assistant/forecasts/feed",
        params={"novel_id": nid},
        json={
            "context": {
                "client_context_id": str(uuid4()),
                "focus_seq": 1,
                "page": "today",
            }
        },
    )
    assert denied.status_code == 404
    calls = []

    async def provider(self, request):
        assert not db.in_transaction()
        wire = "\n".join(message.content for message in request.messages)
        assert "未选分支的凶手暗号" not in wire
        schema = json.loads(request.messages[-1].content.split("schema: ", 1)[1])
        calls.append(schema["title"])
        value = (
            {
                "items": [
                    {
                        "capability_index": 0,
                        "question_kind": "reaction",
                        "anchor_evidence_id": "source_0",
                        "anchor_text": "站员还在等你的回答",
                        "proposal": {
                            "title": "回应站员的询问",
                            "kind": "next_step",
                            "statements": [
                                {
                                    "text": "站员在等回答。",
                                    "basis": "observed",
                                    "evidence_ids": ["source_0"],
                                }
                            ],
                            "why_now": "对话仍未结束。",
                            "verdict": "propose",
                            "directions": [
                                {
                                    "direction_id": "ask",
                                    "title": "追问",
                                    "condition": "如果想多了解车站",
                                    "proposal": "我问站员：末班车何时离开？",
                                    "narrative_commitment": "low",
                                }
                            ],
                        },
                    }
                ]
            }
            if schema["title"] == "ForecastOutput"
            else {
                "verdict": "pass",
                "dimensions": [
                    {"dimension": key, "checked": True}
                    for key in ("prior_prose", "world_rules", "outline")
                ],
            }
        )
        return LLMCallResponse(
            content=json.dumps(value, ensure_ascii=False),
            usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            finish_reason="stop",
        )

    monkeypatch.setattr(OpenAIProvider, "generate", provider)
    monkeypatch.setattr(db, "task_checkpoint_enabled", True, raising=False)
    result = await async_client.post(
        f"{url}/evaluate", json={"context": context, "operation_id": str(uuid4())}
    )
    assert result.status_code == 202, result.text
    run = await db.get(AssistantRun, UUID(result.json()["run_id"]))
    task = await db.get(AsyncTask, run.task_id)
    envelope = new_ai_run_envelope(
        operation_id=str(run.id),
        run_id=str(run.id),
        root_capability_id="assistant.forecast",
        novel_id=nid,
        request_limit=4,
    )
    with ai_run_scope(envelope):
        await runtime.execute(db, task)
    assert envelope.snapshot().requests_started == 2
    assert envelope.snapshot().requests_settled == 2
    feed = await async_client.post(f"{url}/feed", json={"context": context})
    assert feed.status_code == 200, feed.text
    suggestion = next(item for item in feed.json()["items"] if item["directions"])
    before_nodes = await db.scalar(
        select(func.count()).select_from(InteractionMessageNode)
    )
    preview = await async_client.post(
        f"{url}/candidates/{suggestion['candidate_id']}/prefill",
        json={
            "direction_id": "ask",
            "expected_assessment_hash": suggestion["assessment_hash"],
        },
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["sent"] is False and "末班车" in preview.json()["text"]
    assert (
        await db.scalar(select(func.count()).select_from(InteractionMessageNode))
        == before_nodes
    )
    assert len(calls) == 2
    journey.source_context_epoch += 1
    await db.commit()
    stale = await async_client.post(
        f"{url}/candidates/{suggestion['candidate_id']}/prefill",
        json={
            "direction_id": "ask",
            "expected_assessment_hash": suggestion["assessment_hash"],
        },
    )
    assert stale.status_code == 409
