"""探索契约 schema 校验：起点判别、四类 payload、信封与预算模型（P0 §1/§4/§5/§8）。"""

from __future__ import annotations

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
    GapFinding,
    InfluenceLink,
    SandboxOutputV1,
    SceneLineOutputV1,
    apply_changed_assumptions,
    exploration_start_fingerprint,
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
                    {"kind": "state", "text": f"条件{i}"}
                    for i in range(11)
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

    plain = exploration_preview_identity(
        novel_id=NOVEL_ID, scale="sandbox", start=start
    )
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
    assert budget_cf.requests_max == budget_plain.requests_max == 1
    assert budget_cf.preview_hash == preview_exploration_budget(
        novel_id=NOVEL_ID,
        scale="sandbox",
        start=start,
        counterfactual_of_result_id=baseline_a,
        changed_assumptions=changed_a,
    ).preview_hash


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
