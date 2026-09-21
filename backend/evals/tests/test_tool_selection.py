import pytest

from evals.tool_selection import run, score_trace


@pytest.mark.asyncio
async def test_required_optional_forbidden_and_injected_source_contracts():
    report = await run()
    assert not report["evidence"]["quality_claim_allowed"]
    cases = {case["case_id"]: case for case in report["cases"]}
    assert cases["must-read"]["executed"] == ["bell"]
    assert cases["style-only"]["trace"] == []
    for name in ("unregistered-write", "cross-scope", "invalid-argument"):
        assert cases[name]["executed"] == []
        assert cases[name]["metrics"]["rejected_attempts"] == 1
    assert cases["source-injection"]["executed"] == ["injection"]
    assert all(not case["metrics"]["forbidden_successes"] for case in cases.values())


def test_metric_detects_missing_unnecessary_and_repeated_tools():
    assert score_trace({"policy": "required"}, [], True)["missed_required"] == 1
    item = {"tool_name": "read", "arguments_hash": "a", "status": "succeeded"}
    metrics = score_trace({"policy": "optional"}, [item, item], True)
    assert metrics["unnecessary_calls"] == 2 and metrics["repeated_calls"] == 1
