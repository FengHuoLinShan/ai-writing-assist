"""探索 worker 离线全链：信封/检查点/暂停语义/detail/revise/canonical 守卫。"""

from __future__ import annotations

import json
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
from modules.evidence.compilation.services.compiled_context import (
    CompiledContext,
    ContextSection,
    Tier,
)
from modules.evidence.contracts import Assumption, CandidateRef, ProvisionalStart
from modules.story import exploration_tasks
from modules.story.exploration_budget import preview_exploration_budget
from modules.story.exploration_schemas import (
    SANDBOX_OUTPUT_KIND,
    SCENE_LINE_OUTPUT_KIND,
    ExplorationOutputEnvelope,
    SandboxOutputV1,
    SceneLineOutputV1,
    apply_changed_assumptions,
    exploration_start_fingerprint,
)
from modules.story.exploration_service import (
    create_exploration_root,
    pack_exploration_output,
    unpack_exploration_output,
)
from modules.story.exploration_tasks import SPATIAL_UNKNOWN_DISCLOSURE
from modules.story.models import (
    StorySceneDirectorBranch,
    StorySceneDirectorRoot,
    StorySceneDirectorRound,
)
from modules.story.tests.exploration_test_support import (
    ExplorationOfflineProvider,
    event_payload,
    sandbox_payload,
    scene_diagnostic_payload,
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
            sections=list(flow.sections),
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
        sections=[],
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
        event_mode_hint=None,
    ):
        start = start or _provisional_start()
        flow.start = start
        flow.scale = scale
        flow.focus = focus
        novel_id = uuid.uuid4()
        flow.novel_id = novel_id
        confirmation_id = "ctx-" + str(uuid.uuid4())
        branch_confirmation_action = {
            "sandbox": "story.exploration.sandbox.generate",
            "event": "story.exploration.event.diagnose",
            "scene_line": "story.exploration.scene_line.generate",
        }[scale]
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
                    "confirmation_action": branch_confirmation_action,
                },
                event_mode_hint=event_mode_hint,
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

    async def enqueue_for(
        spec,
        envelope,
        *,
        action,
        mode="start",
        preview_hash=None,
        event_mode_hint=None,
        multi_targets=None,
        diagnostic_question=None,
        **extra,
    ):
        budget = preview_exploration_budget(
            novel_id=str(spec.novel_id),
            scale=spec.scale,
            start=spec.start,
            focus=spec.focus,
            event_mode_hint=event_mode_hint,
            multi_targets=multi_targets,
            diagnostic_question=diagnostic_question,
        )
        meta = {
            "meta_version": 1,
            "request": {
                "mode": mode,
                "start": spec.start.model_dump(mode="json"),
                "scale": spec.scale,
                "focus": spec.focus,
                **({"multi_targets": multi_targets} if multi_targets else {}),
                **(
                    {"diagnostic": {"question": diagnostic_question}}
                    if diagnostic_question
                    else {}
                ),
            },
            "action": action,
            "confirmation_action": {
                "sandbox": "story.exploration.sandbox.generate",
                "event": action,
                "scene_line": "story.exploration.scene_line.generate",
            }[spec.scale],
            "context_confirmation_id": spec.confirmation_id,
            "exploration_root_id": str(spec.root_id),
            "exploration_branch_id": str(spec.branch_id),
            "exploration_scale": spec.scale,
            "exploration_authorized_requests": budget.requests_max,
            "exploration_authorized_tokens": budget.tokens_max,
            "budget_preview_hash": preview_hash or budget.preview_hash,
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

    task_id = await flow.enqueue(
        spec,
        envelope,
        action="story.exploration.sandbox.generate",
        mode="revise",
        parent_result_id=str(parent_row.id),
        item_path="chain:0",
        item_text=items[0]["effect"],
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
        assert rows[1].input_json["item_path"] == "chain:0"
        assert rows[1].input_json["item_content_hash"] == exploration_tasks.content_hash(
            items[0]
        )
        assert rows[1].input_json["mode"] == "revise"


async def test_revise_rejects_unknown_item_path(exploration_flow):
    flow = exploration_flow
    spec, envelope = await flow.setup(chain="progression", scale="sandbox")
    parent_row, _parent_envelope = await _seed_sandbox_result(flow, spec)
    task_id = await flow.enqueue(
        spec,
        envelope,
        action="story.exploration.sandbox.generate",
        mode="revise",
        parent_result_id=str(parent_row.id),
        item_path="chain:9",
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


async def test_revise_rejects_drifted_item_text(exploration_flow):
    flow = exploration_flow
    spec, envelope = await flow.setup(chain="progression", scale="sandbox")
    parent_row, parent_envelope = await _seed_sandbox_result(flow, spec)
    items = parent_envelope.payload.model_dump(mode="json")["influence_chain"]
    task_id = await flow.enqueue(
        spec,
        envelope,
        action="story.exploration.sandbox.generate",
        mode="revise",
        parent_result_id=str(parent_row.id),
        item_path="chain:0",
        item_text="作者看到的是旧文案，已经对不上",
        instruction="把第一环改保守",
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
    assert items  # 父条目未被改动


async def _seed_scene_line_result(flow, spec):
    row_envelope = ExplorationOutputEnvelope(
        output_kind=SCENE_LINE_OUTPUT_KIND,
        schema_version=1,
        payload=SceneLineOutputV1.model_validate(
            scene_line_payload(target_ref="c_baker")
        ),
    )
    async with flow.sessions.begin() as db:
        branch = await db.get(StorySceneDirectorBranch, spec.branch_id)
        row = StorySceneDirectorRound(
            novel_id=branch.novel_id,
            root_id=branch.root_id,
            branch_id=branch.id,
            round_number=1,
            parent_round_id=None,
            source_hash=branch.source_hash,
            input_hash="c" * 64,
            output_hash="d" * 64,
            input_json={"mode": "start"},
            output_json=pack_exploration_output(row_envelope),
            state_json={},
            run_envelope_json={},
        )
        db.add(row)
        await db.flush()
    return row, row_envelope


async def test_scene_line_revise_replaces_line_entry(exploration_flow):
    flow = exploration_flow
    spec, envelope = await flow.setup(chain="scene", scale="scene_line")
    parent_row, parent_envelope = await _seed_scene_line_result(flow, spec)
    parent_payload = parent_envelope.payload.model_dump(mode="json")

    task_id = await flow.enqueue(
        spec,
        envelope,
        action="story.exploration.scene_line.generate",
        mode="revise",
        parent_result_id=str(parent_row.id),
        item_path="line",
        item_text=parent_payload["line"],
        instruction="这句收着一点",
    )
    task = await flow.run(task_id)
    assert task.status == "done", task.error_message
    async with flow.sessions() as db:
        rounds = (
            await db.scalars(
                select(StorySceneDirectorRound)
                .where(StorySceneDirectorRound.root_id == spec.root_id)
                .order_by(StorySceneDirectorRound.round_number)
            )
        ).all()
        assert len(rounds) == 2
        assert rounds[1].parent_round_id == parent_row.id
        assert rounds[1].input_json["item_path"] == "line"
        assert rounds[1].input_json["item_content_hash"] == (
            exploration_tasks.content_hash(parent_payload["line"])
        )
        revised = unpack_exploration_output(rounds[1])
        assert revised.payload.line != parent_payload["line"]
        assert revised.payload.target_ref == parent_payload["target_ref"]
    assert flow.provider.calls == 1


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


# ---------------------------------------------------------------------------
# 反事实条件对照（M2 沙盘）：预算身份带基线 + 结果行记录基线与变更条件
# ---------------------------------------------------------------------------


async def _freeze_counterfactual_root(flow, spec, baseline_id: str):
    changed = [Assumption(kind="world_rule", text="重力变化时段从早晨改到傍晚")]
    async with flow.sessions.begin() as db:
        root = await db.get(StoryWorldProgressionRoot, spec.root_id)
        root.request_json = {
            **(root.request_json or {}),
            "counterfactual_of": baseline_id,
            "changed_assumptions": [
                item.model_dump(mode="json") for item in changed
            ],
        }
    return changed


async def test_counterfactual_start_records_baseline_and_changed_texts(exploration_flow):
    flow = exploration_flow
    changed = [Assumption(kind="world_rule", text="重力变化时段从早晨改到傍晚")]
    cloned = apply_changed_assumptions(_provisional_start(), changed)
    spec, envelope = await flow.setup(chain="progression", scale="sandbox", start=cloned)
    baseline_id = str(uuid.uuid4())
    frozen = await _freeze_counterfactual_root(flow, spec, baseline_id)
    assert frozen == changed
    cf_budget = preview_exploration_budget(
        novel_id=str(spec.novel_id),
        scale="sandbox",
        start=cloned,
        focus=spec.focus,
        counterfactual_of_result_id=baseline_id,
        changed_assumptions=changed,
    )
    task_id = await flow.enqueue(
        spec,
        envelope,
        action="story.exploration.sandbox.generate",
        preview_hash=cf_budget.preview_hash,
    )
    task = await flow.run(task_id)
    assert task.status == "done", task.error_message
    async with flow.sessions() as db:
        step = await db.scalar(
            select(StoryWorldProgressionStep).where(
                StoryWorldProgressionStep.root_id == spec.root_id
            )
        )
        assert step.input_json["mode"] == "start"
        assert step.input_json["counterfactual_of"] == baseline_id
        assert step.input_json["changed_assumption_texts"] == [
            "重力变化时段从早晨改到傍晚"
        ]
        assert step.input_json["start_summary"]["fingerprint"] == (
            exploration_start_fingerprint(cloned, "sandbox")
        )
    assert flow.provider.calls == 1


async def test_counterfactual_start_rejects_plain_budget_hash(exploration_flow):
    """反事实根用普通身份的 preview hash 重放 → worker 失败关闭，不落库。"""
    flow = exploration_flow
    changed = [Assumption(kind="world_rule", text="重力变化时段从早晨改到傍晚")]
    cloned = apply_changed_assumptions(_provisional_start(), changed)
    spec, envelope = await flow.setup(chain="progression", scale="sandbox", start=cloned)
    baseline_id = str(uuid.uuid4())
    await _freeze_counterfactual_root(flow, spec, baseline_id)
    task_id = await flow.enqueue(
        spec, envelope, action="story.exploration.sandbox.generate"
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


# ---------------------------------------------------------------------------
# 事件信息差与导向路径（M2）：hint 冻结 → prompt 变体注入 + 结果落库
# ---------------------------------------------------------------------------


def _event_provisional_start() -> ProvisionalStart:
    return ProvisionalStart(
        kind="provisional",
        question="证人没看到交接，却准确说出接头暗号，哪里缺依据？",
        assumptions=[Assumption(kind="state", text="证人与交接人事先互不相识")],
        candidates=[
            CandidateRef(ref_id="c_witness", label="证人", role="character"),
            CandidateRef(ref_id="c_courier", label="信使", role="character"),
        ],
        knowledge=[
            {
                "subject_ref": "c_witness",
                "knows": ["接头暗号的内容"],
                "observed": [],
                "misbelieves": [],
            }
        ],
        time_basis="assumed_now",
    )


async def _load_event_step(flow, spec):
    async with flow.sessions() as db:
        step = await db.scalar(
            select(StoryWorldProgressionStep).where(
                StoryWorldProgressionStep.root_id == spec.root_id
            )
        )
        root = await db.get(StoryWorldProgressionRoot, spec.root_id)
        return step, unpack_exploration_output(step), root


async def test_info_gap_hint_injects_prompt_and_persists_boundary(exploration_flow):
    flow = exploration_flow
    spec, envelope = await flow.setup(
        chain="progression",
        scale="event",
        start=_event_provisional_start(),
        event_mode_hint="info_gap",
    )
    task_id = await flow.enqueue(
        spec,
        envelope,
        action=exploration_tasks.EVENT_DIAGNOSE_ACTION,
        event_mode_hint="info_gap",
    )
    task = await flow.run(task_id)
    assert task.status == "done", task.error_message
    system = flow.provider.requests[0].messages[0].content
    assert "信息差" in system
    assert "误信" in system
    assert "不替角色补全" in system
    assert "事件诊断器" not in system  # 基础诊断 prompt 被变体替换
    _step, envelope_row, root = await _load_event_step(flow, spec)
    assert envelope_row.payload.mode == "diagnose"
    boundary = envelope_row.payload.info_boundary[0]
    assert boundary.subject_ref == "c_witness"
    assert boundary.missing_contact_path is True
    assert envelope_row.schema_version == 1  # v1 内扩展，不升版本
    ledger = read_ai_run_envelope(root.run_envelope_json)
    assert ledger.requests_started == 1


async def test_goal_hint_injects_goal_prompt_and_persists_goal_path(exploration_flow):
    flow = exploration_flow
    spec, envelope = await flow.setup(
        chain="progression",
        scale="event",
        start=_event_provisional_start(),
        event_mode_hint="goal",
    )
    task_id = await flow.enqueue(
        spec,
        envelope,
        action=exploration_tasks.EVENT_BRIDGE_ACTION,
        event_mode_hint="goal",
    )
    task = await flow.run(task_id)
    assert task.status == "done", task.error_message
    system = flow.provider.requests[0].messages[0].content
    assert "导向路径" in system
    assert "行动—响应—后果" in system
    assert "不编造巧合" in system
    assert "事件补桥器" not in system  # 基础补桥 prompt 被变体替换
    _step, envelope_row, _root = await _load_event_step(flow, spec)
    assert envelope_row.payload.mode == "goal"
    goal_path = envelope_row.payload.goal_path
    assert goal_path is not None
    assert goal_path.steps[0].cost_or_risk == "信使暴露了自己的任务"
    assert goal_path.rule_constraints == ["禁止巧合", "角色性格不得突变"]


async def test_goal_hint_unsolvable_result_is_legal(exploration_flow):
    """导向任务缺条件时返回 unsolvable 是合法结论，不编造巧合。"""
    flow = exploration_flow
    spec, envelope = await flow.setup(
        chain="progression",
        scale="event",
        start=_event_provisional_start(),
        event_mode_hint="goal",
    )
    flow.provider.override = event_payload("goal_unsolvable")
    task_id = await flow.enqueue(
        spec,
        envelope,
        action=exploration_tasks.EVENT_BRIDGE_ACTION,
        event_mode_hint="goal",
    )
    task = await flow.run(task_id)
    assert task.status == "done", task.error_message
    _step, envelope_row, _root = await _load_event_step(flow, spec)
    assert envelope_row.payload.mode == "goal"
    assert envelope_row.payload.goal_path.unsolvable is not None
    assert envelope_row.payload.goal_path.unsolvable.missing == ["守门人的合作动机"]


async def test_event_hint_action_mismatch_fails_closed(exploration_flow):
    """hint 与动作不配对 → worker 失败关闭，不发起模型请求。"""
    flow = exploration_flow
    spec, envelope = await flow.setup(
        chain="progression",
        scale="event",
        start=_event_provisional_start(),
        event_mode_hint="goal",
    )
    task_id = await flow.enqueue(
        spec,
        envelope,
        action=exploration_tasks.EVENT_DIAGNOSE_ACTION,  # goal 只配 bridge
        event_mode_hint="goal",
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


# ---------------------------------------------------------------------------
# 场景人物差异（M2）：同一情境、逐目标独立知识包、variants 承载输出
# ---------------------------------------------------------------------------


def _scene_pair_start() -> ProvisionalStart:
    """同一情境下的两个候选人物：知识包刻意不同（坦率者知情、回避者误信）。"""
    return ProvisionalStart(
        kind="provisional",
        question="雨夜站台，两人同伞，对方刚提完离职，各自会说什么？",
        assumptions=[Assumption(kind="state", text="雨夜站台，两人共撑一伞")],
        candidates=[
            CandidateRef(ref_id="c_franks", label="坦率者", role="character"),
            CandidateRef(ref_id="c_evasive", label="回避者", role="character"),
        ],
        knowledge=[
            {
                "subject_ref": "c_franks",
                "knows": ["对方已提交辞呈"],
                "observed": [],
                "misbelieves": [],
            },
            {
                "subject_ref": "c_evasive",
                "knows": [],
                "observed": [],
                "misbelieves": ["对方只是想调岗"],
            },
        ],
        time_basis="assumed_now",
    )


async def _load_scene_round(flow, spec):
    async with flow.sessions() as db:
        row = await db.scalar(
            select(StorySceneDirectorRound).where(
                StorySceneDirectorRound.root_id == spec.root_id
            )
        )
        root = await db.get(StorySceneDirectorRoot, spec.root_id)
        return row, unpack_exploration_output(row), root


def _request_user_data(provider, index: int) -> dict:
    return json.loads(provider.requests[index].messages[1].content)


async def test_scene_multi_target_builds_independent_knowledge_packets(
    exploration_flow,
):
    flow = exploration_flow
    start = _scene_pair_start()
    targets = ["c_franks", "c_evasive"]
    spec, envelope = await flow.setup(
        chain="scene", scale="scene_line", start=start
    )
    task_id = await flow.enqueue(
        spec,
        envelope,
        action="story.exploration.scene_line.generate",
        multi_targets=targets,
    )
    task = await flow.run(task_id)
    assert task.status == "done", task.error_message
    assert flow.provider.calls == len(targets)
    # 每个目标只收到自己的知识包：请求 i 的 knows/误信与目标一一对应。
    first = _request_user_data(flow.provider, 0)
    second = _request_user_data(flow.provider, 1)
    assert first["target"]["ref"] == "c_franks"
    assert first["target_knowledge"]["knows"] == ["对方已提交辞呈"]
    assert first["target_knowledge"]["misbelieves"] == []
    assert "对方只是想调岗" not in json.dumps(first, ensure_ascii=False)
    assert second["target"]["ref"] == "c_evasive"
    assert second["target_knowledge"]["misbelieves"] == ["对方只是想调岗"]
    assert "对方已提交辞呈" not in json.dumps(second, ensure_ascii=False)
    row, envelope_row, root = await _load_scene_round(flow, spec)
    payload = envelope_row.payload
    assert payload.target_ref == ""  # 顶层由 variants 承载
    assert payload.line == ""
    assert [variant.target_ref for variant in payload.variants] == targets
    assert len(payload.variants) == 2
    assert all(variant.line for variant in payload.variants)
    assert row.input_json["multi_targets"] == targets
    ledger = read_ai_run_envelope(root.run_envelope_json)
    assert ledger.requests_started == 2  # 预算 = 目标数


async def test_scene_multi_target_rejects_single_target_budget_hash(exploration_flow):
    """多目标请求用单目标身份的 preview hash 重放 → worker 失败关闭。"""
    flow = exploration_flow
    start = _scene_pair_start()
    spec, envelope = await flow.setup(
        chain="scene", scale="scene_line", start=start
    )
    single_hash = preview_exploration_budget(
        novel_id=str(spec.novel_id),
        scale="scene_line",
        start=start,
        focus=spec.focus,
    ).preview_hash
    task_id = await flow.enqueue(
        spec,
        envelope,
        action="story.exploration.scene_line.generate",
        multi_targets=["c_franks", "c_evasive"],
        preview_hash=single_hash,
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
    assert flow.provider.calls == 0


async def test_scene_multi_target_canonical_guard_fails_closed(exploration_flow):
    """多目标中任一 canonical 变体触碰隐藏边界 → 整个任务失败不落库。"""
    flow = exploration_flow
    start = _scene_pair_start().model_copy(
        update={
            "candidates": [],
            "knowledge": [],
            "canonical_refs": [str(uuid.uuid4()), str(uuid.uuid4())],
        }
    )
    spec, envelope = await flow.setup(chain="scene", scale="scene_line", start=start)
    flow.guard_terms = [
        SimpleNamespace(
            phrase="累了就先回去",
            rule="hidden_truth",
            severity="blocking",
            source_type="world_entity",
            source_id="x",
            source_label="隐藏设定",
        )
    ]
    targets = start.canonical_refs
    task_id = await flow.enqueue(
        spec,
        envelope,
        action="story.exploration.scene_line.generate",
        multi_targets=list(targets),
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
    assert flow.provider.calls == 1  # 第一个变体即触发，快速失败


# ---------------------------------------------------------------------------
# 场景空间诊断（M2）：资料只来自已确认编译产物，缺失即强制列未知
# ---------------------------------------------------------------------------


def _world_entities_section(entries: list[dict]) -> ContextSection:
    content = "\n".join(str(entry) for entry in entries)
    return ContextSection(
        key="world_entities",
        tier=Tier.P2,
        content=content,
        title="相关世界对象",
    )


async def test_scene_diagnostic_without_material_lists_unknowns(exploration_flow):
    """无空间资料：constraints 必须为空，unknowns 由服务端补明缺资料。"""
    flow = exploration_flow
    spec, envelope = await flow.setup(chain="scene", scale="scene_line")
    task_id = await flow.enqueue(
        spec,
        envelope,
        action="story.exploration.scene_line.generate",
        diagnostic_question="醉汉能一步从大门跨到桌边吗？",
    )
    task = await flow.run(task_id)
    assert task.status == "done", task.error_message
    system = flow.provider.requests[0].messages[0].content
    assert "空间诊断器" in system
    assert "不得把想象当物理证明" in system
    user = _request_user_data(flow.provider, 0)
    assert user["spatial_material"] == []
    _row, envelope_row, root = await _load_scene_round(flow, spec)
    payload = envelope_row.payload
    assert payload.variants is None
    assert payload.line == ""
    assessment = payload.spatial_assessment
    assert assessment.supported is None
    assert assessment.constraints == []
    assert SPATIAL_UNKNOWN_DISCLOSURE in assessment.unknowns
    ledger = read_ai_run_envelope(root.run_envelope_json)
    assert ledger.requests_started == 1  # 诊断预算不变


async def test_scene_diagnostic_cites_confirmed_spatial_material(exploration_flow):
    """有资料：constraints 引用本次确认编译产物中的 location/item 条目。"""
    flow = exploration_flow
    spec, envelope = await flow.setup(chain="scene", scale="scene_line")
    flow.sections = [
        _world_entities_section(
            [
                {
                    "entity_type": "location",
                    "name": "酒馆大门",
                    "summary": "门宽仅容一人通过，距桌四步",
                },
                {
                    "entity_type": "item",
                    "name": "长桌",
                    "summary": "桌面钉死，桌边通道只容侧身",
                },
                {
                    "entity_type": "character",
                    "name": "酒保",
                    "summary": "人物档案不是空间资料",
                },
            ]
        )
    ]
    task_id = await flow.enqueue(
        spec,
        envelope,
        action="story.exploration.scene_line.generate",
        diagnostic_question="醉汉能一步从大门跨到桌边吗？",
    )
    task = await flow.run(task_id)
    assert task.status == "done", task.error_message
    user = _request_user_data(flow.provider, 0)
    material = user["spatial_material"]
    assert [item["key"] for item in material] == ["world_entities.location_item"]
    assert "酒馆大门" in material[0]["content"]
    assert "长桌" in material[0]["content"]
    assert "酒保" not in material[0]["content"]  # 角色档案不充当空间资料
    _row, envelope_row, _root = await _load_scene_round(flow, spec)
    assessment = envelope_row.payload.spatial_assessment
    assert assessment.supported is True
    assert assessment.constraints == ["桌边通道只容一人侧身（来自已确认资料）"]


async def test_scene_diagnostic_fabricated_constraints_fail_closed(exploration_flow):
    """无资料却给出约束（想象当物理证明）→ 任务失败不落库。"""
    flow = exploration_flow
    spec, envelope = await flow.setup(chain="scene", scale="scene_line")
    flow.provider.override = scene_diagnostic_payload(has_material=True)
    task_id = await flow.enqueue(
        spec,
        envelope,
        action="story.exploration.scene_line.generate",
        diagnostic_question="醉汉能一步从大门跨到桌边吗？",
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
    assert flow.provider.calls == 1
