"""引导流程运行层：复用 AssistantRun 的确定性推进、停点与恢复（ADR-0032）。

- 运行类型：``AssistantRun.request_json.protocol = "guided_flow_v1"``
  （与 forecast_v1 同一判别模式），不建新表、不加迁移。
- 每流程一个活动 run：同输入重入回到同一停点；不同输入的活动 run 冲突。
- 进度不存当前步骤索引：由领域产物推导；运行记录只冻结版本、输入指纹、
  授权范围（设置与确认引用）与停点原因。
- 停点只在：真实选择、扩大授权（资料确认）、硬性阻断。
"""

from __future__ import annotations

import copy
import hashlib
import json
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from core.config import get_settings
from core.errors import ConflictError, NotFoundError, ValidationError
from modules.assistant.guided_flow.contracts import (
    GuidedFlowStartRequest,
    GuidedFlowView,
)
from modules.assistant.guided_flow.registry import FLOWS, require_flow
from modules.assistant.models import AssistantRun

PROTOCOL = "guided_flow_v1"
ACTIVE_STATUSES = ("running", "waiting_approval")
_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


def available_for(novel_id: str | None) -> bool:
    """capabilities 投影用：当前部署与作品是否可用引导流程（不抛错）。"""
    settings = get_settings()
    if not (settings.assistant_enabled and settings.assistant_guided_flows_enabled):
        return False
    allowlist = settings.guided_flow_project_allowlist
    return not allowlist or (novel_id is not None and str(novel_id) in allowlist)


def enabled(novel_id: str | None = None) -> None:
    """部署级开关加项目白名单，沿用既有 forecast 开关与白名单机制。"""
    settings = get_settings()
    if not (settings.assistant_enabled and settings.assistant_guided_flows_enabled):
        raise ValidationError(
            "引导流程尚未开启", code="guided_flow_disabled", status_code=503
        )
    allowlist = settings.guided_flow_project_allowlist
    if novel_id is not None and allowlist and str(novel_id) not in allowlist:
        raise ValidationError(
            "引导流程尚未向当前作品开放", code="guided_flow_disabled", status_code=503
        )


def _flow_input(payload: dict) -> dict:
    """运行冻结的流程输入：chapter_index 之外的输入由各流程自行校验。"""
    return dict(payload.get("input") or {})


def _request_hash(flow, flow_input: dict, settings: dict) -> str:
    payload = json.dumps(
        {
            "flow": flow.flow_id,
            "version": flow.version,
            "input": flow_input,
            "settings": settings,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


async def _flow_runs(
    db,
    novel_id: str,
    *,
    flow_id: str | None,
    statuses: tuple[str, ...],
    owner_id: str | None = None,
    limit: int = 50,
) -> list[AssistantRun]:
    rows = (
        (
            await db.execute(
                select(AssistantRun)
                .where(
                    AssistantRun.novel_id == UUID(str(novel_id)),
                    AssistantRun.status.in_(statuses),
                )
                .order_by(AssistantRun.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [
        row
        for row in rows
        if (row.request_json or {}).get("protocol") == PROTOCOL
        and (flow_id is None or (row.request_json or {}).get("flow_id") == flow_id)
        and (owner_id is None or str(row.owner_id) == owner_id)
    ]


def _flow_of(run: AssistantRun):
    """取运行冻结的流程定义；注册表版本漂移时失败关闭。"""
    payload = run.request_json or {}
    if payload.get("protocol") != PROTOCOL:
        raise NotFoundError("流程运行不存在")
    flow = FLOWS.get(str(payload.get("flow_id") or ""))
    if flow is None:
        raise ConflictError(
            "该流程已下线，请结束当前流程", code="guided_flow_version_changed"
        )
    if payload.get("flow_version") != flow.version:
        raise ConflictError(
            "流程定义已更新，请结束当前流程后重新开始",
            code="guided_flow_version_changed",
        )
    return flow


async def _require_run(
    db, novel_id: str, run_id: str, owner_id: str, *, lock: bool = False
) -> AssistantRun:
    query = select(AssistantRun).where(
        AssistantRun.id == UUID(str(run_id)),
        AssistantRun.novel_id == UUID(str(novel_id)),
    )
    if lock:
        query = query.with_for_update()
    run = await db.scalar(query.execution_options(populate_existing=True))
    if run is None or str(run.owner_id) != str(owner_id):
        raise NotFoundError("流程运行不存在")
    return run


def _artifacts(run: AssistantRun) -> dict:
    return dict((run.checkpoint_json or {}).get("artifacts") or {})


def _settings(run: AssistantRun) -> dict:
    return dict((run.checkpoint_json or {}).get("settings") or {})


async def _lifecycle(db, novel_id: str, artifacts: dict) -> dict:
    """任务状态与已完成任务的领域结果引用（任务 id → {status, result}）。

    产物既可携带单个 ``task_id``，也可携带 ``task_ids`` 列表（流程 3 的
    批注修订按章拆成多个任务）。
    """
    from modules.assistant.guided_flow.flows import ARTIFACT_TASK_TYPES

    targets: dict[str, tuple[str, str]] = {}
    for key, artifact in artifacts.items():
        if not isinstance(artifact, dict):
            continue
        single = artifact.get("task_id")
        if single:
            targets[str(single)] = (str(key), ARTIFACT_TASK_TYPES.get(str(key), ""))
        for nested in artifact.get("task_ids") or []:
            targets[str(nested)] = (str(key), ARTIFACT_TASK_TYPES.get(str(key), ""))
    if not targets:
        return {}
    from infrastructure.tasks.facade import (
        get_completed_task_payload,
        list_task_lifecycle_contracts,
    )

    contracts = await list_task_lifecycle_contracts(
        db,
        task_ids=sorted(targets),
        novel_id=str(novel_id),
        max_heartbeat_gap=0,
    )
    lifecycle: dict[str, dict] = {}
    for task_id, contract in (contracts or {}).items():
        status = str(contract.status)
        entry = {"status": status, "result": None}
        key, task_type = targets[str(task_id)]
        if status == "done" and task_type:
            payload = await get_completed_task_payload(
                db,
                novel_id=str(novel_id),
                task_id=str(task_id),
                task_type=task_type,
            )
            entry["result"] = dict(payload.result) if payload else None
        lifecycle[str(task_id)] = entry
    return lifecycle


async def _derive(db, novel_id: str, run: AssistantRun, flow):
    from modules.assistant.guided_flow.flows import DERIVERS

    deriver = DERIVERS.get(flow.flow_id)
    if deriver is None:
        raise ConflictError("流程缺少推导实现", code="guided_flow_version_changed")
    return await deriver(
        db,
        novel_id,
        flow_input=_flow_input(run.request_json or {}),
        artifacts=_artifacts(run),
        settings=_settings(run),
        lifecycle=await _lifecycle(db, novel_id, _artifacts(run)),
    )


def _render(run: AssistantRun, flow, derived) -> dict:
    status = derived.run_status
    if run.status == "cancelled":
        status = "cancelled"
    view = GuidedFlowView(
        run_id=str(run.id),
        flow_id=flow.flow_id,
        flow_version=flow.version,
        title=flow.title,
        status=status,
        stop=derived.stop,
        steps=derived.steps,
        chapter_index=_flow_input(run.request_json or {}).get("chapter_index"),
        candidate=derived.candidate,
        panel=derived.panel,
        settings=_settings(run),
    )
    return view.model_dump(mode="json")


def _freeze_checkpoint(run: AssistantRun, artifacts: dict, settings: dict) -> None:
    """落冻结状态。JSON 列的变更检测按相等比较：原地修改后整体重赋值会被
    判为“无变化”，必须深拷贝并显式 flag，产物冻结不允许这样丢失。"""
    run.checkpoint_json = {
        "protocol": PROTOCOL,
        "artifacts": copy.deepcopy(artifacts),
        "settings": copy.deepcopy(settings),
    }
    flag_modified(run, "checkpoint_json")


def _persist(run: AssistantRun, flow, derived) -> None:
    """只冻结版本、输入指纹、授权范围与停点原因；不存步骤索引。"""
    _freeze_checkpoint(run, _artifacts(run), _settings(run))
    run.status = derived.run_status
    run.error = str(derived.stop.get("reason")) if derived.stop else None
    run.result_json = _render(run, flow, derived)
    flag_modified(run, "result_json")


async def start(db, novel_id: str, owner_id: str, data: GuidedFlowStartRequest) -> dict:
    """开始或重入一个流程；开始本身不提交任何任务、不产生费用。

    每流程一个活动 run：同输入重入回到同一停点；不同输入的活动 run 冲突。
    流程专属的开始校验（continue_writing 的工作稿、new_book_opening 的
    构想输入）由 flows 模块提供，失败在落地前拒绝。
    """
    enabled(novel_id)
    flow = require_flow(data.flow_id)
    from modules.assistant.guided_flow.flows import START_CHECKS

    check = START_CHECKS.get(flow.flow_id)
    if check is not None:
        await check(db, novel_id, data)
    settings = {**flow.settings_defaults, **data.settings.model_dump()}
    flow_input = {
        **data.input,
        **({"chapter_index": data.chapter_index} if data.chapter_index else {}),
    }
    request_hash = _request_hash(flow, flow_input, settings)
    active = await _flow_runs(
        db, novel_id, flow_id=flow.flow_id, statuses=ACTIVE_STATUSES, owner_id=owner_id
    )
    for run in active:
        if run.request_hash == request_hash:
            # 幂等重入：刷新或换设备回到同一停点，不产生第二个运行。
            return await view(db, novel_id, str(run.id), owner_id)
    if active:
        raise ConflictError(
            f"已有进行中的「{flow.title}」流程；请先完成或结束它",
            code="guided_flow_active_exists",
        )
    run = AssistantRun(
        owner_id=UUID(str(owner_id)),
        novel_id=UUID(str(novel_id)),
        mode="author",
        status="running",
        request_hash=request_hash,
        request_json={
            "protocol": PROTOCOL,
            "flow_id": flow.flow_id,
            "flow_version": flow.version,
            "input": flow_input,
            "settings": settings,
        },
        budget_json={},
        checkpoint_json={"protocol": PROTOCOL, "artifacts": {}, "settings": settings},
        result_json={},
    )
    db.add(run)
    await db.flush()
    derived = await _derive(db, novel_id, run, flow)
    _persist(run, flow, derived)
    await db.flush()
    return _render(run, flow, derived)


async def active_run(db, novel_id: str, owner_id: str) -> dict | None:
    """当前活动的流程运行（刷新或换设备回到同一停点）。"""
    enabled(novel_id)
    runs = await _flow_runs(
        db, novel_id, flow_id=None, statuses=ACTIVE_STATUSES, owner_id=owner_id
    )
    if not runs:
        return None
    return await view(db, novel_id, str(runs[0].id), owner_id)


async def view(db, novel_id: str, run_id: str, owner_id: str) -> dict:
    enabled(novel_id)
    run = await _require_run(db, novel_id, run_id, owner_id)
    flow = _flow_of(run)
    derived = await _derive(db, novel_id, run, flow)
    return _render(run, flow, derived)


async def advance(
    db, novel_id: str, run_id: str, owner_id: str, step_input: dict
) -> dict:
    """确定性推进：先应用停点输入（若有），再执行就绪的自动步骤，推导停点。

    全程幂等：自动步骤的 operation_id 由（运行、步骤、输入指纹）确定，
    重复推进不会产生第二个付费任务；作者选择输入由各流程在服务端校验，
    只有当前停点接受对应输入。
    """
    enabled(novel_id)
    run = await _require_run(db, novel_id, run_id, owner_id, lock=True)
    flow = _flow_of(run)
    if run.status not in ACTIVE_STATUSES:
        raise ConflictError("流程已结束，不能继续推进", code="guided_flow_finished")
    from modules.assistant.guided_flow.flows import (
        AUTO_STEPS,
        CHOICE_INPUT,
        CONFIRM_INPUT,
    )

    artifacts = _artifacts(run)
    settings = _settings(run)
    input_fingerprint = str(run.request_hash)

    current_stop = str(
        ((await _derive(db, novel_id, run, flow)).stop or {}).get("step_id")
    )
    confirmation_id = str(step_input.get("context_confirmation_id") or "")
    if confirmation_id:
        if current_stop != "confirm_reference":
            raise ConflictError(
                "当前流程不在资料确认停点", code="guided_flow_stop_mismatch"
            )
        applier = CONFIRM_INPUT.get(flow.flow_id)
        if applier is None:
            raise ConflictError(
                "流程缺少确认输入实现", code="guided_flow_version_changed"
            )
        if await applier(db, novel_id, run, flow, artifacts, step_input):
            _freeze_checkpoint(run, artifacts, settings)
            await db.flush()

    choice = step_input.get("choice")
    if isinstance(choice, dict) and choice:
        if current_stop != str(choice.get("step_id") or ""):
            raise ConflictError(
                "当前流程不在这个选择停点", code="guided_flow_stop_mismatch"
            )
        applier = CHOICE_INPUT.get(flow.flow_id)
        if applier is None:
            raise ConflictError(
                "流程缺少选择输入实现", code="guided_flow_version_changed"
            )
        if await applier(db, novel_id, run, flow, artifacts, settings, choice):
            _freeze_checkpoint(run, artifacts, settings)
            await db.flush()

    # 自动步骤按注册顺序推进；产物只增不改，循环上限即步骤数。
    executor = AUTO_STEPS.get(flow.flow_id)
    if executor is None:
        raise ConflictError("流程缺少自动执行实现", code="guided_flow_version_changed")

    def hydrate_candidate_ref(derived) -> bool:
        """任务完成后把领域结果里的候选引用补进冻结产物（引用只补不改）。"""
        candidate = artifacts.get("candidate") or {}
        resolved = derived.candidate or {}
        if (
            candidate.get("task_id")
            and not candidate.get("draft_id")
            and resolved.get("draft_id")
        ):
            artifacts["candidate"] = {
                **candidate,
                "draft_id": str(resolved["draft_id"]),
            }
            return True
        return False

    for _ in range(len(flow.steps) + 1):
        derived = await _derive(db, novel_id, run, flow)
        if hydrate_candidate_ref(derived):
            _freeze_checkpoint(run, artifacts, settings)
            await db.flush()
        states = {item["step_id"]: item["state"] for item in derived.steps}
        produced = {key for key in artifacts}
        progressed = False
        for step in flow.steps:
            if step.kind != "auto" or step.produces in produced:
                continue
            if step.gated_on and not settings.get(step.gated_on, True):
                continue
            if not all(
                states.get(name) in {"done", "skipped"} for name in step.requires
            ):
                continue
            fragment = await executor(
                db,
                novel_id,
                owner_id,
                run,
                flow,
                artifacts,
                step.step_id,
                input_fingerprint=input_fingerprint,
            )
            if fragment is not None:
                artifacts[step.produces] = fragment
                _freeze_checkpoint(run, artifacts, settings)
                await db.flush()
                progressed = True
        if not progressed:
            break

    derived = await _derive(db, novel_id, run, flow)
    _persist(run, flow, derived)
    await db.flush()
    return _render(run, flow, derived)


async def save_settings(
    db,
    novel_id: str,
    run_id: str,
    owner_id: str,
    *,
    semantic_review: bool | None = None,
    rolling_planning: bool | None = None,
    planning_window: int | None = None,
) -> dict:
    """流程设置：生成开始前可修改并重新冻结输入指纹；之后不可改。

    任一自动步骤产物已存在即视为生成已开始；各流程未声明的设置键拒绝。
    """
    enabled(novel_id)
    run = await _require_run(db, novel_id, run_id, owner_id, lock=True)
    flow = _flow_of(run)
    if run.status not in ACTIVE_STATUSES:
        raise ConflictError("流程已结束，不能修改设置", code="guided_flow_finished")
    auto_produces = {step.produces for step in flow.steps if step.kind == "auto"}
    if auto_produces & set(_artifacts(run)):
        raise ConflictError(
            "生成已开始，流程设置不能再修改", code="guided_flow_settings_locked"
        )
    settings = _settings(run)
    known = set(flow.settings_defaults)
    updates = {
        "semantic_review": semantic_review,
        "rolling_planning": rolling_planning,
        "planning_window": planning_window,
    }
    for key, value in updates.items():
        if value is None:
            continue
        if key not in known:
            raise ValidationError(
                f"当前流程没有设置项 {key}", code="guided_flow_settings_locked"
            )
        settings[key] = bool(value) if isinstance(value, bool) else int(value)
    payload = dict(run.request_json or {})
    payload["settings"] = settings
    run.request_json = payload
    flag_modified(run, "request_json")
    run.request_hash = _request_hash(flow, _flow_input(payload), settings)
    _freeze_checkpoint(run, _artifacts(run), settings)
    await db.flush()
    return await view(db, novel_id, run_id, owner_id)


async def abandon(db, novel_id: str, run_id: str, owner_id: str) -> dict:
    """作者结束流程；已生成的候选与已确认资料保持原领域语义，不受影响。"""
    run = await _require_run(db, novel_id, run_id, owner_id, lock=True)
    payload = run.request_json or {}
    if payload.get("protocol") != PROTOCOL:
        raise NotFoundError("流程运行不存在")
    if run.status in _TERMINAL_STATUSES:
        raise ConflictError("流程已结束", code="guided_flow_finished")
    run.status = "cancelled"
    run.checkpoint_json = {}
    flag_modified(run, "checkpoint_json")
    run.result_json = {
        **(run.result_json or {}),
        "status": "cancelled",
        "stop": {
            "step_id": str((run.result_json or {}).get("stop", {}).get("step_id") or ""),
            "kind": "blocked",
            "reason": "流程已由作者结束；已生成候选仍在候选列表中。",
            "actions": [],
        },
    }
    flag_modified(run, "result_json")
    run.error = None
    await db.flush()
    return dict(run.result_json or {})
