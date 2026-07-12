"""Compatibility tests for the old imports LLM step harness path."""

from __future__ import annotations

from infrastructure.llm import agent_step_harness as shared_harness
from modules.imports import agent_step_harness as imports_harness


def test_imports_agent_step_harness_reexports_shared_objects() -> None:
    assert imports_harness.AgentPermissionLevel is shared_harness.AgentPermissionLevel
    assert imports_harness.ContextBudget is shared_harness.ContextBudget
    assert imports_harness.ContextBudgetGuard is shared_harness.ContextBudgetGuard
    assert imports_harness.ManagedLLMStep is shared_harness.ManagedLLMStep
    assert imports_harness.OutputGuard is shared_harness.OutputGuard
    assert imports_harness.StepToolEnvelope is shared_harness.StepToolEnvelope
    assert imports_harness.run_managed_generate is shared_harness.run_managed_generate
    assert imports_harness.run_managed_structured is shared_harness.run_managed_structured
