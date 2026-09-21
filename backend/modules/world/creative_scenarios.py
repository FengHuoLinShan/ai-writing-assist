"""World-owned checks run the same frozen conditions against both rule versions."""

from typing import ClassVar, Literal

from pydantic import Field

from modules.collaboration.contracts import CheckOutput, StrictModel


class ScenarioOutcome(StrictModel):
    key: str
    baseline: Literal["holds", "violated", "uncertain"]
    candidate: Literal["holds", "violated", "uncertain"]
    baseline_reason: str = Field(min_length=1, max_length=1500)
    candidate_reason: str = Field(min_length=1, max_length=1500)
    source_keys: list[str] = Field(min_length=1, max_length=12)


class WorldScenarioCheck(CheckOutput):
    instruction: ClassVar[str] = (
        "对原规则与试改规则重测完全相同的已冻结情境。不得换掉动作、假设或不变量。"
        "逐项说明原版和候选版是否满足不变量以及依据；缺少前提必须 uncertain。"
        "按冻结的 expected 检查，unchanged 保留作者有意安排；不强行修掉文学选择。"
        "只在原问题确有改善且保留其他规则时通过；这是语义检验，不是形式证明。"
    )
    scenario_results: list[ScenarioOutcome] = Field(min_length=1, max_length=8)

    def validate_coverage(self, scenarios, source_keys):
        expected = {value["key"] for value in scenarios}
        actual = {value.key for value in self.scenario_results}
        if actual != expected or len(actual) != len(self.scenario_results):
            raise ValueError(
                "World scenario checks cannot replace or omit a frozen scenario"
            )
        if any(set(value.source_keys) - source_keys for value in self.scenario_results):
            raise ValueError("World scenario checks need actual source references")
        requirements = {
            value["key"]: value.get("expected", "holds") for value in scenarios
        }
        if (
            any(
                value.candidate == "uncertain"
                or value.candidate
                != (
                    value.baseline
                    if requirements[value.key] == "unchanged"
                    else requirements[value.key]
                )
                for value in self.scenario_results
            )
            and self.verdict == "passed"
        ):
            return self.model_copy(
                update={
                    "verdict": "uncertain",
                    "omissions": [*self.omissions, "部分冻结情境仍未证明满足要求。"],
                }
            )
        return self
