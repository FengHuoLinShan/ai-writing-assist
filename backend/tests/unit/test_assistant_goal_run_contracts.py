"""Strict goal-run plans and scoped Assistant API wiring."""

from uuid import UUID

import pytest
from fastapi.routing import APIRoute
from pydantic import BaseModel

from core.errors import ConflictError, ValidationError
from modules.assistant.contracts import AssistantOperation
from modules.assistant.goal_runs.contracts import (
    GoalBudget,
    GoalPlan,
    GoalReference,
)
from modules.assistant.goal_runs.planning import (
    compare_scope,
    operation_catalog_fingerprint,
    plan_scope,
    resolve_reference,
    step_operation_id,
    validate_plan,
)


class ReadValue(BaseModel):
    target_id: str


class WriteValue(BaseModel):
    target_id: str
    value: str


async def _read(_db, _novel_id, _args, *, context=None):
    return {"value": "x"}


async def _write(_db, _novel_id, _args, _preview, *, context=None):
    return {"id": "receipt"}


def _operations():
    return {
        "project.value.read": AssistantOperation(
            "读取对象",
            ReadValue,
            _read,
            permission="read",
            risk_level="R0",
            target_type="artifact",
        ),
        "project.value.edit": AssistantOperation(
            "修改对象",
            WriteValue,
            _read,
            _write,
            permission="confirm",
            risk_level="R2",
            target_type="artifact",
        ),
    }


def _budget():
    return GoalBudget(
        requests=4,
        possible_charge_requests=4,
        tokens=4096,
        time_limit_seconds=600,
    )


def test_goal_budget_requires_an_explicit_bounded_request_envelope():
    assert _budget().requests == 4
    with pytest.raises(ValueError):
        GoalBudget(
            requests=1,
            possible_charge_requests=1,
            tokens=512,
            time_limit_seconds=60,
        )
    with pytest.raises(ValueError):
        GoalBudget(
            requests=4,
            possible_charge_requests=5,
            tokens=4096,
            time_limit_seconds=600,
        )


def test_plan_accepts_only_registered_steps_and_typed_declared_dependencies():
    operations = _operations()
    plan = GoalPlan.model_validate(
        {
            "title": "读取后更新",
            "steps": [
                {
                    "step_id": "read",
                    "operation_id": "project.value.read",
                    "targets": [{"target_type": "artifact", "target_id": "a-1"}],
                    "parameters": {"target_id": "a-1"},
                    "intent": "读取当前版本",
                },
                {
                    "step_id": "edit",
                    "operation_id": "project.value.edit",
                    "depends_on": ["read"],
                    "targets": [
                        {
                            "target_type": "artifact",
                            "target_id": {
                                "step_id": "read",
                                "path": ["value"],
                                "value_type": "string",
                            },
                        }
                    ],
                    "parameters": {
                        "target_id": {
                            "$ref": {
                                "step_id": "read",
                                "path": ["value"],
                                "value_type": "string",
                            }
                        },
                        "value": "approved",
                    },
                    "intent": "更新作者明确选择的对象",
                },
            ],
        }
    )

    assert validate_plan(plan, operations) is plan

    undeclared_dependency = plan.model_copy(
        update={
            "steps": [
                plan.steps[0],
                plan.steps[1].model_copy(update={"depends_on": []}),
            ]
        }
    )
    with pytest.raises(ValidationError, match="前置步骤"):
        validate_plan(undeclared_dependency, operations)

    unregistered = plan.model_copy(
        update={
            "steps": [
                plan.steps[0],
                plan.steps[1].model_copy(update={"operation_id": "project.anything"}),
            ]
        }
    )
    with pytest.raises(ConflictError, match="不可用"):
        validate_plan(unregistered, operations)


def test_plan_rejects_expressions_and_bounds_array_references():
    operations = _operations()
    expression = GoalPlan.model_validate(
        {
            "title": "表达式应拒绝",
            "steps": [
                {
                    "step_id": "read",
                    "operation_id": "project.value.read",
                    "parameters": {"target_id": "a-1"},
                    "intent": "读取",
                },
                {
                    "step_id": "edit",
                    "operation_id": "project.value.edit",
                    "depends_on": ["read"],
                    "parameters": {"target_id": "a-1", "value": {"$eval": "x"}},
                    "intent": "表达式不可执行",
                },
            ],
        }
    )
    with pytest.raises(ValidationError, match="表达式"):
        validate_plan(expression, operations)

    reference = GoalReference(
        step_id="read",
        path=["ids"],
        value_type="array",
        item_type="identifier",
        max_items=2,
    )
    assert resolve_reference(
        {"$ref": reference.model_dump(mode="json")},
        {"read": {"ids": ["a", "b"]}},
    ) == ["a", "b"]
    with pytest.raises(Exception, match="类型"):
        resolve_reference(
            {"$ref": reference.model_dump(mode="json")},
            {"read": {"ids": ["a", "b", "c"]}},
        )


def test_replan_scope_comparison_is_deterministic_and_fail_closed():
    operations = _operations()
    budget = _budget()
    plan = GoalPlan.model_validate(
        {
            "title": "同一范围",
            "steps": [
                {
                    "step_id": "read-a",
                    "operation_id": "project.value.read",
                    "targets": [{"target_type": "artifact", "target_id": "a"}],
                    "parameters": {"target_id": "a"},
                    "intent": "读取 A",
                }
            ],
        }
    )
    fingerprint = operation_catalog_fingerprint(operations)
    scope = plan_scope(
        plan,
        operations,
        budget,
        auto_r2=False,
        catalog_fingerprint=fingerprint,
    )
    renamed_step = plan.model_copy(
        update={
            "steps": [
                plan.steps[0].model_copy(update={"step_id": "read-b"}),
            ]
        }
    )
    renamed_scope = plan_scope(
        renamed_step,
        operations,
        budget,
        auto_r2=False,
        catalog_fingerprint=fingerprint,
    )
    assert compare_scope(renamed_scope, scope) == []

    expanded = dict(scope)
    expanded["targets"] = [*scope["targets"], '"target_id":"b"']
    assert "new_target" in compare_scope(expanded, scope)
    new_module = {
        **scope,
        "operation_ids": [*scope["operation_ids"], "story.structure.inspect"],
        "modules": [*scope["modules"], "story"],
    }
    expansion = compare_scope(new_module, scope)
    assert expansion.count("new_module") == 1
    assert compare_scope({}, scope) == ["unknown_scope"]


def test_step_operation_id_is_stable_uuid5_from_run_step_and_parameters():
    run_id = "53f22760-e1e5-43c5-9261-63953d52c71a"
    left = step_operation_id(run_id, "edit", "a" * 64)
    assert left == step_operation_id(run_id, "edit", "a" * 64)
    assert left != step_operation_id(run_id, "edit", "b" * 64)
    assert UUID(left).version == 5


def test_plan_field_projection_localizes_enum_values_and_locks_unknown_options():
    from modules.assistant.goal_runs.service import _parameter_fields

    fields = _parameter_fields(
        {
            "$defs": {"Decision": {"type": "string", "enum": ["adopt", "reject"]}},
            "properties": {
                "action": {"type": "string", "enum": ["adopt", "reject"]},
                "private_mode": {"type": "string", "enum": ["internal_only"]},
                "nested": {
                    "type": "object",
                    "properties": {"action": {"$ref": "#/$defs/Decision"}},
                },
            },
        },
        {
            "action": "adopt",
            "private_mode": "internal_only",
            "nested": {"action": "reject"},
        },
    )
    by_name = {field["name"]: field for field in fields}

    assert by_name["action"]["enum_options"] == [
        {"value": "adopt", "label": "采用"},
        {"value": "reject", "label": "拒绝"},
    ]
    assert by_name["action"]["editable"] is True
    assert by_name["private_mode"]["enum_options"] == []
    assert by_name["private_mode"]["editable"] is False
    assert by_name["private_mode"]["locked_reason"]
    assert by_name["nested"]["children"][0]["enum_options"][1]["label"] == "拒绝"


def test_goal_routes_are_mounted_under_the_assistant_prefix_with_write_exemptions():
    from app.main import app

    def route_entries(routes, prefix=""):
        for route in routes:
            if isinstance(route, APIRoute):
                yield f"{prefix}{route.path}", route
                continue
            nested = getattr(route, "original_router", None)
            if nested is not None:
                context = getattr(route, "include_context", None)
                nested_prefix = str(getattr(context, "prefix", "") or "")
                yield from route_entries(nested.routes, prefix + nested_prefix)

    goals = {
        path: route
        for path, route in route_entries(app.routes)
        if path.startswith("/api/assistant/goals")
    }
    assert "/api/assistant/goals" in goals
    assert "/api/assistant/goals/{run_id}/advance" in goals
    assert not any("/api/assistant/api/assistant/goals" in path for path in goals)
    for path, route in goals.items():
        if "POST" in route.methods and path not in {
            "/api/assistant/goals/capabilities",
            "/api/assistant/goals/active",
        }:
            assert route.openapi_extra["x-novelcraft-operation-exemption"]
