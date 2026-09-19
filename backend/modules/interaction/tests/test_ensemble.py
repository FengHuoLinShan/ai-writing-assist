"""New RP mode runs through preparation, held audit and atomic node finalization."""

import json
import uuid
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import select

from core.config import get_settings
from infrastructure.llm.schemas import (
    LLMCallResponse,
    LLMStreamChunk,
    LLMToolCall,
    LLMUsage,
)
from infrastructure.tasks.models import AsyncTask
from modules.interaction.models import (
    InteractionActorStateRevision,
    InteractionGenerationAttempt,
)
from modules.interaction.schemas import JourneyCreateRequest
from modules.interaction.services import InteractionService
from modules.interaction.tasks import handle_interaction_story_generate
from modules.interaction.tests.governance_fakes import GovernedAuditMixin
from modules.interaction.tests.test_sources import _ready_source
from modules.story.simulation import RoundResolution


@pytest.mark.parametrize("interrupt", [False, True])
async def test_ensemble_held_stream_commits_actor_state_only_with_story(
    db_session, project_factory, account_llm_connection, monkeypatch, interrupt
):
    settings = replace(
        get_settings(), interaction_agent_enabled=True, interaction_team_enabled=True
    )
    monkeypatch.setattr("core.config.get_settings", lambda: settings)
    monkeypatch.setattr("modules.interaction.services.get_settings", lambda: settings)
    monkeypatch.setattr("modules.project.llm_runtime.get_settings", lambda: settings)
    _, source, anchor, _, key = await _ready_source(db_session, project_factory)
    actor = source.reference_manifest[0]["target_id"]
    compiled = SimpleNamespace(
        blockers=[],
        rendered_context="林默只知道车站的日常。",
        fingerprint="f" * 64,
        snapshot_id=None,
        included_refs=[{"reference_key": key}],
    )
    calls = []

    class Client(GovernedAuditMixin):
        model_name = "deepseek-v4-flash"

        async def generate(self, request, **kwargs):
            calls.append("actor")
            tool = next(t for t in request.tools if t.name.startswith("final_result"))
            return LLMCallResponse(
                tool_calls=[
                    LLMToolCall(
                        id="intent",
                        name=tool.name,
                        arguments=json.dumps(
                            {
                                "kind": "wait",
                                "action": "林默在车站等候",
                                "internal_reason": "私密动机",
                            }
                        ),
                    )
                ],
                usage=LLMUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            )

        async def generate_structured(self, request, schema, **kwargs):
            if schema is RoundResolution:
                calls.append("resolver")
                return schema(outcomes=[{"actor_id": actor, "outcome": "succeeded"}])
            assert "私密动机" not in str(request.messages)
            return await super().generate_structured(request, schema, **kwargs)

        async def generate_stream(self, request, **kwargs):
            calls.append("narrator")
            assert "林默在车站等候" in str(request.messages)
            assert "私密动机" not in str(request.messages)
            yield LLMStreamChunk(content="林默在车站等候。")
            if interrupt:
                raise ConnectionError("synthetic interruption")
            yield LLMStreamChunk(
                finish_reason="stop",
                usage=LLMUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            )

        async def close(self):
            pass

    monkeypatch.setattr(
        "modules.interaction.tasks.create_project_snapshot_llm_client",
        lambda *a, **kw: Client(),
    )
    db_session.task_checkpoint_enabled = True
    response = await InteractionService().create_journey(
        db_session,
        JourneyCreateRequest(
            opening_text="我来到车站，看见林默。",
            idempotency_key="ensemble-integration",
            generation_mode="ensemble",
            source_setup={
                "source_revision_id": str(source.id),
                "progress_anchor_key": anchor["anchor_key"],
                "player_identity": {"kind": "original", "name": "旅人"},
            },
        ),
    )
    attempt = await db_session.get(
        InteractionGenerationAttempt, uuid.UUID(response.attempt.id)
    )
    task_row = await db_session.get(AsyncTask, attempt.task_id)
    task = SimpleNamespace(
        id=task_row.id,
        meta=dict(task_row.meta),
        task_type=task_row.task_type,
        update_progress=lambda _: None,
    )
    await db_session.commit()
    with (
        patch(
            "modules.interaction.generation.compile_interaction_story_context",
            autospec=True,
            return_value=compiled,
        ),
        patch(
            "modules.interaction.ensemble.compile_interaction_story_context",
            autospec=True,
            return_value=compiled,
        ),
    ):
        if interrupt:
            with pytest.raises(ConnectionError):
                await handle_interaction_story_generate(db_session, task)
        else:
            result = await handle_interaction_story_generate(db_session, task)
            assert result["status"] == "completed"
    await db_session.refresh(attempt)
    assert calls == ["actor", "resolver", "narrator"]
    states = list(
        (
            await db_session.scalars(
                select(InteractionActorStateRevision).where(
                    InteractionActorStateRevision.journey_id == attempt.journey_id
                )
            )
        ).all()
    )
    if interrupt:
        assert not states and attempt.visible_text == ""
    else:
        assert len(states) == 1
        assert str(states[0].actor_id) == actor
        assert attempt.visible_text == "林默在车站等候。"
        assert str(states[0].id) in attempt.agent_checkpoint_json["actor_state_refs"]
        assert "私密动机" not in json.dumps(states[0].state_json, ensure_ascii=False)
