"""明确选择后的跨尺度移交（M4-A 切片 1）：契约、六方向语义与安全边界。

冻结契约：``ProvisionalStart.derived_from``（HandoffRef，一跳溯源，旧载荷
序列化不变）；``build_handoff_start`` 只迁移被选条目涉及的假设与主体
（item_path 过滤，空=整结果才全量），未选分支不串入；同尺度 409、
author_edit/lock_set 拒绝、item_path 越界 409、助手无理由 422、跨 novel
404；``derived_from`` 随派生起点冻结进确认 compile_options。
"""

from __future__ import annotations

import uuid

import pytest

from core.errors import ConflictError, DomainError, NotFoundError
from modules.account.settings_constants import LOCAL_OWNER_ID
from modules.evidence.contracts import (
    Assumption,
    CandidateRef,
    HandoffRef,
    KnowledgeEntry,
    ProvisionalStart,
)
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
    build_handoff_start,
    create_exploration_root,
    pack_exploration_output,
    save_exploration_author_edit,
    set_exploration_item_lock,
)
from modules.story.models import StorySceneDirectorRound
from modules.story.world_progression_models import StoryWorldProgressionStep

OWNER_ID = str(LOCAL_OWNER_ID)
_QUESTION = "这个城镇每天只有一小时重力减半，面包师的一天会怎样？"


@pytest.fixture(autouse=True)
def _exploration_gate_off_by_default(monkeypatch):
    from core.config import get_settings

    monkeypatch.setenv("STORY_EXPLORATION_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _enable_exploration(monkeypatch):
    from core.config import get_settings

    monkeypatch.setenv("STORY_EXPLORATION_ENABLED", "true")
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# 夹具：起点与结果载荷
# ---------------------------------------------------------------------------


def _sandbox_start() -> ProvisionalStart:
    return ProvisionalStart(
        kind="provisional",
        question=_QUESTION,
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


def _sandbox_envelope(chain: list[dict] | None = None) -> ExplorationOutputEnvelope:
    return ExplorationOutputEnvelope(
        output_kind=SANDBOX_OUTPUT_KIND,
        schema_version=1,
        payload=SandboxOutputV1.model_validate(
            {
                "question": "重力减半后面包师的一天？",
                "influence_chain": chain if chain is not None else _CHAIN,
            }
        ),
    )


def _event_payload() -> dict:
    return {
        "mode": "diagnose",
        "original_excerpt": "信使不知道地址，却当天把信送到了本人手里",
        "gaps": [
            {
                "description": "缺少信使获知行踪的来源",
                "why_needed": "解释为何能精准送达",
                "possible_fix_hint": "有人认出了收信人",
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


def _event_envelope(payload: dict) -> ExplorationOutputEnvelope:
    return ExplorationOutputEnvelope(
        output_kind=EVENT_OUTPUT_KIND,
        schema_version=1,
        payload=EventOutputV1.model_validate(payload),
    )


def _scene_envelope(
    *, target_ref: str = "c_b", line: str = "你要是累了就先回去吧。"
) -> ExplorationOutputEnvelope:
    return ExplorationOutputEnvelope(
        output_kind=SCENE_LINE_OUTPUT_KIND,
        schema_version=1,
        payload=SceneLineOutputV1.model_validate(
            {
                "target_ref": target_ref,
                "line": line,
                "rationale": "目标只看得到对方疲惫，不知道失业的事。",
                "knowledge_basis": ["observed:对方脚步发沉"],
            }
        ),
    )


def _scene_variants_envelope() -> ExplorationOutputEnvelope:
    return ExplorationOutputEnvelope(
        output_kind=SCENE_LINE_OUTPUT_KIND,
        schema_version=1,
        payload=SceneLineOutputV1.model_validate(
            {
                "rationale": "多目标差异对白",
                "variants": [
                    {"target_ref": "c_a", "line": "我先走了。", "rationale": "A 疲惫"},
                    {"target_ref": "c_b", "line": "你先回去吧。", "rationale": "B 关心"},
                ],
            }
        ),
    )


# ---------------------------------------------------------------------------
# 播种：临时起点根 + AI 结果行
# ---------------------------------------------------------------------------


async def _seed_source(db_session, project_id, *, scale: str, start, envelope):
    from datetime import UTC, datetime, timedelta

    from infrastructure.llm.workflow_budget import new_ai_run_envelope
    from modules.evidence.contracts import ExplorationContextRequest
    from modules.evidence.facade import confirm_exploration_context

    action = {
        "sandbox": "story.exploration.sandbox.generate",
        "event": "story.exploration.event.diagnose",
        "scene_line": "story.exploration.scene_line.generate",
    }[scale]
    confirmation = await confirm_exploration_context(
        db_session,
        ExplorationContextRequest(
            novel_id=str(project_id),
            action=action,
            exploration_scale=scale,
            task="generation",
            scope="project",
            start=start,
        ),
    )
    started_at = datetime.now(UTC)

    def _attach_run_envelope(root):
        # API 层校验结果属于独立探索运行（root_capability_id 门）。
        root.run_envelope_json = (
            new_ai_run_envelope(
                operation_id=str(uuid.uuid4()),
                run_id=str(root.id),
                root_capability_id="story.exploration",
                novel_id=str(project_id),
                request_limit=1,
                budget_mode="bounded",
                token_limit=200_000,
                started_at=started_at,
                deadline_at=started_at + timedelta(hours=1),
            )
            .snapshot()
            .model_dump(mode="json")
        )

    if scale in ("sandbox", "event"):
        root, branch = await create_exploration_root(
            db_session,
            novel_id=str(project_id),
            owner_id=OWNER_ID,
            scale=scale,
            start=start,
            context_confirmation_id=str(uuid.uuid4()),
        )
        _attach_run_envelope(root)
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
        root, branch = await create_exploration_root(
            db_session,
            novel_id=str(project_id),
            owner_id=OWNER_ID,
            scale=scale,
            start=start,
        )
        _attach_run_envelope(root)
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
    branch.request_json = {
        **(branch.request_json or {}),
        "context_confirmation_id": confirmation.id,
        "confirmation_action": action,
    }
    db_session.add(row)
    await db_session.flush()
    return root, branch, row


async def _handoff(
    db_session,
    project_id,
    row,
    *,
    target_scale,
    item_path="",
    selector="author",
    reason="",
):
    return await build_handoff_start(
        db_session,
        str(project_id),
        OWNER_ID,
        str(row.id),
        target_scale,
        item_path,
        selector,
        reason,
    )


# ---------------------------------------------------------------------------
# 六方向语义
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sandbox_to_event_selected_link_topped_and_subjects_filtered(
    db_session, project_factory
):
    """沙盘→事件：被选链条目 effect/mechanism 并为置顶 state 假设；未选条目
    不串入；主体按被选条目 affected_refs 过滤；源假设全量继承其后。"""
    project_id = await project_factory.create_project()
    start = _sandbox_start()
    _root, _branch, row = await _seed_source(
        db_session,
        project_id,
        scale="sandbox",
        start=start,
        envelope=_sandbox_envelope(),
    )

    derived, fingerprint = await _handoff(
        db_session, project_id, row, target_scale="event", item_path="chain:1"
    )
    assert fingerprint == derived.derived_from.source_fingerprint
    assert derived.derived_from is not None
    assert derived.derived_from.source_result_id == str(row.id)
    assert derived.derived_from.source_scale == "sandbox"
    assert derived.derived_from.item_path == "chain:1"
    assert derived.derived_from.selector == "author"
    # 置顶 state 假设携带被选环节的 effect/mechanism，未选环节不出现。
    top = derived.assumptions[0]
    assert top.kind == "state"
    assert "面包师更累" in top.text
    assert "清晨顾客变多" in top.text
    assert "面包更松软" not in top.text
    assert "重力降低让面团发酵更快" not in top.text
    # 源假设（前提集）全量继承，紧跟置顶假设之后。
    assert [(item.kind, item.text) for item in derived.assumptions[1:]] == [
        (item.kind, item.text) for item in start.assumptions
    ]
    # 主体只迁移被选条目涉及者。
    assert [item.ref_id for item in derived.candidates] == ["c_customer"]
    assert [entry.subject_ref for entry in derived.knowledge] == ["c_customer"]
    assert derived.time_basis == "assumed_now"
    assert "移交" in derived.question and "面包师更累" in derived.question


@pytest.mark.asyncio
async def test_sandbox_to_scene_line_whole_situation_and_all_subjects(
    db_session, project_factory
):
    """沙盘→场景（整结果）：首要影响为情境 state 假设，前提继承，
    主体按整结果全部 affected_refs 迁移。"""
    project_id = await project_factory.create_project()
    start = _sandbox_start()
    _root, _branch, row = await _seed_source(
        db_session,
        project_id,
        scale="sandbox",
        start=start,
        envelope=_sandbox_envelope(),
    )

    derived, _fingerprint = await _handoff(
        db_session, project_id, row, target_scale="scene_line"
    )
    assert derived.assumptions[0].kind == "state"
    assert "面包更松软" in derived.assumptions[0].text
    assert [(item.kind, item.text) for item in derived.assumptions[1:]] == [
        (item.kind, item.text) for item in start.assumptions
    ]
    assert [item.ref_id for item in derived.candidates] == ["c_baker", "c_customer"]
    assert {entry.subject_ref for entry in derived.knowledge} == {
        "c_baker",
        "c_customer",
    }


@pytest.mark.asyncio
async def test_event_to_scene_line_whole_carries_excerpt_and_all_subjects(
    db_session, project_factory
):
    """事件→场景（整结果）：源事件摘录为 state 假设；全部主体（候选身份
    与可知包）迁移。"""
    project_id = await project_factory.create_project()
    start = _event_start()
    _root, _branch, row = await _seed_source(
        db_session,
        project_id,
        scale="event",
        start=start,
        envelope=_event_envelope(_event_payload()),
    )

    derived, _fingerprint = await _handoff(
        db_session, project_id, row, target_scale="scene_line"
    )
    assert derived.assumptions[0].kind == "state"
    assert "信使不知道地址" in derived.assumptions[0].text
    assert [item.ref_id for item in derived.candidates] == [
        "c_messenger",
        "c_recipient",
    ]
    assert {entry.subject_ref for entry in derived.knowledge} == {
        "c_messenger",
        "c_recipient",
    }
    assert derived.derived_from.item_path == ""


@pytest.mark.asyncio
async def test_event_to_scene_line_selected_gap_filters_subjects(
    db_session, project_factory
):
    """事件→场景（选缺口）：只迁移被选条目涉及的主体（文本保守匹配），
    未涉主体不串入。"""
    project_id = await project_factory.create_project()
    payload = _event_payload()
    payload["gaps"][0]["description"] = "缺少 c_recipient 行踪被获知的接触路径"
    _root, _branch, row = await _seed_source(
        db_session,
        project_id,
        scale="event",
        start=_event_start(),
        envelope=_event_envelope(payload),
    )

    derived, _fingerprint = await _handoff(
        db_session, project_id, row, target_scale="scene_line", item_path="gap:0"
    )
    assert "缺少 c_recipient 行踪被获知的接触路径" in derived.assumptions[0].text
    assert "缺少当天的路径依据" not in derived.assumptions[0].text
    assert [item.ref_id for item in derived.candidates] == ["c_recipient"]
    assert [entry.subject_ref for entry in derived.knowledge] == ["c_recipient"]


@pytest.mark.asyncio
async def test_event_to_sandbox_selected_gap_only_unselected_excluded(
    db_session, project_factory
):
    """事件→沙盘（追因，选缺口）：被选缺口前提转假设；多缺口源只选一条时
    其余缺口不进入派生起点（未选分支不串入）。"""
    project_id = await project_factory.create_project()
    _root, _branch, row = await _seed_source(
        db_session,
        project_id,
        scale="event",
        start=_event_start(),
        envelope=_event_envelope(_event_payload()),
    )

    derived, _fingerprint = await _handoff(
        db_session, project_id, row, target_scale="sandbox", item_path="gap:0"
    )
    texts = [item.text for item in derived.assumptions]
    assert any("缺少信使获知行踪的来源" in text for text in texts)
    assert any("解释为何能精准送达" in text for text in texts)
    assert any("有人认出了收信人" in text for text in texts)
    assert all("缺少当天的路径依据" not in text for text in texts)
    assert all(item.kind == "state" for item in derived.assumptions)


@pytest.mark.asyncio
async def test_event_to_sandbox_bridge_conditions_become_premises(
    db_session, project_factory
):
    """事件→沙盘（追因，选补桥路径）：路径前提（required_conditions）转
    假设，路径步骤摘录随行。"""
    project_id = await project_factory.create_project()
    payload = {
        "mode": "bridge",
        "original_excerpt": "信使不知道地址，却当天把信送到了本人手里",
        "bridge_candidates": [
            {
                "steps": ["查驿站登记簿", "上门问询"],
                "required_conditions": ["收信人走的是主城门", "登记簿当日有效"],
                "cost_or_risk": "多花半天时间问询",
                "holds": True,
            }
        ],
        "unknowns": [],
        "warnings": [],
    }
    _root, _branch, row = await _seed_source(
        db_session,
        project_id,
        scale="event",
        start=_event_start(),
        envelope=_event_envelope(payload),
    )

    derived, _fingerprint = await _handoff(
        db_session, project_id, row, target_scale="sandbox", item_path="bridge:0"
    )
    texts = [item.text for item in derived.assumptions]
    assert any("查驿站登记簿" in text for text in texts)
    assert any("收信人走的是主城门" in text for text in texts)
    assert any("登记簿当日有效" in text for text in texts)


@pytest.mark.asyncio
async def test_event_goal_whole_constraints_rule_and_path_state(
    db_session, project_factory
):
    """事件→沙盘（整结果，导向模式）：rule_constraints 转 world_rule 假设，
    导向路径摘要转 state 假设。"""
    project_id = await project_factory.create_project()
    payload = {
        "mode": "goal",
        "original_excerpt": "指定结果：信使当天把信送到本人手里",
        "goal_path": {
            "goal": "信使当天把信送到本人手里",
            "steps": [
                {
                    "action": "信使查驿站登记簿",
                    "condition": "登记簿写明收信人当日进城",
                    "response": "守门人指认同姓进城者",
                    "consequence": "当场完成投递",
                    "cost_or_risk": "任务暴露",
                }
            ],
            "rule_constraints": ["禁止巧合", "角色性格不得突变"],
            "unsolvable": None,
        },
        "unknowns": [],
        "warnings": [],
    }
    _root, _branch, row = await _seed_source(
        db_session,
        project_id,
        scale="event",
        start=_event_start(),
        envelope=_event_envelope(payload),
    )

    derived, _fingerprint = await _handoff(
        db_session, project_id, row, target_scale="sandbox"
    )
    rules = [item for item in derived.assumptions if item.kind == "world_rule"]
    assert [item.text for item in rules] == [
        "源事件导向的既定约束：禁止巧合",
        "源事件导向的既定约束：角色性格不得突变",
    ]
    states = [item for item in derived.assumptions if item.kind == "state"]
    assert any("信使当天把信送到本人手里" in item.text for item in states)


@pytest.mark.asyncio
async def test_scene_line_to_event_state_and_identity_with_target_knowledge(
    db_session, project_factory
):
    """场景→事件（追因）：对白/动作与依据转 state 假设 + identity 假设
    （动机待探）；只迁移被选对白目标主体的候选与可知包。"""
    project_id = await project_factory.create_project()
    start = _scene_start()
    _root, _branch, row = await _seed_source(
        db_session,
        project_id,
        scale="scene_line",
        start=start,
        envelope=_scene_envelope(),
    )

    derived, _fingerprint = await _handoff(
        db_session, project_id, row, target_scale="event"
    )
    assert derived.assumptions[0].kind == "state"
    assert "你要是累了就先回去吧。" in derived.assumptions[0].text
    assert "只看得到对方疲惫" in derived.assumptions[0].text
    assert derived.assumptions[1].kind == "identity"
    assert "动机" in derived.assumptions[1].text
    assert [item.ref_id for item in derived.candidates] == ["c_b"]
    assert [entry.subject_ref for entry in derived.knowledge] == ["c_b"]
    assert derived.derived_from.source_scale == "scene_line"


@pytest.mark.asyncio
async def test_scene_line_to_sandbox_inherits_situation_assumptions(
    db_session, project_factory
):
    """场景→沙盘（看影响）：情境假设继承 + 已发生时刻置顶 state 假设。"""
    project_id = await project_factory.create_project()
    start = _scene_start()
    _root, _branch, row = await _seed_source(
        db_session,
        project_id,
        scale="scene_line",
        start=start,
        envelope=_scene_envelope(),
    )

    derived, _fingerprint = await _handoff(
        db_session, project_id, row, target_scale="sandbox"
    )
    assert derived.assumptions[0].kind == "state"
    assert "你要是累了就先回去吧。" in derived.assumptions[0].text
    assert [(item.kind, item.text) for item in derived.assumptions[1:]] == [
        (item.kind, item.text) for item in start.assumptions
    ]
    assert [item.ref_id for item in derived.candidates] == ["c_b"]


# ---------------------------------------------------------------------------
# 校验与安全边界
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_same_scale_handoff_conflicts(db_session, project_factory):
    project_id = await project_factory.create_project()
    _root, _branch, row = await _seed_source(
        db_session,
        project_id,
        scale="sandbox",
        start=_sandbox_start(),
        envelope=_sandbox_envelope(),
    )
    with pytest.raises(ConflictError) as error:
        await _handoff(db_session, project_id, row, target_scale="sandbox")
    assert "同" in str(error.value)


@pytest.mark.asyncio
async def test_author_edit_and_lock_set_rows_rejected(db_session, project_factory):
    project_id = await project_factory.create_project()
    _root, _branch, ai_row = await _seed_source(
        db_session,
        project_id,
        scale="sandbox",
        start=_sandbox_start(),
        envelope=_sandbox_envelope(),
    )
    edited_row, _envelope = await save_exploration_author_edit(
        db_session,
        novel_id=str(project_id),
        owner_id=OWNER_ID,
        base_result_id=str(ai_row.id),
        edited_payload=_sandbox_envelope().payload,
        edit_note="改一条",
    )
    with pytest.raises(ConflictError) as error:
        await _handoff(db_session, project_id, edited_row, target_scale="event")
    assert "作者编辑" in str(error.value)

    lock_row, _lock_envelope = await set_exploration_item_lock(
        db_session,
        novel_id=str(project_id),
        owner_id=OWNER_ID,
        base_result_id=str(ai_row.id),
        lock=True,
        item_path="chain:0",
    )
    with pytest.raises(ConflictError) as lock_error:
        await _handoff(db_session, project_id, lock_row, target_scale="event")
    assert "锁定" in str(lock_error.value)


@pytest.mark.asyncio
async def test_unknown_item_path_conflicts(db_session, project_factory):
    project_id = await project_factory.create_project()
    _root, _branch, row = await _seed_source(
        db_session,
        project_id,
        scale="sandbox",
        start=_sandbox_start(),
        envelope=_sandbox_envelope(),
    )
    for bad_path in ("chain:9", "bogus", "gap:0"):
        with pytest.raises(ConflictError):
            await _handoff(
                db_session, project_id, row, target_scale="event", item_path=bad_path
            )


@pytest.mark.asyncio
async def test_assistant_without_reason_unprocessable(db_session, project_factory):
    project_id = await project_factory.create_project()
    _root, _branch, row = await _seed_source(
        db_session,
        project_id,
        scale="sandbox",
        start=_sandbox_start(),
        envelope=_sandbox_envelope(),
    )
    with pytest.raises(DomainError) as error:
        await _handoff(
            db_session,
            project_id,
            row,
            target_scale="event",
            selector="assistant",
            reason="  ",
        )
    assert error.value.status_code == 422

    # 有理由时通过，且理由/选择者冻结进 derived_from。
    derived, _fingerprint = await _handoff(
        db_session,
        project_id,
        row,
        target_scale="event",
        selector="assistant",
        reason="作者要求把这条影响落到具体事件",
    )
    assert derived.derived_from.selector == "assistant"
    assert derived.derived_from.reason == "作者要求把这条影响落到具体事件"


@pytest.mark.asyncio
async def test_cross_novel_and_foreign_owner_not_found(db_session, project_factory):
    project_id = await project_factory.create_project()
    other_project = await project_factory.create_project(title="别的作品")
    _root, _branch, row = await _seed_source(
        db_session,
        project_id,
        scale="sandbox",
        start=_sandbox_start(),
        envelope=_sandbox_envelope(),
    )
    with pytest.raises(NotFoundError):
        await build_handoff_start(
            db_session,
            str(other_project),
            OWNER_ID,
            str(row.id),
            "event",
            "",
            "author",
            "",
        )
    with pytest.raises(NotFoundError):
        await build_handoff_start(
            db_session,
            str(project_id),
            "00000000-0000-0000-0000-000000000001",
            str(row.id),
            "event",
            "",
            "author",
            "",
        )


@pytest.mark.asyncio
async def test_scene_variants_payload_rejected(db_session, project_factory):
    project_id = await project_factory.create_project()
    _root, _branch, row = await _seed_source(
        db_session,
        project_id,
        scale="scene_line",
        start=_scene_start(),
        envelope=_scene_variants_envelope(),
    )
    with pytest.raises(ConflictError) as error:
        await _handoff(db_session, project_id, row, target_scale="event")
    assert "多目标" in str(error.value)


# ---------------------------------------------------------------------------
# derived_from 冻结与旧载荷兼容
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_derived_from_frozen_into_confirmation_compile_options(
    db_session, test_project_id, monkeypatch
):
    """preview→confirm 往返后，derived_from 完整出现在确认 compile_options
    的 exploration_start 内。"""
    _enable_exploration(monkeypatch)
    from modules.story.exploration_api import confirm_exploration, preview_confirmation

    _root, _branch, row = await _seed_source(
        db_session,
        test_project_id,
        scale="sandbox",
        start=_sandbox_start(),
        envelope=_sandbox_envelope(),
    )
    derived, _fingerprint = await _handoff(
        db_session, test_project_id, row, target_scale="event", item_path="chain:0"
    )
    preview_request = ExplorationConfirmationPreviewRequest(
        novel_id=test_project_id,
        scale="event",
        start=derived,
        action="story.exploration.event.diagnose",
    )
    preview = await preview_confirmation(db_session, preview_request)
    confirmed = await confirm_exploration(
        db_session,
        ExplorationConfirmationRequest(
            **preview_request.model_dump(mode="json"),
            expected_context_fingerprint=preview["context_fingerprint"],
        ),
    )
    from modules.evidence.compilation.models import ContextConfirmation

    record = await db_session.get(
        ContextConfirmation, uuid.UUID(confirmed["confirmation_id"])
    )
    frozen = record.compile_options["exploration_start"]
    assert frozen["derived_from"]["source_result_id"] == str(row.id)
    assert frozen["derived_from"]["source_scale"] == "sandbox"
    assert frozen["derived_from"]["item_path"] == "chain:0"
    assert frozen["derived_from"]["selector"] == "author"
    # 往返后再反序列化，handoff 引用不丢。
    refrozen = ProvisionalStart.model_validate(frozen)
    assert refrozen.derived_from is not None
    assert refrozen.derived_from.source_result_id == str(row.id)


def test_legacy_payload_without_derived_from_roundtrip_stable():
    """旧载荷兼容：无 derived_from 反序列化后 model_dump 不新增键，
    起点指纹不变；带 derived_from 的载荷往返不丢。"""
    old = {
        "kind": "provisional",
        "question": "旧起点？",
        "assumptions": [{"kind": "world_rule", "text": "每天只有一小时重力减半"}],
        "time_basis": "assumed_now",
    }
    start = ProvisionalStart.model_validate(old)
    dump = start.model_dump(mode="json")
    assert "derived_from" not in dump
    assert exploration_start_fingerprint(start, "sandbox") == (
        exploration_start_fingerprint(ProvisionalStart.model_validate(dump), "sandbox")
    )

    handed = start.model_copy(
        update={
            "derived_from": HandoffRef(
                source_result_id=str(uuid.uuid4()),
                source_scale="sandbox",
                item_path="chain:0",
                selector="author",
                reason="",
            )
        }
    )
    roundtrip = ProvisionalStart.model_validate(handed.model_dump(mode="json"))
    assert roundtrip.derived_from is not None
    assert roundtrip.derived_from.item_path == "chain:0"


# ---------------------------------------------------------------------------
# API：POST /results/{result_id}/handoff
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handoff_api_returns_derived_start_and_fingerprint(
    async_client, db_session, project_factory, monkeypatch
):
    _enable_exploration(monkeypatch)
    project_id = await project_factory.create_project()
    root, _branch, row = await _seed_source(
        db_session,
        project_id,
        scale="sandbox",
        start=_sandbox_start(),
        envelope=_sandbox_envelope(),
    )
    response = await async_client.post(
        f"/api/story/exploration/results/{row.id}/handoff",
        json={
            "novel_id": str(project_id),
            "operation_id": str(uuid.uuid4()),
            "target_scale": "event",
            "item_path": "chain:0",
        },
    )
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["requires_confirmation"] is True
    assert body["preview_hint"]
    assert (
        body["source_fingerprint"]
        == body["derived_start"]["derived_from"]["source_fingerprint"]
    )
    derived_start = body["derived_start"]
    assert derived_start["kind"] == "provisional"
    assert derived_start["derived_from"]["source_result_id"] == str(row.id)
    assert derived_start["derived_from"]["source_scale"] == "sandbox"
    assert derived_start["derived_from"]["item_path"] == "chain:0"
    assert derived_start["derived_from"]["selector"] == "author"
    # 派生起点可再反序列化为合法契约（确认请求的 start 即它）。
    assert ProvisionalStart.model_validate(derived_start).derived_from is not None


@pytest.mark.asyncio
async def test_handoff_api_gate_off_503(async_client, db_session, project_factory):
    project_id = await project_factory.create_project()
    _root, _branch, row = await _seed_source(
        db_session,
        project_id,
        scale="sandbox",
        start=_sandbox_start(),
        envelope=_sandbox_envelope(),
    )
    response = await async_client.post(
        f"/api/story/exploration/results/{row.id}/handoff",
        json={
            "novel_id": str(project_id),
            "operation_id": str(uuid.uuid4()),
            "target_scale": "event",
        },
    )
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_handoff_api_assistant_without_reason_422(
    async_client, db_session, project_factory, monkeypatch
):
    _enable_exploration(monkeypatch)
    project_id = await project_factory.create_project()
    _root, _branch, row = await _seed_source(
        db_session,
        project_id,
        scale="sandbox",
        start=_sandbox_start(),
        envelope=_sandbox_envelope(),
    )
    response = await async_client.post(
        f"/api/story/exploration/results/{row.id}/handoff",
        json={
            "novel_id": str(project_id),
            "operation_id": str(uuid.uuid4()),
            "target_scale": "event",
            "selector": "assistant",
        },
    )
    assert response.status_code == 422

    ok = await async_client.post(
        f"/api/story/exploration/results/{row.id}/handoff",
        json={
            "novel_id": str(project_id),
            "operation_id": str(uuid.uuid4()),
            "target_scale": "event",
            "selector": "assistant",
            "reason": "目标需要事件层补桥",
        },
    )
    assert ok.status_code == 200
    assert ok.json()["derived_start"]["derived_from"]["selector"] == "assistant"


@pytest.mark.asyncio
async def test_handoff_api_cross_novel_404_and_same_scale_409(
    async_client, db_session, project_factory, monkeypatch
):
    _enable_exploration(monkeypatch)
    project_id = await project_factory.create_project()
    other_project = await project_factory.create_project(title="别的作品")
    _root, _branch, row = await _seed_source(
        db_session,
        project_id,
        scale="sandbox",
        start=_sandbox_start(),
        envelope=_sandbox_envelope(),
    )
    cross = await async_client.post(
        f"/api/story/exploration/results/{row.id}/handoff",
        json={
            "novel_id": str(other_project),
            "operation_id": str(uuid.uuid4()),
            "target_scale": "event",
        },
    )
    assert cross.status_code == 404

    same = await async_client.post(
        f"/api/story/exploration/results/{row.id}/handoff",
        json={
            "novel_id": str(project_id),
            "operation_id": str(uuid.uuid4()),
            "target_scale": "sandbox",
        },
    )
    assert same.status_code == 409
    assert "同" in same.json()["detail"]


@pytest.mark.asyncio
async def test_handoff_api_unknown_item_path_409(
    async_client, db_session, project_factory, monkeypatch
):
    _enable_exploration(monkeypatch)
    project_id = await project_factory.create_project()
    _root, _branch, row = await _seed_source(
        db_session,
        project_id,
        scale="sandbox",
        start=_sandbox_start(),
        envelope=_sandbox_envelope(),
    )
    response = await async_client.post(
        f"/api/story/exploration/results/{row.id}/handoff",
        json={
            "novel_id": str(project_id),
            "operation_id": str(uuid.uuid4()),
            "target_scale": "event",
            "item_path": "chain:9",
        },
    )
    assert response.status_code == 409
