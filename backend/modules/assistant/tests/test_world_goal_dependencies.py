import uuid

import pytest

from app.assistant_operation_registry import (
    assistant_notice_operations,
    world_operations,
    world_validity_operations,
)
from core.container import container_scope
from core.errors import ValidationError
from core.service_keys import ASSISTANT_REQUIRE_OPERATION_TARGETS
from modules.assistant.contracts import AssistantOperationContext
from modules.assistant.goal_runs.contracts import GoalPlan, GoalStep
from modules.assistant.goal_runs.planning import resolve_reference, validate_plan
from modules.assistant.goal_runs.service import _check_step_targets
from modules.assistant.schemas import WorkContext
from modules.world.models import CoreEntity


def test_world_relation_targets_cannot_hide_another_source_or_relation():
    source, target, other = (str(uuid.uuid4()) for _ in range(3))
    operation = world_operations["world.add_relation"]
    step = GoalStep(
        step_id="connect",
        operation_id=operation.op_id,
        parameters={},
        intent="只连接作者选定的两端",
    )
    pairs = [(operation.target_type, source), (operation.target_type, target)]
    _check_step_targets(
        step, operation, {"source_id": source, "target_id": target}, pairs
    )
    with pytest.raises(ValidationError, match="目标范围"):
        _check_step_targets(
            step, operation, {"source_id": other, "target_id": target}, pairs
        )
    maintain = world_validity_operations["world.maintain_relation"]
    step = step.model_copy(update={"operation_id": maintain.op_id})
    with pytest.raises(ValidationError, match="目标范围"):
        _check_step_targets(
            step, maintain, {"relation_id": other}, [(maintain.target_type, source)]
        )


def test_notice_source_category_is_not_mistaken_for_a_world_entity_target():
    operation = assistant_notice_operations["assistant.notice.mute_category"]
    step = GoalStep(
        step_id="mute",
        operation_id=operation.op_id,
        parameters={
            "source_id": "assistant.proactive",
            "category": "review",
            "expected_row_version": 0,
        },
        intent="静默这一类提醒",
    )
    validate_plan(GoalPlan(title="整理提醒", steps=[step]), {operation.op_id: operation})
    _check_step_targets(step, operation, step.parameters, [])


@pytest.mark.asyncio
async def test_created_receipt_is_read_back_before_dependent_relation(
    db_session, test_project_id
):
    from modules.account.facade import current_account_id

    create = world_operations["world.create_entity"]
    connect = world_operations["world.add_relation"]
    ref = {"$ref": {"step_id": "create", "path": ["id"], "value_type": "identifier"}}
    other = CoreEntity(
        novel_id=uuid.UUID(test_project_id),
        entity_type="character",
        name="船医",
        status="canonical",
    )
    db_session.add(other)
    await db_session.flush()
    plan = GoalPlan.model_validate(
        {
            "title": "新建人物并建立关系",
            "steps": [
                {
                    "step_id": "create",
                    "operation_id": create.op_id,
                    "intent": "创建巡港人",
                    "parameters": {"name": "沈砚", "entity_type": "character"},
                },
                {
                    "step_id": "connect",
                    "operation_id": connect.op_id,
                    "depends_on": ["create"],
                    "intent": "连接真实新人物与船医",
                    "parameters": {
                        "source_id": ref,
                        "target_id": str(other.id),
                        "relation_type": "ally_of",
                        "relation_kind": "social",
                    },
                    "targets": [
                        {"target_type": connect.target_type, "target_id": ref["$ref"]},
                        {"target_type": connect.target_type, "target_id": str(other.id)},
                    ],
                },
            ],
        }
    )
    validate_plan(plan, {create.op_id: create, connect.op_id: connect})
    context = AssistantOperationContext(
        owner_id=str(current_account_id()),
        run_id=str(uuid.uuid4()),
        work=WorkContext(page="world", scope="project"),
    )
    args = create.schema.model_validate(plan.steps[0].parameters)
    receipt = await create.apply(
        db_session,
        test_project_id,
        args,
        await create.prepare(db_session, test_project_id, args, context=context),
        context=context,
    )
    parameters = resolve_reference(plan.steps[1].parameters, {"create": receipt})
    assert parameters["source_id"] == receipt["id"] and parameters["target_id"] == str(
        other.id
    )

    async def allowed(_db, novel_id, _context, targets):
        assert novel_id == test_project_id
        assert {str(identity) for _kind, identity in targets} == {
            receipt["id"],
            str(other.id),
        }

    with container_scope({ASSISTANT_REQUIRE_OPERATION_TARGETS: allowed}):
        parsed = connect.schema.model_validate(parameters)
        preview = await connect.prepare(
            db_session, test_project_id, parsed, context=context
        )
        assert (
            preview["after"]["source"] == "沈砚" and preview["after"]["target"] == "船医"
        )
        row = await db_session.get(CoreEntity, uuid.UUID(receipt["id"]))
        row.name = "作者后来改名"
        await db_session.flush()
        from core.errors import ConflictError

        with pytest.raises(ConflictError, match="已变化"):
            await connect.apply(
                db_session, test_project_id, parsed, preview, context=context
            )
