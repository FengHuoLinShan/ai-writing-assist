"""Map cold start v1: guide independent domain decisions, never authorize spend."""

from copy import deepcopy

from core.container import get
from core.errors import ConflictError, ValidationError
from infrastructure.stable_hash import stable_hash
from modules.assistant.contracts import AssistantOperationContext
from modules.assistant.guided_flow.registry import (
    FlowDefinition,
    StepDefinition,
    register,
)
from modules.assistant.operations import catalog
from modules.assistant.schemas import WorkContext

FLOW = register(
    FlowDefinition(
        flow_id="map_cold_start",
        version=1,
        title="建立可用地图",
        description="确认阅读范围，到演化页独立确认费用，再分批审核空间草图。",
        steps=tuple(
            StepDefinition(step_id=key, kind="author_choice", title=title, produces=key)
            for key, title in (
                ("scope", "确认阅读或补扫范围"),
                ("authorization", "到演化页确认费用"),
                ("monitor", "等待空间发现完成"),
                ("review", "按空间或层级审核草图"),
                ("locations", "可选采用地点"),
                ("usable", "地图可用"),
            )
        ),
    )
)


async def start_check(db, novel_id, data):
    if data.chapter_index or data.input:
        raise ValidationError("请开始后选择阅读或空间补扫范围")


async def derive(db, novel_id, *, flow_input, artifacts, settings, lifecycle):
    from core.service_keys import (
        EVOLUTION_READ_MAP_COLD_START_STATUS,
        WORLD_READ_MAP_COLD_START_DRAFTS,
    )
    from modules.assistant.guided_flow.flows import FlowDerived, _steps_view

    states = {step.step_id: "pending" for step in FLOW.steps}
    panel = {"page": "map", "batch_limit": 20}
    step, reason = "scope", "请选择演化阅读或已读范围空间补扫，先查看授权预览。"
    if artifacts.get("scope"):
        states["scope"] = "done"
        panel = {
            **panel,
            **artifacts["scope"],
            "page": "evolution",
            "authorization_required": True,
        }
        step, reason = "authorization", "请到演化页独立确认计费；助手不能代为确认。"
    binding = artifacts.get("authorization")
    if binding:
        states["authorization"] = "done"
        progress = await get(EVOLUTION_READ_MAP_COLD_START_STATUS)(
            db, novel_id, binding["run_key"], binding["operation_id"]
        )
        panel = {**panel, "progress": progress, "authorization_required": False}
        step, reason = "monitor", "演化正在处理空间信息；完成后刷新进度。"
        if progress["status"] == "needs_reconciliation":
            reason = "部分请求结果未知，请到演化页核对回执；不能重新发送未知请求。"
        elif progress["status"] not in {"pending", "running", "completed"}:
            reason = "演化需要作者处理，请到演化页核对来源、预算或回执。"
        elif progress["status"] == "completed":
            states["monitor"] = "done"
            drafts = await get(WORLD_READ_MAP_COLD_START_DRAFTS)(
                db, novel_id, binding["run_key"]
            )
            panel = {**panel, "page": "map", "drafts": drafts}
            step, reason = (
                "review",
                "按空间或层级分批审核自动草图，每次最多 20 项实际变更。",
            )
            if not drafts["batches_ready"]:
                reason = "空间草图尚未完整就绪；请核对空间覆盖或在地图工作台处理缺口。"
            elif drafts["truncated"]:
                reason = "草图数量超过当前摘要范围，请到地图工作台分批审核。"
            elif drafts["candidate_count"] == 0 and drafts["saved_node_count"] > 0:
                states["review"] = "done"
                step, reason = (
                    "locations",
                    "可以到世界资料页采用候选地点；保留候选绑定也可完成。",
                )
                panel["location_adoption"] = {
                    "page": "world",
                    "uses_original_prefix_gate": True,
                    "optional": True,
                    "cross_domain_atomic": False,
                }
                if artifacts.get("locations"):
                    states["locations"] = "done"
                    states["usable"] = "done"
                    return FlowDerived(
                        steps=_steps_view(FLOW, states, {}),
                        run_status="completed",
                        panel=panel,
                    )
    states[step] = "active"
    return FlowDerived(
        steps=_steps_view(FLOW, states, {}),
        run_status="waiting_approval",
        stop={
            "step_id": step,
            "kind": "author_choice",
            "reason": reason,
            "actions": [
                {"action": "open_" + panel.get("page", "map"), "label": "前往工作台"}
            ],
        },
        panel=panel,
    )


async def choice(db, novel_id, run, flow, artifacts, settings, value):
    from core.service_keys import EVOLUTION_READ_MAP_COLD_START_STATUS

    step, action = value.get("step_id"), value.get("action")
    if step == "scope" and action == "prepare_preview":
        capability = value.get("capability")
        if capability not in {
            "evolution.prepare_spatial_reading",
            "evolution.prepare_spatial_rescan",
        }:
            raise ValidationError("请选择空间发现阅读或空间补扫")
        operation = catalog().get(capability)
        if operation is None:
            raise ConflictError("当前部署未提供空间授权预览")
        args = operation.schema.model_validate(value.get("arguments") or {})
        preview = await operation.prepare(
            db,
            novel_id,
            args,
            context=AssistantOperationContext(
                str(run.id), str(run.owner_id), WorkContext(page="map", scope="project")
            ),
        )
        artifacts["scope"] = {
            "capability": capability,
            "arguments": args.model_dump(mode="json"),
            "preview": deepcopy(preview),
        }
        return True
    if step == "authorization" and action == "bind_authorized_run":
        scope = artifacts["scope"]
        operation_id = scope["arguments"]["operation_id"]
        run_key = str(value.get("run_key") or "")
        if not run_key or len(run_key) > 120:
            raise ValidationError("请在演化页完成授权后选择实际运行")
        progress = await get(EVOLUTION_READ_MAP_COLD_START_STATUS)(
            db, novel_id, run_key, operation_id
        )
        if scope["capability"] == "evolution.prepare_spatial_reading":
            request = progress.get("request") or {}
            expected_fingerprint = scope["preview"]["authorization_preview"][
                "fingerprint"
            ]
            if request.get("expected_fingerprint") != expected_fingerprint:
                raise ConflictError("演化实际授权与当前冻结预览不同，请重新开始流程")
            if any(request.get(key) != item for key, item in scope["arguments"].items()):
                raise ConflictError("实际演化范围与本流程授权预览不同，请重新开始流程")
        else:
            rescan = progress.get("spatial_rescan") or {}
            body = {
                key: item for key, item in scope["arguments"].items() if key != "run_key"
            }
            body.update(
                expected_fingerprint=scope["preview"]["authorization_preview"][
                    "fingerprint"
                ],
                authorization_confirmed=True,
            )
            if progress.get("authorization_request_hash") != stable_hash(body):
                raise ConflictError("空间补扫实际授权与当前冻结预览不同")
            if run_key != scope["arguments"]["run_key"] or any(
                rescan.get(key) != scope["arguments"][key]
                for key in ("from_scene_index", "through_scene_index")
            ):
                raise ConflictError("实际补扫范围与本流程不同")
        artifacts["authorization"] = {"run_key": run_key, "operation_id": operation_id}
        return True
    if step in {"monitor", "review", "locations"} and action == "refresh":
        return False
    if step == "locations" and action == "finish":
        artifacts["locations"] = {"author_decision": "finish_after_world_review_or_skip"}
        return True
    raise ValidationError(
        "当前地图停点不接受该操作；费用确认和领域采用请在对应工作台完成"
    )


async def auto_step(*args, **kwargs):
    return False
