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


def test_paid_story_goal_steps_use_registered_exact_child_capabilities():
    # Importing the owning task handlers registers their canonical root IDs.
    import modules.story.tasks  # noqa: F401
    from app.assistant_operation_registry import story_generation_operations
    from infrastructure.tasks.registry import TaskRegistry
    from modules.assistant.goal_runs.service import (
        TASK_OPERATION_TYPES,
        _assert_plan_operations_supported,
        _scope_capabilities,
    )

    expected = {
        "story.character_card.generate": (
            "story_character_card_generate",
            "story.character_card",
        ),
        "story.reaction.generate": ("story_reaction_propose", "story.reaction"),
    }
    steps = []
    for index, (operation_id, (task_type, capability)) in enumerate(expected.items()):
        assert TASK_OPERATION_TYPES[operation_id] == task_type
        assert TaskRegistry().get_root_capability(task_type) == capability
        steps.append(
            {
                "step_id": f"paid_{index}",
                "operation_id": operation_id,
                "parameters": {},
                "intent": "生成仅供审阅的候选",
            }
        )
    plan = GoalPlan.model_validate({"title": "来源预览", "steps": steps})
    _assert_plan_operations_supported(plan, story_generation_operations)
    assert _scope_capabilities(plan, story_generation_operations) == [
        "assistant.goal.plan",
        "story.character_card",
        "story.reaction",
    ]


def test_goal_planner_sees_only_operations_that_execution_can_authorize():
    from app.bootstrap import _container_services
    from app.task_runtime import register_task_handlers
    from core.service_keys import ASSISTANT_OPERATIONS
    from modules.assistant.goal_runs.service import (
        _assert_plan_operations_supported,
        _goal_planning_catalog,
    )

    register_task_handlers()
    operations = dict(_container_services())[ASSISTANT_OPERATIONS]
    available, unavailable = _goal_planning_catalog(operations)
    offered = {item["operation_id"] for item in available}
    omitted = {item["operation_id"]: item["reason"] for item in unavailable}

    assert "story.character_card.generate" in offered
    assert "story.reaction.generate" in offered
    assert "writing.generate_candidate" in offered
    assert "story.plan_structure" in omitted  # model fee without a goal task
    assert "evidence.focused_search" in omitted  # separate R4 authorization
    assert "imports.organize" in omitted
    assert all(omitted.values())
    assert offered.isdisjoint(omitted)
    for operation_id in offered:
        plan = GoalPlan.model_validate(
            {
                "title": "执行能力重验",
                "steps": [
                    {
                        "step_id": "step",
                        "operation_id": operation_id,
                        "parameters": {},
                        "intent": "只验证目录能力",
                    }
                ],
            }
        )
        _assert_plan_operations_supported(plan, operations)

    complex_schema = next(
        item["parameter_schema"]
        for item in available
        if item["operation_id"] == "world.dossier.entry.edit"
    )
    assert complex_schema["required"]
    assert complex_schema["$defs"]["DossierEntryUpdate"]["required"] == [
        "expected_revision_id"
    ]


@pytest.mark.parametrize(
    ("operation_id", "character_key"),
    [
        ("story.character_card.generate", "character_id"),
        ("story.reaction.generate", "character_ids"),
    ],
)
def test_paid_story_goal_scope_freezes_scene_and_every_character(
    operation_id, character_key
):
    from app.assistant_operation_registry import story_generation_operations
    from modules.assistant.goal_runs.service import _check_step_targets

    scene_id = "00000000-0000-4000-8000-000000000001"
    character_ids = [
        "00000000-0000-4000-8000-000000000002",
        "00000000-0000-4000-8000-000000000003",
    ]
    participants = character_ids[:1] if character_key == "character_id" else character_ids
    character_value = participants[0] if character_key == "character_id" else participants
    parameters = {
        "scene_id": scene_id,
        character_key: character_value,
    }
    target_pairs = [("outline_scene", scene_id)] + [
        ("core_entity", item) for item in participants
    ]
    plan = GoalPlan.model_validate(
        {
            "title": "候选预览",
            "steps": [
                {
                    "step_id": "generate",
                    "operation_id": operation_id,
                    "parameters": parameters,
                    "targets": [
                        {"target_type": kind, "target_id": target}
                        for kind, target in target_pairs
                    ],
                    "intent": "审阅当前场景和人物的候选",
                }
            ],
        }
    )
    operation = story_generation_operations[operation_id]
    validate_plan(plan, story_generation_operations)
    _check_step_targets(plan.steps[0], operation, parameters, target_pairs)
    for narrowed in (target_pairs[1:], target_pairs[:-1]):
        with pytest.raises(ValidationError, match="精确列出"):
            _check_step_targets(plan.steps[0], operation, parameters, narrowed)
    with pytest.raises(ValidationError, match="精确列出"):
        _check_step_targets(
            plan.steps[0],
            operation,
            parameters,
            target_pairs + [("core_entity", scene_id)],
        )
    wrong_kind = plan.model_copy(
        update={
            "steps": [
                plan.steps[0].model_copy(
                    update={
                        "targets": [
                            plan.steps[0]
                            .targets[0]
                            .model_copy(update={"target_type": "story_character_card"}),
                            *plan.steps[0].targets[1:],
                        ]
                    }
                )
            ]
        }
    )
    with pytest.raises(ValidationError, match="目标类型"):
        validate_plan(wrong_kind, story_generation_operations)


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
    with pytest.raises(ValueError):
        GoalBudget(
            requests=2,
            possible_charge_requests=1,
            tokens=4096,
            time_limit_seconds=600,
        )


def test_goal_large_schema_is_rejected_before_provider_reservation():
    from uuid import uuid4

    from infrastructure.llm.schemas import LLMMessage
    from infrastructure.llm.workflow_budget import new_ai_run_envelope
    from modules.assistant.goal_runs.service import (
        GoalPlanningScopeError,
        _goal_prompt_token_limit,
    )

    budget = GoalBudget(
        requests=2,
        possible_charge_requests=2,
        tokens=12000,
        time_limit_seconds=600,
    )
    envelope = new_ai_run_envelope(
        operation_id=str(uuid4()),
        run_id=str(uuid4()),
        root_capability_id="assistant.goal.run",
        novel_id=str(uuid4()),
        request_limit=budget.requests,
        token_limit=budget.tokens,
        budget_mode="goal",
        scope_fingerprint="a" * 64,
        authorized_step_capabilities=["assistant.goal.plan"],
    )
    with pytest.raises(GoalPlanningScopeError, match="缩小范围或增加预算"):
        _goal_prompt_token_limit(
            [LLMMessage(role="user", content="完整目录" * 3000)],
            envelope,
            budget,
            {"profile": {"model": "gpt-6-luna", "max_tokens": 8192}},
            minimum_output=512,
            maximum_output=8000,
        )
    allowed = _goal_prompt_token_limit(
        [LLMMessage(role="user", content="短目标")],
        envelope,
        budget,
        {"profile": {"model": "gpt-6-luna", "max_tokens": 1024}},
        minimum_output=512,
        maximum_output=8000,
    )
    assert allowed == 1024
    with pytest.raises(GoalPlanningScopeError, match="冻结输出上限"):
        _goal_prompt_token_limit(
            [LLMMessage(role="user", content="短目标")],
            envelope,
            budget,
            {"profile": {"model": "gpt-6-luna"}},
            minimum_output=512,
            maximum_output=8000,
        )
    assert envelope.snapshot().requests_started == 0


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
