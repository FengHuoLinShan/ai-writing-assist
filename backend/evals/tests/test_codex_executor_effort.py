"""codex executor reasoning effort 允许集回归。"""

import pytest

from evals.codex_executor import CodexStructuredExecutor


@pytest.mark.parametrize("effort", [None, "low", "medium", "high", "xhigh", "max"])
def test_codex_executor_accepts_official_efforts(effort):
    executor = CodexStructuredExecutor(
        model="gpt-5.6-luna",
        reasoning_effort=effort,
        command="codex",
    )
    # Luna 未显式指定 effort 时回退其专属默认 medium。
    assert executor.reasoning_effort == (effort or "medium")


def test_codex_executor_rejects_unknown_effort():
    with pytest.raises(ValueError, match="unsupported eval reasoning effort"):
        CodexStructuredExecutor(
            model="gpt-5.6-luna",
            reasoning_effort="ultra",
            command="codex",
        )
