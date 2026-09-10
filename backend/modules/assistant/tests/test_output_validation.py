import json
from types import SimpleNamespace

import pytest

from core.container import container_scope
from infrastructure.llm.agent_runtime import AgentRunBudget, run_project_agent
from infrastructure.llm.schemas import (
    LLMCallRequest,
    LLMCallResponse,
    LLMMessage,
    LLMToolCall,
    LLMUsage,
)
from modules.assistant.operations import (
    operation_manifest,
    resolve_operations,
    validate_agent_answer,
)
from modules.assistant.schemas import AssistantAnswer
from modules.project.assistant_tools import OPERATIONS


def test_verified_issue_must_reference_an_existing_domain_finding():
    from pydantic_ai import ModelRetry

    ctx = SimpleNamespace(
        deps=SimpleNamespace(operations={}, evidence_refs={"read": {"text": "原文"}})
    )
    answer = AssistantAnswer(
        answer="有一处待核对",
        findings=[
            {
                "kind": "issue",
                "title": "问题",
                "summary": "待核对",
                "evidence_ids": ["read"],
                "domain_finding_id": "finding-1",
            }
        ],
    )
    with pytest.raises(ModelRetry, match="领域复核"):
        validate_agent_answer(ctx, answer)
    ctx.deps.evidence_refs["read"] = {
        "domain_reference": {"type": "writing_review"},
        "review_result": {"findings": [{"finding_id": "finding-1"}]},
    }
    assert validate_agent_answer(ctx, answer) == answer


def test_frozen_operation_scope_rejects_new_tools_and_changed_revisions():
    from dataclasses import replace

    from pydantic_ai import ModelRetry

    from core.errors import ConflictError

    with container_scope({"assistant.operations": dict(OPERATIONS)}):
        manifest = operation_manifest()
        operations = resolve_operations(manifest)
        ctx = SimpleNamespace(
            deps=SimpleNamespace(evidence_refs={}, operations=operations)
        )
        answer = AssistantAnswer(
            answer="准备修改",
            actions=[
                {
                    "key": "later",
                    "capability": "project.future_tool",
                    "title": "未授权能力",
                }
            ],
        )
        with pytest.raises(ModelRetry):
            validate_agent_answer(ctx, answer)
    changed = {key: replace(op, revision="2") for key, op in OPERATIONS.items()}
    with container_scope({"assistant.operations": changed}):
        with pytest.raises(ConflictError):
            resolve_operations(manifest)


@pytest.mark.asyncio
async def test_invalid_domain_arguments_are_corrected_once_inside_sdk_budget():
    class Client:
        model_name = "deepseek-v4-flash"
        calls = 0

        async def generate(self, request, *, transport_retries):
            assert transport_retries is False
            self.calls += 1
            output = next(
                tool
                for tool in request.tools
                if "answer" in tool.parameters.get("properties", {})
            )
            value = {
                "answer": "已准备待办方案",
                "actions": [
                    {
                        "key": "todo",
                        "capability": "project.add_task",
                        "title": "核对年龄",
                        "arguments": {
                            "title": "核对年龄",
                            "due_date": "sometime" if self.calls == 1 else "2026-09-11",
                        },
                    }
                ],
            }
            return LLMCallResponse(
                tool_calls=[
                    LLMToolCall(
                        id=f"reply-{self.calls}",
                        name=output.name,
                        arguments=json.dumps(value, ensure_ascii=False),
                    )
                ],
                usage=LLMUsage(prompt_tokens=10, completion_tokens=3, total_tokens=13),
            )

    client, budget = Client(), AgentRunBudget()
    with container_scope({"assistant.operations": OPERATIONS}):
        result = await run_project_agent(
            client,
            LLMCallRequest(messages=[LLMMessage(content="明天提醒我核对年龄")]),
            tools=[],
            deps=SimpleNamespace(evidence_refs={}, operations=None),
            output_type=AssistantAnswer,
            output_validator=validate_agent_answer,
            budget=budget,
            input_limit=8000,
        )
    assert client.calls == budget.requests == 2
    assert result.output.actions[0].arguments["due_date"] == "2026-09-11"
    assert budget.usage_complete
