import pytest

from evals.collaboration_comparison import export_blind_review, run
from modules.assistant.teams.contracts import blueprint_snapshot


@pytest.mark.asyncio
async def test_three_arms_share_scope_permissions_budget_and_reuse_receipts(tmp_path):
    report = await run()
    arms = report["arms"]
    for key in ("scope_hash", "tool_contract_hash"):
        assert len({arm[key] for arm in arms}) == 1
    assert all(arm["budget_limit"] == arms[0]["budget_limit"] for arm in arms)
    assert [arm["scripted_requests"] for arm in arms] == [1, 3, 3]
    assert all(arm["recovery_repeated_requests"] == 0 for arm in arms)
    assert all(arm["provider_requests"] == 0 for arm in arms)
    export_blind_review(report, tmp_path)
    html = (tmp_path / "blind-review.html").read_text()
    assert "bounded_team" not in html and "single_agent" not in html
    assert (tmp_path / "blind-review-key.private.json").is_file()


def test_versioned_methods_do_not_expand_legacy_tool_permissions():
    legacy = blueprint_snapshot(version=1)
    current = blueprint_snapshot()
    assert "methods" not in legacy
    assert current["read_tools"] == legacy["read_tools"]
    assert current["methods"]["facts"]["world-rules-v1"]
    assert current["hash"] != legacy["hash"]
