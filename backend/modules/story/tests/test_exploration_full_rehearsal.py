"""临时起点完整排演 worker 执行器（M3-B 切片 2）离线全链测试。

覆盖：多轮全链调用计量与轮次连续、author_goal 只进作者统筹包、候选知识包
隔离、观察/素材跨轮传递、canonical hidden guard 失败关闭、检查点中断续跑
不重跑已完成轮、预算耗尽暂停、preview hash 含排演身份、根冻结意图一致性、
检查点模式与聚焦任务互斥、跨 novel 拒绝、结果落库与信封判别。
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import select

from infrastructure.llm.schemas import AI_RUN_ENVELOPE_KEY, read_ai_run_envelope
from infrastructure.tasks.enqueuer import enqueue_task
from infrastructure.tasks.worker import TaskWorker
from modules.account.settings_constants import LOCAL_OWNER_ID
from modules.evidence.contracts import Assumption, CandidateRef, ProvisionalStart
from modules.story import exploration_tasks
from modules.story.exploration_budget import preview_exploration_budget
from modules.story.exploration_schemas import (
    FULL_REHEARSAL_OUTPUT_KIND,
    FullRehearsalOutputV1,
    FullRehearsalRequest,
)
from modules.story.exploration_service import (
    list_exploration_history_results,
    pack_exploration_output,
    unpack_exploration_output,
)
from modules.story.models import (
    StorySceneDirectorBranch,
    StorySceneDirectorRoot,
    StorySceneDirectorRound,
)
from modules.story.tests.exploration_test_support import full_rehearsal_card
from modules.story.tests.test_exploration_worker import (  # noqa: F401
    _Manager,
    exploration_engine,
    exploration_flow,
)

OWNER_ID = str(LOCAL_OWNER_ID)

_AUTHOR_GOAL = "对比两人对离职话题的立场差异（作者私密目的）"
_AUTHOR_PRIVATE = "作者私享：对方下周其实会回来"
_OBSERVATION_TEXT = "对方把伞柄又握紧了一些。"


def _rehearsal_pair_start() -> ProvisionalStart:
    """两个候选人物：知识/误信刻意不同，另带一条作者私享。"""
    return ProvisionalStart(
        kind="provisional",
        question="雨夜站台，对方刚提完离职，两人各自会说什么？",
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
        author_private=[_AUTHOR_PRIVATE],
        time_basis="assumed_now",
    )


def _rehearsal(
    targets=("c_franks", "c_evasive"),
    rounds=2,
    author_goal=_AUTHOR_GOAL,
) -> FullRehearsalRequest:
    return FullRehearsalRequest(
        targets=list(targets), rounds=rounds, author_goal=author_goal
    )


async def _freeze_rehearsal_root(flow, spec, rehearsal: FullRehearsalRequest) -> None:
    """把排演意图冻结进根 request_json（对齐 create_exploration_root 的 API 行为）。"""
    async with flow.sessions.begin() as db:
        root = await db.get(StorySceneDirectorRoot, spec.root_id)
        root.request_json = {
            **(root.request_json or {}),
            "full_rehearsal": rehearsal.model_dump(mode="json"),
        }


async def _latest_root_envelope(flow, spec) -> dict:
    """读取根上最新累计预算信封（第二次入队须携带最新快照，对齐续算链路）。"""
    async with flow.sessions() as db:
        root = await db.get(StorySceneDirectorRoot, spec.root_id)
        return dict(root.run_envelope_json or {})


async def _enqueue_rehearsal(
    flow,
    spec,
    envelope,
    rehearsal: FullRehearsalRequest,
    *,
    preview_hash: str | None = None,
    novel_id: str | None = None,
    envelope_snapshot: dict | None = None,
):
    budget = preview_exploration_budget(
        novel_id=str(novel_id or spec.novel_id),
        scale="scene_line",
        start=spec.start,
        focus=spec.focus,
        full_rehearsal=rehearsal,
    )
    # 预算 guard 从携带的快照派生（对齐 API _exploration_meta 的续算行为）。
    snapshot = envelope_snapshot or envelope.snapshot().model_dump(mode="json")
    meta = {
        AI_RUN_ENVELOPE_KEY: snapshot,
        "exploration_root_id": str(spec.root_id),
        "exploration_branch_id": str(spec.branch_id),
        "exploration_scale": "scene_line",
        "exploration_authorized_requests": budget.requests_max,
        "exploration_authorized_tokens": budget.tokens_max,
        "exploration_deadline_seconds": 3600,
        "exploration_acknowledged_unknown_requests": int(
            snapshot.get("requests_unknown") or 0
        ),
        "exploration_baseline_requests_started": int(
            snapshot.get("requests_started") or 0
        ),
        "exploration_baseline_recent_attempts_overflow": int(
            snapshot.get("recent_attempts_overflow") or 0
        ),
        "llm_execution_snapshot": {"novel_id": str(spec.novel_id)},
        "action": "story.exploration.scene_line.generate",
        "confirmation_action": "story.exploration.scene_line.generate",
        "context_confirmation_id": spec.confirmation_id,
        "request": {
            "mode": "start",
            "start": spec.start.model_dump(mode="json"),
            "scale": "scene_line",
            "focus": spec.focus,
            "full_rehearsal": rehearsal.model_dump(mode="json"),
        },
        "budget_preview_hash": preview_hash or budget.preview_hash,
    }
    async with flow.sessions.begin() as db:
        task_id = uuid.UUID(
            enqueue_task(
                db,
                exploration_tasks.EXPLORATION_SCENE_TASK,
                novel_id=str(novel_id or spec.novel_id),
                meta=meta,
            )
        )
        root = await db.get(StorySceneDirectorRoot, spec.root_id)
        branch = await db.get(StorySceneDirectorBranch, spec.branch_id)
        if root is not None and branch is not None:
            root.current_task_id = branch.current_task_id = task_id
    return task_id


async def _load_flow_rows(flow, spec):
    async with flow.sessions() as db:
        row = await db.scalar(
            select(StorySceneDirectorRound).where(
                StorySceneDirectorRound.root_id == spec.root_id
            )
        )
        root = await db.get(StorySceneDirectorRoot, spec.root_id)
        branch = await db.get(StorySceneDirectorBranch, spec.branch_id)
    return row, unpack_exploration_output(row), root, branch


async def _rehearsal_round_rows(flow, spec) -> list:
    async with flow.sessions() as db:
        return list(
            (
                await db.scalars(
                    select(StorySceneDirectorRound).where(
                        StorySceneDirectorRound.root_id == spec.root_id
                    )
                )
            ).all()
        )


def _request_user_data(provider, index: int) -> dict:
    return json.loads(provider.generation_requests[index].messages[1].content)


def _performance_requests(provider) -> list[dict]:
    return [
        _request_user_data(provider, index)
        for index, request in enumerate(provider.generation_requests)
        if json.loads(request.messages[1].content).get("mode")
        == "full_rehearsal_performance"
    ]


def _orchestration_requests(provider) -> list[dict]:
    return [
        _request_user_data(provider, index)
        for index, request in enumerate(provider.generation_requests)
        if json.loads(request.messages[1].content).get("mode")
        == "full_rehearsal_orchestration"
    ]


# ---------------------------------------------------------------------------
# 全链：调用计量、轮次连续、表演覆盖、观察传递、落库与信封
# ---------------------------------------------------------------------------


async def test_full_rehearsal_three_rounds_two_targets_full_chain(
    exploration_flow,  # noqa: F811
):
    """三轮两目标全链：调用 (2+1)×3 次、轮次连续、每轮表演覆盖全部目标。"""
    flow = exploration_flow
    targets = ["c_franks", "c_evasive"]
    start = _rehearsal_pair_start()
    spec, envelope = await flow.setup(
        chain="scene", scale="scene_line", start=start, request_limit=100
    )
    rehearsal = _rehearsal(targets=targets, rounds=3)
    await _freeze_rehearsal_root(flow, spec, rehearsal)
    task_id = await _enqueue_rehearsal(flow, spec, envelope, rehearsal)
    task = await flow.run(task_id)
    assert task.status == "done", task.error_message
    assert flow.provider.calls == (len(targets) + 1) * 3 * 3 == 27

    row, envelope_row, root, branch = await _load_flow_rows(flow, spec)
    assert envelope_row is not None
    assert envelope_row.output_kind == FULL_REHEARSAL_OUTPUT_KIND
    assert envelope_row.schema_version == 1
    payload = envelope_row.payload
    assert isinstance(payload, FullRehearsalOutputV1)
    assert payload.targets == targets
    assert [item.round_number for item in payload.rounds] == [1, 2, 3]
    for round_item in payload.rounds:
        assert [card.target_ref for card in round_item.performances] == targets
        assert all(card.line_or_beat for card in round_item.performances)
        assert round_item.materials, "统筹每轮至少回一条素材"
        assert {item.target_ref for item in round_item.observations} <= set(targets)
    # 观察传递：第 2/3 轮表演卡的输入带上一轮自己的观察回执
    later_cards = [
        item for item in _performance_requests(flow.provider) if item["round"] >= 2
    ]
    assert later_cards
    assert all(
        item["previous_round"]["own_observations"] == [_OBSERVATION_TEXT]
        for item in later_cards
    )
    assert row.input_json["mode"] == "full_rehearsal"
    assert row.input_json["targets"] == targets
    assert row.input_json["rounds"] == 3
    assert branch.pending_round_json == {}
    assert root.status == "ready" and branch.status == "complete"
    ledger = read_ai_run_envelope(root.run_envelope_json)
    assert ledger.requests_started == 27
    # 任务终态信封可就地渲染（P0 §8/D）
    result = dict(task.result or {})
    assert result["status"] == "completed"
    assert result["output_kind"] == FULL_REHEARSAL_OUTPUT_KIND
    assert result["payload"]["targets"] == targets


async def test_full_rehearsal_author_goal_only_in_author_packets(
    exploration_flow,  # noqa: F811
):
    """author_goal/作者私享只进作者统筹包，绝不进任何目标角色包。"""
    flow = exploration_flow
    start = _rehearsal_pair_start()
    spec, envelope = await flow.setup(
        chain="scene", scale="scene_line", start=start, request_limit=100
    )
    rehearsal = _rehearsal(rounds=1)
    await _freeze_rehearsal_root(flow, spec, rehearsal)
    task_id = await _enqueue_rehearsal(flow, spec, envelope, rehearsal)
    task = await flow.run(task_id)
    assert task.status == "done", task.error_message

    performances = _performance_requests(flow.provider)
    orchestrations = _orchestration_requests(flow.provider)
    assert len(performances) == 2 and len(orchestrations) == 1
    for item in performances:
        text = json.dumps(item, ensure_ascii=False)
        assert _AUTHOR_GOAL not in text
        assert _AUTHOR_PRIVATE not in text
    orchestration = orchestrations[0]
    assert _AUTHOR_GOAL in json.dumps(orchestration, ensure_ascii=False)
    assert orchestration["author_packet"]["author_private"] == [_AUTHOR_PRIVATE]


async def test_full_rehearsal_candidate_packets_isolated(
    exploration_flow,  # noqa: F811
):
    """候选各自知识包隔离：每个表演卡请求只带自己的 knows/observed/误信。"""
    flow = exploration_flow
    start = _rehearsal_pair_start()
    spec, envelope = await flow.setup(
        chain="scene", scale="scene_line", start=start, request_limit=100
    )
    rehearsal = _rehearsal(rounds=1)
    await _freeze_rehearsal_root(flow, spec, rehearsal)
    task_id = await _enqueue_rehearsal(flow, spec, envelope, rehearsal)
    task = await flow.run(task_id)
    assert task.status == "done", task.error_message

    first, second = _performance_requests(flow.provider)
    assert first["target"]["ref"] == "c_franks"
    assert first["target_knowledge"]["knows"] == ["对方已提交辞呈"]
    assert "对方只是想调岗" not in json.dumps(first, ensure_ascii=False)
    assert second["target"]["ref"] == "c_evasive"
    assert second["target_knowledge"]["misbelieves"] == ["对方只是想调岗"]
    assert "对方已提交辞呈" not in json.dumps(second, ensure_ascii=False)


async def test_full_rehearsal_observation_and_materials_feed_next_round(
    exploration_flow,  # noqa: F811
):
    """统筹产出的观察/素材进入下一轮对应输入包（角色包与统筹包分流）。"""
    flow = exploration_flow
    start = _rehearsal_pair_start()
    spec, envelope = await flow.setup(
        chain="scene", scale="scene_line", start=start, request_limit=100
    )
    rehearsal = _rehearsal(rounds=2)
    await _freeze_rehearsal_root(flow, spec, rehearsal)
    task_id = await _enqueue_rehearsal(flow, spec, envelope, rehearsal)
    task = await flow.run(task_id)
    assert task.status == "done", task.error_message

    round_two_cards = [
        item for item in _performance_requests(flow.provider) if item["round"] == 2
    ]
    assert len(round_two_cards) == 2
    for item in round_two_cards:
        previous = item["previous_round"]
        assert previous["round_number"] == 1
        assert previous["own_performance"]["target_ref"] == item["target"]["ref"]
        assert previous["own_observations"] == [_OBSERVATION_TEXT]
    round_two_orchestration = next(
        item for item in _orchestration_requests(flow.provider) if item["round"] == 2
    )
    assert round_two_orchestration["prior_rounds"][0]["round_number"] == 1
    assert round_two_orchestration["prior_rounds"][0]["materials"]
    assert round_two_orchestration["prior_state_notes"] == ["第1轮：各目标维持原有立场。"]


# ---------------------------------------------------------------------------
# 失败关闭：canonical hidden guard / preview hash / 根意图一致性 / 跨 novel
# ---------------------------------------------------------------------------


async def test_full_rehearsal_canonical_guard_fails_closed(
    exploration_flow,  # noqa: F811
):
    """canonical 目标表演卡触碰隐藏边界 → 整个任务失败，不落库。"""
    from types import SimpleNamespace

    flow = exploration_flow
    start = _rehearsal_pair_start().model_copy(
        update={
            "candidates": [],
            "knowledge": [],
            "author_private": [],
            "canonical_refs": [str(uuid.uuid4()), str(uuid.uuid4())],
        }
    )
    spec, envelope = await flow.setup(chain="scene", scale="scene_line", start=start)
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
    override = full_rehearsal_card(start.canonical_refs[0])
    override["line_or_beat"] = "难怪你昨天被解雇了，失业的人都会这样。"
    flow.provider.override = override
    rehearsal = _rehearsal(targets=tuple(start.canonical_refs), rounds=1)
    await _freeze_rehearsal_root(flow, spec, rehearsal)
    task_id = await _enqueue_rehearsal(flow, spec, envelope, rehearsal)
    task = await flow.run(task_id)
    assert task.status == "failed"
    assert await _rehearsal_round_rows(flow, spec) == []
    assert flow.provider.calls == 3  # 第一张 canonical 表演卡即快速失败


async def test_full_rehearsal_rejects_plain_budget_hash(
    exploration_flow,  # noqa: F811
):
    """排演请求用不含排演身份的 preview hash 重放 → 失败关闭，0 次调用。"""
    flow = exploration_flow
    start = _rehearsal_pair_start()
    spec, envelope = await flow.setup(chain="scene", scale="scene_line", start=start)
    plain_hash = preview_exploration_budget(
        novel_id=str(spec.novel_id),
        scale="scene_line",
        start=start,
        focus=spec.focus,
    ).preview_hash
    rehearsal = _rehearsal(rounds=1)
    await _freeze_rehearsal_root(flow, spec, rehearsal)
    task_id = await _enqueue_rehearsal(
        flow, spec, envelope, rehearsal, preview_hash=plain_hash
    )
    task = await flow.run(task_id)
    assert task.status == "failed"
    assert await _rehearsal_round_rows(flow, spec) == []
    assert flow.provider.calls == 0


async def test_full_rehearsal_root_intent_mismatch_fails_closed(
    exploration_flow,  # noqa: F811
):
    """任务 meta 的排演意图与根 request_json 冻结意图不一致 → 失败关闭。"""
    flow = exploration_flow
    start = _rehearsal_pair_start()
    spec, envelope = await flow.setup(chain="scene", scale="scene_line", start=start)
    await _freeze_rehearsal_root(flow, spec, _rehearsal(rounds=1))
    tampered = _rehearsal(rounds=2)  # 与根冻结轮次不一致
    task_id = await _enqueue_rehearsal(flow, spec, envelope, tampered)
    task = await flow.run(task_id)
    assert task.status == "failed"
    assert flow.provider.calls == 0


async def test_full_rehearsal_cross_novel_task_rejected(
    exploration_flow,  # noqa: F811
):
    """任务落在另一 novel 名下（跨 novel 重放）→ 根定位即失败，0 次调用。

    根按 (novel_id, id) 定位：跨 novel 的 meta 重放查不到根，handler 在任何
    模型调用前失败关闭；终态信封镜像同样按 novel 定位失败（基础设施侧的
    二次防线），异常向外传播。
    """
    flow = exploration_flow
    start = _rehearsal_pair_start()
    spec, envelope = await flow.setup(chain="scene", scale="scene_line", start=start)
    rehearsal = _rehearsal(rounds=1)
    await _freeze_rehearsal_root(flow, spec, rehearsal)
    other_novel = uuid.uuid4()
    task_id = await _enqueue_rehearsal(
        flow, spec, envelope, rehearsal, novel_id=str(other_novel)
    )
    worker = TaskWorker(
        db_manager=_Manager(flow.engine, flow.sessions), heartbeat_interval=60.0
    )
    with pytest.raises(Exception):  # noqa: B017 - handler 与镜像双重失败关闭
        await worker.run_once(task_id=task_id, novel_id=str(other_novel))
    assert await _rehearsal_round_rows(flow, spec) == []
    assert flow.provider.calls == 0


# ---------------------------------------------------------------------------
# 检查点：中断续跑不重跑已完成轮、预算耗尽暂停、检查点模式互斥
# ---------------------------------------------------------------------------


async def test_full_rehearsal_pause_then_resume_skips_completed_rounds(
    exploration_flow,  # noqa: F811
):
    """第 2 轮首卡中断 → paused_unknown；续跑只补第 2 轮，不重跑第 1 轮。"""
    flow = exploration_flow
    targets = ["c_franks", "c_evasive"]
    start = _rehearsal_pair_start()
    spec, envelope = await flow.setup(
        chain="scene", scale="scene_line", start=start, request_limit=100
    )
    rehearsal = _rehearsal(targets=targets, rounds=2)
    await _freeze_rehearsal_root(flow, spec, rehearsal)
    task_id = await _enqueue_rehearsal(flow, spec, envelope, rehearsal)

    real_generate = flow.provider.generate

    async def flaky_generate(request):
        if flow.provider.calls == 9:  # 第 1 轮已完成（3 次调用），第 2 轮首卡前
            raise TimeoutError("synthetic unknown result")
        return await real_generate(request)

    flow.provider.generate = flaky_generate
    first_task = await flow.run(task_id)
    assert first_task.status == "done"  # 暂停以正常终态 + 凭据返回
    first_result = dict(first_task.result or {})
    assert first_result["status"] == "paused_unknown"
    assert first_result["needs_author_resume"] is True
    async with flow.sessions() as db:
        root = await db.get(StorySceneDirectorRoot, spec.root_id)
        branch = await db.get(StorySceneDirectorBranch, spec.branch_id)
        assert root.status == "paused_unknown"
        assert branch.status == "paused_unknown"
        pending = branch.pending_round_json
        assert pending["mode"] == "full_rehearsal"
        assert pending["round_number"] == 2
        assert [item["round_number"] for item in pending["completed_rounds"]] == [1]
    assert flow.provider.calls == 9
    # 3 次成功 + 1 次结果未知（预留计入 started）
    assert read_ai_run_envelope(root.run_envelope_json).requests_started == 10

    flow.provider.generate = real_generate
    resume_task_id = await _enqueue_rehearsal(
        flow,
        spec,
        envelope,
        rehearsal,
        envelope_snapshot=await _latest_root_envelope(flow, spec),
    )
    resume_task = await flow.run(resume_task_id)
    assert resume_task.status == "done", resume_task.error_message
    assert flow.provider.calls == 18  # 只补第 2 轮的 3 次调用
    resumed_rounds = {
        json.loads(request.messages[1].content).get("round")
        for request in flow.provider.generation_requests[3:]
    }
    assert resumed_rounds == {2}

    _row, envelope_row, root, branch = await _load_flow_rows(flow, spec)
    assert [item.round_number for item in envelope_row.payload.rounds] == [1, 2]
    assert branch.pending_round_json == {}
    assert root.status == "ready"
    # 4（含 1 次未知）+ 续跑 3 次
    assert read_ai_run_envelope(root.run_envelope_json).requests_started == 19


async def test_full_rehearsal_budget_exhausted_pauses_with_checkpoint(
    exploration_flow,  # noqa: F811
):
    """请求预算只够第 1 轮：第 2 轮首请求前 paused_budget，已完成轮保留。"""
    flow = exploration_flow
    targets = ["c_franks", "c_evasive"]
    start = _rehearsal_pair_start()
    spec, envelope = await flow.setup(
        chain="scene", scale="scene_line", start=start, request_limit=9
    )
    rehearsal = _rehearsal(targets=targets, rounds=2)
    await _freeze_rehearsal_root(flow, spec, rehearsal)
    task_id = await _enqueue_rehearsal(flow, spec, envelope, rehearsal)
    task = await flow.run(task_id)
    assert task.status == "done"  # 暂停以正常终态 + 凭据返回
    result = dict(task.result or {})
    assert result["status"] == "paused_budget"
    assert result["budget_stop"] == "request_budget_exhausted"
    assert result["needs_author_resume"] is True
    async with flow.sessions() as db:
        root = await db.get(StorySceneDirectorRoot, spec.root_id)
        branch = await db.get(StorySceneDirectorBranch, spec.branch_id)
        assert root.status == "paused_budget"
        pending = branch.pending_round_json
        assert pending["round_number"] == 2
        assert [item["round_number"] for item in pending["completed_rounds"]] == [1]
    assert await _rehearsal_round_rows(flow, spec) == []  # 未完成不落结果行
    assert flow.provider.calls == 9
    assert read_ai_run_envelope(root.run_envelope_json).requests_started == 9


async def test_full_rehearsal_pending_conflicts_with_plain_scene_task(
    exploration_flow,  # noqa: F811
):
    """排演暂停后，普通聚焦任务在同一分支续跑 → 检查点模式不一致失败关闭。"""
    flow = exploration_flow
    start = _rehearsal_pair_start()
    spec, envelope = await flow.setup(
        chain="scene", scale="scene_line", start=start, request_limit=9
    )
    rehearsal = _rehearsal(rounds=2)
    await _freeze_rehearsal_root(flow, spec, rehearsal)
    task_id = await _enqueue_rehearsal(flow, spec, envelope, rehearsal)
    await flow.run(task_id)  # 预算耗尽暂停，留下排演检查点

    budget = preview_exploration_budget(
        novel_id=str(spec.novel_id),
        scale="scene_line",
        start=spec.start,
        focus=spec.focus,
    )
    async with flow.sessions.begin() as db:
        plain_task_id = uuid.UUID(
            enqueue_task(
                db,
                exploration_tasks.EXPLORATION_SCENE_TASK,
                novel_id=str(spec.novel_id),
                meta={
                    AI_RUN_ENVELOPE_KEY: await _latest_root_envelope(flow, spec),
                    "exploration_root_id": str(spec.root_id),
                    "exploration_branch_id": str(spec.branch_id),
                    "exploration_scale": "scene_line",
                    "exploration_authorized_requests": budget.requests_max,
                    "exploration_authorized_tokens": budget.tokens_max,
                    "exploration_deadline_seconds": 3600,
                    "exploration_acknowledged_unknown_requests": 0,
                    "exploration_baseline_requests_started": 0,
                    "exploration_baseline_recent_attempts_overflow": 0,
                    "llm_execution_snapshot": {"novel_id": str(spec.novel_id)},
                    "action": "story.exploration.scene_line.generate",
                    "confirmation_action": "story.exploration.scene_line.generate",
                    "context_confirmation_id": spec.confirmation_id,
                    "request": {
                        "mode": "start",
                        "start": spec.start.model_dump(mode="json"),
                        "scale": "scene_line",
                        "focus": spec.focus,
                    },
                    "budget_preview_hash": budget.preview_hash,
                    "target_ref": "c_franks",
                },
            )
        )
        root = await db.get(StorySceneDirectorRoot, spec.root_id)
        branch = await db.get(StorySceneDirectorBranch, spec.branch_id)
        root.current_task_id = branch.current_task_id = plain_task_id
    plain_task = await flow.run(plain_task_id)
    assert plain_task.status == "failed"
    assert "检查点" in (plain_task.error_message or "")
    assert flow.provider.calls == 9  # 未新增模型调用


# ---------------------------------------------------------------------------
# 落库与历史：信封往返、历史列表与摘要标签
# ---------------------------------------------------------------------------


async def test_full_rehearsal_result_roundtrip_and_history_label(
    exploration_flow,  # noqa: F811
):
    """单目标单轮：信封判别、payload 模型、历史列表与摘要标签。"""
    flow = exploration_flow
    start = _rehearsal_pair_start()
    spec, envelope = await flow.setup(
        chain="scene", scale="scene_line", start=start, request_limit=100
    )
    rehearsal = _rehearsal(targets=("c_franks",), rounds=1)
    await _freeze_rehearsal_root(flow, spec, rehearsal)
    task_id = await _enqueue_rehearsal(flow, spec, envelope, rehearsal)
    task = await flow.run(task_id)
    assert task.status == "done", task.error_message
    assert flow.provider.calls == 6  # 1 张表演卡 + 1 次统筹

    row, envelope_row, root, branch = await _load_flow_rows(flow, spec)
    assert envelope_row.output_kind == FULL_REHEARSAL_OUTPUT_KIND
    assert isinstance(envelope_row.payload, FullRehearsalOutputV1)
    assert pack_exploration_output(envelope_row) == row.output_json
    result = dict(task.result or {})
    assert result["result_id"] == str(row.id)
    assert result["payload"] == envelope_row.payload.model_dump(mode="json")
    assert root.current_task_id is None and branch.current_task_id is None

    async with flow.sessions() as db:
        history = await list_exploration_history_results(
            db,
            novel_id=str(spec.novel_id),
            owner_id=OWNER_ID,
            root_id=str(spec.root_id),
            scale="scene_line",
            limit=10,
            offset=0,
        )
    assert history["total"] == 1
    item = history["items"][0]
    assert item["output_kind"] == FULL_REHEARSAL_OUTPUT_KIND
    assert item["payload"]["targets"] == ["c_franks"]
    assert item["label"] == full_rehearsal_card("c_franks")["line_or_beat"]
