"""Frozen World scenarios cannot disappear or silently change success criteria."""

import pytest

from modules.world.contracts import WorldScenarioCheck


def test_same_scenario_is_required_on_both_versions_and_unknown_cannot_pass():
    value = WorldScenarioCheck(
        verdict="passed",
        scenario_results=[
            {
                "key": "one_key",
                "baseline": "violated",
                "candidate": "holds",
                "baseline_reason": "两人都拿走了唯一钥匙。",
                "candidate_reason": "候选限制了唯一持有者。",
                "source_keys": ["world:one"],
            }
        ],
    )
    scenarios = [{"key": "one_key", "expected": "holds"}]
    assert value.validate_coverage(scenarios, {"world:one"}).verdict == "passed"
    with pytest.raises(ValueError, match="omit"):
        value.validate_coverage([*scenarios, {"key": "price"}], {"world:one"})
    with pytest.raises(ValueError, match="source"):
        value.validate_coverage(scenarios, set())
    unknown = value.model_copy(
        update={
            "scenario_results": [
                value.scenario_results[0].model_copy(update={"candidate": "uncertain"})
            ]
        }
    )
    assert unknown.validate_coverage(scenarios, {"world:one"}).verdict == "uncertain"
    intentional = value.model_copy(
        update={
            "scenario_results": [
                value.scenario_results[0].model_copy(update={"candidate": "violated"})
            ]
        }
    )
    assert (
        intentional.validate_coverage(
            [{"key": "one_key", "expected": "unchanged"}], {"world:one"}
        ).verdict
        == "passed"
    )
