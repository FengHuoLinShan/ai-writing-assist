"""探索预算预览：初始恰好 1 次请求、token 区间按输入包长度估算（P0 §5）。"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from modules.evidence.contracts import ProvisionalStart
from modules.story.exploration_budget import preview_exploration_budget
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
