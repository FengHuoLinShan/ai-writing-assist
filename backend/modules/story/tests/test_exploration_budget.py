"""探索预算预览：初始恰好 1 次请求、token 区间按输入包长度估算（P0 §5）。"""

from __future__ import annotations

import json
import uuid

import pytest
from pydantic import ValidationError

from modules.evidence.contracts import ProvisionalStart
from modules.story.exploration_budget import (
    exploration_preview_identity,
    preview_exploration_budget,
)
from modules.story.exploration_schemas import (
    ExplorationBudgetPreview,
    FullRehearsalRequest,
)


def _start(question: str = "这个城镇每天只有一小时重力减半，面包师的一天会怎样？"):
    return ProvisionalStart.model_validate(
        {
            "kind": "provisional",
            "question": question,
            "assumptions": [{"kind": "world_rule", "text": "每天只有一小时重力减半"}],
            "time_basis": "assumed_now",
        }
    )


@pytest.mark.parametrize("scale", ["sandbox", "event", "scene_line"])
def test_initial_budget_is_exactly_one_request(scale):
    preview = preview_exploration_budget(
        novel_id=str(uuid.uuid4()), scale=scale, start=_start()
    )
    assert isinstance(preview, ExplorationBudgetPreview)
    assert preview.requests_min == 1
    assert preview.requests_max == 1
    assert preview.follow_up_max_requests == 1
    assert 0 <= preview.tokens_min <= preview.tokens_max
    assert len(preview.preview_hash) == 64
    assert preview.token_estimate.minimum == preview.tokens_min
    assert preview.token_estimate.maximum == preview.tokens_max


def test_preview_hash_is_deterministic_and_binds_inputs():
    novel_id, start = str(uuid.uuid4()), _start()
    first = preview_exploration_budget(novel_id=novel_id, scale="sandbox", start=start)
    again = preview_exploration_budget(novel_id=novel_id, scale="sandbox", start=start)
    assert first.preview_hash == again.preview_hash
    assert (
        preview_exploration_budget(
            novel_id=novel_id, scale="sandbox", start=start, focus="只看面包师"
        ).preview_hash
        != first.preview_hash
    )
    assert (
        preview_exploration_budget(
            novel_id=novel_id,
            scale="sandbox",
            start=_start(question="如果重力完全消失呢？"),
        ).preview_hash
        != first.preview_hash
    )
    assert (
        preview_exploration_budget(
            novel_id=novel_id, scale="event", start=start
        ).preview_hash
        != first.preview_hash
    )


def test_longer_input_package_raises_token_floor():
    short = preview_exploration_budget(novel_id="n", scale="scene_line", start=_start())
    long_question = "细节" * 800
    long = preview_exploration_budget(
        novel_id="n", scale="scene_line", start=_start(question=long_question)
    )
    assert long.tokens_min > short.tokens_min
    assert long.tokens_max >= long.tokens_min


def test_invalid_scale_is_rejected():
    with pytest.raises(ValueError):
        preview_exploration_budget(novel_id="n", scale="novel", start=_start())


def test_budget_identity_includes_event_mode_hint():
    """事件模式提示纳入预算身份：不同 hint → 不同 hash；缺省不含该键（M2）。"""
    novel_id, start = str(uuid.uuid4()), _start()
    plain = exploration_preview_identity(novel_id=novel_id, scale="event", start=start)
    assert "event_mode_hint" not in plain
    info_gap = exploration_preview_identity(
        novel_id=novel_id, scale="event", start=start, event_mode_hint="info_gap"
    )
    goal = exploration_preview_identity(
        novel_id=novel_id, scale="event", start=start, event_mode_hint="goal"
    )
    assert info_gap["event_mode_hint"] == "info_gap"
    identities = {
        json.dumps(plain, sort_keys=True, ensure_ascii=False),
        json.dumps(info_gap, sort_keys=True, ensure_ascii=False),
        json.dumps(goal, sort_keys=True, ensure_ascii=False),
    }
    assert len(identities) == 3

    plain_budget = preview_exploration_budget(
        novel_id=novel_id, scale="event", start=start
    )
    info_budget = preview_exploration_budget(
        novel_id=novel_id, scale="event", start=start, event_mode_hint="info_gap"
    )
    goal_budget = preview_exploration_budget(
        novel_id=novel_id, scale="event", start=start, event_mode_hint="goal"
    )
    assert (
        len(
            {
                plain_budget.preview_hash,
                info_budget.preview_hash,
                goal_budget.preview_hash,
            }
        )
        == 3
    )
    # 同一 hint 确定性；请求数不变（预算不变，仍 1 请求）
    assert (
        info_budget.preview_hash
        == preview_exploration_budget(
            novel_id=novel_id, scale="event", start=start, event_mode_hint="info_gap"
        ).preview_hash
    )
    assert info_budget.requests_max == goal_budget.requests_max == 1


def test_budget_model_rejects_inconsistent_ranges():
    with pytest.raises(ValidationError):
        ExplorationBudgetPreview(
            requests_min=2,
            requests_max=1,
            follow_up_max_requests=1,
            tokens_min=10,
            tokens_max=20,
            preview_hash="a" * 64,
        )
    with pytest.raises(ValidationError):
        ExplorationBudgetPreview(
            requests_min=1,
            requests_max=1,
            follow_up_max_requests=1,
            tokens_min=30,
            tokens_max=20,
            preview_hash="a" * 64,
        )
    with pytest.raises(ValidationError):
        ExplorationBudgetPreview(
            requests_min=1,
            requests_max=1,
            follow_up_max_requests=1,
            tokens_min=1,
            tokens_max=2,
            preview_hash="not-a-hash",
        )


def test_multi_targets_scale_requests_and_identity():
    """场景多目标（M2）：预算 = 目标数；目标列表纳入身份。"""
    novel_id, start = str(uuid.uuid4()), _start()
    targets = ["c_franks", "c_evasive", "c_bystander"]
    multi = preview_exploration_budget(
        novel_id=novel_id,
        scale="scene_line",
        start=start,
        multi_targets=targets,
    )
    assert multi.requests_min == multi.requests_max == 3
    assert multi.follow_up_max_requests == 1
    single = preview_exploration_budget(
        novel_id=novel_id, scale="scene_line", start=start
    )
    assert single.requests_min == single.requests_max == 1
    assert multi.tokens_max > single.tokens_max  # 输出按目标数放大
    # 目标列表纳入身份：不同目标集合/顺序 → 不同 hash
    other = preview_exploration_budget(
        novel_id=novel_id,
        scale="scene_line",
        start=start,
        multi_targets=["c_evasive", "c_franks", "c_bystander"],
    )
    assert multi.preview_hash != other.preview_hash
    assert multi.preview_hash == preview_exploration_budget(
        novel_id=novel_id,
        scale="scene_line",
        start=start,
        multi_targets=list(targets),
    ).preview_hash
    identity = exploration_preview_identity(
        novel_id=novel_id, scale="scene_line", start=start, multi_targets=targets
    )
    assert identity["multi_targets"] == targets


def test_diagnostic_question_changes_budget_identity():
    """空间诊断（M2）：预算不变（1 请求），诊断问题纳入身份。"""
    novel_id, start = str(uuid.uuid4()), _start()
    plain = preview_exploration_budget(
        novel_id=novel_id, scale="scene_line", start=start
    )
    diagnostic = preview_exploration_budget(
        novel_id=novel_id,
        scale="scene_line",
        start=start,
        diagnostic_question="他能一步从大门跨到桌边吗？",
    )
    assert diagnostic.requests_min == diagnostic.requests_max == 1
    assert diagnostic.preview_hash != plain.preview_hash
    assert diagnostic.preview_hash == preview_exploration_budget(
        novel_id=novel_id,
        scale="scene_line",
        start=start,
        diagnostic_question="他能一步从大门跨到桌边吗？",
    ).preview_hash
    identity = exploration_preview_identity(
        novel_id=novel_id,
        scale="scene_line",
        start=start,
        diagnostic_question="他能一步从大门跨到桌边吗？",
    )
    assert identity["diagnostic_question_chars"] == len("他能一步从大门跨到桌边吗？")


# ---------------------------------------------------------------------------
# 临时起点完整排演（M3-B）：预算 = (目标数 + 1) × 轮次，与聚焦输出分开计量
# ---------------------------------------------------------------------------


def _rehearsal(targets=("c_franks", "c_evasive"), rounds=2, author_goal="看分歧"):
    return FullRehearsalRequest(
        targets=list(targets), rounds=rounds, author_goal=author_goal
    )


def test_full_rehearsal_budget_is_targets_plus_one_per_round():
    novel_id, start = str(uuid.uuid4()), _start()
    two_by_two = preview_exploration_budget(
        novel_id=novel_id,
        scale="scene_line",
        start=start,
        full_rehearsal=_rehearsal(targets=("c_a", "c_b"), rounds=2),
    )
    assert two_by_two.requests_min == two_by_two.requests_max == (2 + 1) * 2
    single = preview_exploration_budget(
        novel_id=novel_id,
        scale="scene_line",
        start=start,
        full_rehearsal=_rehearsal(targets=("c_a",), rounds=1),
    )
    assert single.requests_min == single.requests_max == 2
    three_rounds = preview_exploration_budget(
        novel_id=novel_id,
        scale="scene_line",
        start=start,
        full_rehearsal=_rehearsal(targets=("c_a", "c_b", "c_c"), rounds=3),
    )
    assert three_rounds.requests_min == three_rounds.requests_max == (3 + 1) * 3
    # 有界：min == max；token 区间随请求次数放大
    assert two_by_two.tokens_min <= two_by_two.tokens_max
    assert two_by_two.tokens_max > single.tokens_max
    assert single.follow_up_max_requests == 1


def test_full_rehearsal_identity_binds_targets_rounds_and_goal():
    novel_id, start = str(uuid.uuid4()), _start()
    first = preview_exploration_budget(
        novel_id=novel_id,
        scale="scene_line",
        start=start,
        full_rehearsal=_rehearsal(),
    )
    # 同输入确定性
    assert (
        first.preview_hash
        == preview_exploration_budget(
            novel_id=novel_id,
            scale="scene_line",
            start=start,
            full_rehearsal=_rehearsal(),
        ).preview_hash
    )
    # targets / rounds / author_goal 任一变化都改变身份
    assert (
        first.preview_hash
        != preview_exploration_budget(
            novel_id=novel_id,
            scale="scene_line",
            start=start,
            full_rehearsal=_rehearsal(targets=("c_b", "c_a")),
        ).preview_hash
    )
    assert (
        first.preview_hash
        != preview_exploration_budget(
            novel_id=novel_id,
            scale="scene_line",
            start=start,
            full_rehearsal=_rehearsal(rounds=3),
        ).preview_hash
    )
    assert (
        first.preview_hash
        != preview_exploration_budget(
            novel_id=novel_id,
            scale="scene_line",
            start=start,
            full_rehearsal=_rehearsal(author_goal="另一个私密目的"),
        ).preview_hash
    )
    identity = exploration_preview_identity(
        novel_id=novel_id,
        scale="scene_line",
        start=start,
        full_rehearsal=_rehearsal(),
    )
    assert identity["full_rehearsal"] == {
        "targets": ["c_franks", "c_evasive"],
        "rounds": 2,
        "author_goal_chars": len("看分歧"),
    }


def test_full_rehearsal_hash_differs_from_plain_and_multi_targets():
    novel_id, start = str(uuid.uuid4()), _start()
    hashes = {
        preview_exploration_budget(
            novel_id=novel_id, scale="scene_line", start=start
        ).preview_hash,
        preview_exploration_budget(
            novel_id=novel_id,
            scale="scene_line",
            start=start,
            multi_targets=["c_franks", "c_evasive"],
        ).preview_hash,
        preview_exploration_budget(
            novel_id=novel_id,
            scale="scene_line",
            start=start,
            full_rehearsal=_rehearsal(targets=("c_franks", "c_evasive"), rounds=1),
        ).preview_hash,
    }
    # 三种模式（聚焦单目标 / 多目标对白 / 完整排演）身份互不相同
    assert len(hashes) == 3
