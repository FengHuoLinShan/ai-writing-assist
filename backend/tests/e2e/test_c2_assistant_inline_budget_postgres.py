"""Assistant C2 previews spend the parent run through the real inline Story worker."""

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app as _app  # noqa: F401 - register the production catalog
from infrastructure.llm.agent_runtime import AgentRunBudget
from infrastructure.llm.schemas import AIRunEnvelopeV4, read_ai_run_envelope
from infrastructure.llm.workflow_budget import current_ai_run_envelope
from infrastructure.tasks.enqueuer import enqueue_task
from infrastructure.tasks.models import AsyncTask
from infrastructure.tasks.registry import TaskRegistry
from infrastructure.tasks.worker import TaskWorker
from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID
from modules.account.models import Account
from modules.assistant.evidence_tools import AssistantToolContext
from modules.assistant.operations import catalog, execute_suggestion, operation_manifest
from modules.assistant.schemas import WorkContext
from modules.assistant.service import _assistant_catalog_budget_scope
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
from tests.e2e.config import require_e2e_database_url

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


class _TaskManager:
    def __init__(self, engine, sessions):
        self.engine = engine
        self.session_factory = sessions


@pytest.mark.parametrize("provider_fails", [False, True])
async def test_assistant_c2_inline_story_uses_one_parent_run(monkeypatch, provider_fails):
    import modules.assistant.tasks  # noqa: F401 - production registration
    import modules.story.assistant_generation_tools as story_ops
    import modules.story.task_submission as story_submission
    import modules.story.tasks as story_tasks

    engine = create_async_engine(require_e2e_database_url(), pool_size=5, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    novel_id, scene_id, character_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    provider = _ChainProvider([_card_payload(), _AUDIT_PASS_PAYLOAD])
    if provider_fails:
        from infrastructure.llm.errors import LLMAuthError

        async def fail_generate(_request):
            provider.calls += 1
            raise LLMAuthError("offline test failure")

        provider.generate = fail_generate
    actual_generate = provider.generate
    provider_runs = []

    async def capture_generate(request):
        run = current_ai_run_envelope()
        assert run is not None
        provider_runs.append((run.run_id, run.snapshot().started_at))
        return await actual_generate(request)

    provider.generate = capture_generate
    registry = TaskRegistry()
    original_handler = registry._handlers["assistant_turn"]

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
        del novel_id, action, confirmation_id
        return SimpleNamespace(
            compiled=SimpleNamespace(
                sections=[], warnings=[], budget_tokens=0, total_tokens=0
            ),
            compile_options=(
                await fresh(
                    None,
                    novel_id="",
                    action="story.character_card.generate",
                    confirmation_id="",
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

    async def fake_parent(db, task):
        deps = AssistantToolContext(
            db=db,
            novel_id=str(novel_id),
            owner_id=str(BOOTSTRAP_ACCOUNT_ID),
            work=WorkContext(page="scene", scope="project", scene_id=scene_id),
            client=None,
            budget=AgentRunBudget(),
            checkpoint=noop,
            run_id=str(task.id),
            task_id=str(task.id),
            llm_snapshot={
                "novel_id": str(novel_id),
                "profile": {"model": "deepseek-flash"},
            },
            operations={
                "story.character_card.generate": catalog()[
                    "story.character_card.generate"
                ]
            },
        )
        return await execute_suggestion(
            SimpleNamespace(deps=deps),
            "story.character_card.generate",
            {"scene_id": str(scene_id), "character_id": str(character_id)},
        )

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
    monkeypatch.setitem(registry._handlers, "assistant_turn", fake_parent)
    try:
        async with sessions.begin() as db:
            if await db.get(Account, BOOTSTRAP_ACCOUNT_ID) is None:
                db.add(Account(id=BOOTSTRAP_ACCOUNT_ID, support_code=uuid.uuid4().hex))
            db.add(Project(id=novel_id, owner_id=BOOTSTRAP_ACCOUNT_ID, title="C2 inline"))
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
        frozen = {
            "story.character_card.generate": operation_manifest()[
                "story.character_card.generate"
            ]
        }
        scope = _assistant_catalog_budget_scope("9", frozen)
        assert scope == {
            "scope_fingerprint": scope["scope_fingerprint"],
            "authorized_step_capabilities": ["story.character_card"],
        }
        async with sessions.begin() as db:
            task_id = uuid.UUID(
                enqueue_task(
                    db,
                    "assistant_turn",
                    novel_id=str(novel_id),
                    meta={"_assistant_catalog_budget_v1": scope},
                )
            )
        returned = await TaskWorker(
            db_manager=_TaskManager(engine, sessions), heartbeat_interval=60.0
        ).run_once()
        assert returned is not None and returned.id == task_id
        async with sessions() as db:
            parent = await db.get(AsyncTask, task_id)
            assert parent is not None
            envelope = read_ai_run_envelope(parent.meta["_ai_run_envelope"])
            assert isinstance(envelope, AIRunEnvelopeV4)
            assert provider_runs == [(str(task_id), envelope.started_at)] * provider.calls
            children = (
                await db.scalars(
                    select(AsyncTask).where(
                        AsyncTask.novel_id == novel_id,
                        AsyncTask.id != task_id,
                    )
                )
            ).all()
            assert len(children) == 1
            assert children[0].meta["_parent_task_id"] == str(task_id)
            assert "_ai_run_envelope" not in children[0].meta
            if provider_fails:
                assert children[0].status == "failed"
                assert parent.result["domain_result"]["status"] == "incomplete"
                assert envelope.requests_started >= 1
            else:
                assert children[0].status == "done"
                assert parent.result["domain_result"]["status"] == "completed"
                content = parent.result["domain_result"]["preview"]["content"]
                assert content["version"] == "character_card.v2"
                assert content["interpretations"][0]["source_fact_ids"] == [
                    "story:known-goal"
                ]
                assert envelope.requests_started == envelope.requests_settled == 2
                assert provider.calls == 2
    finally:
        registry._handlers["assistant_turn"] = original_handler
        await engine.dispose()
