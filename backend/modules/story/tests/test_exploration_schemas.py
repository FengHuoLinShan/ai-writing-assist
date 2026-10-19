"""探索契约 schema 校验：起点判别、四类 payload、信封与预算模型（P0 §1/§4/§5/§8）。"""

from __future__ import annotations

import copy
import uuid

import pytest
from pydantic import ValidationError

from modules.evidence.contracts import Assumption, CandidateRef, ProvisionalStart
from modules.story.exploration_budget import (
    exploration_preview_identity,
    preview_exploration_budget,
)
from modules.story.exploration_schemas import (
    AUTHOR_EDIT_OUTPUT_KIND,
    EVENT_OUTPUT_KIND,
    FULL_REHEARSAL_OUTPUT_KIND,
    LOCK_SET_OUTPUT_KIND,
    SANDBOX_OUTPUT_KIND,
    SCENE_LINE_OUTPUT_KIND,
    AuthorEditPayloadV1,
    BridgePath,
    EventOutputV1,
    ExplorationCompareRequest,
    ExplorationConfirmationPreviewRequest,
    ExplorationConfirmationRequest,
    ExplorationOutputEnvelope,
    ExplorationPreviewRequest,
    ExplorationReviseRequest,
    ExplorationSaveEditRequest,
    ExplorationStartTaskRequest,
    FullRehearsalOutputV1,
    GapFinding,
    GoalPath,
    InfluenceLink,
    InfoGap,
    LockedItem,
    LockSetPayloadV1,
    SandboxOutputV1,
    SceneLineOutputV1,
    apply_changed_assumptions,
    exploration_start_fingerprint,
    validate_scene_targets,
)

NOVEL_ID = str(uuid.uuid4())
SCENE_ID = str(uuid.uuid4())


def _provisional_payload(**overrides):
    payload = {
        "kind": "provisional",
        "question": "这个城镇每天只有一小时重力减半，面包师的一天会怎样？",
        "assumptions": [{"kind": "world_rule", "text": "每天只有一小时重力减半"}],
        "time_basis": "assumed_now",
    }
    payload.update(overrides)
    return payload


def _sandbox_payload(**overrides):
    payload = {
        "question": "重力减半后面包师的一天？",
        "influence_chain": [
            {
                "condition": "揉面时间不变",
                "mechanism": "重力降低让面团发酵更快",
                "effect": "面包气孔更大、更松软",
                "affected_refs": ["c_baker"],
                "holds_when": "炉温可以维持",
                "unknown": "酵母活性是否随气压变化",
            }
        ],
        "preconditions": ["城镇仍有可靠炉火"],
        "unknowns": ["精确生产率未知"],
        "warnings": ["不读取章节，不编造精确生产率"],
    }
    payload.update(overrides)
    return payload


def _event_payload(**overrides):
    payload = {
        "mode": "diagnose",
        "original_excerpt": "信使不知道地址，却当天把信送到了本人手里",
        "gaps": [
            {
                "description": "缺少信使如何得知收件人身份的信息",
                "why_needed": "没有该信息无法解释当天送达",
            }
        ],
        "unknowns": ["信使与收件人的关系未知"],
        "warnings": [],
    }
    payload.update(overrides)
    return payload


def _scene_line_payload(**overrides):
    payload = {
        "target_ref": "c_b",
        "line": "你要是累了就先回去吧，别硬撑着。",
        "rationale": "B 只看见 A 疲惫，不知道失业；用关心语气回应，不泄露秘密。",
        "action": "把手里的话题收住",
        "knowledge_basis": ["B 的观察：A 一整天没精神"],
        "withheld": ["B 不知道 A 失业，也不该猜出来"],
        "unknowns": ["A 是否愿意接话"],
        "warnings": [],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# 起点判别（P0 §1/§8）
# ---------------------------------------------------------------------------


def test_preview_request_discriminates_provisional_start():
    request = ExplorationPreviewRequest.model_validate(
        {
            "novel_id": NOVEL_ID,
            "scale": "sandbox",
            "start": _provisional_payload(),
            "focus": "只看面包师的一天",
        }
    )
    assert isinstance(request.start, ProvisionalStart)
    assert request.novel_id == NOVEL_ID
    assert request.focus == "只看面包师的一天"


def test_preview_request_discriminates_scene_anchor_start():
    request = ExplorationPreviewRequest.model_validate(
        {
            "novel_id": NOVEL_ID,
            "scale": "scene_line",
            "start": {"kind": "scene_anchor", "scene_id": SCENE_ID},
        }
    )
    assert request.start.kind == "scene_anchor"
    assert request.start.scene_id == SCENE_ID


def test_provisional_start_rejects_scene_id_field():
    with pytest.raises(ValidationError):
        ExplorationPreviewRequest.model_validate(
            {
                "novel_id": NOVEL_ID,
                "scale": "sandbox",
                "start": _provisional_payload(scene_id=SCENE_ID),
            }
        )


def test_scene_anchor_start_requires_scene_id():
    with pytest.raises(ValidationError):
        ExplorationPreviewRequest.model_validate(
            {
                "novel_id": NOVEL_ID,
                "scale": "scene_line",
                "start": {"kind": "scene_anchor"},
            }
        )


def test_unknown_start_kind_rejected():
    with pytest.raises(ValidationError):
        ExplorationPreviewRequest.model_validate(
            {
                "novel_id": NOVEL_ID,
                "scale": "sandbox",
                "start": {"kind": "mystery", "scene_id": SCENE_ID},
            }
        )


def test_provisional_start_requires_at_least_one_assumption():
    with pytest.raises(ValidationError):
        ExplorationPreviewRequest.model_validate(
            {
                "novel_id": NOVEL_ID,
                "scale": "sandbox",
                "start": _provisional_payload(assumptions=[]),
            }
        )


def test_confirmation_preview_binds_action_to_scale():
    ok = ExplorationConfirmationPreviewRequest.model_validate(
        {
            "novel_id": NOVEL_ID,
            "scale": "event",
            "action": "story.exploration.event.diagnose",
            "start": _provisional_payload(),
        }
    )
    assert ok.action == "story.exploration.event.diagnose"
    with pytest.raises(ValidationError):
        ExplorationConfirmationPreviewRequest.model_validate(
            {
                "novel_id": NOVEL_ID,
                "scale": "event",
                "action": "story.exploration.sandbox.generate",
                "start": _provisional_payload(),
            }
        )


def test_confirmation_request_requires_fingerprint():
    base = {
        "novel_id": NOVEL_ID,
        "scale": "event",
        "action": "story.exploration.event.bridge",
        "start": _provisional_payload(),
    }
    with pytest.raises(ValidationError):
        ExplorationConfirmationRequest.model_validate(base)
    confirmed = ExplorationConfirmationRequest.model_validate(
        {**base, "expected_context_fingerprint": "a" * 64}
    )
    assert confirmed.expected_context_fingerprint == "a" * 64


def test_start_task_request_requires_confirmation_and_preview_hash():
    base = {
        "novel_id": NOVEL_ID,
        "scale": "sandbox",
        "action": "story.exploration.sandbox.generate",
        "start": _provisional_payload(),
        "operation_id": str(uuid.uuid4()),
    }
    with pytest.raises(ValidationError):
        ExplorationStartTaskRequest.model_validate(base)
    task = ExplorationStartTaskRequest.model_validate(
        {
            **base,
            "context_confirmation_id": "ctx-123",
            "budget_preview_hash": "b" * 64,
        }
    )
    assert task.context_confirmation_id == "ctx-123"
    assert task.budget_preview_hash == "b" * 64
    with pytest.raises(ValidationError):
        ExplorationStartTaskRequest.model_validate(
            {**base, "context_confirmation_id": "ctx-123", "budget_preview_hash": "xyz"}
        )


def test_detail_and_revise_requests_normalize_ids():
    from modules.story.exploration_schemas import ExplorationDetailRequest

    result_id = str(uuid.uuid4())
    detail = ExplorationDetailRequest.model_validate(
        {
            "novel_id": NOVEL_ID,
            "result_id": result_id,
            "focus": "把影响链第二步说详细点",
            "operation_id": str(uuid.uuid4()),
        }
    )
    assert detail.result_id == result_id
    revise = ExplorationReviseRequest.model_validate(
        {
            "novel_id": NOVEL_ID,
            "revision_of": result_id,
            "item_path": "chain:0",
            "item_text": "面包更松软",
            "instruction": "在不靠巧合的条件下补一个环节",
            "bridge_target": "信使当天必须知道地址",
            "operation_id": str(uuid.uuid4()),
        }
    )
    assert revise.bridge_target == "信使当天必须知道地址"
    assert revise.item_path == "chain:0"
    with pytest.raises(ValidationError):
        ExplorationReviseRequest.model_validate(
            {
                "novel_id": NOVEL_ID,
                "item_path": "",
                "instruction": "修订",
                "operation_id": str(uuid.uuid4()),
            }
        )
    with pytest.raises(ValidationError):
        ExplorationReviseRequest.model_validate(
            {
                "novel_id": NOVEL_ID,
                "item_path": "chain:0",
                "item_text": "x" * 4001,
                "instruction": "修订",
                "operation_id": str(uuid.uuid4()),
            }
        )


def test_save_edit_request_forbids_extra_fields():
    request = ExplorationSaveEditRequest.model_validate(
        {
            "novel_id": NOVEL_ID,
            "base_result_id": str(uuid.uuid4()),
            "edited_payload": _sandbox_payload(),
            "edit_note": "把发酵机制改得更保守",
        }
    )
    assert request.edit_note == "把发酵机制改得更保守"
    with pytest.raises(ValidationError):
        ExplorationSaveEditRequest.model_validate(
            {
                "novel_id": NOVEL_ID,
                "base_result_id": str(uuid.uuid4()),
                "edited_payload": _sandbox_payload(),
                "output_kind": SANDBOX_OUTPUT_KIND,
            }
        )


def test_compare_request_rejects_same_result():
    result_id = str(uuid.uuid4())
    with pytest.raises(ValidationError):
        ExplorationCompareRequest.model_validate(
            {
                "novel_id": NOVEL_ID,
                "first_result_id": result_id,
                "second_result_id": result_id,
            }
        )


# ---------------------------------------------------------------------------
# 输出 payload（P0 §4）
# ---------------------------------------------------------------------------


def test_sandbox_allows_single_link_chain():
    payload = SandboxOutputV1.model_validate(_sandbox_payload())
    assert len(payload.influence_chain) == 1
    assert payload.unknowns == ["精确生产率未知"]


def test_sandbox_requires_chain_and_bounds_length():
    with pytest.raises(ValidationError):
        SandboxOutputV1.model_validate(_sandbox_payload(influence_chain=[]))
    with pytest.raises(ValidationError):
        SandboxOutputV1.model_validate(
            _sandbox_payload(
                influence_chain=[
                    {
                        "condition": f"条件{i}",
                        "mechanism": "机制",
                        "effect": "后果",
                    }
                    for i in range(13)
                ]
            )
        )


def test_sandbox_link_allows_missing_conditions():
    link = InfluenceLink(condition="未知条件", mechanism="未知机制", effect="未知后果")
    assert link.holds_when is None
    assert link.unknown is None


def test_event_diagnose_requires_gaps_and_forbids_bridge_candidates():
    payload = EventOutputV1.model_validate(_event_payload())
    assert payload.mode == "diagnose"
    with pytest.raises(ValidationError):
        EventOutputV1.model_validate(_event_payload(gaps=[]))
    with pytest.raises(ValidationError):
        EventOutputV1.model_validate(
            _event_payload(
                bridge_candidates=[
                    BridgePath(
                        steps=["信使询问驿站"],
                        required_conditions=["驿站有登记"],
                        cost_or_risk="多花半天",
                        holds=True,
                    )
                ]
            )
        )


def test_event_bridge_without_candidates_requires_unsolvable():
    bridge_payload = _event_payload(
        mode="bridge",
        gaps=[
            GapFinding(
                description="缺少收件人身份来源",
                why_needed="补桥必须解释送达如何定位",
            )
        ],
    )
    # 指定结果禁止巧合时允许“无法成立”并列缺项（合法路径）。
    unsolvable = EventOutputV1.model_validate(
        {
            **bridge_payload,
            "unsolvable": {
                "reason": "在不引入巧合的前提下无法成立",
                "missing": ["收件人身份来源", "信使当日行程"],
            },
        }
    )
    assert unsolvable.unsolvable is not None
    assert unsolvable.unsolvable.missing == ["收件人身份来源", "信使当日行程"]
    with pytest.raises(ValidationError):
        EventOutputV1.model_validate(bridge_payload)


def test_event_bridge_with_candidates():
    payload = EventOutputV1.model_validate(
        {
            **_event_payload(mode="bridge"),
            "bridge_candidates": [
                {
                    "steps": ["信使先到驿站查名册", "按名册找到唯一同姓收件人"],
                    "required_conditions": ["驿站当日开放", "名册登记完整"],
                    "cost_or_risk": "依赖名册可信度",
                    "holds": True,
                }
            ],
        }
    )
    assert len(payload.bridge_candidates) == 1
    assert payload.bridge_candidates[0].holds is True


# ---------------------------------------------------------------------------
# 事件信息差与导向路径（M2）：info_boundary / goal_path / 三模式互斥
# ---------------------------------------------------------------------------


def _info_gap_payload(**overrides):
    payload = {
        "mode": "diagnose",
        "original_excerpt": "证人没看到交接，却准确说出接头暗号",
        "gaps": [
            {
                "description": "证人与交接现场之间缺少接触路径",
                "why_needed": "没有接触就无法得知暗号",
            }
        ],
        "info_boundary": [
            {
                "subject_ref": "c_witness",
                "knows": ["接头暗号的内容"],
                "not_known": ["交接发生的地点与时间"],
                "missing_contact_path": True,
            }
        ],
        "unknowns": [],
        "warnings": [],
    }
    payload.update(overrides)
    return payload


def _goal_path_payload(**overrides):
    payload = {
        "goal": "信使当天把信送到本人手里",
        "steps": [
            {
                "action": "信使向守门人出示驿站登记摘录",
                "condition": "登记摘录写明收信人当日进城",
                "response": "守门人指认唯一的同姓进城者",
                "consequence": "信使当场完成投递",
                "cost_or_risk": "信使暴露了自己的任务",
            }
        ],
        "rule_constraints": ["禁止巧合", "角色性格不得突变"],
        "unsolvable": None,
    }
    payload.update(overrides)
    return payload


def test_event_info_boundary_requires_subject_and_bounds_lists():
    payload = EventOutputV1.model_validate(_info_gap_payload())
    assert payload.info_boundary[0].missing_contact_path is True
    assert payload.info_boundary[0].subject_ref == "c_witness"
    # subject_ref 与描述都不给 → 拒绝
    with pytest.raises(ValidationError):
        InfoGap(knows=[], not_known=[], missing_contact_path=False)
    # 描述可以替代 ref
    described = EventOutputV1.model_validate(
        _info_gap_payload(
            info_boundary=[
                {
                    "subject_description": "守门人",
                    "knows": ["登记簿上有收信人"],
                    "not_known": [],
                    "missing_contact_path": False,
                }
            ]
        )
    )
    assert described.info_boundary[0].subject_description == "守门人"
    # 清单条目超长（>500 字）与清单超量（>12 条）→ 拒绝
    with pytest.raises(ValidationError):
        EventOutputV1.model_validate(
            _info_gap_payload(
                info_boundary=[
                    {
                        "subject_ref": "c_witness",
                        "knows": ["x" * 501],
                        "not_known": [],
                        "missing_contact_path": False,
                    }
                ]
            )
        )
    with pytest.raises(ValidationError):
        EventOutputV1.model_validate(
            _info_gap_payload(
                info_boundary=[
                    {
                        "subject_description": "守门人",
                        "knows": [f"线索{i}" for i in range(13)],
                        "not_known": [],
                        "missing_contact_path": False,
                    }
                ]
            )
        )
    # info_boundary 上限 12 条
    with pytest.raises(ValidationError):
        EventOutputV1.model_validate(
            _info_gap_payload(
                info_boundary=[
                    {
                        "subject_ref": f"c_{i}",
                        "knows": [],
                        "not_known": [],
                        "missing_contact_path": False,
                    }
                    for i in range(13)
                ]
            )
        )


def test_event_three_modes_are_mutually_exclusive():
    GoalPath.model_validate(_goal_path_payload())
    # goal 模式必须给 goal_path
    with pytest.raises(ValidationError):
        EventOutputV1.model_validate(_event_payload(mode="goal", goal_path=None))
    # goal 模式禁 bridge_candidates
    with pytest.raises(ValidationError):
        EventOutputV1.model_validate(
            {
                **_event_payload(mode="goal"),
                "goal_path": _goal_path_payload(),
                "bridge_candidates": [
                    BridgePath(
                        steps=["x"],
                        required_conditions=[],
                        cost_or_risk="y",
                        holds=True,
                    )
                ],
            }
        )
    # diagnose 模式禁 goal_path
    with pytest.raises(ValidationError):
        EventOutputV1.model_validate(_event_payload(goal_path=_goal_path_payload()))
    # bridge 模式禁 goal_path
    bridge_base = _event_payload(
        mode="bridge",
        bridge_candidates=[
            {
                "steps": ["x"],
                "required_conditions": [],
                "cost_or_risk": "y",
                "holds": True,
            }
        ],
    )
    with pytest.raises(ValidationError):
        EventOutputV1.model_validate({**bridge_base, "goal_path": _goal_path_payload()})
    # 未知模式名 → 拒绝
    with pytest.raises(ValidationError):
        EventOutputV1.model_validate(_event_payload(mode="timeline"))


def test_event_goal_path_bounds_and_unsolvable_is_legal():
    # 无解是合法结论：goal_path 存在但 unsolvable 列出缺项，不编造巧合
    unsolvable = EventOutputV1.model_validate(
        {
            **_event_payload(mode="goal"),
            "goal_path": _goal_path_payload(
                unsolvable={
                    "reason": "守门人没有配合动机，无法在不靠巧合的前提下成立",
                    "missing": ["守门人的合作动机"],
                }
            ),
        }
    )
    assert unsolvable.goal_path is not None
    assert unsolvable.goal_path.unsolvable.missing == ["守门人的合作动机"]
    # steps 上限 8；rule_constraints 上限 10
    with pytest.raises(ValidationError):
        EventOutputV1.model_validate(
            {
                **_event_payload(mode="goal"),
                "goal_path": _goal_path_payload(
                    steps=[_goal_path_payload()["steps"][0] for _ in range(9)]
                ),
            }
        )
    with pytest.raises(ValidationError):
        EventOutputV1.model_validate(
            {
                **_event_payload(mode="goal"),
                "goal_path": _goal_path_payload(
                    rule_constraints=[f"约束{i}" for i in range(11)]
                ),
            }
        )
    # 环节缺字段（无代价）→ 拒绝
    step = _goal_path_payload()["steps"][0]
    incomplete = {k: v for k, v in step.items() if k != "cost_or_risk"}
    with pytest.raises(ValidationError):
        GoalPath.model_validate({**_goal_path_payload(), "steps": [incomplete]})


def test_start_task_request_event_mode_hint_scale_value_and_action_guard():
    base = {
        "novel_id": NOVEL_ID,
        "scale": "event",
        "action": "story.exploration.event.diagnose",
        "start": _provisional_payload(),
        "operation_id": str(uuid.uuid4()),
        "context_confirmation_id": "ctx-hint",
        "budget_preview_hash": "d" * 64,
    }
    ok = ExplorationStartTaskRequest.model_validate(
        {**base, "event_mode_hint": "info_gap"}
    )
    assert ok.event_mode_hint == "info_gap"
    # 非法值 → 拒绝
    with pytest.raises(ValidationError):
        ExplorationStartTaskRequest.model_validate(
            {**base, "event_mode_hint": "timeline"}
        )
    # 跨尺度 → 拒绝（沙盘不接受事件模式提示）
    with pytest.raises(ValidationError):
        ExplorationStartTaskRequest.model_validate(
            {
                **base,
                "scale": "sandbox",
                "action": "story.exploration.sandbox.generate",
                "event_mode_hint": "goal",
            }
        )
    # info_hint 配 diagnose；goal 必须配 bridge 动作
    with pytest.raises(ValidationError):
        ExplorationStartTaskRequest.model_validate(
            {
                **base,
                "action": "story.exploration.event.bridge",
                "event_mode_hint": "info_gap",
            }
        )
    goal_ok = ExplorationStartTaskRequest.model_validate(
        {
            **base,
            "action": "story.exploration.event.bridge",
            "event_mode_hint": "goal",
        }
    )
    assert goal_ok.event_mode_hint == "goal"
    # goal 提示配 diagnose 动作 → 拒绝
    with pytest.raises(ValidationError):
        ExplorationStartTaskRequest.model_validate({**base, "event_mode_hint": "goal"})


def test_scene_line_output_bounds_and_fields():
    payload = SceneLineOutputV1.model_validate(_scene_line_payload())
    assert payload.line.startswith("你要是累了")
    with pytest.raises(ValidationError):
        SceneLineOutputV1.model_validate(_scene_line_payload(line="太" * 501))
    with pytest.raises(ValidationError):
        SceneLineOutputV1.model_validate(_scene_line_payload(rationale=""))


def test_author_edit_payload_must_match_base_shape():
    ok = AuthorEditPayloadV1(
        base_output_kind=SANDBOX_OUTPUT_KIND,
        base_result_id=str(uuid.uuid4()),
        edited_payload=SandboxOutputV1.model_validate(_sandbox_payload()),
        edit_note="调整影响链",
    )
    assert ok.edited_payload.question.endswith("？")
    with pytest.raises(ValidationError):
        AuthorEditPayloadV1(
            base_output_kind=EVENT_OUTPUT_KIND,
            base_result_id=str(uuid.uuid4()),
            edited_payload=SandboxOutputV1.model_validate(_sandbox_payload()),
        )


def test_envelope_wraps_all_four_kinds_and_freezes_version():
    cases = [
        (SANDBOX_OUTPUT_KIND, SandboxOutputV1.model_validate(_sandbox_payload())),
        (EVENT_OUTPUT_KIND, EventOutputV1.model_validate(_event_payload())),
        (SCENE_LINE_OUTPUT_KIND, SceneLineOutputV1.model_validate(_scene_line_payload())),
        (
            AUTHOR_EDIT_OUTPUT_KIND,
            AuthorEditPayloadV1(
                base_output_kind=SANDBOX_OUTPUT_KIND,
                base_result_id=str(uuid.uuid4()),
                edited_payload=SandboxOutputV1.model_validate(_sandbox_payload()),
            ),
        ),
    ]
    for output_kind, payload in cases:
        envelope = ExplorationOutputEnvelope(
            output_kind=output_kind, schema_version=1, payload=payload
        )
        restored = ExplorationOutputEnvelope.model_validate(
            envelope.model_dump(mode="json")
        )
        assert restored.output_kind == output_kind
        assert restored.schema_version == 1
        assert type(restored.payload) is type(payload)
    with pytest.raises(ValidationError):
        ExplorationOutputEnvelope(
            output_kind=SANDBOX_OUTPUT_KIND,
            schema_version=2,
            payload=SandboxOutputV1.model_validate(_sandbox_payload()),
        )
    with pytest.raises(ValidationError):
        ExplorationOutputEnvelope(
            output_kind="story.exploration.novel",
            schema_version=1,
            payload=SandboxOutputV1.model_validate(_sandbox_payload()),
        )


# ---------------------------------------------------------------------------
# 起点指纹（同起点比较的判别依据）
# ---------------------------------------------------------------------------


def test_start_fingerprint_is_deterministic_and_discriminating():
    start = ProvisionalStart.model_validate(_provisional_payload())
    same = ProvisionalStart.model_validate(_provisional_payload())
    changed = ProvisionalStart.model_validate(
        _provisional_payload(question="换一个问题：如果重力永远消失呢？")
    )
    base = exploration_start_fingerprint(start, "sandbox")
    assert base == exploration_start_fingerprint(same, "sandbox")
    assert len(base) == 64
    assert base != exploration_start_fingerprint(start, "event")
    assert base != exploration_start_fingerprint(changed, "sandbox")


# ---------------------------------------------------------------------------
# 反事实条件对照（M2）：请求字段 + 克隆语义 + 预算身份
# ---------------------------------------------------------------------------


def _start_task_base(**overrides):
    base = {
        "novel_id": NOVEL_ID,
        "scale": "sandbox",
        "action": "story.exploration.sandbox.generate",
        "start": _provisional_payload(),
        "operation_id": str(uuid.uuid4()),
        "context_confirmation_id": "ctx-cf",
        "budget_preview_hash": "c" * 64,
    }
    base.update(overrides)
    return base


def test_start_task_request_accepts_counterfactual_fields():
    baseline_id = str(uuid.uuid4())
    request = ExplorationStartTaskRequest.model_validate(
        {
            **_start_task_base(start=None),
            "counterfactual_of_result_id": baseline_id,
            "changed_assumptions": [
                {"kind": "world_rule", "text": "重力变化时段从早晨改到傍晚"}
            ],
        }
    )
    assert request.counterfactual_of_result_id == baseline_id
    assert request.start is None
    assert request.changed_assumptions[0].text == "重力变化时段从早晨改到傍晚"
    with pytest.raises(ValidationError):
        ExplorationStartTaskRequest.model_validate(
            {
                **_start_task_base(start=None),
                "counterfactual_of_result_id": "not-a-uuid",
                "changed_assumptions": [
                    {"kind": "world_rule", "text": "重力变化时段改到傍晚"}
                ],
            }
        )


def test_counterfactual_request_rejects_partial_fields_and_explicit_start():
    baseline_id = str(uuid.uuid4())
    changed = [{"kind": "world_rule", "text": "重力变化时段改到傍晚"}]
    # 只给基线不给变更条件
    with pytest.raises(ValidationError):
        ExplorationStartTaskRequest.model_validate(
            _start_task_base(counterfactual_of_result_id=baseline_id)
        )
    # 只给变更条件不给基线
    with pytest.raises(ValidationError):
        ExplorationStartTaskRequest.model_validate(
            _start_task_base(changed_assumptions=changed)
        )
    # 反事实请求不允许再直接传 start
    with pytest.raises(ValidationError):
        ExplorationStartTaskRequest.model_validate(
            {
                **_start_task_base(),
                "counterfactual_of_result_id": baseline_id,
                "changed_assumptions": changed,
            }
        )
    # 反事实对照仅支持沙盘尺度
    with pytest.raises(ValidationError):
        ExplorationStartTaskRequest.model_validate(
            {
                **_start_task_base(start=None, scale="event"),
                "action": "story.exploration.event.diagnose",
                "counterfactual_of_result_id": baseline_id,
                "changed_assumptions": changed,
            }
        )


def test_counterfactual_changed_assumptions_rejects_empty_and_identity_kind():
    baseline_id = str(uuid.uuid4())
    with pytest.raises(ValidationError):
        ExplorationStartTaskRequest.model_validate(
            {
                **_start_task_base(start=None),
                "counterfactual_of_result_id": baseline_id,
                "changed_assumptions": [],
            }
        )
    with pytest.raises(ValidationError):
        ExplorationStartTaskRequest.model_validate(
            {
                **_start_task_base(start=None),
                "counterfactual_of_result_id": baseline_id,
                "changed_assumptions": [
                    {"kind": "identity", "text": "面包师其实是退役骑兵"}
                ],
            }
        )
    with pytest.raises(ValidationError):
        ExplorationStartTaskRequest.model_validate(
            {
                **_start_task_base(start=None),
                "counterfactual_of_result_id": baseline_id,
                "changed_assumptions": [
                    {"kind": "state", "text": f"条件{i}"} for i in range(11)
                ],
            }
        )


def test_apply_changed_assumptions_replaces_same_kind_and_keeps_rest_verbatim():
    start = ProvisionalStart(
        kind="provisional",
        question="这个城镇每天只有一小时重力减半，面包师的一天会怎样？",
        assumptions=[
            Assumption(kind="world_rule", text="每天只有一小时重力减半"),
            Assumption(kind="state", text="城镇仍靠手作炉与畜力磨坊"),
        ],
        candidates=[CandidateRef(ref_id="c_baker", label="面包师", role="character")],
        knowledge=[
            {
                "subject_ref": "c_baker",
                "knows": ["自己每天三点起床"],
                "observed": [],
                "misbelieves": [],
            }
        ],
        time_basis="收获季第一周",
    )
    cloned = apply_changed_assumptions(
        start,
        [Assumption(kind="world_rule", text="重力变化时段从早晨改到傍晚")],
    )
    # 同 kind：text 以 changed 为准，位置不变
    assert cloned.assumptions[0].kind == "world_rule"
    assert cloned.assumptions[0].text == "重力变化时段从早晨改到傍晚"
    # 未改条件与其余起点内容逐字保留
    assert cloned.assumptions[1] == start.assumptions[1]
    assert cloned.question == start.question
    assert cloned.time_basis == start.time_basis
    assert cloned.candidates == start.candidates
    assert cloned.knowledge == start.knowledge
    # 原起点不被原地修改
    assert start.assumptions[0].text == "每天只有一小时重力减半"
    assert cloned != start


def test_apply_changed_assumptions_appends_new_kind_and_multiple_changes():
    start = ProvisionalStart.model_validate(_provisional_payload())
    cloned = apply_changed_assumptions(
        start,
        [
            Assumption(kind="state", text="城镇粮仓只够两周"),
            Assumption(kind="world_rule", text="重力变化时段从早晨改到傍晚"),
        ],
    )
    # 基线只有一条 world_rule：第一条 changed 追加，第二条替换既有 world_rule
    assert [item.kind for item in cloned.assumptions] == ["world_rule", "state"]
    assert cloned.assumptions[0].text == "重力变化时段从早晨改到傍晚"
    assert cloned.assumptions[1].text == "城镇粮仓只够两周"


def test_counterfactual_budget_identity_includes_baseline_and_changed():
    start = ProvisionalStart.model_validate(_provisional_payload())
    baseline_a, baseline_b = str(uuid.uuid4()), str(uuid.uuid4())
    changed_a = [Assumption(kind="world_rule", text="重力变化时段从早晨改到傍晚")]
    changed_b = [Assumption(kind="world_rule", text="重力变化时段改到深夜")]

    plain = exploration_preview_identity(novel_id=NOVEL_ID, scale="sandbox", start=start)
    assert "counterfactual_of_result_id" not in plain

    cf_a = exploration_preview_identity(
        novel_id=NOVEL_ID,
        scale="sandbox",
        start=start,
        counterfactual_of_result_id=baseline_a,
        changed_assumptions=changed_a,
    )
    cf_a_again = exploration_preview_identity(
        novel_id=NOVEL_ID,
        scale="sandbox",
        start=start,
        counterfactual_of_result_id=baseline_a,
        changed_assumptions=changed_a,
    )
    assert cf_a == cf_a_again
    assert cf_a["counterfactual_of_result_id"] == baseline_a
    assert cf_a["changed_assumptions"] == [
        item.model_dump(mode="json") for item in changed_a
    ]
    # 基线不同或变更条件不同 → 身份与 preview_hash 都不同
    changed_b_dump = [item.model_dump(mode="json") for item in changed_b]
    for variant in (
        dict(cf_a, counterfactual_of_result_id=baseline_b),
        dict(cf_a, changed_assumptions=changed_b_dump),
    ):
        assert variant != cf_a
    budget_cf = preview_exploration_budget(
        novel_id=NOVEL_ID,
        scale="sandbox",
        start=start,
        counterfactual_of_result_id=baseline_a,
        changed_assumptions=changed_a,
    )
    budget_plain = preview_exploration_budget(
        novel_id=NOVEL_ID, scale="sandbox", start=start
    )
    assert budget_cf.preview_hash != budget_plain.preview_hash
    assert budget_cf.requests_max == budget_plain.requests_max == 5
    assert (
        budget_cf.preview_hash
        == preview_exploration_budget(
            novel_id=NOVEL_ID,
            scale="sandbox",
            start=start,
            counterfactual_of_result_id=baseline_a,
            changed_assumptions=changed_a,
        ).preview_hash
    )


def test_compare_request_defaults_to_same_start_and_accepts_counterfactual():
    request = ExplorationCompareRequest.model_validate(
        {
            "novel_id": NOVEL_ID,
            "first_result_id": str(uuid.uuid4()),
            "second_result_id": str(uuid.uuid4()),
        }
    )
    assert request.mode == "same_start"
    counterfactual = ExplorationCompareRequest.model_validate(
        {
            "novel_id": NOVEL_ID,
            "first_result_id": str(uuid.uuid4()),
            "second_result_id": str(uuid.uuid4()),
            "mode": "counterfactual",
        }
    )
    assert counterfactual.mode == "counterfactual"
    with pytest.raises(ValidationError):
        ExplorationCompareRequest.model_validate(
            {
                "novel_id": NOVEL_ID,
                "first_result_id": str(uuid.uuid4()),
                "second_result_id": str(uuid.uuid4()),
                "mode": "timeline",
            }
        )


# ---------------------------------------------------------------------------
# 场景人物差异与空间诊断（M2）：请求字段与三种输出形态
# ---------------------------------------------------------------------------


def _scene_start_task_base(**overrides):
    payload = {
        "novel_id": NOVEL_ID,
        "scale": "scene_line",
        "action": "story.exploration.scene_line.generate",
        "start": _provisional_payload(
            candidates=[
                {"ref_id": "c_franks", "label": "坦率者", "role": "character"},
                {"ref_id": "c_evasive", "label": "回避者", "role": "character"},
            ]
        ),
        "operation_id": str(uuid.uuid4()),
        "context_confirmation_id": "ctx-multi",
        "budget_preview_hash": "e" * 64,
    }
    payload.update(overrides)
    return payload


def test_multi_targets_requires_scene_scale():
    ok = ExplorationStartTaskRequest.model_validate(
        {**_scene_start_task_base(), "multi_targets": ["c_franks", "c_evasive"]}
    )
    assert ok.multi_targets == ["c_franks", "c_evasive"]
    # 跨尺度拒绝：沙盘不接受多目标
    with pytest.raises(ValidationError):
        ExplorationStartTaskRequest.model_validate(
            {
                **_scene_start_task_base(),
                "scale": "sandbox",
                "action": "story.exploration.sandbox.generate",
                "multi_targets": ["c_franks", "c_evasive"],
            }
        )
    # 事件尺度同样拒绝
    with pytest.raises(ValidationError):
        ExplorationStartTaskRequest.model_validate(
            {
                **_scene_start_task_base(),
                "scale": "event",
                "action": "story.exploration.event.diagnose",
                "multi_targets": ["c_franks", "c_evasive"],
            }
        )


def test_multi_targets_bounds_and_uniqueness():
    base = _scene_start_task_base()
    # 1 个目标低于下限；5 个超过上限；重复目标拒绝
    with pytest.raises(ValidationError):
        ExplorationStartTaskRequest.model_validate(
            {**base, "multi_targets": ["c_franks"]}
        )
    with pytest.raises(ValidationError):
        ExplorationStartTaskRequest.model_validate(
            {
                **base,
                "multi_targets": ["c_a", "c_b", "c_c", "c_d", "c_e"],
            }
        )
    with pytest.raises(ValidationError):
        ExplorationStartTaskRequest.model_validate(
            {**base, "multi_targets": ["c_franks", "c_franks"]}
        )
    # 4 个目标为合法上限
    four_candidates_base = _scene_start_task_base()
    four_candidates_base["start"] = _provisional_payload(
        candidates=[
            {"ref_id": f"c_p{i}", "label": f"人物{i}", "role": "character"}
            for i in range(4)
        ]
    )
    ok = ExplorationStartTaskRequest.model_validate(
        {**four_candidates_base, "multi_targets": ["c_p0", "c_p1", "c_p2", "c_p3"]}
    )
    assert len(ok.multi_targets) == 4


def test_multi_targets_and_diagnostic_are_mutually_exclusive():
    base = _scene_start_task_base()
    with pytest.raises(ValidationError):
        ExplorationStartTaskRequest.model_validate(
            {
                **base,
                "multi_targets": ["c_franks", "c_evasive"],
                "diagnostic": {"question": "他能一步跨到桌边吗？"},
            }
        )
    ok = ExplorationStartTaskRequest.model_validate(
        {**base, "diagnostic": {"question": "他能一步跨到桌边吗？"}}
    )
    assert ok.diagnostic.question == "他能一步跨到桌边吗？"
    assert ok.diagnostic.subject_ref is None
    assert ok.multi_targets is None


def test_diagnostic_requires_scene_scale():
    with pytest.raises(ValidationError):
        ExplorationStartTaskRequest.model_validate(
            {
                **_scene_start_task_base(),
                "scale": "sandbox",
                "action": "story.exploration.sandbox.generate",
                "diagnostic": {"question": "他能一步跨到桌边吗？"},
            }
        )
    with pytest.raises(ValidationError):
        ExplorationStartTaskRequest.model_validate(
            {
                **_scene_start_task_base(),
                "diagnostic": {"question": ""},
            }
        )
    with pytest.raises(ValidationError):
        ExplorationStartTaskRequest.model_validate(
            {
                **_scene_start_task_base(),
                "diagnostic": {"question": "问" * 2001},
            }
        )


def test_scene_line_single_shape_requires_target_and_line():
    with pytest.raises(ValidationError):
        SceneLineOutputV1.model_validate(_scene_line_payload(target_ref=""))
    with pytest.raises(ValidationError):
        SceneLineOutputV1.model_validate(_scene_line_payload(line=""))


def test_scene_line_variants_payload_shape():
    def _variant(ref):
        return {
            "target_ref": ref,
            "line": "你先回去吧。",
            "rationale": "各自知识包内的回应。",
        }

    ok = SceneLineOutputV1.model_validate(
        {
            "rationale": "同一情境按各目标独立知识包分别生成。",
            "variants": [_variant("c_franks"), _variant("c_evasive")],
        }
    )
    assert [variant.target_ref for variant in ok.variants] == ["c_franks", "c_evasive"]
    # 顶层 target_ref/line 必须为空，由 variants 承载
    with pytest.raises(ValidationError):
        SceneLineOutputV1.model_validate(
            {
                "target_ref": "c_franks",
                "rationale": "顶层不能带单目标。",
                "variants": [_variant("c_franks"), _variant("c_evasive")],
            }
        )
    # target_ref 重复拒绝
    with pytest.raises(ValidationError):
        SceneLineOutputV1.model_validate(
            {
                "rationale": "重复目标。",
                "variants": [_variant("c_franks"), _variant("c_franks")],
            }
        )
    # 嵌套 variants 拒绝
    with pytest.raises(ValidationError):
        SceneLineOutputV1.model_validate(
            {
                "rationale": "不得嵌套。",
                "variants": [
                    _variant("c_franks"),
                    {
                        "rationale": "嵌套。",
                        "variants": [_variant("c_a"), _variant("c_b")],
                    },
                ],
            }
        )
    # 变体缺少台词拒绝
    with pytest.raises(ValidationError):
        SceneLineOutputV1.model_validate(
            {
                "rationale": "缺台词。",
                "variants": [
                    _variant("c_franks"),
                    {"target_ref": "c_evasive", "rationale": "没有 line"},
                ],
            }
        )


def test_scene_line_spatial_assessment_payload():
    ok = SceneLineOutputV1.model_validate(
        {
            "rationale": "只依据已确认空间资料判断。",
            "spatial_assessment": {
                "supported": True,
                "constraints": ["桌边通道只容侧身"],
                "unknowns": ["大门到桌子的精确距离"],
            },
        }
    )
    assert ok.spatial_assessment.supported is True
    assert ok.target_ref == "" and ok.line == ""
    # diagnostic 形态也允许附带台词，但 constraints/unknowns 有界
    with pytest.raises(ValidationError):
        SceneLineOutputV1.model_validate(
            {
                "rationale": "越界。",
                "spatial_assessment": {
                    "constraints": [f"约束{i}" for i in range(11)],
                },
            }
        )
    # variants 与 spatial_assessment 互斥
    with pytest.raises(ValidationError):
        SceneLineOutputV1.model_validate(
            {
                "rationale": "不得同时承载。",
                "variants": [
                    {"target_ref": "c_a", "line": "好", "rationale": "r"},
                    {"target_ref": "c_b", "line": "嗯", "rationale": "r"},
                ],
                "spatial_assessment": {"supported": False},
            }
        )


def test_validate_scene_targets_membership():
    start = ProvisionalStart.model_validate(
        _provisional_payload(
            candidates=[
                {"ref_id": "c_franks", "label": "坦率者", "role": "character"},
                {"ref_id": "c_evasive", "label": "回避者", "role": "character"},
            ],
            canonical_refs=[str(uuid.uuid4())],
        )
    )
    validate_scene_targets(start, ["c_franks", "c_evasive", start.canonical_refs[0]])
    with pytest.raises(ValueError):
        validate_scene_targets(start, ["c_stranger"])


# ---------------------------------------------------------------------------
# 锁定集载荷（M3-A）：extra=forbid、哈希与标签边界、信封五类判别
# ---------------------------------------------------------------------------


def test_lock_set_payload_schema_forbids_extra_and_bounds_fields():
    payload = LockSetPayloadV1(
        locked_items=[
            LockedItem(
                item_path="chain:0",
                item_content_hash="a" * 64,
                label="面包更松软",
            )
        ],
        note="结局满意，后续修订保留",
    )
    assert payload.locked_items[0].item_path == "chain:0"
    assert payload.note.endswith("保留")

    # extra=forbid：未知字段拒绝
    with pytest.raises(ValidationError):
        LockSetPayloadV1.model_validate(
            {
                "locked_items": [],
                "note": None,
                "unexpected": True,
            }
        )
    with pytest.raises(ValidationError):
        LockedItem.model_validate(
            {"item_path": "chain:0", "item_content_hash": "a" * 64, "oops": 1}
        )
    # item_content_hash 必须 64hex
    with pytest.raises(ValidationError):
        LockedItem(item_path="chain:0", item_content_hash="zz" * 32)
    # item_path 1..120、label 0..200
    with pytest.raises(ValidationError):
        LockedItem(item_path="", item_content_hash="a" * 64)
    with pytest.raises(ValidationError):
        LockedItem(item_path="x" * 121, item_content_hash="a" * 64)
    with pytest.raises(ValidationError):
        LockedItem(item_path="line", item_content_hash="a" * 64, label="长" * 201)

    envelope = ExplorationOutputEnvelope(
        output_kind=LOCK_SET_OUTPUT_KIND, schema_version=1, payload=payload
    )
    restored = ExplorationOutputEnvelope.model_validate(envelope.model_dump(mode="json"))
    assert restored.output_kind == LOCK_SET_OUTPUT_KIND
    assert type(restored.payload) is LockSetPayloadV1
    with pytest.raises(ValidationError):
        ExplorationOutputEnvelope(
            output_kind="story.exploration.locked",
            schema_version=1,
            payload=payload,
        )


# ---------------------------------------------------------------------------
# 临时起点完整排演（M3-B）：请求边界、互斥与 payload 形状
# ---------------------------------------------------------------------------


def _full_rehearsal_payload(**overrides):
    payload = {
        "targets": ["c_franks", "c_evasive"],
        "rounds": 2,
        "author_goal": "看两人对同一谣言的不同反应",
    }
    payload.update(overrides)
    return payload


def test_full_rehearsal_request_bounds_and_uniqueness():
    base = _scene_start_task_base()
    ok = ExplorationStartTaskRequest.model_validate(
        {**base, "full_rehearsal": _full_rehearsal_payload()}
    )
    assert ok.full_rehearsal.targets == ["c_franks", "c_evasive"]
    assert ok.full_rehearsal.rounds == 2
    assert ok.full_rehearsal.author_goal == "看两人对同一谣言的不同反应"
    # targets 1..6：空列表与 7 个目标都拒绝；重复目标拒绝
    with pytest.raises(ValidationError):
        ExplorationStartTaskRequest.model_validate(
            {**base, "full_rehearsal": _full_rehearsal_payload(targets=[])}
        )
    with pytest.raises(ValidationError):
        ExplorationStartTaskRequest.model_validate(
            {
                **base,
                "full_rehearsal": _full_rehearsal_payload(
                    targets=[f"c_t{i}" for i in range(75)]
                ),
            }
        )
    with pytest.raises(ValidationError):
        ExplorationStartTaskRequest.model_validate(
            {
                **base,
                "full_rehearsal": _full_rehearsal_payload(
                    targets=["c_franks", "c_franks"]
                ),
            }
        )
    # rounds 1..3；author_goal 0..2000
    with pytest.raises(ValidationError):
        ExplorationStartTaskRequest.model_validate(
            {**base, "full_rehearsal": _full_rehearsal_payload(rounds=0)}
        )
    expanded = ExplorationStartTaskRequest.model_validate(
        {
            **base,
            "full_rehearsal": _full_rehearsal_payload(
                rounds=4, targets=[f"c_t{i}" for i in range(7)]
            ),
        }
    )
    assert expanded.full_rehearsal.rounds == 4
    assert len(expanded.full_rehearsal.targets) == 7
    with pytest.raises(ValidationError):
        ExplorationStartTaskRequest.model_validate(
            {**base, "full_rehearsal": _full_rehearsal_payload(author_goal="长" * 2001)}
        )
    single = ExplorationStartTaskRequest.model_validate(
        {
            **base,
            "full_rehearsal": _full_rehearsal_payload(
                targets=["c_franks"], rounds=3, author_goal=""
            ),
        }
    )
    assert single.full_rehearsal.rounds == 3


def test_full_rehearsal_requires_scene_scale_and_excludes_focus_variants():
    base = _scene_start_task_base()
    # 仅场景一句对白尺度接受
    with pytest.raises(ValidationError):
        ExplorationStartTaskRequest.model_validate(
            {
                **base,
                "scale": "sandbox",
                "action": "story.exploration.sandbox.generate",
                "full_rehearsal": _full_rehearsal_payload(),
            }
        )
    with pytest.raises(ValidationError):
        ExplorationStartTaskRequest.model_validate(
            {
                **base,
                "scale": "event",
                "action": "story.exploration.event.diagnose",
                "full_rehearsal": _full_rehearsal_payload(),
            }
        )
    # 与 multi_targets / diagnostic 互斥
    with pytest.raises(ValidationError):
        ExplorationStartTaskRequest.model_validate(
            {
                **base,
                "full_rehearsal": _full_rehearsal_payload(),
                "multi_targets": ["c_franks", "c_evasive"],
            }
        )
    with pytest.raises(ValidationError):
        ExplorationStartTaskRequest.model_validate(
            {
                **base,
                "full_rehearsal": _full_rehearsal_payload(),
                "diagnostic": {"question": "他能一步跨到桌边吗？"},
            }
        )
    # 与反事实对照互斥
    with pytest.raises(ValidationError):
        ExplorationStartTaskRequest.model_validate(
            {
                **base,
                "start": None,
                "counterfactual_of_result_id": str(uuid.uuid4()),
                "changed_assumptions": [{"kind": "world_rule", "text": "重力恢复正常"}],
                "full_rehearsal": _full_rehearsal_payload(),
            }
        )


def test_full_rehearsal_output_payload_shape():
    payload = {
        "targets": ["c_franks", "c_evasive"],
        "rounds": [
            {
                "round_number": 1,
                "performances": [
                    {
                        "target_ref": "c_franks",
                        "line_or_beat": "这话我在城门口就听说了。",
                        "rationale": "坦率者只依据已声明的见闻说话。",
                        "basis_refs": ["observed:城门口人群"],
                    },
                    {
                        "target_ref": "c_evasive",
                        "line_or_beat": "先看看别人怎么说。",
                        "rationale": "回避者误信消息已人尽皆知，选择跟随。",
                        "basis_refs": ["misbelieves:消息已公开"],
                    },
                ],
                "materials": [
                    {
                        "kind": "crowd",
                        "text": "井台边三五个人压低声音议论。",
                        "perceiver_refs": ["c_franks", "c_evasive"],
                    }
                ],
                "observations": [
                    {
                        "target_ref": "c_evasive",
                        "observed": "坦率者当众反驳了传言。",
                    }
                ],
            },
            {
                "round_number": 2,
                "performances": [
                    {
                        "target_ref": "c_franks",
                        "line_or_beat": "我不重复第二遍。",
                        "rationale": "上一轮被围观后态度更硬。",
                        "basis_refs": [],
                    },
                    {
                        "target_ref": "c_evasive",
                        "line_or_beat": "好吧，就按你说的办。",
                        "rationale": "观察到对方强硬后改口。",
                        "basis_refs": [],
                    },
                ],
                "materials": [],
                "observations": [],
            },
        ],
        "state_notes": ["回避者已改口，误信被部分纠正。"],
        "unknowns": ["围观者是否会把冲突传出去"],
        "warnings": [],
    }
    output = FullRehearsalOutputV1.model_validate(payload)
    assert len(output.rounds) == 2
    # extra=forbid：未知字段拒绝
    with pytest.raises(ValidationError):
        FullRehearsalOutputV1.model_validate({**payload, "nope": 1})
    # 轮次编号必须从 1 起连续
    broken_number = copy.deepcopy(payload)
    broken_number["rounds"][1]["round_number"] = 3
    with pytest.raises(ValidationError):
        FullRehearsalOutputV1.model_validate(broken_number)
    # 每轮表演卡必须恰好覆盖全部目标且不重复
    missing_target = copy.deepcopy(payload)
    missing_target["rounds"][1]["performances"] = missing_target["rounds"][1][
        "performances"
    ][:1]
    with pytest.raises(ValidationError):
        FullRehearsalOutputV1.model_validate(missing_target)
    duplicated = copy.deepcopy(payload)
    duplicated["rounds"][1]["performances"][1]["target_ref"] = "c_franks"
    with pytest.raises(ValidationError):
        FullRehearsalOutputV1.model_validate(duplicated)
    # 观察回执与素材感知者只能引用本次目标
    stray_observation = copy.deepcopy(payload)
    stray_observation["rounds"][0]["observations"][0]["target_ref"] = "c_stranger"
    with pytest.raises(ValidationError):
        FullRehearsalOutputV1.model_validate(stray_observation)
    stray_perceiver = copy.deepcopy(payload)
    stray_perceiver["rounds"][0]["materials"][0]["perceiver_refs"] = ["c_stranger"]
    with pytest.raises(ValidationError):
        FullRehearsalOutputV1.model_validate(stray_perceiver)
    # 字段长度受限：台词 1..500、依据 1..2000
    with pytest.raises(ValidationError):
        FullRehearsalOutputV1.model_validate(
            {
                **payload,
                "rounds": [
                    {
                        **payload["rounds"][0],
                        "performances": [
                            {
                                **payload["rounds"][0]["performances"][0],
                                "line_or_beat": "长" * 501,
                            },
                            payload["rounds"][0]["performances"][1],
                        ],
                    }
                ],
            }
        )


def test_envelope_wraps_full_rehearsal_as_sixth_kind():
    payload = FullRehearsalOutputV1(
        targets=["c_franks"],
        rounds=[
            {
                "round_number": 1,
                "performances": [
                    {
                        "target_ref": "c_franks",
                        "line_or_beat": "我先说。",
                        "rationale": "唯一目标开场。",
                        "basis_refs": [],
                    }
                ],
            }
        ],
    )
    envelope = ExplorationOutputEnvelope(
        output_kind=FULL_REHEARSAL_OUTPUT_KIND, schema_version=1, payload=payload
    )
    restored = ExplorationOutputEnvelope.model_validate(envelope.model_dump(mode="json"))
    assert restored.output_kind == FULL_REHEARSAL_OUTPUT_KIND
    assert type(restored.payload) is FullRehearsalOutputV1
    # 六类判别联合完整可用
    cases = (
        (SANDBOX_OUTPUT_KIND, SandboxOutputV1.model_validate(_sandbox_payload())),
        (EVENT_OUTPUT_KIND, EventOutputV1.model_validate(_event_payload())),
        (
            SCENE_LINE_OUTPUT_KIND,
            SceneLineOutputV1(target_ref="c_a", line="好。", rationale="按候选知识"),
        ),
        (
            AUTHOR_EDIT_OUTPUT_KIND,
            AuthorEditPayloadV1(
                base_output_kind=SANDBOX_OUTPUT_KIND,
                base_result_id=str(uuid.uuid4()),
                edited_payload=SandboxOutputV1.model_validate(_sandbox_payload()),
            ),
        ),
        (LOCK_SET_OUTPUT_KIND, LockSetPayloadV1(locked_items=[])),
        (FULL_REHEARSAL_OUTPUT_KIND, payload),
    )
    assert len({kind for kind, _ in cases}) == 6
    for kind, payload_item in cases:
        wrapped = ExplorationOutputEnvelope(
            output_kind=kind, schema_version=1, payload=payload_item
        )
        assert wrapped.output_kind == kind
    with pytest.raises(ValidationError):
        ExplorationOutputEnvelope(
            output_kind="story.exploration.rehearsal",
            schema_version=1,
            payload=payload,
        )
