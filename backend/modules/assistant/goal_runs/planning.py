"""Deterministic plan validation and scope comparison for goal runs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from core.errors import ConflictError, ValidationError
from modules.assistant.contracts import AssistantOperation
from modules.assistant.goal_runs.contracts import (
    GoalBudget,
    GoalPlan,
    GoalReference,
)

MAX_PLAN_STEPS = 30
MAX_PLAN_BYTES = 96_000
MAX_REFERENCE_ITEMS = 20
_RISK_ORDER = {f"R{index}": index for index in range(5)}
_SOURCE_TARGET_TYPES = {
    "story.character_card.generate": ("outline_scene", "core_entity"),
    "story.reaction.generate": ("outline_scene", "core_entity"),
}


def goal_target_types(
    operation_id: str, operation: AssistantOperation
) -> tuple[str, ...]:
    """The source objects an approved goal step may read or act upon."""
    return _SOURCE_TARGET_TYPES.get(operation_id, (operation.target_type,))


def canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def operation_catalog_fingerprint(
    operations: Mapping[str, AssistantOperation],
) -> str:
    rows = []
    for operation_id, operation in sorted(operations.items()):
        if not operation.ai_available:
            continue
        rows.append(
            {
                "op_id": operation_id,
                "revision": operation.revision,
                "version": operation.op_version,
                "schema": operation.schema.model_json_schema(),
                "risk": operation.risk_level,
                "fee": operation.fee_category,
                "reversibility": operation.reversibility,
                "preconditions": list(operation.preconditions),
                "produces": list(operation.produces),
                "target_type": operation.target_type,
                "goal_target_types": list(goal_target_types(operation_id, operation)),
                "transaction_mode": operation.transaction_mode,
            }
        )
    return digest(rows)


def module_for(operation_id: str) -> str:
    return operation_id.split(".", maxsplit=1)[0]


def _references(value: Any) -> list[GoalReference]:
    found: list[GoalReference] = []
    if isinstance(value, dict):
        if "$ref" in value:
            if set(value) != {"$ref"}:
                raise ValidationError("步骤引用不能附带表达式或额外字段")
            try:
                found.append(GoalReference.model_validate(value["$ref"]))
            except Exception as error:
                raise ValidationError("步骤引用格式不正确") from error
            return found
        if any(key in value for key in ("$eval", "eval", "expression", "$each")):
            raise ValidationError("计划只允许类型化引用，不允许表达式或任意展开")
        for child in value.values():
            found.extend(_references(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_references(child))
    return found


def _validate_reference_graph(plan: GoalPlan) -> None:
    by_id = {step.step_id: step for step in plan.steps}
    if len(by_id) != len(plan.steps):
        raise ValidationError("步骤标识重复")
    for step in plan.steps:
        if len(set(step.depends_on)) != len(step.depends_on):
            raise ValidationError("同一步骤不能重复列出前置步骤")
        if step.step_id in step.depends_on:
            raise ValidationError("步骤不能依赖自身")
        if set(step.depends_on) - by_id.keys():
            raise ValidationError("计划引用了不存在的前置步骤")
        references = _references(step.parameters)
        references.extend(
            target.target_id
            for target in step.targets
            if isinstance(target.target_id, GoalReference)
        )
        for reference in references:
            if reference.step_id not in by_id:
                raise ValidationError("参数引用了不存在的前置步骤")
            if reference.step_id not in step.depends_on:
                raise ValidationError("参数引用必须同时声明为前置步骤")
    remaining = set(by_id)
    complete: set[str] = set()
    while remaining:
        ready = {
            step_id for step_id in remaining if set(by_id[step_id].depends_on) <= complete
        }
        if not ready:
            raise ValidationError("步骤依赖存在循环")
        complete.update(ready)
        remaining.difference_update(ready)


def _assert_json_size(plan: GoalPlan) -> None:
    encoded = canonical(plan.model_dump(mode="json"))
    if len(encoded.encode("utf-8")) > MAX_PLAN_BYTES:
        raise ValidationError("计划内容过大，请减少步骤或参数")


def validate_plan(
    plan: GoalPlan,
    operations: Mapping[str, AssistantOperation],
    *,
    validate_parameters: bool = True,
) -> GoalPlan:
    if len(plan.steps) > MAX_PLAN_STEPS:
        raise ValidationError("一次目标最多包含 30 个步骤")
    _assert_json_size(plan)
    _validate_reference_graph(plan)
    for step in plan.steps:
        operation = operations.get(step.operation_id)
        if operation is None or not operation.ai_available:
            raise ConflictError("计划包含当前不可用的操作，请重新规划")
        if operation.permission == "read" and operation.risk_level != "R0":
            raise ConflictError("目录只读操作的风险声明已变化")
        if operation.permission == "suggest" and operation.risk_level != "R1":
            raise ConflictError("目录建议操作的风险声明已变化")
        if operation.permission == "confirm" and operation.risk_level == "R0":
            raise ConflictError("目录确认操作的风险声明已变化")
        allowed_target_types = goal_target_types(step.operation_id, operation)
        if any(target.target_type not in allowed_target_types for target in step.targets):
            raise ValidationError("目标类型与操作目录不一致")
        if validate_parameters and not _references(step.parameters):
            try:
                operation.schema.model_validate(step.parameters)
            except Exception as error:
                raise ValidationError(
                    f"「{operation.label}」的参数不符合操作要求"
                ) from error
        if operation.permission == "read" and operation.apply is not None:
            raise ConflictError("目录只读操作不能声明写入回调")
        if operation.permission != "read" and operation.apply is None:
            raise ConflictError("目录操作缺少执行回调")
        if operation.transaction_mode == "multi_stage" and operation.read_result is None:
            raise ConflictError("多阶段操作缺少领域回执接口，不能进入目标计划")
    return plan


def _target_key(target_type: str, target_id: Any) -> str:
    if isinstance(target_id, GoalReference):
        return canonical(
            {
                "target_type": target_type,
                "reference": target_id.model_dump(mode="json"),
            }
        )
    return canonical({"target_type": target_type, "target_id": str(target_id)})


def plan_scope(
    plan: GoalPlan,
    operations: Mapping[str, AssistantOperation],
    budget: GoalBudget,
    *,
    auto_r2: bool,
    catalog_fingerprint: str,
) -> dict[str, Any]:
    operation_ids = sorted({step.operation_id for step in plan.steps})
    modules = sorted({module_for(operation_id) for operation_id in operation_ids})
    risks = [operations[item].risk_level for item in operation_ids]
    targets = sorted(
        _target_key(target.target_type, target.target_id)
        for step in plan.steps
        for target in step.targets
    )
    return {
        "operation_ids": operation_ids,
        "modules": modules,
        "targets": targets,
        "max_risk": max(risks, key=_RISK_ORDER.__getitem__),
        "budget": budget.model_dump(mode="json"),
        "auto_r2": bool(auto_r2),
        "catalog_fingerprint": catalog_fingerprint,
    }


def compare_scope(proposed: dict[str, Any], approved: dict[str, Any]) -> list[str]:
    """Return deterministic expansion reasons; model judgments are never read."""
    reasons: list[str] = []
    required = {
        "operation_ids",
        "modules",
        "targets",
        "max_risk",
        "budget",
        "auto_r2",
        "catalog_fingerprint",
    }
    if not required <= proposed.keys() or not required <= approved.keys():
        return ["unknown_scope"]
    if not all(
        isinstance(value, list)
        for value in (
            proposed["operation_ids"],
            proposed["modules"],
            proposed["targets"],
            approved["operation_ids"],
            approved["modules"],
            approved["targets"],
        )
    ):
        return ["unknown_scope"]
    if (
        proposed.get("max_risk") not in _RISK_ORDER
        or approved.get("max_risk") not in _RISK_ORDER
    ):
        reasons.append("unknown_risk")
    if not isinstance(proposed.get("auto_r2"), bool) or not isinstance(
        approved.get("auto_r2"), bool
    ):
        reasons.append("unknown_auto_limit")
    if not set(proposed.get("operation_ids", ())) <= set(
        approved.get("operation_ids", ())
    ):
        reasons.append("new_operation")
    if not set(proposed.get("modules", ())) <= set(approved.get("modules", ())):
        reasons.append("new_module")
    if not set(proposed.get("targets", ())) <= set(approved.get("targets", ())):
        reasons.append("new_target")
    if _RISK_ORDER.get(proposed.get("max_risk"), 99) > _RISK_ORDER.get(
        approved.get("max_risk"), -1
    ):
        reasons.append("higher_risk")
    proposed_budget = proposed.get("budget") or {}
    approved_budget = approved.get("budget") or {}
    for key in (
        "requests",
        "possible_charge_requests",
        "tokens",
        "time_limit_seconds",
    ):
        try:
            if int(proposed_budget[key]) > int(approved_budget[key]):
                reasons.append("larger_budget")
                break
        except (KeyError, TypeError, ValueError):
            reasons.append("unknown_budget")
            break
    if proposed.get("auto_r2") and not approved.get("auto_r2"):
        reasons.append("higher_auto_limit")
    if proposed.get("catalog_fingerprint") != approved.get("catalog_fingerprint"):
        reasons.append("catalog_changed")
    return reasons


def resolve_reference(value: Any, results: Mapping[str, Any]) -> Any:
    if isinstance(value, dict) and "$ref" in value:
        reference = GoalReference.model_validate(value["$ref"])
        if reference.step_id not in results:
            raise ConflictError("前置步骤尚无可用产物")
        current: Any = results[reference.step_id]
        for part in reference.path:
            if isinstance(part, str) and isinstance(current, Mapping) and part in current:
                current = current[part]
            elif (
                isinstance(part, int)
                and isinstance(current, list)
                and part < len(current)
            ):
                current = current[part]
            else:
                raise ConflictError("前置产物已变化，引用字段不可用")
        _validate_reference_value(reference, current)
        return current
    if isinstance(value, dict):
        return {key: resolve_reference(child, results) for key, child in value.items()}
    if isinstance(value, list):
        return [resolve_reference(child, results) for child in value]
    return value


def _validate_reference_value(reference: GoalReference, value: Any) -> None:
    matches = {
        "string": lambda x: isinstance(x, str),
        "identifier": lambda x: isinstance(x, str) and 0 < len(x) <= 128,
        "integer": lambda x: type(x) is int,
        "number": lambda x: type(x) in {int, float},
        "boolean": lambda x: type(x) is bool,
        "object": lambda x: isinstance(x, dict),
        "array": lambda x: (
            isinstance(x, list) and len(x) <= int(reference.max_items or 0)
        ),
    }
    if not matches[reference.value_type](value):
        raise ConflictError("前置产物类型与参数引用不一致")
    if reference.value_type == "array" and reference.item_type is not None:
        item_probe = reference.model_copy(update={"value_type": reference.item_type})
        for item in value:
            _validate_reference_value(item_probe, item)


def parameter_fingerprint(
    operation: AssistantOperation, parameters: dict[str, Any]
) -> str:
    try:
        validated = operation.schema.model_validate(parameters)
    except Exception as error:
        raise ValidationError(f"「{operation.label}」的参数不符合操作要求") from error
    return digest(validated.model_dump(mode="json"))


def step_operation_id(run_id: str, step_id: str, params_fingerprint: str) -> str:
    import uuid

    return str(uuid.uuid5(uuid.UUID(run_id), f"goal-step:{step_id}:{params_fingerprint}"))
