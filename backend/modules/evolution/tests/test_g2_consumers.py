"""Production handlers share one source chain; the provider alone is synthetic."""

import json
from dataclasses import replace
from uuid import UUID

import pytest

from core.config import get_settings
from core.errors import ConflictError
from evals.v4_vertical_slice import PROSE, engineering_checks, run_slice
from infrastructure.llm.providers import OpenAIProvider
from infrastructure.llm.schemas import LLMCallResponse, LLMUsage
from infrastructure.tasks.models import AsyncTask
from modules.assistant.forecast import runtime as forecasts
from modules.assistant.forecast.tests.test_forecasts import settings_on
from modules.collaboration import cases, runtime
from modules.evolution.contracts import CommittedUnderstanding
from modules.evolution.facade import read_committed_understanding
from modules.evolution.tasks import handle_evolution_scene_step


async def test_real_handlers_connect_understanding_cases_forecast_and_map(
    db_session, test_project_id, account_llm_connection, monkeypatch
):
    db, nid = db_session, test_project_id
    settings_on(monkeypatch)
    settings = replace(
        get_settings(), assistant_enabled=True, collaboration_v2_enabled=True
    )
    monkeypatch.setattr(cases, "get_settings", lambda: settings)
    monkeypatch.setattr(db, "task_checkpoint_enabled", True, raising=False)
    report, prompts, stages = {}, {}, []
    understanding = "两次出现不能证明中间路线，封锁仍只是青竹的说法。"

    async def provider(self, request):
        assert not db.in_transaction()
        contract = json.loads(request.messages[-1].content.split("schema: ", 1)[1])
        schema = contract["title"]
        user = next(m.content for m in request.messages if m.role == "user")
        prompts.setdefault(schema, []).append(user)
        inputs = json.loads(user) if schema == "GraphDelta" else {}
        if schema == "SceneSample":
            index = len(prompts[schema]) - 1
            location = ("白石城", "渡口")[index]
            value = {
                "observations": [
                    {
                        "predicate": f"林舟出现在{location}",
                        "quote": f"林舟出现在{location}",
                        "modality": "event_observed",
                        "mentions": [{"surface": "林舟", "entity_type": "character"}],
                    }
                ],
                "scene_events": [
                    {
                        "dimension": "locations",
                        "event_type": "entity_moved",
                        "subject_surface": "林舟",
                        "source_observation_indices": [0],
                        "snapshot_after": {"text_state": location},
                    }
                ],
            }
            if index == 0:
                value["observations"].append(
                    {
                        "predicate": "青竹声称渡口已经封锁",
                        "quote": "青竹说渡口已经封锁",
                        "modality": "character_statement",
                        "mentions": [{"surface": "青竹", "entity_type": "character"}],
                    }
                )
                value["scene_events"].append(
                    {
                        "dimension": "knowledge",
                        "event_type": "knowledge_changed",
                        "subject_surface": "青竹",
                        "knowledge_subject": "青竹",
                        "source_observation_indices": [1],
                        "snapshot_after": {
                            "target_type": "event",
                            "known_content": "渡口已经封锁",
                            "knowledge_level": "rumor",
                        },
                    }
                )
        elif schema == "StateReview":
            from tests.support.evolution_review import frozen_state_review

            value = (await frozen_state_review(**json.loads(user)))["result"]
        elif schema == "GraphDelta":
            assert contract["$defs"]["RecipeWorkProposal"]["properties"]["capability"][
                "enum"
            ] == ["investigate", "countercheck", "compare"]
            assert "再 test" not in request.messages[0].content
            assert PROSE[0] in inputs["sources"]
            assert '"chapter_index": 1' in inputs["sources"]
            revision = inputs["expected_plan_revision"]
            if revision:
                assert inputs["work"][0]["proposal"]["question"] == "哪些事实尚不能确定？"
            value = {
                "expected_plan_revision": revision,
                "reason": "检查人物的知识边界",
                "finish": revision > 0,
                "items": []
                if revision
                else [
                    {
                        "logical_key": "inspect",
                        "capability": "investigate",
                        "question": "哪些事实尚不能确定？",
                    }
                ],
            }
        elif schema == "WorkOutput":
            assert "世界压力检查先用 scenarios" not in request.messages[0].content
            value = {
                "summary": understanding,
                "claims": [
                    {
                        "kind": "interpretation",
                        "text": understanding,
                        "evidence_keys": [
                            f"writing_draft:{draft}" for draft in report["draft_ids"][:2]
                        ],
                    }
                ],
            }
        elif schema == "AuditVerdictOutput":
            value = {
                "verdict": "pass",
                "dimensions": [
                    {"dimension": name, "checked": True}
                    for name in ("prior_prose", "world_rules", "outline")
                ],
            }
        elif schema == "ForecastOutput":
            value = {
                "items": [
                    {
                        "capability_index": 0,
                        "question_kind": "reaction",
                        "anchor_evidence_id": "source_0",
                        "anchor_text": "林舟在渡口等候",
                        "proposal": {
                            "title": "保留等待的未知",
                            "kind": "creative_opportunity",
                            "statements": [
                                {
                                    "text": "林舟仍在等候。",
                                    "basis": "observed",
                                    "evidence_ids": ["source_0"],
                                }
                            ],
                            "why_now": "消息尚未传来。",
                            "directions": [
                                {
                                    "direction_id": "wait",
                                    "title": "轻量回应",
                                    "condition": "如果继续等待",
                                    "proposal": "观察渡口的动静。",
                                    "narrative_commitment": "low",
                                    "may_leave_open": True,
                                }
                            ],
                            "unknowns": ["封锁是否真实", "中间行程"],
                            "verdict": "propose",
                        },
                    }
                ]
            }
        else:
            raise AssertionError(schema)
        return LLMCallResponse(
            content=json.dumps(value, ensure_ascii=False),
            finish_reason="stop",
            usage=LLMUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
        )

    monkeypatch.setattr(OpenAIProvider, "generate", provider)

    async def execute(task_id):
        task = await db.get(AsyncTask, UUID(task_id))
        handler = {
            "evolution_scene_step_v2": handle_evolution_scene_step,
            "collaboration_run": runtime.execute,
            "assistant_forecast": forecasts.execute,
        }[task.task_type]
        result = await handler(db, task)
        task.status, task.result = "done", result
        await db.commit()

    await run_slice(db, nid, execute, report, stages.append)
    assert all(engineering_checks(report).values()), engineering_checks(report)
    assert stages[-1] == "source_change_checked"
    first, second = prompts["WorkOutput"]
    evolution = report["cases"][0]["manifest"]["evolution"]
    assert len(evolution) == 2
    assert evolution[0]["receipt_id"] in first
    assert "character_statement" in first
    assert evolution[0]["observations"][0]["observation_id"] in first
    assert report["cognition"][0]["record_id"] in second
    assert understanding in prompts["ForecastOutput"][0]
    assert understanding in prompts["AuditVerdictOutput"][-1]
    assert report["cognition"][0]["record_id"] in prompts["AuditVerdictOutput"][-1]
    assert PROSE[0] in prompts["ForecastOutput"][0]
    assert report["cognition"][0]["evolution_refs"] == evolution
    assert report["map"]["routes"][0]["status"] == "unknown"
    lin = next(
        item
        for item in report["map"]["presence_items"]
        if item["character_name"] == "林舟"
    )
    assert lin["feature_id"] == "place1"
    with pytest.raises(ConflictError, match="场景理解"):
        await read_committed_understanding(
            db,
            nid,
            {},
            required=[CommittedUnderstanding.model_validate(ref) for ref in evolution],
        )
