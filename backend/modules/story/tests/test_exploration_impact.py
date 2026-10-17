"""影响与比较标记（M3-A 切片 2）：结构化受影响项、实际读集与父版本、关系标记。

冻结契约：counterfactual compare 在 changed_conditions 之外给出
``affected_items``（chain:N/gap:N/bridge:N/line 按索引同构 diff，内容哈希
判定，0..24 条）与 ``affected_items_granularity``（粒度不足披露
conservative 并置空，不伪称精确）；反事实结果行 input_json 补记
``base_result_fingerprint`` 与 ``parent_output_hash``，compare 响应相应行
回传 ``parent_output_hash``；same_start 模式同根父子一跳标记
``relation=parent_child`` 并给相对差异，默认 ``same_start`` 行为不变。
"""

from __future__ import annotations

import uuid
from copy import deepcopy

import pytest

from modules.account.settings_constants import LOCAL_OWNER_ID
from modules.evidence.contracts import Assumption, ProvisionalStart, SceneAnchorStart
from modules.story.exploration_schemas import (
    EVENT_OUTPUT_KIND,
    SANDBOX_OUTPUT_KIND,
    SCENE_LINE_OUTPUT_KIND,
    EventOutputV1,
    ExplorationOutputEnvelope,
    SandboxOutputV1,
    SceneLineOutputV1,
    exploration_start_fingerprint,
)
from modules.story.exploration_service import (
    compute_affected_items,
    create_exploration_root,
    pack_exploration_output,
    set_exploration_item_lock,
)
from modules.story.exploration_tasks import _counterfactual_baseline_provenance
from modules.story.models import StorySceneDirectorRound
from modules.story.world_progression_models import StoryWorldProgressionStep

OWNER_ID = str(LOCAL_OWNER_ID)
_QUESTION = "这个城镇每天只有一小时重力减半，面包师的一天会怎样？"
_CHANGED_TEXT = "重力变化时段从早晨改到傍晚"


@pytest.fixture(autouse=True)
def _exploration_gate_off_by_default(monkeypatch):
    from core.config import get_settings

    monkeypatch.setenv("STORY_EXPLORATION_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _provisional_start() -> ProvisionalStart:
    return ProvisionalStart(
        kind="provisional",
        question=_QUESTION,
        assumptions=[Assumption(kind="world_rule", text="每天只有一小时重力减半")],
        time_basis="assumed_now",
    )


def _sandbox_envelope(chain: list[dict]) -> ExplorationOutputEnvelope:
    return ExplorationOutputEnvelope(
        output_kind=SANDBOX_OUTPUT_KIND,
        schema_version=1,
        payload=SandboxOutputV1.model_validate(
            {"question": "重力减半后面包师的一天？", "influence_chain": chain}
        ),
    )


_CHAIN_TWO_LINKS = [
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
]


def _event_diagnose_envelope(gaps: list[dict]) -> ExplorationOutputEnvelope:
    return ExplorationOutputEnvelope(
        output_kind=EVENT_OUTPUT_KIND,
        schema_version=1,
        payload=EventOutputV1.model_validate(
            {
                "mode": "diagnose",
                "original_excerpt": "信使不知道地址，却当天把信送到了本人手里",
                "gaps": gaps,
            }
        ),
    )


def _event_bridge_envelope(bridges: list[dict]) -> ExplorationOutputEnvelope:
    return ExplorationOutputEnvelope(
        output_kind=EVENT_OUTPUT_KIND,
        schema_version=1,
        payload=EventOutputV1.model_validate(
            {
                "mode": "bridge",
                "original_excerpt": "信使不知道地址，却当天把信送到了本人手里",
                "bridge_candidates": bridges,
            }
        ),
    )


def _event_goal_envelope(*, first_action: str) -> ExplorationOutputEnvelope:
    return ExplorationOutputEnvelope(
        output_kind=EVENT_OUTPUT_KIND,
        schema_version=1,
        payload=EventOutputV1.model_validate(
            {
                "mode": "goal",
                "original_excerpt": "信使要在日落前把密信送到城外驿站",
                "goal_path": {
                    "goal": "日落前送达",
                    "steps": [
                        {
                            "action": first_action,
                            "condition": "路线未被封锁",
                            "response": "信使出发",
                            "consequence": "信件按时送达",
                            "cost_or_risk": "马匹损耗",
                        }
                    ],
                },
            }
        ),
    )


def _scene_line_envelope(line: str) -> ExplorationOutputEnvelope:
    return ExplorationOutputEnvelope(
        output_kind=SCENE_LINE_OUTPUT_KIND,
        schema_version=1,
        payload=SceneLineOutputV1.model_validate(
            {
                "target_ref": "c_b",
                "line": line,
                "rationale": "B 只看见 A 疲惫。",
            }
        ),
    )


def _scene_variants_envelope(*, second_line: str) -> ExplorationOutputEnvelope:
    return ExplorationOutputEnvelope(
        output_kind=SCENE_LINE_OUTPUT_KIND,
        schema_version=1,
        payload=SceneLineOutputV1.model_validate(
            {
                "rationale": "多目标差异对白",
                "variants": [
                    {"target_ref": "c_a", "line": "我先走了。", "rationale": "A 疲惫"},
                    {
                        "target_ref": "c_b",
                        "line": second_line,
                        "rationale": "B 关心",
                    },
                ]
            }
        ),
    )


async def _seed_progression_root(db_session, project_id, *, scale: str = "sandbox"):
    start = _provisional_start()
    root, branch = await create_exploration_root(
        db_session,
        novel_id=str(project_id),
        owner_id=OWNER_ID,
        scale=scale,
        start=start,
        context_confirmation_id=str(uuid.uuid4()),
    )
    return root, branch, start


async def _add_step(
    db_session,
    root,
    branch,
    *,
    envelope: ExplorationOutputEnvelope,
    step_number: int,
    input_json: dict | None = None,
    parent_id=None,
    output_hash: str | None = None,
) -> StoryWorldProgressionStep:
    step = StoryWorldProgressionStep(
        novel_id=root.novel_id,
        root_id=root.id,
        branch_id=branch.id,
        parent_step_id=parent_id,
        step_number=step_number,
        source_hash=root.source_hash,
        input_hash="a" * 64,
        output_hash=output_hash or (f"{step_number:x}" * 64),
        input_json=input_json or {"mode": "start"},
        result_json=pack_exploration_output(envelope),
        state_json={},
        metrics_json={"mode": "start", "exploration": True},
        basis_changed=False,
    )
    db_session.add(step)
    await db_session.flush()
    return step


async def _seed_scene_root(db_session, project_id):
    start = SceneAnchorStart(kind="scene_anchor", scene_id=str(uuid.uuid4()))
    root, branch = await create_exploration_root(
        db_session,
        novel_id=str(project_id),
        owner_id=OWNER_ID,
        scale="scene_line",
        start=start,
    )
    return root, branch


async def _add_scene_round(
    db_session,
    root,
    branch,
    *,
    envelope: ExplorationOutputEnvelope,
    round_number: int,
    parent_id=None,
    input_json: dict | None = None,
):
    row = StorySceneDirectorRound(
        novel_id=root.novel_id,
        root_id=root.id,
        branch_id=branch.id,
        round_number=round_number,
        parent_round_id=parent_id,
        source_hash=root.source_hash,
        input_hash="c" * 64,
        output_hash="d" * 64,
        input_json=input_json or {"mode": "start"},
        output_json=pack_exploration_output(envelope),
        state_json={},
        run_envelope_json={},
    )
    db_session.add(row)
    await db_session.flush()
    return row


def _cf_input_json(baseline_id, *, texts=(_CHANGED_TEXT,)) -> dict:
    return {
        "mode": "start",
        "counterfactual_of": str(baseline_id),
        "changed_assumption_texts": list(texts),
    }


def _compare_body(project_id, first, second, mode: str | None = None) -> dict:
    body = {
        "novel_id": str(project_id),
        "first_result_id": str(first),
        "second_result_id": str(second),
    }
    if mode is not None:
        body["mode"] = mode
    return body


async def _post_compare(async_client, project_id, first, second, mode=None):
    return await async_client.post(
        "/api/story/exploration/compare",
        json=_compare_body(project_id, first, second, mode),
    )


# ---------------------------------------------------------------------------
# counterfactual：沙盘/事件结构化受影响项
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_counterfactual_compare_marks_changed_item(
    async_client, db_session, project_factory
):
    project_id = await project_factory.create_project()
    base_root, base_branch, _start = await _seed_progression_root(db_session, project_id)
    baseline = await _add_step(
        db_session,
        base_root,
        base_branch,
        envelope=_sandbox_envelope(_CHAIN_TWO_LINKS),
        step_number=1,
    )
    derived_root, derived_branch, _dstart = await _seed_progression_root(
        db_session, project_id
    )
    changed_chain = deepcopy(_CHAIN_TWO_LINKS)
    changed_chain[1]["effect"] = "面包师改做凉菜"
    variant = await _add_step(
        db_session,
        derived_root,
        derived_branch,
        envelope=_sandbox_envelope(changed_chain),
        step_number=1,
        input_json=_cf_input_json(baseline.id),
    )

    response = await _post_compare(
        async_client, project_id, baseline.id, variant.id, mode="counterfactual"
    )
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["mode"] == "counterfactual"
    assert body["changed_conditions"] == [_CHANGED_TEXT]
    assert body["affected_items_granularity"] == "exact"
    assert body["affected_items"] == [
        {
            "item_path": "chain:1",
            "status": "changed",
            "base_excerpt": "面包师更累",
            "derived_excerpt": "面包师改做凉菜",
        }
    ]


@pytest.mark.asyncio
async def test_counterfactual_compare_marks_added_item(
    async_client, db_session, project_factory
):
    project_id = await project_factory.create_project()
    base_root, base_branch, _start = await _seed_progression_root(db_session, project_id)
    baseline = await _add_step(
        db_session,
        base_root,
        base_branch,
        envelope=_sandbox_envelope(_CHAIN_TWO_LINKS),
        step_number=1,
    )
    derived_root, derived_branch, _dstart = await _seed_progression_root(
        db_session, project_id
    )
    grown_chain = deepcopy(_CHAIN_TWO_LINKS) + [
        {
            "condition": "炉温不稳",
            "mechanism": "发酵难以预测",
            "effect": "废品率上升",
        }
    ]
    variant = await _add_step(
        db_session,
        derived_root,
        derived_branch,
        envelope=_sandbox_envelope(grown_chain),
        step_number=1,
        input_json=_cf_input_json(baseline.id),
    )

    body = (
        await _post_compare(
            async_client, project_id, baseline.id, variant.id, mode="counterfactual"
        )
    ).json()
    assert body["affected_items"] == [
        {
            "item_path": "chain:2",
            "status": "added",
            "base_excerpt": "",
            "derived_excerpt": "废品率上升",
        }
    ]


@pytest.mark.asyncio
async def test_counterfactual_compare_marks_removed_item(
    async_client, db_session, project_factory
):
    project_id = await project_factory.create_project()
    base_root, base_branch, _start = await _seed_progression_root(db_session, project_id)
    baseline = await _add_step(
        db_session,
        base_root,
        base_branch,
        envelope=_sandbox_envelope(_CHAIN_TWO_LINKS),
        step_number=1,
    )
    derived_root, derived_branch, _dstart = await _seed_progression_root(
        db_session, project_id
    )
    variant = await _add_step(
        db_session,
        derived_root,
        derived_branch,
        envelope=_sandbox_envelope(_CHAIN_TWO_LINKS[:1]),
        step_number=1,
        input_json=_cf_input_json(baseline.id),
    )

    body = (
        await _post_compare(
            async_client, project_id, baseline.id, variant.id, mode="counterfactual"
        )
    ).json()
    assert body["affected_items"] == [
        {
            "item_path": "chain:1",
            "status": "removed",
            "base_excerpt": "面包师更累",
            "derived_excerpt": "",
        }
    ]


@pytest.mark.asyncio
async def test_counterfactual_compare_event_gaps_and_bridge_diff(
    async_client, db_session, project_factory
):
    """事件载荷：诊断缺口 → 补桥候选的跨模式 diff（gap 全 removed + bridge added）。"""
    project_id = await project_factory.create_project()
    base_root, base_branch, _start = await _seed_progression_root(
        db_session, project_id, scale="event"
    )
    baseline = await _add_step(
        db_session,
        base_root,
        base_branch,
        envelope=_event_diagnose_envelope(
            [
                {
                    "description": "缺少行踪来源",
                    "why_needed": "解释为何能精准送达",
                },
                {
                    "description": "缺马匹来源",
                    "why_needed": "解释当天往返",
                },
            ]
        ),
        step_number=1,
    )
    derived_root, derived_branch, _dstart = await _seed_progression_root(
        db_session, project_id, scale="event"
    )
    variant = await _add_step(
        db_session,
        derived_root,
        derived_branch,
        envelope=_event_bridge_envelope(
            [
                {
                    "steps": ["打听行踪", "顺路捎信"],
                    "required_conditions": ["驿站掌柜愿意透露"],
                    "cost_or_risk": "泄露行踪",
                    "holds": True,
                }
            ]
        ),
        step_number=1,
        input_json=_cf_input_json(baseline.id),
    )

    body = (
        await _post_compare(
            async_client, project_id, baseline.id, variant.id, mode="counterfactual"
        )
    ).json()
    assert body["affected_items_granularity"] == "exact"
    assert body["affected_items"] == [
        {
            "item_path": "gap:0",
            "status": "removed",
            "base_excerpt": "缺少行踪来源",
            "derived_excerpt": "",
        },
        {
            "item_path": "gap:1",
            "status": "removed",
            "base_excerpt": "缺马匹来源",
            "derived_excerpt": "",
        },
        {
            "item_path": "bridge:0",
            "status": "added",
            "base_excerpt": "",
            "derived_excerpt": "打听行踪\n顺路捎信",
        },
    ]


# ---------------------------------------------------------------------------
# 粒度保守披露：路径语法不可表达时置空，不伪称精确
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_granularity_conservative_for_goal_and_variants(
    async_client, db_session, project_factory
):
    project_id = await project_factory.create_project()
    goal_root, goal_branch, _start = await _seed_progression_root(
        db_session, project_id, scale="event"
    )
    goal_base = await _add_step(
        db_session,
        goal_root,
        goal_branch,
        envelope=_event_goal_envelope(first_action="抄近道穿集市"),
        step_number=1,
    )
    goal_derived_root, goal_derived_branch, _gdstart = await _seed_progression_root(
        db_session, project_id, scale="event"
    )
    goal_variant = await _add_step(
        db_session,
        goal_derived_root,
        goal_derived_branch,
        envelope=_event_goal_envelope(first_action="走官道换马"),
        step_number=1,
        input_json=_cf_input_json(goal_base.id),
    )

    body = (
        await _post_compare(
            async_client, project_id, goal_base.id, goal_variant.id, mode="counterfactual"
        )
    ).json()
    assert body["affected_items_granularity"] == "conservative"
    assert body["affected_items"] == []

    # 多目标对白（variants）同样无法按 line 单条精确表达 → 保守披露
    scene_root, scene_branch = await _seed_scene_root(db_session, project_id)
    variants_base = await _add_scene_round(
        db_session,
        scene_root,
        scene_branch,
        envelope=_scene_variants_envelope(second_line="你先回去吧。"),
        round_number=1,
    )
    variants_derived_root, variants_derived_branch = await _seed_scene_root(
        db_session, project_id
    )
    variants_variant = await _add_scene_round(
        db_session,
        variants_derived_root,
        variants_derived_branch,
        envelope=_scene_variants_envelope(second_line="你也早点歇着。"),
        round_number=1,
        input_json=_cf_input_json(variants_base.id),
    )

    body = (
        await _post_compare(
            async_client,
            project_id,
            variants_base.id,
            variants_variant.id,
            mode="counterfactual",
        )
    ).json()
    assert body["affected_items_granularity"] == "conservative"
    assert body["affected_items"] == []


# ---------------------------------------------------------------------------
# 实际读集与父版本：input_json 补记 + compare 回读
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_counterfactual_baseline_provenance_reads_baseline_row(
    db_session, project_factory
):
    project_id = await project_factory.create_project()
    root, branch, start = await _seed_progression_root(db_session, project_id)
    baseline = await _add_step(
        db_session,
        root,
        branch,
        envelope=_sandbox_envelope(_CHAIN_TWO_LINKS),
        step_number=1,
        output_hash="f" * 64,
    )
    provenance = await _counterfactual_baseline_provenance(
        db_session, novel_id=root.novel_id, baseline_result_id=str(baseline.id)
    )
    assert provenance["base_result_fingerprint"] == exploration_start_fingerprint(
        start, "sandbox"
    )
    assert provenance["parent_output_hash"] == "f" * 64

    missing = await _counterfactual_baseline_provenance(
        db_session, novel_id=root.novel_id, baseline_result_id=str(uuid.uuid4())
    )
    assert missing == {"base_result_fingerprint": None, "parent_output_hash": None}


@pytest.mark.asyncio
async def test_counterfactual_compare_read_back_parent_output_hash(
    async_client, db_session, project_factory
):
    """响应相应行回传行内记录的父版本哈希；无记录行为 null。"""
    project_id = await project_factory.create_project()
    base_root, base_branch, start = await _seed_progression_root(db_session, project_id)
    baseline_fingerprint = exploration_start_fingerprint(start, "sandbox")
    baseline = await _add_step(
        db_session,
        base_root,
        base_branch,
        envelope=_sandbox_envelope(_CHAIN_TWO_LINKS),
        step_number=1,
        output_hash="e" * 64,
    )
    derived_root, derived_branch, _dstart = await _seed_progression_root(
        db_session, project_id
    )
    variant = await _add_step(
        db_session,
        derived_root,
        derived_branch,
        envelope=_sandbox_envelope(_CHAIN_TWO_LINKS),
        step_number=1,
        output_hash="9" * 64,
        input_json={
            "mode": "start",
            "counterfactual_of": str(baseline.id),
            "changed_assumption_texts": [_CHANGED_TEXT],
            "base_result_fingerprint": baseline_fingerprint,
            "parent_output_hash": "e" * 64,
        },
    )

    body = (
        await _post_compare(
            async_client, project_id, baseline.id, variant.id, mode="counterfactual"
        )
    ).json()
    assert body["first"]["parent_output_hash"] is None
    assert body["second"]["parent_output_hash"] == "e" * 64
    # 两侧 payload 相同 → 无受影响项，但仍如实给出精确粒度
    assert body["affected_items"] == []
    assert body["affected_items_granularity"] == "exact"


# ---------------------------------------------------------------------------
# parent_child 关系标记与默认 same_start 行为不变
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_same_start_parent_child_relation_and_line_diff(
    async_client, db_session, project_factory
):
    project_id = await project_factory.create_project()
    root, branch = await _seed_scene_root(db_session, project_id)
    ancestor = await _add_scene_round(
        db_session,
        root,
        branch,
        envelope=_scene_line_envelope("你要是累了就先回去吧。"),
        round_number=1,
    )
    descendant = await _add_scene_round(
        db_session,
        root,
        branch,
        envelope=_scene_line_envelope("累了就回去，别硬撑。"),
        round_number=2,
        parent_id=ancestor.id,
    )

    body = (
        await _post_compare(async_client, project_id, ancestor.id, descendant.id)
    ).json()
    assert body["relation"] == "parent_child"
    assert body["start_fingerprint"]
    assert "changed_conditions" not in body
    assert body["affected_items"] == [
        {
            "item_path": "line",
            "status": "changed",
            "base_excerpt": "你要是累了就先回去吧。",
            "derived_excerpt": "累了就回去，别硬撑。",
        }
    ]

    # 请求顺序反过来：base 仍是祖先侧
    reversed_body = (
        await _post_compare(async_client, project_id, descendant.id, ancestor.id)
    ).json()
    assert reversed_body["relation"] == "parent_child"
    assert reversed_body["affected_items"] == body["affected_items"]


@pytest.mark.asyncio
async def test_same_start_default_relation_and_two_hops_stay_same_start(
    async_client, db_session, project_factory
):
    """默认 same_start 行为不变；父子链超过一跳不标 parent_child。"""
    project_id = await project_factory.create_project()
    root_a, branch_a, _start = await _seed_progression_root(db_session, project_id)
    step_a1 = await _add_step(
        db_session,
        root_a,
        branch_a,
        envelope=_sandbox_envelope(_CHAIN_TWO_LINKS),
        step_number=1,
    )
    root_b, branch_b, _bstart = await _seed_progression_root(db_session, project_id)
    step_b1 = await _add_step(
        db_session,
        root_b,
        branch_b,
        envelope=_sandbox_envelope(_CHAIN_TWO_LINKS),
        step_number=1,
    )

    body = (await _post_compare(async_client, project_id, step_a1.id, step_b1.id)).json()
    assert body["relation"] == "same_start"
    assert "affected_items" not in body
    assert "affected_items_granularity" not in body
    assert "parent_output_hash" not in body["first"]
    assert "parent_output_hash" not in body["second"]

    # 同根两跳（祖父 ↔ 孙）：不算一跳父子，仍 same_start
    step_a2 = await _add_step(
        db_session,
        root_a,
        branch_a,
        envelope=_sandbox_envelope(_CHAIN_TWO_LINKS),
        step_number=2,
        parent_id=step_a1.id,
    )
    step_a3 = await _add_step(
        db_session,
        root_a,
        branch_a,
        envelope=_sandbox_envelope(_CHAIN_TWO_LINKS),
        step_number=3,
        parent_id=step_a2.id,
    )
    hops = (
        await _post_compare(async_client, project_id, step_a1.id, step_a3.id)
    ).json()
    assert hops["relation"] == "same_start"
    assert "affected_items" not in hops

    # 一跳仍标记，且 diff 以祖先为 base
    one_hop = (
        await _post_compare(async_client, project_id, step_a1.id, step_a2.id)
    ).json()
    assert one_hop["relation"] == "parent_child"
    assert one_hop["affected_items"] == []


# ---------------------------------------------------------------------------
# 失败关闭与锁定共存
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unrelated_counterfactual_still_conflicts(
    async_client, db_session, project_factory
):
    project_id = await project_factory.create_project()
    root_a, branch_a, _start = await _seed_progression_root(db_session, project_id)
    step_a = await _add_step(
        db_session,
        root_a,
        branch_a,
        envelope=_sandbox_envelope(_CHAIN_TWO_LINKS),
        step_number=1,
    )
    root_b, branch_b, _bstart = await _seed_progression_root(db_session, project_id)
    step_b = await _add_step(
        db_session,
        root_b,
        branch_b,
        envelope=_sandbox_envelope(_CHAIN_TWO_LINKS),
        step_number=1,
    )

    response = await _post_compare(
        async_client, project_id, step_a.id, step_b.id, mode="counterfactual"
    )
    assert response.status_code == 409
    assert "反事实衍生关系" in response.json()["detail"]


@pytest.mark.asyncio
async def test_locked_items_coexist_with_affected_items(
    async_client, db_session, project_factory
):
    project_id = await project_factory.create_project()
    base_root, base_branch, _start = await _seed_progression_root(db_session, project_id)
    baseline = await _add_step(
        db_session,
        base_root,
        base_branch,
        envelope=_sandbox_envelope(_CHAIN_TWO_LINKS),
        step_number=1,
    )
    _lock_row, _lock_envelope = await set_exploration_item_lock(
        db_session,
        novel_id=str(project_id),
        owner_id=OWNER_ID,
        base_result_id=str(baseline.id),
        lock=True,
        item_path="chain:0",
    )
    derived_root, derived_branch, _dstart = await _seed_progression_root(
        db_session, project_id
    )
    changed_chain = deepcopy(_CHAIN_TWO_LINKS)
    changed_chain[0]["effect"] = "面包变硬"
    variant = await _add_step(
        db_session,
        derived_root,
        derived_branch,
        envelope=_sandbox_envelope(changed_chain),
        step_number=1,
        input_json=_cf_input_json(baseline.id),
    )

    body = (
        await _post_compare(
            async_client, project_id, baseline.id, variant.id, mode="counterfactual"
        )
    ).json()
    assert body["first"]["locked_items"] == ["chain:0"]
    assert body["second"]["locked_items"] == []
    assert body["affected_items"] == [
        {
            "item_path": "chain:0",
            "status": "changed",
            "base_excerpt": "面包更松软",
            "derived_excerpt": "面包变硬",
        }
    ]


# ---------------------------------------------------------------------------
# compute_affected_items 直测：上限截断与摘录截选
# ---------------------------------------------------------------------------


def test_compute_affected_items_lists_all_changed_and_truncates_excerpts():
    long_effect = "很长的结论" * 40  # 200 字，摘录截到 120
    base_chain = [
        {"condition": f"条件{i}", "mechanism": "m", "effect": f"效果{i}"}
        for i in range(12)
    ]
    derived_chain = [
        {"condition": f"条件{i}", "mechanism": "m", "effect": long_effect}
        for i in range(12)
    ]
    items, granularity = compute_affected_items(
        _sandbox_envelope(base_chain), _sandbox_envelope(derived_chain)
    )
    assert granularity == "exact"
    assert [item["item_path"] for item in items] == [
        f"chain:{i}" for i in range(12)
    ]
    assert all(item["status"] == "changed" for item in items)
    assert items[0]["base_excerpt"] == "效果0"
    assert len(items[0]["derived_excerpt"]) == 120
    assert items[0]["derived_excerpt"] == long_effect[:120]
