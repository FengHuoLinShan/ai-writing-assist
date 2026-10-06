"""Assistant entry to the existing project dedupe scan and controlled workbench."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from core.container import get
from core.errors import ConflictError
from infrastructure.tasks.facade import get_completed_task_payload
from modules.project.schemas import SmartDedupScanRequest
from modules.project.smart_dedup import SmartDedupService


class ScanDuplicates(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scopes: list[
        Literal[
            "world_entity",
            "plot_thread",
            "outline_arc",
            "scene",
            "foreshadowing_plan",
            "reveal_plan",
        ]
    ] = Field(
        default_factory=lambda: [
            "world_entity",
            "plot_thread",
            "outline_arc",
            "scene",
            "foreshadowing_plan",
            "reveal_plan",
        ],
        min_length=1,
        max_length=6,
    )


async def _preview(db, novel_id, args, *, context=None):
    require_operation_targets = get("assistant.require_operation_targets")
    await require_operation_targets(db, novel_id, context, [], aggregate=True)
    if context and context.work.scope != "project":
        raise ConflictError("查重需明确选择整个作品范围，或从原智能去重入口开始")
    return {
        "title": "查找相似资料",
        "scopes": sorted(set(args.scopes)),
        "effect": "仅生成相似建议；在原去重工作台比较和确认后才会修改资料",
    }


async def _submit(db, novel_id, args, preview, *, context=None):
    receipt = await SmartDedupService().submit_scan(
        db,
        novel_id,
        SmartDedupScanRequest(
            scopes=preview["scopes"], operation_id=UUID(context.operation_id)
        ),
        llm_snapshot=context.llm_snapshot,
        internal_meta=context.internal_meta,
    )
    return {
        "type": "smart_dedup_scan",
        "id": receipt.task_id,
        "task_id": receipt.task_id,
        "task_type": "smart_dedup_scan",
        "label": "相似资料扫描",
    }


async def _read(db, novel_id, reference):
    task = await get_completed_task_payload(
        db, novel_id=novel_id, task_type="smart_dedup_scan", task_id=reference["task_id"]
    )
    if task is None:
        return {
            "status": "incomplete",
            "omissions": ["扫描尚未完成；原任务和已用额度保持，请从原回执继续"],
        }
    result = task.result
    return {
        "status": "completed",
        "summary": result.get("summary"),
        "scanned_counts": result.get("scanned_counts"),
        "group_count": len(result.get("groups") or []),
        "group_receipts": result.get("group_receipts") or {},
        "authority": "相似建议不是重复结论；请到原工作台选择主对象和处理方式",
        "omissions": result.get("warnings") or [],
    }


# 纯数据声明（AO-5）：不 import assistant 契约；组合根
# app/assistant_operation_registry 按 AssistantOperation 原构造语义物化。
OPERATIONS_SPEC = {
    "project.scan_duplicates": {
        "label": "查找相似资料",
        "schema": ScanDuplicates,
        "prepare": _preview,
        "apply": _submit,
        "permission": "suggest",
        "read_result": _read,
    }
}
