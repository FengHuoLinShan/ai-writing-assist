"""新书开篇世界观骨架 suggest 操作（BR-5 World 侧）。

与 ``story.plan_structure → story.adopt_structure`` 同构：``prepare`` 只读
预演，``apply`` 经幂等 operation_id 入队 World 自有任务
（``world_opening_skeleton``），任务完成后作者在骨架包上逐条取舍并采用。
方向卡本包阶段由参数传入（Assistant 方向卡 step 后续集成）；骨架生成不编译
Evidence 上下文，输入只有作者构想、选定方向与服务端读取的项目已有对象，
空项目可直接运行。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from core.errors import ConflictError
from modules.project.facade import require_active_project


class DraftOpeningSkeleton(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vision: str = Field(..., min_length=1, max_length=20000)
    direction_title: str | None = Field(default=None, max_length=255)
    direction: dict[str, str] | None = Field(default=None)

    @classmethod
    def task_request(cls, novel_id: str, args: DraftOpeningSkeleton):
        from modules.world.schemas import WorldOpeningSkeletonTaskRequest

        return WorldOpeningSkeletonTaskRequest(
            novel_id=novel_id,
            vision=args.vision,
            direction_title=args.direction_title,
            direction=args.direction,
        )


def _require_scope(context) -> None:
    if context is not None and context.work.excluded_targets:
        raise ConflictError(
            "骨架生成只使用作者构想与项目已有世界对象，不支持排除范围；"
            "请清除排除项后重试"
        )


async def _prepare(db, novel_id, args, *, context=None):
    _require_scope(context)
    from modules.world.services.worldbuilding.opening_skeleton import (
        OpeningSkeletonService,
    )

    await require_active_project(db, novel_id)
    catalog = await OpeningSkeletonService().existing_catalog(db, novel_id)
    return {
        "title": "准备新书开篇世界观骨架",
        "existing_object_count": len(catalog),
        "after": args.model_dump(mode="json"),
        "effect": (
            "一次生成待审世界观骨架采用包（世界前提、规则、地点、势力、人物、"
            "传说与核心关系）；输出只作候选，逐条取舍后才采用，可整体撤销"
        ),
    }


async def _apply(db, novel_id, args, preview, *, context=None):
    _require_scope(context)
    from modules.world.services.worldbuilding.opening_skeleton import (
        OPENING_SKELETON_TASK_TYPE,
        OpeningSkeletonService,
    )

    if await _prepare(db, novel_id, args, context=context) != preview:
        raise ConflictError("项目已有对象已变化，请重新查看骨架准备情况")
    request = DraftOpeningSkeleton.task_request(novel_id, args)
    submitted = await OpeningSkeletonService().submit_task(
        db,
        request,
        llm_snapshot=context.llm_snapshot if context else None,
        internal_meta=context.internal_meta if context else None,
        operation_id=(
            str(context.operation_id) if context and context.operation_id else None
        ),
    )
    return {
        "type": OPENING_SKELETON_TASK_TYPE,
        "id": submitted["task_id"],
        "task_id": submitted["task_id"],
        "task_type": OPENING_SKELETON_TASK_TYPE,
        "status": submitted["status"],
        "label": "世界观骨架生成中",
    }


async def _read_result(db, novel_id, reference):
    from infrastructure.tasks.facade import get_completed_task_payload

    task = await get_completed_task_payload(
        db,
        task_id=reference["task_id"],
        task_type="world_opening_skeleton",
        novel_id=novel_id,
    )
    if task is None:
        return {
            "status": "incomplete",
            "omissions": ["骨架生成尚未完成，可查看原任务回执"],
        }
    result = dict(task.result or {})
    receipt = result.get("_opening_skeleton_result")
    if not isinstance(receipt, dict):
        receipt = result
    suggestion_id = str(receipt.get("package_suggestion_id") or "")
    review_status = receipt.get("knowledge_review_status")
    return {
        "status": "completed" if suggestion_id else "failed",
        "authority": "骨架包尚未采用；逐条取舍并采用前不进入任何生成上下文",
        "package_suggestion_id": suggestion_id,
        "knowledge_review_status": review_status,
        "counts": {
            key: receipt.get(key)
            for key in (
                "created_entities",
                "fill_existing",
                "reference_existing",
                "attached_aliases",
                "relations",
            )
        },
        "dropped_items": receipt.get("dropped_items") or [],
        "omissions": (
            ["知识审查未通过：包可查看但不能采用，请重新生成"]
            if review_status == "blocked"
            else []
        ),
    }


# 纯数据声明（AO-5）：组合根 app/assistant_operation_registry 物化。
OPERATIONS_SPEC = {
    "world.draft_opening_skeleton": {
        "label": "起草新书开篇世界观骨架",
        "schema": DraftOpeningSkeleton,
        "prepare": _prepare,
        "apply": _apply,
        "permission": "suggest",
        "read_result": _read_result,
    },
}
