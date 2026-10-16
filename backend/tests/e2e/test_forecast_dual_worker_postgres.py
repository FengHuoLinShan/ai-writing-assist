"""Run the two default Scene forecasts through the real task lease and offline client."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport
from sqlalchemy import select

from app.main import app
from core.database import get_manager
from infrastructure.llm.client import LLMClient
from infrastructure.llm.schemas import (
    AI_RUN_ENVELOPE_KEY,
    LLMCallResponse,
    LLMUsage,
    read_ai_run_envelope,
)
from infrastructure.tasks.models import AsyncTask
from infrastructure.tasks.worker import TaskWorker
from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID
from modules.account.models import Account
from modules.assistant.forecast import runtime
from modules.assistant.forecast.models import ForecastCandidate
from modules.assistant.forecast.tests.test_forecasts import settings_on
from modules.assistant.models import AssistantRun
from modules.project.models import Project
from modules.story.outline_state.models import Scene
from modules.world.models import Character, CoreEntity
from modules.writing.facade import create_draft_only
from tests.support.http import XhrAsyncClient

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


def _option(direction: str, motive: str) -> dict:
    return {
        "direction_id": direction,
        "motive": motive,
        "motive_reason": "先确认可见线索，再决定是否回应",
        "trigger": "若对方继续问起渡口",
        "behavior": ["先停下", "再问对方看见了什么"],
        "expression": "望向河面",
        "body_language": "肩膀稍稍收紧",
        "voice": {
            "line": "你看见什么了？",
            "delivery": "放轻声音",
            "subtext": "先核对线索",
        },
        "psychology": "想弄清真相，也想保留退路",
        "psychological_trigger": "对方追问",
        "defense": "把话题留在可核对的范围",
        "notices": [],
        "overlooks": [],
        "change": {"emotion": "仍有疑虑", "relationship": "保持距离", "goal": "查明经过"},
        "basis": [{"kind": "creative_choice", "note": "这是作者可选择的表演方向"}],
        "assumptions": ["对话尚未结束"],
    }


@pytest.mark.parametrize("fail_transition", [False, True])
async def test_default_scene_dual_forecast_uses_one_real_worker_budget(
    monkeypatch, fail_transition
):
    novel_id, character_id, scene_id = uuid4(), uuid4(), uuid4()
    async with get_manager().session_factory() as db:
        if await db.get(Account, BOOTSTRAP_ACCOUNT_ID) is None:
            db.add(
                Account(id=BOOTSTRAP_ACCOUNT_ID, support_code="forecast-offline-owner")
            )
        db.add(Project(id=novel_id, owner_id=BOOTSTRAP_ACCOUNT_ID, title="双卡离线验收"))
        await db.flush()
        db.add(
            CoreEntity(
                id=character_id,
                novel_id=novel_id,
                entity_type="character",
                name="阿舟",
                status="canonical",
                hidden_truth="ROLE_PRIVATE_SECRET",
                reveal_level="author_only",
            )
        )
        db.add(
            Character(
                entity_id=character_id, novel_id=novel_id, name="阿舟", status="canonical"
            )
        )
        db.add(
            Scene(
                id=scene_id,
                novel_id=novel_id,
                scene_index=0,
                title="渡口",
                goal="核对渡口线索",
                must_happen="AUTHOR_FUTURE_PLAN",
                chapter_ids=["1"],
                pov_character_id=str(character_id),
                status="canonical",
            )
        )
        await db.flush()
        draft = await create_draft_only(
            db, str(novel_id), 1, "渡口", "她在渡口停下，听见对方问起旧桥。"
        )
        draft_id, source_hash = draft.id, draft.content_hash
        await db.commit()

    settings_on(monkeypatch)

    async def snapshot(_db, _novel):
        return {"offline": True}

    monkeypatch.setattr(runtime, "build_project_llm_execution_snapshot", snapshot)
    calls: list[str] = []
    packets: dict[str, dict] = {}

    class OfflineProvider:
        name = "offline"

        async def generate(self, request):
            schema = json.loads(request.messages[-1].content.split("schema: ", 1)[1])
            name = schema["title"]
            calls.append(name)
            if name == "CharacterResponseForecastOutput":
                packet = json.loads(
                    next(m.content for m in request.messages if m.role == "user")
                )
                packets["role"] = packet
                assert "ROLE_PRIVATE_SECRET" not in json.dumps(packet, ensure_ascii=False)
                assert "AUTHOR_FUTURE_PLAN" not in json.dumps(packet, ensure_ascii=False)
                answer = {
                    "items": [
                        {
                            "proposal": {
                                "title": "保留两种回应",
                                "why_now": "渡口询问尚未解决",
                                "options": [
                                    _option("protect_first", "protect"),
                                    _option("understand_first", "understand"),
                                ],
                                "unknowns": ["对方意图尚不清楚"],
                            }
                        }
                    ]
                }
            elif name == "ForecastOutput":
                if fail_transition:
                    raise RuntimeError("offline transition response lost")
                packet = json.loads(
                    next(m.content for m in request.messages if m.role == "user")
                )
                packets["transition"] = packet
                anchor = packet["sources"][0]["text"][:8]
                answer = {
                    "items": [
                        {
                            "capability_index": 0,
                            "question_kind": "continuation",
                            "anchor_evidence_id": "source_0",
                            "anchor_text": anchor,
                            "proposal": {
                                "title": "渡口转场",
                                "kind": "creative_opportunity",
                                "statements": [
                                    {
                                        "text": anchor,
                                        "basis": "observed",
                                        "evidence_ids": ["source_0"],
                                    }
                                ],
                                "why_now": "当前场景之后需要衔接。",
                                "directions": [
                                    {
                                        "direction_id": "direct_cut",
                                        "title": "直接切场",
                                        "condition": "若下一场已安排",
                                        "proposal": "先保留问题，再切到下一场。",
                                        "narrative_commitment": "low",
                                        "may_leave_open": True,
                                    }
                                ],
                                "verdict": "propose",
                            },
                        }
                    ]
                }
            else:
                assert name == "AuditVerdictOutput"
                answer = {
                    "verdict": "pass",
                    "dimensions": [
                        {"dimension": key, "checked": True}
                        for key in ("prior_prose", "world_rules", "outline")
                    ],
                }
            return LLMCallResponse(
                content=json.dumps(answer, ensure_ascii=False),
                usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                finish_reason="stop",
            )

    provider = OfflineProvider()

    @asynccontextmanager
    async def offline_client(_db, _novel, _snapshot):
        client = LLMClient.from_project_settings(
            {"llm": {"provider_id": "deepseek", "model": "deepseek-flash"}}
        )
        client._provider = provider
        yield client

    monkeypatch.setattr(runtime, "open_project_snapshot_llm_client", offline_client)
    focus = {
        "client_context_id": str(uuid4()),
        "focus_seq": 1,
        "page": "scene",
        "scene_id": str(scene_id),
        "draft_id": draft_id,
        "expected_source_hash": source_hash,
        "editor_state": "saved",
        "explicit_instruction": "只提供可选择的反应和转场",
    }
    async with XhrAsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        submitted = await client.post(
            "/api/assistant/forecasts/evaluate",
            params={"novel_id": str(novel_id)},
            json={
                "operation_id": str(uuid4()),
                "context": focus,
                "horizon": {"unit": "scene"},
            },
        )
        assert submitted.status_code == 202, submitted.text
    run_id = UUID(submitted.json()["run_id"])
    async with get_manager().session_factory() as db:
        run = await db.get(AssistantRun, run_id)
        task_id = run.task_id
        assert run.request_json["selected_capabilities"] == [
            "story.character_response.v2",
            "story.scene_transition.v1",
        ]
    finished = await TaskWorker(db_manager=get_manager()).run_once(
        task_id=task_id, novel_id=novel_id
    )
    assert finished is not None
    async with get_manager().session_factory() as db:
        run = await db.get(AssistantRun, run_id)
        task = await db.get(AsyncTask, task_id)
        cards = (
            await db.scalars(
                select(ForecastCandidate).where(ForecastCandidate.run_id == run_id)
            )
        ).all()
        envelope = read_ai_run_envelope(task.meta[AI_RUN_ENVELOPE_KEY])
        if fail_transition:
            assert finished.status == run.status == "failed"
            assert cards == []
            assert run.checkpoint_json["primary_calculated"]
            assert run.budget_json["usage_unknown"]
            assert envelope.requests_started == 3
            assert envelope.requests_settled == 2
            assert calls == [
                "CharacterResponseForecastOutput",
                "AuditVerdictOutput",
                "ForecastOutput",
            ]
        else:
            assert finished.status == "done"
            assert run.status == "completed"
            assert run.budget_json["requests"] == 4
            assert {card.capability_id for card in cards} == {
                "story.character_response.v2",
                "story.scene_transition.v1",
            }
            assert envelope.requests_started == envelope.requests_settled == 4
            assert calls == [
                "CharacterResponseForecastOutput",
                "AuditVerdictOutput",
                "ForecastOutput",
                "AuditVerdictOutput",
            ]
            assert packets["role"] != packets["transition"]
