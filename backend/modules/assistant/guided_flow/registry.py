"""服务端注册的引导流程步骤表（ADR-0032 决策 1/2）。

流程定义是纯声明数据加推导/执行函数，构建期做结构校验：步骤只允许引用
已注册操作或既有领域任务；产物单一生产者；依赖只指向更早步骤（无环）。
模型与前端不可修改，运行期不开放任何 DSL。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from core.errors import ValidationError

StepKind = Literal["auto", "author_confirm", "author_choice"]

KINDS: tuple[str, ...] = ("auto", "author_confirm", "author_choice")


@dataclass(frozen=True)
class StepDefinition:
    """一个流程步骤的声明。

    - ``auto``：自动执行；``operation`` 引用已注册 suggest 类操作（复用
      uuid5 幂等执行），或 ``domain_task`` 引用既有领域任务类型。
    - ``author_confirm``：作者确认，复用既有确认与批次指纹重验协议。
    - ``author_choice``：作者选择（方向、采用/返修等真实决定点）。
    ``gated_on`` 命名一个运行设置键；该设置为关闭时步骤整体跳过
    （如流程 2 的独立语义审查）。
    """

    step_id: str
    kind: StepKind
    title: str
    stop_reason: str = ""
    produces: str = ""
    requires: tuple[str, ...] = ()
    operation: str | None = None
    domain_task: str | None = None
    gated_on: str | None = None


@dataclass(frozen=True)
class FlowDefinition:
    """带版本号的流程步骤表；``version`` 变化即行为变化。"""

    flow_id: str
    version: int
    title: str
    description: str
    steps: tuple[StepDefinition, ...]
    settings_defaults: dict[str, Any] = field(default_factory=dict)


def validate_flow(flow: FlowDefinition) -> None:
    """构建期结构校验：未知类型、重复步骤、前向依赖/环、单一生产者。"""
    if not flow.flow_id or flow.version < 1:
        raise ValidationError("引导流程标识与版本必须有效")
    if not flow.steps:
        raise ValidationError(f"流程 {flow.flow_id} 没有任何步骤")
    seen: set[str] = set()
    producers: dict[str, str] = {}
    for step in flow.steps:
        if step.kind not in KINDS:
            raise ValidationError(f"步骤 {step.step_id} 使用了未知类型 {step.kind!r}")
        if step.step_id in seen:
            raise ValidationError(f"流程 {flow.flow_id} 步骤标识重复：{step.step_id}")
        if not step.produces:
            raise ValidationError(f"步骤 {step.step_id} 未声明产物")
        if step.produces in producers:
            raise ValidationError(
                f"产物 {step.produces} 有多个生产者（{producers[step.produces]}）"
            )
        producers[step.produces] = step.step_id
        unknown = set(step.requires) - seen
        if unknown:
            raise ValidationError(
                f"步骤 {step.step_id} 依赖未知或更晚的步骤：{sorted(unknown)}"
            )
        if step.step_id in step.requires:
            raise ValidationError(f"步骤 {step.step_id} 依赖自身")
        if step.kind == "auto":
            if bool(step.operation) == bool(step.domain_task):
                raise ValidationError(
                    f"自动步骤 {step.step_id} 必须且只能引用一个已注册操作或领域任务"
                )
        elif step.operation or step.domain_task:
            raise ValidationError(f"步骤 {step.step_id} 不是自动步骤，不能引用操作")
        seen.add(step.step_id)


FLOWS: dict[str, FlowDefinition] = {}


def register(flow: FlowDefinition) -> FlowDefinition:
    validate_flow(flow)
    FLOWS[flow.flow_id] = flow
    return flow


def require_flow(flow_id: str, *, operations: dict | None = None) -> FlowDefinition:
    """取已注册流程，并按当前操作目录校验自动步骤的引用仍然有效。"""
    from modules.assistant.operations import catalog

    flow = FLOWS.get(flow_id)
    if flow is None:
        raise ValidationError("引导流程不存在或未开启", code="guided_flow_unknown")
    available = catalog() if operations is None else operations
    for step in flow.steps:
        if step.kind != "auto" or not step.operation:
            continue
        operation = available.get(step.operation)
        if operation is None:
            raise ValidationError(
                f"流程引用的操作 {step.operation} 未注册", code="guided_flow_unknown"
            )
        if operation.permission != "suggest":
            raise ValidationError(
                f"流程只能自动执行建议类操作：{step.operation}",
                code="guided_flow_unknown",
            )
    return flow
