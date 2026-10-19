"""跨尺度移交端到端集成测试（M4-A 切片 2）：handoff → 确认 → start → worker。

每条链在独立 SQLite 引擎上走真实 API 层（``handoff_exploration_result`` →
confirmation preview/confirm → ``start_exploration_task`` → TaskWorker），
模型调用由 ``ExplorationOfflineProvider`` 离线合成，无真实模型：

1. 沙盘→事件：确认 compile_options 冻结 derived_from 与派生假设；worker 跑完
   后新结果行起点指纹与派生起点一致，根为独立新根、源根逐字不变。
2. 事件（gap:0）→场景一句对白：场景结果只收到被选缺口涉及主体的知识包。
3. 场景对白→事件（追因）：identity/state 假设进入确认冻结。
4. 移交链二跳：A(event)→B(sandbox，worker 产出)→C(event，零模型派生)；
   C 的 derived_from 只记 B（一跳），B 起点中来自 A 的假设经语义继承进入 C。
5. 护栏：派生任务 worker 异常暂停后源分支与源预算信封不变、新根信封独立
   计量；重复 handoff 同参数幂等返回同一派生起点。
"""

from __future__ import annotations

import copy
import json
import uuid
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core.base import Base
from core.config import get_settings
from infrastructure.llm.client import LLMClient
from infrastructure.llm.limits import reset_llm_limiter_for_tests
from infrastructure.llm.schemas import read_ai_run_envelope
from infrastructure.llm.secret_store import encrypt_secret, fingerprint_secret
from infrastructure.llm.workflow_budget import new_ai_run_envelope
from infrastructure.tasks.models import AsyncTask
from infrastructure.tasks.worker import TaskWorker
from modules.account.settings_constants import (
    ACCOUNT_LLM_PROVIDER_TEMPLATES,
    LOCAL_OWNER_ID,
)
from modules.account.settings_repositories import (
    AccountLLMCredentialRepository,
    GlobalLLMDefaultsRepository,
)
from modules.evidence.compilation.models import ContextConfirmation
from modules.evidence.contracts import (
    Assumption,
    CandidateRef,
    KnowledgeEntry,
    ProvisionalStart,
)
from modules.story.exploration_api import (
    ExplorationHandoffApiRequest,
    ExplorationStartApiRequest,
    confirm_exploration,
    handoff_exploration_result,
    preview_confirmation,
    start_exploration_task,
)
from modules.story.exploration_budget import preview_exploration_budget
from modules.story.exploration_schemas import (
    EVENT_OUTPUT_KIND,
    SANDBOX_OUTPUT_KIND,
    SCENE_LINE_OUTPUT_KIND,
    EventOutputV1,
    ExplorationConfirmationPreviewRequest,
    ExplorationConfirmationRequest,
    ExplorationOutputEnvelope,
    SandboxOutputV1,
    SceneLineOutputV1,
    exploration_start_fingerprint,
)
from modules.story.exploration_service import (
    create_exploration_root,
    pack_exploration_output,
    unpack_exploration_output,
)
from modules.story.models import (
    StorySceneDirectorBranch,
    StorySceneDirectorRoot,
    StorySceneDirectorRound,
)
from modules.story.tests.exploration_test_support import ExplorationOfflineProvider
from modules.story.world_progression_models import (
    StoryWorldProgressionBranch,
    StoryWorldProgressionRoot,
    StoryWorldProgressionStep,
)

OWNER_ID = str(LOCAL_OWNER_ID)

SANDBOX_ACTION = "story.exploration.sandbox.generate"
EVENT_DIAGNOSE_ACTION = "story.exploration.event.diagnose"
SCENE_LINE_ACTION = "story.exploration.scene_line.generate"


class _Manager:
    def __init__(self, engine, sessions):
        self.engine = engine
        self.session_factory = sessions


@pytest_asyncio.fixture
async def handoff_engine():
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
async def flow(handoff_engine, monkeypatch):
    """离线移交全链夹具：gate 开启、模型离线、确认/入队/worker 全走真实实现。"""
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

    monkeypatch.setattr(
        "modules.story.exploration_tasks.open_project_snapshot_llm_client",
        offline_client,
    )

    sessions = async_sessionmaker(handoff_engine, expire_on_commit=False)
    novel_id = uuid.uuid4()
    async with sessions.begin() as db:
        from modules.project.models import Project

        project = Project(id=novel_id, title="移交端到端测试")
        db.add(project)
        await db.flush()
        owner_id = str(project.owner_id)
        # start 端点的执行快照解析真实账户连接：种本地 owner 的已验证连接，
        # 让 build_project_llm_execution_snapshot 全程离线（仅 DB 读取）。
        api_key = "handoff-e2e-key"
        await AccountLLMCredentialRepository().upsert(
            db,
            {
                "owner_id": LOCAL_OWNER_ID,
                "provider_id": "deepseek",
                "encrypted_api_key": encrypt_secret(api_key),
                "key_fingerprint": fingerprint_secret(
                    api_key,
                    purpose="account-llm-api-key",
                ),
                "verified_at": datetime.now(UTC),
            },
        )
        await GlobalLLMDefaultsRepository().upsert(
            db,
            {
                "owner_id": LOCAL_OWNER_ID,
                **ACCOUNT_LLM_PROVIDER_TEMPLATES["deepseek"],
            },
        )

    return SimpleNamespace(
        engine=handoff_engine,
        sessions=sessions,
        provider=provider,
        novel_id=novel_id,
        owner_id=owner_id,
    )


# ---------------------------------------------------------------------------
# 播种与步骤助手
# ---------------------------------------------------------------------------


def _attach_run_envelope(root, novel_id) -> None:
    """源根附独立探索运行信封：API 移交的结果定位按能力门校验。"""
    started_at = datetime.now(UTC)
    root.run_envelope_json = (
        new_ai_run_envelope(
            operation_id=str(uuid.uuid4()),
            run_id=str(root.id),
            root_capability_id="story.exploration",
            novel_id=str(novel_id),
            request_limit=1,
            budget_mode="bounded",
            token_limit=200_000,
            started_at=started_at,
            deadline_at=started_at + timedelta(hours=1),
        )
        .snapshot()
        .model_dump(mode="json")
    )


async def _seed_source(flow, *, scale, start, envelope):
    """种一个已跑完的源探索根 + AI 结果行；返回根/分支/行及其快照。"""
    async with flow.sessions.begin() as db:
        from modules.evidence.contracts import ExplorationContextRequest
        from modules.evidence.facade import confirm_exploration_context

        action = {
            "sandbox": "story.exploration.sandbox.generate",
            "event": "story.exploration.event.diagnose",
            "scene_line": "story.exploration.scene_line.generate",
        }[scale]
        confirmation = await confirm_exploration_context(
            db,
            ExplorationContextRequest(
                novel_id=str(flow.novel_id),
                action=action,
                exploration_scale=scale,
                task="generation",
                scope="scene" if start.kind == "scene_anchor" else "project",
                start=start,
                scene_id=start.scene_id if start.kind == "scene_anchor" else None,
                visible_until_scene_id=start.scene_id
                if start.kind == "scene_anchor"
                else None,
            ),
        )
        root, branch = await create_exploration_root(
            db,
            novel_id=str(flow.novel_id),
            owner_id=OWNER_ID,
            scale=scale,
            start=start,
            context_confirmation_id=(
                str(uuid.uuid4()) if scale in ("sandbox", "event") else None
            ),
        )
        branch.request_json = {
            **(branch.request_json or {}),
            "context_confirmation_id": confirmation.id,
            "confirmation_action": action,
        }
        _attach_run_envelope(root, flow.novel_id)
        if scale in ("sandbox", "event"):
            row = StoryWorldProgressionStep(
                novel_id=root.novel_id,
                root_id=root.id,
                branch_id=branch.id,
                step_number=1,
                source_hash=root.source_hash,
                input_hash="a" * 64,
                output_hash="b" * 64,
                input_json={"mode": "start"},
                result_json=pack_exploration_output(envelope),
                state_json={},
                metrics_json={"mode": "start", "exploration": True},
                basis_changed=False,
            )
        else:
            row = StorySceneDirectorRound(
                novel_id=root.novel_id,
                root_id=root.id,
                branch_id=branch.id,
                round_number=1,
                source_hash=root.source_hash,
                input_hash="c" * 64,
                output_hash="d" * 64,
                input_json={"mode": "start"},
                output_json=pack_exploration_output(envelope),
                state_json={},
                run_envelope_json={},
            )
        db.add(row)
        await db.flush()
        root.status = "ready"
        branch.status = "complete"
        await db.flush()
        root_snap = _root_snapshot(root)
        row_snap = _row_snapshot(row)
    return SimpleNamespace(
        root=root,
        branch=branch,
        row=row,
        root_snap=root_snap,
        row_snap=row_snap,
    )


def _root_snapshot(root) -> dict:
    return {
        "id": str(root.id),
        "status": root.status,
        "source_hash": root.source_hash,
        "novel_id": str(root.novel_id),
        "request_json": copy.deepcopy(root.request_json),
        "run_envelope_json": copy.deepcopy(root.run_envelope_json),
        "current_task_id": (str(root.current_task_id) if root.current_task_id else None),
    }


def _row_snapshot(row) -> dict:
    payload = row.result_json if hasattr(row, "result_json") else row.output_json
    return {
        "input_hash": row.input_hash,
        "output_hash": row.output_hash,
        "input_json": copy.deepcopy(row.input_json),
        "payload_json": copy.deepcopy(payload),
    }


async def _handoff(
    flow, row, *, target_scale, item_path="", selector="author", reason=""
):
    async with flow.sessions.begin() as db:
        return await handoff_exploration_result(
            db,
            result_id=str(row.id),
            data=ExplorationHandoffApiRequest(
                novel_id=str(flow.novel_id),
                operation_id=uuid.uuid4(),
                target_scale=target_scale,
                item_path=item_path,
                selector=selector,
                reason=reason,
            ),
        )


async def _confirm_and_start(flow, derived, *, scale, action):
    preview_request = ExplorationConfirmationPreviewRequest(
        novel_id=str(flow.novel_id),
        scale=scale,
        start=derived,
        action=action,
    )
    async with flow.sessions.begin() as db:
        preview = await preview_confirmation(db, preview_request)
        confirmed = await confirm_exploration(
            db,
            ExplorationConfirmationRequest(
                **preview_request.model_dump(mode="json"),
                expected_context_fingerprint=preview["context_fingerprint"],
            ),
        )
    budget = preview_exploration_budget(
        novel_id=str(flow.novel_id), scale=scale, start=derived, focus=""
    )
    async with flow.sessions.begin() as db:
        started = await start_exploration_task(
            db,
            data=ExplorationStartApiRequest(
                novel_id=str(flow.novel_id),
                scale=scale,
                start=derived,
                action=action,
                focus="",
                context_confirmation_id=confirmed["confirmation_id"],
                budget_preview_hash=budget.preview_hash,
                operation_id=uuid.uuid4(),
            ),
        )
    return confirmed, started


async def test_handoff_rejects_source_mutation_after_target_confirmation(flow):
    from core.errors import ConflictError
    from modules.evidence.facade import prepare_confirmed_ai_action

    source = await _seed_source(
        flow, scale="sandbox", start=_sandbox_start(), envelope=_sandbox_envelope()
    )
    handed = await _handoff(flow, source.row, target_scale="event", item_path="chain:0")
    derived = ProvisionalStart.model_validate(handed["derived_start"])
    confirmed, _started = await _confirm_and_start(
        flow, derived, scale="event", action=EVENT_DIAGNOSE_ACTION
    )
    async with flow.sessions.begin() as db:
        row = await db.get(StoryWorldProgressionStep, source.row.id)
        changed = copy.deepcopy(row.result_json)
        changed["payload"]["influence_chain"][0]["holds_when"] = "来源已经换了条件"
        row.result_json = changed
    async with flow.sessions.begin() as db:
        with pytest.raises(ConflictError, match="移交来源"):
            await prepare_confirmed_ai_action(
                db,
                novel_id=str(flow.novel_id),
                action=EVENT_DIAGNOSE_ACTION,
                confirmation_id=confirmed["confirmation_id"],
            )


async def test_scene_handoff_target_confirmation_preserves_source_cutoff(flow):
    from modules.evidence.contracts import SceneAnchorStart
    from modules.story.outline_state.models import Scene

    async with flow.sessions.begin() as db:
        scene = Scene(
            novel_id=flow.novel_id,
            scene_index=0,
            title="过去的雨夜",
            goal="目标不是人物知识",
        )
        db.add(scene)
        await db.flush()
        scene_id = str(scene.id)
    source = await _seed_source(
        flow,
        scale="scene_line",
        start=SceneAnchorStart(kind="scene_anchor", scene_id=scene_id),
        envelope=_scene_envelope(),
    )
    handed = await _handoff(flow, source.row, target_scale="event")
    confirmed, _started = await _confirm_and_start(
        flow,
        ProvisionalStart.model_validate(handed["derived_start"]),
        scale="event",
        action=EVENT_DIAGNOSE_ACTION,
    )
    async with flow.sessions() as db:
        record = await db.get(
            ContextConfirmation, uuid.UUID(confirmed["confirmation_id"])
        )
        assert record.compile_options["scene_id"] == scene_id
        assert record.compile_options["visible_until_scene_id"] == scene_id


async def _run_task(flow, task_id) -> AsyncTask:
    worker = TaskWorker(
        db_manager=_Manager(flow.engine, flow.sessions),
        heartbeat_interval=60.0,
    )
    await worker.run_once(task_id=uuid.UUID(str(task_id)), novel_id=str(flow.novel_id))
    async with flow.sessions() as db:
        return await db.get(AsyncTask, uuid.UUID(str(task_id)))


async def _confirmation_options(flow, confirmation_id) -> dict:
    async with flow.sessions() as db:
        record = await db.get(ContextConfirmation, uuid.UUID(str(confirmation_id)))
        return dict(record.compile_options or {})


async def _progression_root_and_steps(flow, root_id):
    async with flow.sessions() as db:
        root = await db.get(StoryWorldProgressionRoot, uuid.UUID(str(root_id)))
        steps = (
            await db.scalars(
                select(StoryWorldProgressionStep)
                .where(StoryWorldProgressionStep.root_id == uuid.UUID(str(root_id)))
                .order_by(StoryWorldProgressionStep.step_number)
            )
        ).all()
        return root, steps


async def _scene_root_and_rounds(flow, root_id):
    async with flow.sessions() as db:
        root = await db.get(StorySceneDirectorRoot, uuid.UUID(str(root_id)))
        rounds = (
            await db.scalars(
                select(StorySceneDirectorRound)
                .where(StorySceneDirectorRound.root_id == uuid.UUID(str(root_id)))
                .order_by(StorySceneDirectorRound.round_number)
            )
        ).all()
        return root, rounds


async def _refetch_source(flow, source):
    async with flow.sessions() as db:
        if hasattr(source.row, "result_json"):
            root = await db.get(StoryWorldProgressionRoot, source.root.id)
            branch = await db.get(StoryWorldProgressionBranch, source.branch.id)
            row = await db.get(StoryWorldProgressionStep, source.row.id)
        else:
            root = await db.get(StorySceneDirectorRoot, source.root.id)
            branch = await db.get(StorySceneDirectorBranch, source.branch.id)
            row = await db.get(StorySceneDirectorRound, source.row.id)
        return root, branch, row


async def _assert_source_untouched(flow, source) -> None:
    """源根/分支/结果行内容与状态逐字不变（含哈希字段与预算信封）。"""
    root, branch, row = await _refetch_source(flow, source)
    assert _root_snapshot(root) == source.root_snap
    assert branch.status == "complete"
    assert root.current_task_id is None and branch.current_task_id is None
    assert _row_snapshot(row) == source.row_snap


def _request_user_data(provider, index: int) -> dict:
    return json.loads(provider.generation_requests[index].messages[1].content)


def _assert_absent(texts: str, banned: list[str]) -> None:
    for item in banned:
        assert item not in texts, f"未选内容串入：{item}"


# ---------------------------------------------------------------------------
# 夹具：起点与结果载荷
# ---------------------------------------------------------------------------


def _sandbox_start() -> ProvisionalStart:
    return ProvisionalStart(
        kind="provisional",
        question="这个城镇每天只有一小时重力减半，面包师的一天会怎样？",
        assumptions=[
            Assumption(kind="world_rule", text="每天只有一小时重力减半"),
            Assumption(kind="state", text="面包师沿用石炉揉面"),
        ],
        candidates=[
            CandidateRef(ref_id="c_baker", label="面包师", role="character"),
            CandidateRef(ref_id="c_customer", label="清晨顾客", role="character"),
        ],
        knowledge=[
            KnowledgeEntry(subject_ref="c_baker", knows=["揉面的手艺"]),
            KnowledgeEntry(subject_ref="c_customer", knows=["面包店的位置"]),
        ],
        time_basis="assumed_now",
    )


_CHAIN = [
    {
        "condition": "揉面时间不变",
        "mechanism": "重力降低让面团发酵更快",
        "effect": "面包更松软",
        "affected_refs": ["c_baker"],
    },
    {
        "condition": "出炉提前",
        "mechanism": "清晨顾客变多",
        "effect": "面包师更累",
        "affected_refs": ["c_customer"],
    },
]


def _sandbox_envelope() -> ExplorationOutputEnvelope:
    return ExplorationOutputEnvelope(
        output_kind=SANDBOX_OUTPUT_KIND,
        schema_version=1,
        payload=SandboxOutputV1.model_validate(
            {"question": "重力减半后面包师的一天？", "influence_chain": _CHAIN}
        ),
    )


def _event_start() -> ProvisionalStart:
    return ProvisionalStart(
        kind="provisional",
        question="信使为什么能送到？",
        assumptions=[Assumption(kind="state", text="信件当天送达")],
        candidates=[
            CandidateRef(ref_id="c_messenger", label="信使", role="character"),
            CandidateRef(ref_id="c_recipient", label="收信人", role="character"),
        ],
        knowledge=[
            KnowledgeEntry(subject_ref="c_messenger", knows=["投递任务"]),
            KnowledgeEntry(subject_ref="c_recipient", knows=["自己的行踪"]),
        ],
        time_basis="assumed_now",
    )


def _event_envelope() -> ExplorationOutputEnvelope:
    """两缺口事件诊断：gap:0 写明 c_recipient（保守匹配），gap:1 涉另一条件。"""
    return ExplorationOutputEnvelope(
        output_kind=EVENT_OUTPUT_KIND,
        schema_version=1,
        payload=EventOutputV1.model_validate(
            {
                "mode": "diagnose",
                "original_excerpt": "信使不知道地址，却当天把信送到了本人手里",
                "gaps": [
                    {
                        "description": "缺少 c_recipient 行踪被获知的接触路径",
                        "why_needed": "解释为何能精准送达",
                        "possible_fix_hint": "有人在城门口认出了收信人",
                    },
                    {
                        "description": "缺少当天的路径依据",
                        "why_needed": "解释当天往返的可能",
                    },
                ],
                "info_boundary": [
                    {
                        "subject_ref": "c_messenger",
                        "subject_description": "信使",
                        "knows": ["投递任务"],
                        "not_known": ["收信人的地址"],
                        "missing_contact_path": True,
                    },
                    {
                        "subject_ref": "c_recipient",
                        "subject_description": "收信人",
                        "knows": ["自己的行踪"],
                        "not_known": [],
                        "missing_contact_path": False,
                    },
                ],
                "unknowns": [],
                "warnings": [],
            }
        ),
    )


def _scene_start() -> ProvisionalStart:
    return ProvisionalStart(
        kind="provisional",
        question="A 刚失业；B 不知此事，只看见 A 很疲惫。B 会说什么？",
        assumptions=[
            Assumption(kind="state", text="A 刚失业，心情低落"),
            Assumption(kind="state", text="B 不知道失业的事"),
        ],
        candidates=[
            CandidateRef(ref_id="c_a", label="阿澜", role="character"),
            CandidateRef(ref_id="c_b", label="白舟", role="character"),
        ],
        knowledge=[
            KnowledgeEntry(subject_ref="c_a", knows=["自己失业了"]),
            KnowledgeEntry(
                subject_ref="c_b", knows=["A 脚步发沉"], observed=["A 很疲惫"]
            ),
        ],
        time_basis="assumed_now",
    )


def _scene_envelope() -> ExplorationOutputEnvelope:
    return ExplorationOutputEnvelope(
        output_kind=SCENE_LINE_OUTPUT_KIND,
        schema_version=1,
        payload=SceneLineOutputV1.model_validate(
            {
                "target_ref": "c_b",
                "line": "你要是累了就先回去吧。",
                "rationale": "目标只看得到对方疲惫，不知道失业的事。",
                "knowledge_basis": ["observed:对方脚步发沉"],
            }
        ),
    )


# ---------------------------------------------------------------------------
# 链 1：沙盘 → 事件
# ---------------------------------------------------------------------------


async def test_sandbox_to_event_full_chain(flow):
    source = await _seed_source(
        flow, scale="sandbox", start=_sandbox_start(), envelope=_sandbox_envelope()
    )
    body = await _handoff(flow, source.row, target_scale="event", item_path="chain:1")
    assert (
        body["source_fingerprint"]
        == body["derived_start"]["derived_from"]["source_fingerprint"]
    )
    derived = ProvisionalStart.model_validate(body["derived_start"])
    # 派生起点：derived_from 一跳记录；未选链条目（chain:0）不串入。
    assert derived.derived_from.source_result_id == str(source.row.id)
    assert derived.derived_from.source_scale == "sandbox"
    assert derived.derived_from.item_path == "chain:1"
    assert derived.derived_from.selector == "author"
    assert derived.assumptions[0].kind == "state"
    assert "面包师更累" in derived.assumptions[0].text
    _assert_absent(
        json.dumps(derived.model_dump(mode="json"), ensure_ascii=False),
        ["面包更松软", "揉面时间不变"],
    )
    assert [item.ref_id for item in derived.candidates] == ["c_customer"]
    assert [entry.subject_ref for entry in derived.knowledge] == ["c_customer"]

    confirmed, started = await _confirm_and_start(
        flow, derived, scale="event", action=EVENT_DIAGNOSE_ACTION
    )
    options = await _confirmation_options(flow, confirmed["confirmation_id"])
    # 确认冻结：derived_from 与派生假设（含继承前提）进 compile_options。
    assert options["exploration_scale"] == "event"
    frozen = options["exploration_start"]
    assert frozen["derived_from"]["source_result_id"] == str(source.row.id)
    assert frozen["derived_from"]["item_path"] == "chain:1"
    assert frozen["assumptions"][0]["text"] == derived.assumptions[0].text
    assert [(item["kind"], item["text"]) for item in frozen["assumptions"][1:]] == [
        (item.kind, item.text) for item in _sandbox_start().assumptions
    ]
    assert ProvisionalStart.model_validate(frozen).derived_from is not None

    new_root_id = uuid.UUID(started["root_id"])
    assert new_root_id != source.root.id  # 独立新根
    task = await _run_task(flow, started["task_id"])
    assert task.status == "done", task.error_message
    assert dict(task.result or {})["status"] == "completed"

    derived_fingerprint = exploration_start_fingerprint(derived, "event")
    root, steps = await _progression_root_and_steps(flow, new_root_id)
    assert root.status == "ready"
    assert root.novel_id == flow.novel_id
    assert flow.owner_id == OWNER_ID  # 新根归属同 owner/novel（经项目归属）
    assert root.request_json["exploration_start_fingerprint"] == derived_fingerprint
    assert len(steps) == 1
    step = steps[0]
    assert step.novel_id == flow.novel_id
    assert step.input_json["mode"] == "start"
    assert step.input_json["start_summary"]["fingerprint"] == derived_fingerprint
    envelope_row = unpack_exploration_output(step)
    assert envelope_row.output_kind == EVENT_OUTPUT_KIND
    assert envelope_row.payload.mode == "diagnose"
    ledger = read_ai_run_envelope(root.run_envelope_json)
    assert ledger.requests_started == 3

    # 模型输入只含被选内容：未选链条目与其主体不进入请求。
    user = _request_user_data(flow.provider, 0)
    _assert_absent(
        json.dumps(user, ensure_ascii=False), ["面包更松软", "揉面时间不变", "c_baker"]
    )
    assert set(user["candidate_summaries"]) == {"c_customer"}
    await _assert_source_untouched(flow, source)


# ---------------------------------------------------------------------------
# 链 2：事件（gap:0）→ 场景一句对白
# ---------------------------------------------------------------------------


async def test_event_gap_to_scene_line_full_chain(flow):
    source = await _seed_source(
        flow, scale="event", start=_event_start(), envelope=_event_envelope()
    )
    body = await _handoff(flow, source.row, target_scale="scene_line", item_path="gap:0")
    derived = ProvisionalStart.model_validate(body["derived_start"])
    assert derived.derived_from.item_path == "gap:0"
    assert derived.assumptions[0].kind == "state"
    assert "缺少 c_recipient 行踪被获知的接触路径" in derived.assumptions[0].text
    _assert_absent(
        json.dumps(derived.model_dump(mode="json"), ensure_ascii=False),
        ["缺少当天的路径依据"],
    )
    assert [item.ref_id for item in derived.candidates] == ["c_recipient"]
    assert [entry.subject_ref for entry in derived.knowledge] == ["c_recipient"]

    _confirmed, started = await _confirm_and_start(
        flow, derived, scale="scene_line", action=SCENE_LINE_ACTION
    )
    new_root_id = uuid.UUID(started["root_id"])
    task = await _run_task(flow, started["task_id"])
    assert task.status == "done", task.error_message

    root, rounds = await _scene_root_and_rounds(flow, new_root_id)
    assert root.status == "ready"
    assert root.novel_id == flow.novel_id
    derived_fingerprint = exploration_start_fingerprint(derived, "scene_line")
    assert root.request_json["exploration_start_fingerprint"] == derived_fingerprint
    assert len(rounds) == 1
    row = rounds[0]
    assert row.novel_id == flow.novel_id
    assert row.input_json["start_summary"]["fingerprint"] == derived_fingerprint
    envelope_row = unpack_exploration_output(row)
    assert envelope_row.output_kind == SCENE_LINE_OUTPUT_KIND
    assert envelope_row.payload.variants is None
    assert envelope_row.payload.target_ref == "c_recipient"
    assert envelope_row.payload.line

    # 场景结果只收到被选缺口涉及主体的知识包：c_messenger 的可知与未选缺口不进请求。
    user = _request_user_data(flow.provider, 0)
    assert user["target"]["ref"] == "c_recipient"
    assert user["target_knowledge"]["knows"] == ["自己的行踪"]
    _assert_absent(
        json.dumps(user, ensure_ascii=False), ["投递任务", "缺少当天的路径依据"]
    )
    await _assert_source_untouched(flow, source)


# ---------------------------------------------------------------------------
# 链 3：场景对白 → 事件（追因）
# ---------------------------------------------------------------------------


async def test_scene_line_to_event_full_chain(flow):
    source = await _seed_source(
        flow, scale="scene_line", start=_scene_start(), envelope=_scene_envelope()
    )
    body = await _handoff(flow, source.row, target_scale="event")
    derived = ProvisionalStart.model_validate(body["derived_start"])
    assert derived.derived_from.source_scale == "scene_line"
    assert derived.derived_from.item_path == ""
    assert derived.assumptions[0].kind == "state"
    assert "你要是累了就先回去吧。" in derived.assumptions[0].text
    # 追因：identity 假设（动机待探）进入派生起点。
    assert derived.assumptions[1].kind == "identity"
    assert "动机" in derived.assumptions[1].text
    assert [item.ref_id for item in derived.candidates] == ["c_b"]

    confirmed, started = await _confirm_and_start(
        flow, derived, scale="event", action=EVENT_DIAGNOSE_ACTION
    )
    options = await _confirmation_options(flow, confirmed["confirmation_id"])
    frozen = options["exploration_start"]
    assert frozen["derived_from"]["source_result_id"] == str(source.row.id)
    assert frozen["assumptions"][0]["kind"] == "state"
    assert frozen["assumptions"][1]["kind"] == "identity"
    assert "动机" in frozen["assumptions"][1]["text"]

    new_root_id = uuid.UUID(started["root_id"])
    task = await _run_task(flow, started["task_id"])
    assert task.status == "done", task.error_message

    root, steps = await _progression_root_and_steps(flow, new_root_id)
    assert root.status == "ready"
    assert root.novel_id == flow.novel_id
    derived_fingerprint = exploration_start_fingerprint(derived, "event")
    assert root.request_json["exploration_start_fingerprint"] == derived_fingerprint
    assert len(steps) == 1
    step = steps[0]
    assert step.novel_id == flow.novel_id
    assert step.input_json["start_summary"]["fingerprint"] == derived_fingerprint
    envelope_row = unpack_exploration_output(step)
    assert envelope_row.output_kind == EVENT_OUTPUT_KIND
    # 未选对白主体（阿澜）不串入模型请求。
    user = _request_user_data(flow.provider, 0)
    _assert_absent(json.dumps(user, ensure_ascii=False), ["阿澜", "自己失业了"])
    await _assert_source_untouched(flow, source)


# ---------------------------------------------------------------------------
# 链 4：移交链二跳（A(event) → B(sandbox) → C(event)）
# ---------------------------------------------------------------------------


async def test_two_hop_handoff_keeps_one_hop_ref_and_semantic_chain(flow):
    source = await _seed_source(
        flow, scale="event", start=_event_start(), envelope=_event_envelope()
    )
    # 第一跳：A 的 gap:0 → 沙盘派生起点 → 确认 → start → worker 产出 B 结果行。
    hop1 = await _handoff(flow, source.row, target_scale="sandbox", item_path="gap:0")
    b_start = ProvisionalStart.model_validate(hop1["derived_start"])
    _assert_absent(
        b_start.model_dump(mode="json").__str__(), ["缺少当天的路径依据"]
    )  # 未选缺口不串入
    _confirmed_b, started_b = await _confirm_and_start(
        flow, b_start, scale="sandbox", action=SANDBOX_ACTION
    )
    b_root_id = uuid.UUID(started_b["root_id"])
    task_b = await _run_task(flow, started_b["task_id"])
    assert task_b.status == "done", task_b.error_message
    b_root, b_steps = await _progression_root_and_steps(flow, b_root_id)
    assert b_root.status == "ready"
    assert len(b_steps) == 1
    b_row = b_steps[0]
    b_envelope = unpack_exploration_output(b_row)
    assert b_envelope.output_kind == SANDBOX_OUTPUT_KIND

    # 第二跳：B 的结果再移交 C（事件），零模型派生。
    hop2 = await _handoff(flow, b_row, target_scale="event", item_path="chain:0")
    c_start = ProvisionalStart.model_validate(hop2["derived_start"])
    # 一跳记录：C 的 derived_from 指向 B 的结果 id，不指向 A。
    assert c_start.derived_from.source_result_id == str(b_row.id)
    assert c_start.derived_from.source_result_id != str(source.row.id)
    assert c_start.derived_from.source_scale == "sandbox"
    assert c_start.derived_from.item_path == "chain:0"
    # 语义继承：C 置顶假设携带 B 结果的被选影响；B 起点（来自 A 的缺口前提）
    # 的假设原样保留在 C 的前提集中。
    assert c_start.assumptions[0].kind == "state"
    assert "面包更松软，出炉提前" in c_start.assumptions[0].text
    assert {(item.kind, item.text) for item in b_start.assumptions}.issubset(
        {(item.kind, item.text) for item in c_start.assumptions[1:]}
    )
    assert any("精确发酵速率未知" in item.text for item in c_start.assumptions)
    assert any(
        "缺少 c_recipient 行踪被获知的接触路径" in item.text
        for item in c_start.assumptions[1:]
    )
    # B 根冻结起点中的 A 假设在第二跳后仍在（源不可变 + 一跳溯源不断链）。
    b_root_refetch, _b_steps_refetch = await _progression_root_and_steps(flow, b_root_id)
    frozen_b = ProvisionalStart.model_validate(
        b_root_refetch.request_json["exploration_start"]
    )
    assert frozen_b.derived_from.source_result_id == str(source.row.id)
    assert [(item.kind, item.text) for item in frozen_b.assumptions] == [
        (item.kind, item.text) for item in b_start.assumptions
    ]
    await _assert_source_untouched(flow, source)


# ---------------------------------------------------------------------------
# 链 5：护栏
# ---------------------------------------------------------------------------


async def test_handoff_derived_failure_leaves_source_and_budgets_independent(flow):
    source = await _seed_source(
        flow, scale="sandbox", start=_sandbox_start(), envelope=_sandbox_envelope()
    )
    body = await _handoff(flow, source.row, target_scale="event", item_path="chain:1")
    derived = ProvisionalStart.model_validate(body["derived_start"])
    _confirmed, started = await _confirm_and_start(
        flow, derived, scale="event", action=EVENT_DIAGNOSE_ACTION
    )
    derived_root_id = uuid.UUID(started["root_id"])

    flow.provider.fail_next = True  # worker 模型请求异常（结果未知）
    task = await _run_task(flow, started["task_id"])
    assert dict(task.result or {})["status"] == "paused_unknown"

    root, steps = await _progression_root_and_steps(flow, derived_root_id)
    assert root.status == "paused_unknown"
    branch = await _branch_status(flow, started["branch_id"])
    assert branch == "paused_unknown"
    assert steps == []  # 派生任务未落任何结果行
    derived_ledger = read_ai_run_envelope(root.run_envelope_json)
    # 预算独立：新根信封独立计量本次未知请求，与源根信封互不相干。
    assert derived_ledger.run_id == str(derived_root_id)
    assert derived_ledger.requests_unknown == 1
    await _assert_source_untouched(flow, source)

    async with flow.sessions() as db:
        source_root = await db.get(StoryWorldProgressionRoot, source.root.id)
        source_ledger = read_ai_run_envelope(source_root.run_envelope_json)
    assert source_ledger.run_id == str(source.root.id)
    assert source_ledger.requests_unknown == 0
    assert source_ledger.requests_started == 0


async def _branch_status(flow, branch_id) -> str:
    async with flow.sessions() as db:
        branch = await db.get(StoryWorldProgressionBranch, uuid.UUID(str(branch_id)))
        return branch.status


async def test_repeated_handoff_same_params_is_idempotent(flow):
    source = await _seed_source(
        flow, scale="sandbox", start=_sandbox_start(), envelope=_sandbox_envelope()
    )
    first = await _handoff(flow, source.row, target_scale="event", item_path="chain:1")
    second = await _handoff(flow, source.row, target_scale="event", item_path="chain:1")
    assert first["derived_start"] == second["derived_start"]
    assert first["source_fingerprint"] == second["source_fingerprint"]
    assert (
        ProvisionalStart.model_validate(first["derived_start"]).derived_from is not None
    )
    # 移交零模型调用：重复派生不产生任何请求。
    assert flow.provider.calls == 0
    await _assert_source_untouched(flow, source)
