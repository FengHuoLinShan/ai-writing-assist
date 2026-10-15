import json
from types import SimpleNamespace

import pytest

from app.assistant_operation_registry import project_operations
from core.container import container_scope
from infrastructure.llm.agent_runtime import AgentRunBudget, run_project_agent
from infrastructure.llm.schemas import (
    LLMCallRequest,
    LLMCallResponse,
    LLMMessage,
    LLMToolCall,
    LLMUsage,
)
from modules.assistant.contracts import AssistantOperation
from modules.assistant.operations import (
    operation_manifest,
    resolve_operations,
    runtime_protocol,
    validate_agent_answer,
)
from modules.assistant.schemas import AssistantAnswer


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

    with container_scope({"assistant.operations": dict(project_operations)}):
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
    changed = {key: replace(op, revision="2") for key, op in project_operations.items()}
    with container_scope({"assistant.operations": changed}):
        with pytest.raises(ConflictError):
            resolve_operations(manifest)


def test_runtime_v6_is_a_fresh_frozen_operation_directory():
    payload = {"runtime_version": "6", "operations": {}, "read_tools": {}}
    assert runtime_protocol(payload) == payload


def test_runtime_v4_freezes_new_operations_without_widening_old_manifests():
    from modules.world.assistant_vocabulary_tools import OPERATIONS_SPEC

    operation = AssistantOperation(
        label=OPERATIONS_SPEC["world.vocabulary.create"]["label"],
        schema=OPERATIONS_SPEC["world.vocabulary.create"]["schema"],
        prepare=OPERATIONS_SPEC["world.vocabulary.create"]["prepare"],
        apply=OPERATIONS_SPEC["world.vocabulary.create"]["apply"],
    )
    with container_scope({"assistant.operations": dict(project_operations)}):
        old_manifest = operation_manifest(legacy=True)
    with container_scope(
        {
            "assistant.operations": {
                **project_operations,
                "world.vocabulary.create": operation,
            }
        }
    ):
        new_manifest = operation_manifest(legacy=True)
        assert "world.vocabulary.create" not in resolve_operations(old_manifest)
        assert "world.vocabulary.create" in resolve_operations(new_manifest)
        payload = {"runtime_version": "4", "operations": new_manifest}
        assert runtime_protocol(payload) is payload


@pytest.mark.parametrize(
    "schema_hash,interior",
    [
        ("afb6aa06a68c39a27026fc50565cdc87d72e266e569b362d95fdd23a428c2bc8", False),
        ("061686f1c3f683f833a391f1515de6fea596a0403a38f357390d53b5bc54e5e7", True),
    ],
)
def test_frozen_map_node_schema_keeps_original_fields(schema_hash, interior):
    from uuid import uuid4

    from pydantic import ValidationError

    from app.assistant_operation_registry import world_map_operations
    from modules.assistant.evidence_tools import fingerprint

    with container_scope({"assistant.operations": world_map_operations}):
        resolved = resolve_operations(
            {"map.create_node": {"schema_hash": schema_hash, "revision": "1"}}
        )
        schema = resolved["map.create_node"].schema
        assert fingerprint(schema.model_json_schema()) == schema_hash
        assert schema.model_validate({"title": "旧运行"}).title == "旧运行"
        with pytest.raises(ValidationError):
            schema.model_validate(
                {
                    "title": "旧运行",
                    "level_type_ref": str(uuid4()),
                    "level_type_revision_id": str(uuid4()),
                }
            )
        if interior:
            assert (
                schema.model_validate({"title": "室内", "level": "interior"}).level
                == "interior"
            )
        else:
            with pytest.raises(ValidationError):
                schema.model_validate({"title": "室内", "level": "interior"})


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
    with container_scope({"assistant.operations": project_operations}):
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


def test_new_merge_operation_does_not_widen_frozen_v6_runs():
    from app.assistant_operation_registry import world_map_operations

    old = {
        name: operation
        for name, operation in world_map_operations.items()
        if name != "map.merge_nodes"
    }
    with container_scope({"assistant.operations": old}):
        frozen = {
            "runtime_version": "6",
            "operations": operation_manifest(legacy=True),
            "read_tools": {},
        }
    with container_scope({"assistant.operations": dict(world_map_operations)}):
        restored = resolve_operations(runtime_protocol(frozen)["operations"])
        fresh = operation_manifest(legacy=True)
    assert "map.merge_nodes" not in restored
    assert "map.preview_node_merge" in restored
    assert fresh["map.merge_nodes"] == {
        "revision": "2",
        "schema_hash": "2c04c4b212a0dda6e4c71a0dd64688599bd566b9c9e3cdad9d8922c088cecce9",
    }
    assert (
        fresh["map.preview_node_merge"] == frozen["operations"]["map.preview_node_merge"]
    )


def test_legacy_run_manifest_stays_two_fields_and_replays_after_v7_catalog():
    from app.assistant_operation_registry import world_map_operations

    with container_scope({"assistant.operations": dict(world_map_operations)}):
        legacy = operation_manifest(legacy=True)
        fresh = operation_manifest()
        restored = resolve_operations(legacy)
    assert set(legacy["map.merge_nodes"]) == {"schema_hash", "revision"}
    assert set(fresh["map.merge_nodes"]) == {
        "schema_hash",
        "revision",
        "op_version",
        "metadata_hash",
        "metadata",
        "schema",
    }
    assert restored["map.merge_nodes"].schema.model_fields.keys() == (
        world_map_operations["map.merge_nodes"].schema.model_fields.keys()
    )
    assert restored["map.prepare_tray_placement"].permission == "confirm"
    with container_scope({"assistant.operations": dict(world_map_operations)}):
        assert (
            resolve_operations(operation_manifest())[
                "map.prepare_tray_placement"
            ].permission
            == "read"
        )


def test_v7_frozen_operation_can_be_described_but_not_executed_after_change():
    from dataclasses import replace
    from types import SimpleNamespace

    from modules.assistant.operations import describe_operation

    original = dict(project_operations)
    with container_scope({"assistant.operations": original}):
        frozen = operation_manifest()
    changed = {
        **original,
        "project.add_task": replace(
            original["project.add_task"], description="用途已变化"
        ),
    }
    with container_scope({"assistant.operations": changed}):
        executable = resolve_operations(frozen, allow_stale=True)
        ctx = SimpleNamespace(
            deps=SimpleNamespace(
                operations=executable,
                operation_catalog_snapshot=frozen,
            )
        )
        description = __import__("asyncio").run(
            describe_operation(ctx, "project.add_task")
        )
    assert "project.add_task" not in executable
    assert "project.update_task" in executable
    assert description["executable"] is False
    assert description["unavailable_reason"] == "操作已下线或已变更"
    assert description["schema"] == frozen["project.add_task"]["schema"]


def test_find_operations_is_small_and_never_embeds_schema():
    from types import SimpleNamespace

    from modules.assistant.operations import find_operations

    with container_scope({"assistant.operations": dict(project_operations)}):
        operations = resolve_operations(operation_manifest())
        ctx = SimpleNamespace(
            deps=SimpleNamespace(
                operations=operations,
                operation_catalog_snapshot=operation_manifest(),
            )
        )
        result = __import__("asyncio").run(find_operations(ctx, query="待办"))
    assert len(result["operations"]) <= 8
    assert all("schema" not in item for item in result["operations"])


def test_read_operation_only_calls_prepare_never_apply():
    import asyncio
    from types import SimpleNamespace

    from pydantic import BaseModel

    from modules.assistant.operations import read_operation
    from modules.assistant.schemas import WorkContext

    class Args(BaseModel):
        value: str

    calls = []

    async def guard():
        return None

    async def prepare(_db, _novel_id, args, *, context):
        calls.append(args.value)
        return {"status": "read"}

    async def apply(*_args, **_kwargs):
        raise AssertionError("read_operation must never invoke apply")

    operation = AssistantOperation(
        "读取示例", Args, prepare, apply, permission="read", risk_level="R0"
    )
    ctx = SimpleNamespace(
        deps=SimpleNamespace(
            guard=guard,
            operations={"sample.read": operation},
            operation_catalog_snapshot={},
            run_id="run",
            session_id=None,
            owner_id="owner",
            work=WorkContext(),
            operation_trace_enabled=False,
            db=object(),
            novel_id="novel",
        )
    )
    assert asyncio.run(read_operation(ctx, "sample.read", {"value": "safe"})) == {
        "status": "read"
    }
    assert calls == ["safe"]
