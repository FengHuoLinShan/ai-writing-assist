"""Budget preview must expose full estimated needs when grants are too small."""

import pytest

from modules.story.world_progression_budget import preview_progression_budget
from modules.story.world_progression_schemas import ProgressionBudgetPreviewRequest


@pytest.mark.parametrize(
    ("policy", "steps", "minimum_calls", "maximum_calls"),
    [("one_step", None, 2, 2), ("n_steps", 3, 6, 6), ("until_budget", None, 2, 2)],
)
def test_preview_never_clamps_required_estimates_to_insufficient_grant(
    policy, steps, minimum_calls, maximum_calls
):
    request = ProgressionBudgetPreviewRequest(
        novel_id="00000000-0000-0000-0000-000000000001",
        participants=[
            {"id": "00000000-0000-0000-0000-000000000002", "kind": "character"}
        ],
        run_policy=policy,
        steps=steps,
        request_limit=1,
        token_limit=1,
        time_budget_seconds=1,
    )
    preview = preview_progression_budget(
        request,
        {
            "scene_id": "00000000-0000-0000-0000-000000000003",
            "source_hash": "frozen-source",
            "map_state": {"coverage": "available"},
        },
        model_name="offline-test",
        metrics=[],
    )

    calls = preview["request_budget"]
    tokens = preview["token_budget"]
    time = preview["time_budget"]
    assert (calls["estimate_minimum"], calls["estimate_maximum"]) == (
        minimum_calls,
        maximum_calls,
    )
    assert calls["max_complete_steps_before_guard"] == 0
    assert calls["estimate_minimum"] > calls["limit"]
    assert 1 < tokens["estimate_minimum"] <= tokens["estimate_maximum"]
    assert 1 < time["estimate_minimum_seconds"] <= time["estimate_maximum_seconds"]
    assert any("请求额度不足" in item for item in preview["warnings"])
    assert any("Token 最低需求" in item for item in preview["warnings"])
    assert any("最短耗时" in item for item in preview["warnings"])
    if policy == "until_budget":
        assert calls["estimate_scope"] == "authorization_window"
        assert any("无法预知完成步数" in item for item in preview["warnings"])
    else:
        assert calls["estimate_scope"] == "complete_selection"
