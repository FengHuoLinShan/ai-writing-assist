"""Guided author review of a Story world-progression run (ADR-0032/0041)."""

from __future__ import annotations

from copy import deepcopy
from uuid import UUID, uuid5

from core.container import get
from core.errors import ConflictError, ValidationError
from infrastructure.stable_hash import stable_hash
from modules.assistant.contracts import AssistantOperationContext
from modules.assistant.guided_flow.registry import (
    FlowDefinition,
    StepDefinition,
    register,
)
from modules.assistant.schemas import WorkContext
from modules.evidence.facade import prepare_confirmed_ai_action

FLOW_ID = "world_progression_review"
FLOW_VERSION = 1
WORLD_PROGRESSION_REVIEW = register(
    FlowDefinition(
        flow_id=FLOW_ID,
        version=FLOW_VERSION,
        title="世界推进复核",
        description=(
            "选择参与者与推进方式，单独确认根预算；查看候选步骤后，再逐条预览并采用大纲钩子。"
        ),
        steps=(
            StepDefinition(
                step_id="select_scope",
                kind="author_choice",
                title="选择参与者与推进方式",
                produces="selection",
            ),
            StepDefinition(
                step_id="confirm_reference",
                kind="author_confirm",
                title="确认截止场景资料",
                stop_reason="请确认参与者在本场景可用的资料；目标与秘密只供导演裁决。",
                produces="context_confirmation",
                requires=("select_scope",),
            ),
            StepDefinition(
                step_id="authorize_progression",
                kind="author_choice",
                title="确认根预算并推进",
                produces="progression_run",
                requires=("confirm_reference",),
            ),
            StepDefinition(
                step_id="review_progression",
                kind="author_choice",
                title="复核候选步骤与钩子",
                produces="progression_review",
                requires=("authorize_progression",),
            ),
            StepDefinition(
                step_id="confirm_rolling_hook",
                kind="author_confirm",
                title="确认钩子规划窗口",
                stop_reason="采用大纲候选前，请确认当前滚动窗口资料。",
                produces="hook_confirmation",
                requires=("review_progression",),
            ),
            StepDefinition(
                step_id="review_hooks",
                kind="author_choice",
                title="预览世界推进钩子",
                produces="hook_preview",
                requires=("confirm_rolling_hook",),
            ),
            StepDefinition(
                step_id="adopt_hook",
                kind="author_choice",
                title="逐条确认采用大纲候选",
                produces="hook_adoption",
                requires=("review_hooks",),
            ),
            StepDefinition(
                step_id="finish_flow",
                kind="author_choice",
                title="结束复核",
                produces="flow_completion",
                requires=("review_progression",),
            ),
        ),
    )
)


def _operations():
    from core.service_keys import ASSISTANT_OPERATIONS

    try:
        return get(ASSISTANT_OPERATIONS)
    except KeyError as exc:
        raise ConflictError("当前部署尚未装配世界推进操作目录") from exc


def _context(run, owner_id: str, *, operation_id: str, confirmation_id=None, action=None):
    confirmation_uuid = UUID(str(confirmation_id)) if confirmation_id else None
    return AssistantOperationContext(
        run_id=str(run.id),
        owner_id=str(owner_id),
        work=WorkContext(
            page="outline",
            scope="project",
            context_confirmation_id=confirmation_uuid,
            context_confirmation_action=action if confirmation_uuid else None,
        ),
        operation_id=operation_id,
        trace_enabled=True,
        trace_actor_type="guided_flow",
        trace_entrypoint="assistant.guided_flow.world_progression_review",
        trace_session_id=str(run.session_id) if run.session_id else None,
    )


def _operation_id(run, step: str, identity: str = "") -> str:
    return str(
        uuid5(
            UUID(str(run.id)),
            f"{FLOW_ID}:v{FLOW_VERSION}:{step}:{run.request_hash}:{identity}",
        )
    )


def _selection(flow_input: dict, novel_id: str) -> dict:
    return {**flow_input, "novel_id": str(novel_id)}


def _budget_payload(selection: dict) -> dict:
    return {
        key: value
        for key, value in selection.items()
        if key != "budget_preview_hash"
    }


def _hook_items(history: dict, root_id: str) -> list[dict]:
    root = next(
        (item for item in history.get("roots", []) if str(item.get("id")) == root_id),
        None,
    )
    if root is None:
        return []
    hooks = []
    for branch in root.get("branches", []):
        for step in branch.get("steps", []):
            for hook in (step.get("result") or {}).get("plot_hooks", []):
                hooks.append(
                    {
                        **dict(hook),
                        "step_id": str(step["id"]),
                        "branch_id": str(branch["id"]),
                        "cutoff_chapter": root.get("cutoff_chapter"),
                    }
                )
    return hooks


async def start_check(db, novel_id, data):
    """Freeze a valid author selection and an R0 budget hash before the flow starts."""
    operation = _operations().get("story.world_progression.preview")
    if operation is None:
        raise ConflictError("当前部署未提供世界推进预算预览")
    raw = {
        key: value
        for key, value in data.input.items()
        if key != "budget_preview_hash"
    }
    args = operation.schema.model_validate({**raw, "novel_id": str(novel_id)})
    preview = await operation.prepare(db, str(novel_id), args)
    supplied_hash = str(data.input.get("budget_preview_hash") or "")
    if not supplied_hash:
        raise ConflictError("请先完成并确认 Story 世界推进预算预览")
    if supplied_hash != preview["preview_hash"]:
        raise ConflictError("资料或预算预览已变化，请重新预览后开始引导流程")
    normalized = args.model_dump(mode="json")
    normalized["scene_id"] = str(preview["scene_id"])
    normalized["budget_preview_hash"] = preview["preview_hash"]
    data.input = normalized


async def _read_history(db, novel_id, root_id):
    operation = _operations().get("story.world_progression.history")
    if operation is None:
        raise ConflictError("当前部署未提供世界推进历史读取")
    args = operation.schema.model_validate(
        {"novel_id": str(novel_id), "root_id": str(root_id)}
    )
    return await operation.prepare(db, str(novel_id), args)


async def derive(db, novel_id, *, flow_input, artifacts, settings, lifecycle):
    from modules.assistant.guided_flow.flows import FlowDerived, _steps_view

    states = {step.step_id: "pending" for step in WORLD_PROGRESSION_REVIEW.steps}
    details = {}
    selection = _selection(flow_input, novel_id)
    preview_operation = _operations().get("story.world_progression.preview")
    if preview_operation is None:
        return FlowDerived(
            steps=_steps_view(WORLD_PROGRESSION_REVIEW, states, details),
            run_status="waiting_approval",
            stop={
                "step_id": "select_scope",
                "kind": "blocked",
                "reason": "当前部署没有注册世界推进操作目录。",
                "actions": [],
            },
        )
    preview_args = preview_operation.schema.model_validate(_budget_payload(selection))
    preview = await preview_operation.prepare(db, str(novel_id), preview_args)
    states["select_scope"] = "done"
    details["select_scope"] = (
        f"{preview['participants']} 位参与者 · "
        f"{'导向推进' if preview['mode'] == 'directed' else '自由推进'} · "
        f"{preview['step_length']}"
    )
    states["confirm_reference"] = "active"
    if "context_confirmation" not in artifacts:
        return FlowDerived(
            steps=_steps_view(WORLD_PROGRESSION_REVIEW, states, details),
            run_status="waiting_approval",
            stop={
                "step_id": "confirm_reference",
                "kind": "author_confirm",
                "reason": "确认截止场景的作者资料后，才会执行参与者意图推演。",
                "actions": [
                    {"action": "confirm_progression_context", "label": "确认资料"}
                ],
            },
            panel={"selection": selection, "budget_preview": preview},
        )

    states["confirm_reference"] = "done"
    run_artifact = artifacts.get("progression_run") or {}
    if not run_artifact:
        states["authorize_progression"] = "active"
        return FlowDerived(
            steps=_steps_view(WORLD_PROGRESSION_REVIEW, states, details),
            run_status="waiting_approval",
            stop={
                "step_id": "authorize_progression",
                "kind": "author_choice",
                "reason": (
                    "预算预览已就绪。单独确认后才会创建持久根预算并提交一步或连续推进。"
                ),
                "actions": [
                    {"action": "confirm_and_start", "label": "确认预算并推进"}
                ],
            },
            panel={"selection": selection, "budget_preview": preview},
        )

    states["authorize_progression"] = "done"
    task = lifecycle.get("progression_run") or {}
    task_status = str(task.get("status") or "unknown")
    if task_status in {"pending", "running", "queued"}:
        states["review_progression"] = "active"
        return FlowDerived(
            steps=_steps_view(WORLD_PROGRESSION_REVIEW, states, details),
            run_status="running",
            panel={
                "selection": selection,
                "progression_run": run_artifact,
                "task_status": task_status,
                "message": "世界推进任务仍在运行；候选步骤保存后会在这里出现。",
            },
        )
    if task_status != "done":
        states["review_progression"] = "blocked"
        return FlowDerived(
            steps=_steps_view(WORLD_PROGRESSION_REVIEW, states, details),
            run_status="waiting_approval",
            stop={
                "step_id": "review_progression",
                "kind": "blocked",
                "reason": (
                    "推进任务未能完成。请先查看历史中的失败或用量状态；"
                    "不会自动重试。"
                ),
                "actions": [{"action": "refresh_progression", "label": "刷新历史"}],
            },
            panel={"progression_run": run_artifact, "task_status": task_status},
        )

    root_id = str(run_artifact.get("root_id") or "")
    history = await _read_history(db, novel_id, root_id)
    hooks = _hook_items(history, root_id)
    selection_state = artifacts.get("progression_review") or {}
    if not selection_state:
        states["review_progression"] = "active"
        actions = (
            [
                {"action": "review_hooks", "label": "查看可用剧情钩子"},
                {"action": "finish_without_hooks", "label": "结束复核"},
            ]
            if hooks
            else [{"action": "finish_without_hooks", "label": "结束复核"}]
        )
        return FlowDerived(
            steps=_steps_view(WORLD_PROGRESSION_REVIEW, states, details),
            run_status="waiting_approval",
            stop={
                "step_id": "review_progression",
                "kind": "author_choice",
                "reason": "候选步骤已保存。你可以继续逐条预览剧情钩子，也可以结束复核。",
                "actions": actions,
            },
            panel={"progression_run": run_artifact, "history": history, "hooks": hooks},
        )

    if selection_state.get("done"):
        states["review_progression"] = "done"
        states["finish_flow"] = "done"
        return FlowDerived(
            steps=_steps_view(WORLD_PROGRESSION_REVIEW, states, details),
            run_status="completed",
            panel={"progression_run": run_artifact, "history": history},
        )

    states["review_progression"] = "done"
    hook_selection = artifacts.get("hook_selection") or {}
    selected_hook = next(
        (item for item in hooks if item.get("hook_id") == hook_selection.get("hook_id")),
        None,
    )
    adopted_ids = set((artifacts.get("hook_adoption") or {}).keys())
    if selected_hook is not None and selected_hook["hook_id"] not in adopted_ids:
        hook_key = stable_hash(
            {
                "hook_id": selected_hook["hook_id"],
                "asset_type": hook_selection.get("asset_type"),
                "start_chapter": hook_selection.get("start_chapter"),
                "end_chapter": hook_selection.get("end_chapter"),
            }
        )
        confirmations = artifacts.get("hook_confirmation") or {}
        previews = artifacts.get("hook_preview") or {}
        confirmation = confirmations.get(hook_key)
        hook_preview = previews.get(hook_key)
        panel = {
            "progression_run": run_artifact,
            "history": history,
            "hooks": hooks,
            "selected_hook": selected_hook,
            "hook_selection": hook_selection,
            "hook_preview": hook_preview,
            "hook_adoption": artifacts.get("hook_adoption") or {},
        }
        if confirmation is None:
            states["confirm_rolling_hook"] = "active"
            return FlowDerived(
                steps=_steps_view(WORLD_PROGRESSION_REVIEW, states, details),
                run_status="waiting_approval",
                stop={
                    "step_id": "confirm_rolling_hook",
                    "kind": "author_confirm",
                    "reason": "预览该钩子前，请确认本次滚动规划窗口和当前结构资料。",
                    "actions": [
                        {"action": "confirm_hook_context", "label": "确认规划资料"}
                    ],
                },
                panel=panel,
            )
        states["confirm_rolling_hook"] = "done"
        if hook_preview is None:
            states["review_hooks"] = "active"
            return FlowDerived(
                steps=_steps_view(WORLD_PROGRESSION_REVIEW, states, details),
                run_status="waiting_approval",
                stop={
                    "step_id": "review_hooks",
                    "kind": "author_choice",
                    "reason": "已确认资料。只读预览窗口后，仍需你单独确认采用。",
                    "actions": [
                        {"action": "preview_hook", "label": "预览滚动规划窗口"},
                        {"action": "choose_another_hook", "label": "改选其他钩子"},
                    ],
                },
                panel=panel,
            )
        states["review_hooks"] = "done"
        states["adopt_hook"] = "active"
        return FlowDerived(
            steps=_steps_view(WORLD_PROGRESSION_REVIEW, states, details),
            run_status="waiting_approval",
            stop={
                "step_id": "adopt_hook",
                "kind": "author_choice",
                "reason": "预览不写入资产。确认后才会创建可编辑的大纲候选。",
                "actions": [
                    {"action": "adopt_hook", "label": "R3 采用为大纲候选"},
                    {"action": "choose_another_hook", "label": "改选其他钩子"},
                ],
            },
            panel=panel,
        )

    states["confirm_rolling_hook"] = "pending"
    states["review_hooks"] = "active"
    remaining = [item for item in hooks if item.get("hook_id") not in adopted_ids]
    return FlowDerived(
        steps=_steps_view(WORLD_PROGRESSION_REVIEW, states, details),
        run_status="waiting_approval",
        stop={
            "step_id": "review_hooks",
            "kind": "author_choice",
            "reason": "可以选择下一条钩子，逐条预览并采用；完成后结束流程。",
            "actions": [
                {"action": "finish_flow", "label": "结束复核"},
                *(
                    [{"action": "select_hook", "label": "选择剧情钩子"}]
                    if remaining
                    else []
                ),
            ],
        },
        panel={
            "progression_run": run_artifact,
            "history": history,
            "hooks": remaining,
            "hook_adoption": artifacts.get("hook_adoption") or {},
        },
    )


async def apply_confirm_input(db, novel_id, run, flow, artifacts, step_input):
    confirmation_id = str(step_input.get("context_confirmation_id") or "")
    if not confirmation_id:
        return False
    step_id = str(step_input.get("step_id") or "")
    if step_id == "confirm_reference":
        fixed = await prepare_confirmed_ai_action(
            db,
            novel_id=str(novel_id),
            action="story.one_click.simulate",
            confirmation_id=confirmation_id,
        )
        selection = _selection(
            (run.request_json or {}).get("input") or {}, str(novel_id)
        )
        options = dict(fixed.compile_options or {})
        expected_characters = {
            str(item["id"])
            for item in selection.get("participants", [])
            if item.get("kind") == "character"
        }
        expected_groups = {
            str(item["id"])
            for item in selection.get("participants", [])
            if item.get("kind") == "group"
        }
        if (
            str(options.get("scene_id") or "") != str(selection.get("scene_id") or "")
            or expected_characters != set(map(str, options.get("character_ids") or []))
            or not expected_groups <= set(map(str, options.get("entity_ids") or []))
            or any(fixed.confirmation.excluded_asset_ids.values())
        ):
            raise ConflictError("资料确认范围与本次参与者或截止场景不一致")
        previous = artifacts.get("context_confirmation") or {}
        if previous.get("confirmation_id") == confirmation_id:
            return False
        artifacts["context_confirmation"] = {
            "confirmation_id": confirmation_id,
            "context_fingerprint": fixed.confirmation.context_fingerprint,
        }
        return True
    if step_id == "confirm_rolling_hook":
        fixed = await prepare_confirmed_ai_action(
            db,
            novel_id=str(novel_id),
            action="outline.generate",
            confirmation_id=confirmation_id,
        )
        options = dict(fixed.compile_options or {})
        selection = artifacts.get("hook_selection") or {}
        if (
            options.get("scope") != "full"
            or options.get("budget_tokens") != 0
            or any(fixed.confirmation.excluded_asset_ids.values())
            or options.get("chapter_index") != selection.get("start_chapter")
            or options.get("planning_window_end") != selection.get("end_chapter")
        ):
            raise ConflictError("钩子规划确认不包含冻结的完整窗口")
        key = stable_hash(
            {
                "hook_id": selection.get("hook_id"),
                "asset_type": selection.get("asset_type"),
                "start_chapter": selection.get("start_chapter"),
                "end_chapter": selection.get("end_chapter"),
            }
        )
        confirmations = dict(artifacts.get("hook_confirmation") or {})
        if confirmations.get(key, {}).get("confirmation_id") == confirmation_id:
            return False
        confirmations[key] = {
            "confirmation_id": confirmation_id,
            "context_fingerprint": fixed.confirmation.context_fingerprint,
        }
        artifacts["hook_confirmation"] = confirmations
        return True
    raise ValidationError("当前引导流程不接受此资料确认")


def _current_selection(artifacts, choice):
    selection = artifacts.get("hook_selection") or {}
    if choice.get("hook_id") and str(choice["hook_id"]) != str(selection.get("hook_id")):
        return None
    return selection


async def _run_start(db, novel_id, owner_id, run, flow, artifacts):
    from core.service_keys import ASSISTANT_OPERATIONS

    operation = get(ASSISTANT_OPERATIONS).get("story.world_progression.start")
    if operation is None:
        raise ConflictError("当前部署未提供世界推进启动操作")
    selection = _selection((run.request_json or {}).get("input") or {}, novel_id)
    context_confirmation_id = str(
        (artifacts.get("context_confirmation") or {}).get("confirmation_id") or ""
    )
    if not context_confirmation_id:
        raise ConflictError("请先确认截止场景资料")
    args = operation.schema.model_validate(
        {
            **selection,
            "operation_id": _operation_id(run, "authorize_progression"),
            "context_confirmation_id": context_confirmation_id,
            "budget_preview_hash": selection["budget_preview_hash"],
        }
    )
    context = _context(
        run,
        str(owner_id),
        operation_id=str(args.operation_id),
        confirmation_id=context_confirmation_id,
        action="story.one_click.simulate",
    )
    preview = await operation.prepare(db, str(novel_id), args, context=context)
    if preview["preview_hash"] != args.budget_preview_hash:
        raise ConflictError("资料、预算或模型配置已变化，请重新预览")
    result = await operation.apply(db, str(novel_id), args, preview, context=context)
    return {
        "task_id": str(result["task_id"]),
        "root_id": str(result["root_id"]),
        "branch_id": str(result["branch_id"]),
    }


def _hook_request(novel_id, run, selection, confirmation_id, operation_id):
    return {
        "novel_id": str(novel_id),
        "root_id": str((run.request_json or {}).get("input", {}).get("root_id") or ""),
        "step_id": str(selection.get("step_id") or ""),
        "hook_id": str(selection.get("hook_id") or ""),
        "asset_type": selection.get("asset_type"),
        "operation_id": operation_id,
        "context_confirmation_id": confirmation_id,
        "start_chapter": selection.get("start_chapter"),
        "end_chapter": selection.get("end_chapter"),
        "draft": deepcopy(selection.get("draft") or {}),
    }


async def _preview_selected_hook(db, novel_id, run, artifacts):
    operation = _operations().get("story.world_progression.preview_hook")
    if operation is None:
        raise ConflictError("当前部署未提供钩子预览")
    selection = artifacts.get("hook_selection") or {}
    key = stable_hash(
        {
            "hook_id": selection.get("hook_id"),
            "asset_type": selection.get("asset_type"),
            "start_chapter": selection.get("start_chapter"),
            "end_chapter": selection.get("end_chapter"),
        }
    )
    confirmation_id = str(
        (artifacts.get("hook_confirmation") or {}).get(key, {}).get(
            "confirmation_id"
        )
        or ""
    )
    root_id = str((artifacts.get("progression_run") or {}).get("root_id") or "")
    request = {
        **_hook_request(
            novel_id,
            run,
            {**selection, "root_id": root_id},
            confirmation_id,
            _operation_id(run, "preview_hook", key),
        ),
        "root_id": root_id,
    }
    args = operation.schema.model_validate(request)
    context = _context(
        run,
        str(run.owner_id),
        operation_id=str(args.operation_id),
        confirmation_id=confirmation_id,
        action="outline.generate",
    )
    return await operation.prepare(db, str(novel_id), args, context=context), key


def _set_hook_selection(artifacts, selection):
    hook_id = str(selection.get("hook_id") or "")
    if not hook_id:
        raise ValidationError("请选择一条剧情钩子")
    asset_type = selection.get("asset_type")
    if asset_type not in {"plot_thread", "outline_arc", "planned_scene"}:
        raise ValidationError("请选择剧情线、篇章或计划场景")
    try:
        start = int(selection.get("start_chapter") or 0)
        end = int(selection.get("end_chapter") or 0)
    except (TypeError, ValueError) as exc:
        raise ValidationError("请填写有效的章节窗口") from exc
    if start < 1 or end < start:
        raise ValidationError("请填写有效的章节窗口")
    artifacts["hook_selection"] = {
        **dict(selection),
        "hook_id": hook_id,
        "asset_type": asset_type,
        "start_chapter": start,
        "end_chapter": end,
        "step_id": str(selection.get("step_id") or ""),
    }


async def choice(db, novel_id, run, flow, artifacts, settings, value):
    step, action = str(value.get("step_id") or ""), str(value.get("action") or "")
    if step == "authorize_progression" and action == "confirm_and_start":
        if artifacts.get("progression_run"):
            return False
        artifacts["progression_run"] = await _run_start(
            db, str(novel_id), str(run.owner_id), run, flow, artifacts
        )
        return True
    if step == "review_progression":
        if action == "refresh_progression":
            return False
        if action == "finish_without_hooks":
            artifacts["progression_review"] = {"done": True}
            artifacts["flow_completion"] = {"reason": "author_finished"}
            return True
        if action == "review_hooks":
            artifacts["progression_review"] = {"done": False}
            return True
    if step == "review_hooks":
        selection = value.get("selection") or {}
        if action in {"select_hook", "choose_another_hook"}:
            _set_hook_selection(artifacts, selection)
            return True
        if action == "preview_hook":
            preview, key = await _preview_selected_hook(db, novel_id, run, artifacts)
            previews = dict(artifacts.get("hook_preview") or {})
            previews[key] = preview
            artifacts["hook_preview"] = previews
            return True
        if action == "finish_flow":
            artifacts["progression_review"] = {"done": True}
            artifacts["flow_completion"] = {"reason": "author_finished"}
            return True
    if step == "adopt_hook" and action == "adopt_hook":
        operation = _operations().get("story.world_progression.adopt_hook")
        if operation is None:
            raise ConflictError("当前部署未提供钩子采用操作")
        selection = artifacts.get("hook_selection") or {}
        key = stable_hash(
            {
                "hook_id": selection.get("hook_id"),
                "asset_type": selection.get("asset_type"),
                "start_chapter": selection.get("start_chapter"),
                "end_chapter": selection.get("end_chapter"),
            }
        )
        preview = (artifacts.get("hook_preview") or {}).get(key)
        confirmation_id = str(
            (artifacts.get("hook_confirmation") or {}).get(key, {}).get(
                "confirmation_id"
            )
            or ""
        )
        if preview is None or not confirmation_id:
            raise ConflictError("请先确认滚动窗口并完成钩子预览")
        root_id = str((artifacts.get("progression_run") or {}).get("root_id") or "")
        operation_id = _operation_id(run, "adopt_hook", key)
        args = operation.schema.model_validate(
            {
                **_hook_request(
                    novel_id,
                    run,
                    {**selection, "root_id": root_id},
                    confirmation_id,
                    operation_id,
                ),
                "root_id": root_id,
                "preview_hash": preview["preview_hash"],
            }
        )
        context = _context(
            run,
            str(run.owner_id),
            operation_id=str(args.operation_id),
            confirmation_id=confirmation_id,
            action="outline.generate",
        )
        prepared = await operation.prepare(db, str(novel_id), args, context=context)
        if prepared["preview_hash"] != preview["preview_hash"]:
            raise ConflictError("钩子预览依据已变化，请重新预览")
        result = await operation.apply(db, str(novel_id), args, prepared, context=context)
        adoptions = dict(artifacts.get("hook_adoption") or {})
        adoptions[str(selection["hook_id"])] = dict(result)
        artifacts["hook_adoption"] = adoptions
        artifacts.pop("hook_selection", None)
        return True
    if step == "adopt_hook" and action == "choose_another_hook":
        _set_hook_selection(artifacts, value.get("selection") or {})
        return True
    raise ValidationError("当前世界推进引导流程不接受此操作")


async def auto_step(*args, **kwargs):
    return None
