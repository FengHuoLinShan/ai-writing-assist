"""One author-approved Goal v3 executes Story inside its frozen root budget."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app as _app  # noqa: F401 - production task and catalog wiring
from core.container import container_scope
from infrastructure.llm.schemas import AIRunEnvelopeV3, read_ai_run_envelope
from infrastructure.llm.workflow_budget import current_ai_run_envelope
from infrastructure.tasks.models import AsyncTask
from modules.account.models import Account
from modules.assistant.goal_runs import service
from modules.assistant.goal_runs.contracts import (
    GoalAction,
    GoalBudget,
    GoalPlan,
    GoalPlanApproval,
    GoalRunStart,
)
from modules.assistant.operations import catalog
from modules.assistant.tests.test_goal_runs import _PlanningClient
from modules.project.models import Project
from modules.story.outline_state.models import Scene
from modules.story.tests.test_run_envelope_story import (
    _AUDIT_PASS_PAYLOAD,
    _card_payload,
    _chain_client,
    _ChainProvider,
    _stub_scene_context,
)
from modules.world.models import CoreEntity
from tests.e2e.config import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


@pytest.mark.parametrize(
    ("request_limit", "crash_after_submit"), [(8, False), (4, False), (8, True)]
)
async def test_story_card_goal_reuses_approved_root_and_replays_without_new_charge(
    monkeypatch,
    request_limit,
    crash_after_submit,
):
    import modules.story.assistant_generation_tools as story_ops
    import modules.story.task_submission as story_submission
    import modules.story.tasks as story_tasks

    engine = create_async_engine(DATABASE_URL, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    owner_id, novel_id, scene_id, character_id = (uuid.uuid4() for _ in range(4))
    provider = _ChainProvider([_card_payload(), _AUDIT_PASS_PAYLOAD])
    provider_runs = []
    original_generate = provider.generate

    async def capture_generate(request):
        ledger = current_ai_run_envelope()
        assert ledger is not None
        provider_runs.append((ledger.run_id, ledger.snapshot().started_at))
        return await original_generate(request)

    provider.generate = capture_generate

    async def no_project_gate(*_args, **_kwargs):
        return None

    async def project_context(*_args, **_kwargs):
        return SimpleNamespace(
            title="Goal Story 合成项目",
            genre="奇幻",
            tone="简洁",
            language="zh",
            current_stage="writing",
        )

    async def execution_snapshot(*_args, **_kwargs):
        return {
            "novel_id": str(novel_id),
            "profile": {"model": "deepseek-flash"},
            "llm": {"model": "deepseek-flash"},
        }

    async def trace_disabled(*_args, **_kwargs):
        return False

    async def preview(_db, _options):
        return {"blockers": [], "context_fingerprint": "a" * 64}

    async def confirmed(_db, _request):
        return SimpleNamespace(id=str(uuid.uuid4()))

    async def fresh(_db, *, novel_id, action, confirmation_id):
        del novel_id, confirmation_id
        return SimpleNamespace(
            compile_options={
                "consumer_action": action,
                "retrieval_purpose": "story_character_card",
                "scope": "scene",
                "scene_id": str(scene_id),
                "visible_until_scene_id": str(scene_id),
                "character_ids": [str(character_id)],
                "reveal_mode": "character",
                "viewpoint_character_id": str(character_id),
                "content_mode": "canonical",
                "context_mode": "canonical",
                "include_pending_objects": False,
                "budget_tokens": 6000,
            }
        )

    async def noop(*_args, **_kwargs):
        return None

    async def story_confirmed(_db, *, novel_id, action, confirmation_id):
        return SimpleNamespace(
            compiled=SimpleNamespace(
                sections=[], warnings=[], budget_tokens=0, total_tokens=0
            ),
            compile_options=(
                await fresh(
                    None,
                    novel_id=novel_id,
                    action=action,
                    confirmation_id=confirmation_id,
                )
            ).compile_options,
        )

    async def scene_context(_db, *, novel_id, scene_id, character_ids):
        return _stub_scene_context(novel_id, scene_id, str(character_ids[0]))

    async def reveals(_db, **_kwargs):
        return {
            str(character_id): {
                "markdown": "该人物可见的已确认事实",
                "deterministic_facts": [
                    {
                        "fact_id": "story:known-goal",
                        "kind": "story_state",
                        "layer": "fact",
                        "subject_id": str(character_id),
                        "dimension": "entities",
                        "field": "current_goal",
                        "value": "守住码头",
                        "checkpoint_id": "checkpoint-1",
                    }
                ],
                "reference_patterns": [],
                "reference_dimensions": (),
                "hash": "confirmed-reveal-hash",
            }
        }

    async def snapshot(_db, **_kwargs):
        return SimpleNamespace(id=str(uuid.uuid4()))

    async def settings(_db, _novel_id, _snapshot):
        return {"llm": {"provider_id": "deepseek", "model": "deepseek-flash"}}

    plan = GoalPlan.model_validate(
        {
            "title": "生成人物卡候选",
            "steps": [
                {
                    "step_id": "card",
                    "operation_id": "story.character_card.generate",
                    "parameters": {
                        "scene_id": str(scene_id),
                        "character_id": str(character_id),
                    },
                    "targets": [
                        {"target_type": "outline_scene", "target_id": str(scene_id)},
                        {"target_type": "core_entity", "target_id": str(character_id)},
                    ],
                    "intent": "生成仅供作者审阅的候选",
                }
            ],
        }
    )
    operation = catalog()["story.character_card.generate"]
    submitted = 0
    if crash_after_submit:
        original_apply = operation.apply

        class ProcessExited(BaseException):
            pass

        async def crash_after_domain_commit(db, *args, **kwargs):
            nonlocal submitted
            reference = await original_apply(db, *args, **kwargs)
            submitted += 1
            assert reference["task_id"]
            await db.commit()
            raise ProcessExited

        operation = replace(operation, apply=crash_after_domain_commit)
    monkeypatch.setattr(service, "_feature_enabled", lambda _novel_id: True)
    monkeypatch.setattr(service, "_require_goal_project", no_project_gate)
    monkeypatch.setattr(service, "_trace_enabled", trace_disabled)
    monkeypatch.setattr(service, "get_any_project_context", project_context)
    monkeypatch.setattr(
        service, "build_project_llm_execution_snapshot", execution_snapshot
    )
    monkeypatch.setattr(
        service, "_operation_registry", lambda: {operation.op_id: operation}
    )

    @asynccontextmanager
    async def planning_client(*_args, **_kwargs):
        yield _PlanningClient(plan)

    monkeypatch.setattr(service, "open_project_snapshot_llm_client", planning_client)
    monkeypatch.setattr(story_ops, "preview_context_confirmation", preview)
    monkeypatch.setattr(story_ops, "confirm_context", confirmed)
    monkeypatch.setattr(story_submission, "require_fresh_confirmation", fresh)
    monkeypatch.setattr(story_submission, "attach_result_ref", noop)
    monkeypatch.setattr(story_tasks, "prepare_confirmed_ai_action", story_confirmed)
    monkeypatch.setattr(story_tasks, "render_compiled_context", lambda _: "")
    monkeypatch.setattr(story_tasks, "get_scene_story_context", scene_context)
    monkeypatch.setattr(story_tasks, "_compile_character_reveals", reveals)
    monkeypatch.setattr(story_tasks, "create_context_snapshot", snapshot)
    monkeypatch.setattr(story_tasks, "restore_project_llm_execution_settings", settings)
    monkeypatch.setattr(
        story_tasks,
        "create_project_snapshot_llm_client",
        lambda *args, **kwargs: _chain_client(monkeypatch, provider),
    )
    try:
        async with sessions.begin() as db:
            db.add(Account(id=owner_id, support_code=owner_id.hex[:16]))
            db.add(Project(id=novel_id, owner_id=owner_id, title="Goal Story 合成项目"))
            db.add(Scene(id=scene_id, novel_id=novel_id, scene_index=0))
            db.add(
                CoreEntity(
                    id=character_id,
                    novel_id=novel_id,
                    entity_type="character",
                    name="人物",
                    status="canonical",
                )
            )
        budget = GoalBudget(
            requests=request_limit,
            possible_charge_requests=request_limit,
            tokens=20_000,
            time_limit_seconds=600,
        )
        with container_scope({"assistant.operations": {operation.op_id: operation}}):
            async with sessions() as db:
                started = await service.start_goal(
                    db,
                    GoalRunStart(
                        novel_id=novel_id,
                        request_id=uuid.uuid4(),
                        goal="为本场景生成人物卡候选",
                        budget=budget,
                    ),
                    str(owner_id),
                )
            assert started["status"] == "waiting_approval"
            async with sessions() as db:
                approval = service.approve_goal_plan(
                    db,
                    str(novel_id),
                    started["run_id"],
                    GoalPlanApproval(
                        expected_revision=started["revision"],
                        plan=plan,
                        budget=budget,
                    ),
                    str(owner_id),
                )
                if crash_after_submit:
                    with pytest.raises(ProcessExited):
                        await approval
                else:
                    completed = await approval
            if crash_after_submit:
                async with sessions() as db:
                    incomplete = await service.get_goal(
                        db, str(novel_id), started["run_id"], str(owner_id)
                    )
                    assert incomplete["steps"][0]["status"] == "applying"
                    completed = await service.advance_goal(
                        db,
                        str(novel_id),
                        started["run_id"],
                        str(owner_id),
                        GoalAction(expected_revision=incomplete["revision"]),
                    )
                assert submitted == 1
            assert completed["status"] == "completed", (
                completed["stop_code"],
                completed["stop_reason"],
                completed["steps"],
            )
            assert completed["steps"][0]["status"] == "completed"
            assert completed["budget"]["used"]["requests"] == 4
            async with sessions() as db:
                replay = await service.advance_goal(
                    db,
                    str(novel_id),
                    started["run_id"],
                    str(owner_id),
                    GoalAction(expected_revision=completed["revision"]),
                )
            assert replay["status"] == "completed"
            assert replay["budget"]["used"]["requests"] == 4
        async with sessions() as db:
            run = await service._load_goal_run(
                db, str(novel_id), started["run_id"], str(owner_id)
            )
            ledger = read_ai_run_envelope(run.checkpoint_json["goal"]["envelope"])
            assert isinstance(ledger, AIRunEnvelopeV3)
            assert ledger.authorized_step_capabilities == [
                "assistant.goal.plan",
                "story.character_card",
            ]
            assert ledger.requests_started == ledger.requests_settled == 4
            assert provider.calls == 2
            assert provider_runs == [(str(run.id), ledger.started_at)] * 2
            record = run.checkpoint_json["goal"]["step_records"]["card"]
            child = await db.get(AsyncTask, uuid.UUID(record["operation_id"]))
            assert child is not None and child.status == "done"
            assert child.meta["_parent_task_id"] == str(run.task_id)
            assert "_ai_run_envelope" not in child.meta
            assert child.result["preview"]["content"]["version"] == "character_card.v2"
    finally:
        await engine.dispose()
