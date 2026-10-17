"""探索 worker 离线全链：信封/检查点/暂停语义/detail/revise/canonical 守卫。"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest_asyncio
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core.base import Base
from core.config import get_settings
from infrastructure.llm.client import LLMClient
from infrastructure.llm.limits import reset_llm_limiter_for_tests
from infrastructure.llm.schemas import AI_RUN_ENVELOPE_KEY, read_ai_run_envelope
from infrastructure.llm.workflow_budget import new_ai_run_envelope
from infrastructure.tasks.enqueuer import enqueue_task
from infrastructure.tasks.models import AsyncTask
from infrastructure.tasks.worker import TaskWorker
from modules.account.settings_constants import LOCAL_OWNER_ID
from modules.evidence.compilation.services.compiled_context import CompiledContext
from modules.evidence.contracts import Assumption, CandidateRef, ProvisionalStart
from modules.story import exploration_tasks
from modules.story.exploration_budget import preview_exploration_budget
from modules.story.exploration_schemas import (
    SANDBOX_OUTPUT_KIND,
    SCENE_LINE_OUTPUT_KIND,
    ExplorationOutputEnvelope,
    SandboxOutputV1,
)
from modules.story.exploration_service import (
    create_exploration_root,
    pack_exploration_output,
    unpack_exploration_output,
)
from modules.story.models import StorySceneDirectorBranch, StorySceneDirectorRound
from modules.story.tests.exploration_test_support import (
    ExplorationOfflineProvider,
    sandbox_payload,
    scene_line_payload,
)
from modules.story.world_progression_models import (
    StoryWorldProgressionBranch,
    StoryWorldProgressionRoot,
    StoryWorldProgressionStep,
)
from modules.story.world_progression_service import append_progression_step

OWNER_ID = str(LOCAL_OWNER_ID)


def _provisional_start(question: str = "重力减半后面包师的一天会怎样？"):
    return ProvisionalStart(
        kind="provisional",
        question=question,
        assumptions=[Assumption(kind="world_rule", text="每天只有一小时重力减半")],
        candidates=[CandidateRef(ref_id="c_baker", label="面包师", role="character")],
        knowledge=[
            {
                "subject_ref": "c_baker",
                "knows": ["自己每天三点起床"],
                "observed": [],
                "misbelieves": [],
            }
        ],
        time_basis="assumed_now",
    )


class _Manager:
    def __init__(self, engine, sessions):
        self.engine = engine
        self.session_factory = sessions


@pytest_asyncio.fixture
async def exploration_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def disable_implicit_transactions(connection, _record):
        connection.isolation_level = None

    @event.listens_for(engine.sync_engine, "begin")
    def begin_transaction(connection):
        connection.exec_driver_sql("BEGIN")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def exploration_flow(exploration_engine, monkeypatch):
    settings = replace(get_settings(), story_exploration_enabled=True)
    monkeypatch.setattr(
        "modules.story.exploration_feature.get_settings", lambda: settings
    )
    provider = ExplorationOfflineProvider()

    @asynccontextmanager
    async def offline_client(_db, _novel_id, _snapshot):
        reset_llm_limiter_for_tests()
        client = LLMClient.from_project_settings(
            {"llm": {"provider_id": "deepseek", "model": "deepseek-flash"}}
        )
        client._provider = provider  # type: ignore[attr-defined]
        yield client

    async def confirmed(_db, *, novel_id, action, confirmation_id, **_kwargs):
        start = flow.start
        compiled = CompiledContext(
            sections=[],
            selection_trace={
                "exploration": {
                    "start_kind": start.kind,
                    "exploration_start": start.model_dump(mode="json"),
                    "exploration_scale": flow.scale,
                    "exploration_focus": flow.focus,
                }
            },
        )
        return SimpleNamespace(
            compiled=compiled,
            rendered_markdown="作者确认的资料（合成）",
            compile_options={},
        )

    async def guard_terms(_db, *, confirmed_context):
        return list(flow.guard_terms)

    monkeypatch.setattr(exploration_tasks, "prepare_confirmed_ai_action", confirmed)
    monkeypatch.setattr(
        exploration_tasks, "open_project_snapshot_llm_client", offline_client
    )
    monkeypatch.setattr(exploration_tasks, "build_hidden_guard_context", guard_terms)

    sessions = async_sessionmaker(
        exploration_engine, expire_on_commit=False, autoflush=False
    )
    flow = SimpleNamespace(
        engine=exploration_engine,
        sessions=sessions,
        provider=provider,
        scale="sandbox",
        focus="",
        start=None,
        guard_terms=[],
        novel_id=None,
        setup=None,
        enqueue=None,
        run=None,
    )

    async def setup(
        *,
        chain: str,
        scale: str,
        start=None,
        focus: str = "",
        request_limit=5,
    ):
        start = start or _provisional_start()
        flow.start = start
        flow.scale = scale
        flow.focus = focus
        novel_id = uuid.uuid4()
        flow.novel_id = novel_id
        confirmation_id = "ctx-" + str(uuid.uuid4())
        async with sessions.begin() as db:
            from modules.project.models import Project

            db.add(Project(id=novel_id, title="探索离线 Worker 测试"))
            await db.flush()
            root, branch = await create_exploration_root(
                db,
                novel_id=str(novel_id),
                owner_id=OWNER_ID,
                scale=scale,
                start=start,
                context_confirmation_id=(
                    confirmation_id if chain == "progression" else None
                ),
                status="queued",
                branch_request_json={
                    "context_confirmation_id": confirmation_id,
                    "confirmation_action": (
                        "story.exploration.sandbox.generate"
                        if scale == "sandbox"
                        else "story.exploration.scene_line.generate"
                    ),
                },
            )
            started_at = datetime.now(UTC)
            envelope = new_ai_run_envelope(
                operation_id=str(uuid.uuid4()),
                run_id=str(root.id),
                root_capability_id="story.exploration",
                novel_id=str(novel_id),
                request_limit=request_limit,
                budget_mode="bounded",
                token_limit=200_000,
                started_at=started_at,
                deadline_at=started_at + timedelta(hours=1),
            )
            root.run_envelope_json = envelope.snapshot().model_dump(mode="json")
        return (
            SimpleNamespace(
                root_id=root.id,
                branch_id=branch.id,
                novel_id=novel_id,
                confirmation_id=confirmation_id,
                start=start,
                scale=scale,
                focus=focus,
            ),
            envelope,
        )

    async def enqueue_for(spec, envelope, *, action, mode="start", **extra):
        budget = preview_exploration_budget(
            novel_id=str(spec.novel_id),
            scale=spec.scale,
            start=spec.start,
            focus=spec.focus,
        )
        meta = {
            "meta_version": 1,
            "request": {
                "mode": mode,
                "start": spec.start.model_dump(mode="json"),
                "scale": spec.scale,
                "focus": spec.focus,
            },
            "action": action,
            "confirmation_action": (
                "story.exploration.sandbox.generate"
                if spec.scale == "sandbox"
                else "story.exploration.scene_line.generate"
            ),
            "context_confirmation_id": spec.confirmation_id,
            "exploration_root_id": str(spec.root_id),
            "exploration_branch_id": str(spec.branch_id),
            "exploration_scale": spec.scale,
            "exploration_authorized_requests": 1,
            "exploration_authorized_tokens": budget.tokens_max,
            "budget_preview_hash": budget.preview_hash,
            "exploration_deadline_seconds": 3600,
            "exploration_acknowledged_unknown_requests": 0,
            "exploration_baseline_requests_started": 0,
            "exploration_baseline_recent_attempts_overflow": 0,
            "llm_execution_snapshot": {"novel_id": str(spec.novel_id)},
            AI_RUN_ENVELOPE_KEY: envelope.snapshot().model_dump(mode="json"),
            **extra,
        }
        task_type = (
            exploration_tasks.EXPLORATION_SCENE_TASK
            if spec.scale == "scene_line"
            else exploration_tasks.EXPLORATION_PROGRESSION_TASK
        )
        async with flow.sessions.begin() as db:
            task_id = uuid.UUID(
                enqueue_task(
                    db, task_type, novel_id=str(spec.novel_id), meta=meta
                )
            )
            if spec.scale == "scene_line":
                from modules.story.models import StorySceneDirectorRoot

                root_row = await db.get(StorySceneDirectorRoot, spec.root_id)
                branch = await db.get(StorySceneDirectorBranch, spec.branch_id)
            else:
                root_row = await db.get(StoryWorldProgressionRoot, spec.root_id)
                branch = await db.get(StoryWorldProgressionBranch, spec.branch_id)
            root_row.current_task_id = branch.current_task_id = task_id
        return task_id

    async def run(task_id):
        worker = TaskWorker(
            db_manager=_Manager(exploration_engine, flow.sessions),
            heartbeat_interval=60.0,
        )
        await worker.run_once(task_id=task_id, novel_id=str(flow.novel_id))
        async with flow.sessions() as db:
            return await db.get(AsyncTask, task_id)

    flow.setup = setup
    flow.enqueue = enqueue_for
    flow.run = run
    yield flow


async def test_sandbox_start_persists_compact_step_and_result_envelope(exploration_flow):
    flow = exploration_flow
    spec, envelope = await flow.setup(chain="progression", scale="sandbox")
    task_id = await flow.enqueue(
        spec, envelope, action="story.exploration.sandbox.generate"
    )
    task = await flow.run(task_id)
    assert task.status == "done", task.error_message
    result = dict(task.result or {})
    assert result["status"] == "completed"
    assert result["output_kind"] == SANDBOX_OUTPUT_KIND
    async with flow.sessions() as db:
        step = await db.scalar(
            select(StoryWorldProgressionStep).where(
                StoryWorldProgressionStep.root_id == spec.root_id
            )
        )
        root = await db.get(StoryWorldProgressionRoot, spec.root_id)
        branch = await db.get(StoryWorldProgressionBranch, spec.branch_id)
        envelope_row = unpack_exploration_output(step)
        assert envelope_row is not None
        assert envelope_row.output_kind == SANDBOX_OUTPUT_KIND
        assert step.result_json["payload"]["influence_chain"]
        assert step.input_json["mode"] == "start"
        assert step.state_json == {}
        assert step.metrics_json == {"mode": "start", "exploration": True}
        assert root.status == "ready" and branch.status == "complete"
        assert root.current_task_id is None and branch.current_task_id is None
        assert branch.pending_step_json == {}
        assert branch.parent_step_id == step.id
    assert result["result_id"] == str(step.id)
    assert flow.provider.calls == 1
    ledger = read_ai_run_envelope(root.run_envelope_json)
    assert ledger.requests_started == 1


async def test_scene_line_candidate_persists_director_round(exploration_flow):
    flow = exploration_flow
    spec, envelope = await flow.setup(chain="scene", scale="scene_line")
    task_id = await flow.enqueue(
        spec,
        envelope,
        action="story.exploration.scene_line.generate",
        target_ref="c_baker",
    )
    task = await flow.run(task_id)
    assert task.status == "done", task.error_message
    result = dict(task.result or {})
    assert result["output_kind"] == SCENE_LINE_OUTPUT_KIND
    async with flow.sessions() as db:
        row = await db.scalar(
            select(StorySceneDirectorRound).where(
                StorySceneDirectorRound.root_id == spec.root_id
            )
        )
        envelope_row = unpack_exploration_output(row)
        assert envelope_row.payload.target_ref == "c_baker"
        assert envelope_row.payload.line
        assert row.round_number == 1
        assert row.parent_round_id is None
    assert result["result_id"] == str(row.id)


async def test_preview_hash_mismatch_fails_closed(exploration_flow):
    flow = exploration_flow
    spec, envelope = await flow.setup(chain="progression", scale="sandbox")
    async with flow.sessions.begin() as db:
        task_id = uuid.UUID(
            enqueue_task(
                db,
                exploration_tasks.EXPLORATION_PROGRESSION_TASK,
                novel_id=str(spec.novel_id),
                meta={
                    AI_RUN_ENVELOPE_KEY: envelope.snapshot().model_dump(mode="json"),
                    "exploration_root_id": str(spec.root_id),
                    "exploration_branch_id": str(spec.branch_id),
                    "exploration_scale": spec.scale,
                    "exploration_authorized_requests": 1,
                    "exploration_authorized_tokens": 1000,
                    "exploration_deadline_seconds": 3600,
                    "llm_execution_snapshot": {"novel_id": str(spec.novel_id)},
                    "action": "story.exploration.sandbox.generate",
                    "request": {
                        "mode": "start",
                        "start": spec.start.model_dump(mode="json"),
                        "scale": spec.scale,
                        "focus": spec.focus,
                    },
                    "budget_preview_hash": "0" * 64,
                    "context_confirmation_id": spec.confirmation_id,
                },
            )
        )
    task = await flow.run(task_id)
    assert task.status == "failed"
    async with flow.sessions() as db:
        steps = (
            await db.scalars(
                select(StoryWorldProgressionStep).where(
                    StoryWorldProgressionStep.root_id == spec.root_id
                )
            )
        ).all()
        assert steps == []
    assert flow.provider.calls == 0


async def test_unknown_provider_result_pauses_with_checkpoint(exploration_flow):
    flow = exploration_flow
    spec, envelope = await flow.setup(chain="progression", scale="sandbox")
    flow.provider.fail_next = True
    task_id = await flow.enqueue(
        spec, envelope, action="story.exploration.sandbox.generate"
    )
    await flow.run(task_id)
    async with flow.sessions() as db:
        root = await db.get(StoryWorldProgressionRoot, spec.root_id)
        branch = await db.get(StoryWorldProgressionBranch, spec.branch_id)
        assert root.status == "paused_unknown"
        assert branch.status == "paused_unknown"
        assert branch.pending_step_json["mode"] == "start"
        ledger = read_ai_run_envelope(root.run_envelope_json)
        assert ledger.requests_unknown == 1
        steps = (
            await db.scalars(
                select(StoryWorldProgressionStep).where(
                    StoryWorldProgressionStep.root_id == spec.root_id
                )
            )
        ).all()
        assert steps == []
    assert flow.provider.calls == 1


async def _seed_sandbox_result(flow, spec):
    row_envelope = ExplorationOutputEnvelope(
        output_kind=SANDBOX_OUTPUT_KIND,
        schema_version=1,
        payload=SandboxOutputV1.model_validate(
            {
                "question": sandbox_payload()["question"],
                "influence_chain": [
                    {
                        "condition": "揉面时间不变",
                        "mechanism": "重力降低让面团发酵更快",
                        "effect": "面包更松软",
                    },
                    {
                        "condition": "出炉提前",
                        "mechanism": "清晨顾客变多",
                        "effect": "面包师更累",
                    },
                ],
            }
        ),
    )
    async with flow.sessions.begin() as db:
        root = await db.get(StoryWorldProgressionRoot, spec.root_id)
        branch = await db.get(StoryWorldProgressionBranch, spec.branch_id)
        row = await append_progression_step(
            db,
            novel_id=str(spec.novel_id),
            root=root,
            branch=branch,
            parent_step_id=None,
            source_hash=branch.source_hash,
            input_payload={"mode": "start"},
            output_payload=pack_exploration_output(row_envelope),
            state={},
            metrics={"mode": "start"},
            basis_changed=False,
        )
        branch.parent_step_id = row.id
    return row, row_envelope


async def test_revise_locks_one_item_and_copies_the_rest(exploration_flow):
    flow = exploration_flow
    spec, envelope = await flow.setup(chain="progression", scale="sandbox")
    parent_row, parent_envelope = await _seed_sandbox_result(flow, spec)
    items = parent_envelope.payload.model_dump(mode="json")["influence_chain"]
    target_hash = exploration_tasks._fnv1a_hash(items[0])

    task_id = await flow.enqueue(
        spec,
        envelope,
        action="story.exploration.sandbox.generate",
        mode="revise",
        parent_result_id=str(parent_row.id),
        changed_item_hash=target_hash,
        instruction="把第一环改保守",
    )
    task = await flow.run(task_id)
    assert task.status == "done", task.error_message
    async with flow.sessions() as db:
        rows = (
            await db.scalars(
                select(StoryWorldProgressionStep)
                .where(StoryWorldProgressionStep.root_id == spec.root_id)
                .order_by(StoryWorldProgressionStep.step_number)
            )
        ).all()
        assert len(rows) == 2
        revised = unpack_exploration_output(rows[1])
        chain = revised.payload.model_dump(mode="json")["influence_chain"]
        assert len(chain) == 2
        assert chain[0]["effect"] != items[0]["effect"]
        assert chain[1] == items[1]
        assert rows[1].input_json["changed_item_hash"] == target_hash
        assert rows[1].input_json["mode"] == "revise"


async def test_revise_rejects_stale_item_hash(exploration_flow):
    flow = exploration_flow
    spec, envelope = await flow.setup(chain="progression", scale="sandbox")
    parent_row, _parent_envelope = await _seed_sandbox_result(flow, spec)
    task_id = await flow.enqueue(
        spec,
        envelope,
        action="story.exploration.sandbox.generate",
        mode="revise",
        parent_result_id=str(parent_row.id),
        changed_item_hash="fnv1a:deadbeef",
        instruction="改第一条",
    )
    task = await flow.run(task_id)
    assert task.status == "failed"
    async with flow.sessions() as db:
        rows = (
            await db.scalars(
                select(StoryWorldProgressionStep).where(
                    StoryWorldProgressionStep.root_id == spec.root_id
                )
            )
        ).all()
        assert len(rows) == 1
    assert flow.provider.calls == 0


async def test_canonical_scene_line_guard_fails_closed_without_persist(exploration_flow):
    flow = exploration_flow
    start = _provisional_start().model_copy(
        update={
            "candidates": [],
            "knowledge": [],
            "canonical_refs": [str(uuid.uuid4())],
        }
    )
    spec, envelope = await flow.setup(chain="scene", scale="scene_line", start=start)
    flow.provider.override = scene_line_payload(
        target_ref=start.canonical_refs[0],
        line="难怪你昨天被解雇了，失业的人都会这样。",
    )
    flow.guard_terms = [
        SimpleNamespace(
            phrase="被解雇了",
            rule="hidden_truth",
            severity="blocking",
            source_type="world_entity",
            source_id="x",
            source_label="隐藏设定",
        )
    ]
    task_id = await flow.enqueue(
        spec,
        envelope,
        action="story.exploration.scene_line.generate",
        target_ref=start.canonical_refs[0],
    )
    task = await flow.run(task_id)
    assert task.status == "failed"
    async with flow.sessions() as db:
        rows = (
            await db.scalars(
                select(StorySceneDirectorRound).where(
                    StorySceneDirectorRound.root_id == spec.root_id
                )
            )
        ).all()
        assert rows == []
        branch = await db.get(StorySceneDirectorBranch, spec.branch_id)
        assert branch.status == "failed"
    assert flow.provider.calls == 1
