"""Browser gate aggregation must accept only the documented outcome table."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/aggregate_browser_gate.py"
spec = importlib.util.spec_from_file_location("aggregate_browser_gate", SCRIPT)
aggregator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aggregator)

FUNCTIONAL = {
    "browser_suite": "test:e2e:functional",
    "shard_plan": "[1,2]",
    "shard_total": "2",
}
SMOKE = {
    "browser_suite": "test:e2e:smoke",
    "shard_plan": "[1]",
    "shard_total": "1",
}


@pytest.mark.parametrize("suite_kwargs", [FUNCTIONAL, SMOKE])
def test_browser_run_passes_only_when_every_shard_succeeded(suite_kwargs):
    ok, _ = aggregator.aggregate(
        classify_result="success",
        browser="true",
        shard_result="success",
        **suite_kwargs,
    )
    assert ok
    for result in ("failure", "cancelled", "skipped"):
        passed, message = aggregator.aggregate(
            classify_result="success",
            browser="true",
            shard_result=result,
            **suite_kwargs,
        )
        assert not passed, result
        assert result in message


@pytest.mark.parametrize("shard_result", ["failure", "cancelled", "success"])
def test_browser_not_required_rejects_any_non_skipped_shard_execution(shard_result):
    passed, message = aggregator.aggregate(
        classify_result="success",
        browser="false",
        shard_result=shard_result,
        **SMOKE,
    )
    assert not passed, shard_result
    assert shard_result in message


@pytest.mark.parametrize("suite_kwargs", [FUNCTIONAL, SMOKE], ids=["functional", "smoke"])
def test_browser_not_required_passes_when_shard_job_skipped(suite_kwargs):
    ok, message = aggregator.aggregate(
        classify_result="success",
        browser="false",
        shard_result="skipped",
        **suite_kwargs,
    )
    assert ok
    assert "not required" in message


@pytest.mark.parametrize("classify_result", ["failure", "cancelled", "skipped"])
@pytest.mark.parametrize("browser", ["true", "false"])
def test_classification_failure_never_passes_the_gate(classify_result, browser):
    passed, message = aggregator.aggregate(
        classify_result=classify_result,
        browser=browser,
        shard_result="skipped" if browser == "false" else "success",
        **FUNCTIONAL,
    )
    assert not passed
    assert classify_result in message


@pytest.mark.parametrize(
    "overrides",
    [
        {"browser": ""},
        {"browser": "TRUE"},
        {"browser": "1"},
        {"browser_suite": ""},
        {"browser_suite": "test:e2e:functional "},
        {"shard_plan": ""},
        {"shard_plan": "[1]"},
        {"shard_plan": "[1,2,3]"},
        {"shard_total": ""},
        {"shard_total": "1"},
        {"classify_result": ""},
        {"classify_result": "SUCCESS"},
        {"shard_result": ""},
    ],
)
def test_missing_or_abnormal_outputs_fail_closed(overrides):
    kwargs = dict(
        classify_result="success",
        browser="true",
        browser_suite="test:e2e:functional",
        shard_plan="[1,2]",
        shard_total="2",
        shard_result="success",
    )
    kwargs.update(overrides)
    passed, _message = aggregator.aggregate(**kwargs)
    assert not passed, overrides


def test_smoke_suite_must_not_expand_to_two_shards():
    passed, message = aggregator.aggregate(
        classify_result="success",
        browser="true",
        browser_suite="test:e2e:smoke",
        shard_plan="[1,2]",
        shard_total="2",
        shard_result="success",
    )
    assert not passed
    assert "test:e2e:smoke" in message


def test_cli_entry_point_exit_codes():
    base = dict(
        CLASSIFY_RESULT="success",
        BROWSER="true",
        BROWSER_SUITE="test:e2e:functional",
        SHARD_PLAN="[1,2]",
        SHARD_TOTAL="2",
    )
    failing = dict(SHARD_RESULT="failure")
    for overrides, expected_code in ((dict(SHARD_RESULT="success"), 0), (failing, 1)):
        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            env={**dict(os.environ), **base, **overrides},
            capture_output=True,
            text=True,
        )
        assert result.returncode == expected_code, result.stderr
