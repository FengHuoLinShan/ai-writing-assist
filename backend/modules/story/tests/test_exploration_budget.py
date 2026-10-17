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
from modules.story.exploration_schemas import ExplorationBudgetPreview


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
