"""新书开篇世界观骨架任务路由。

入队 ``world_opening_skeleton`` 任务；幂等键为 operation_id + 请求指纹。
本包阶段方向由参数传入，Assistant 方向卡 step 后续经
``world.draft_opening_skeleton`` suggest 操作复用同一任务。包的读取、
预览（含逐条冲突）、条目取舍与回滚都走 adoption-packages 既有路由。
"""

from __future__ import annotations

from fastapi import HTTPException

from core.dependencies import DbSession
from modules.project.facade import (
    build_project_llm_execution_snapshot,
    require_active_project,
)
from modules.world.api._shared import router
from modules.world.schemas import WorldOpeningSkeletonTaskRequest
from modules.world.services.worldbuilding.opening_skeleton import (
    OpeningSkeletonService,
)


@router.post("/opening-skeleton/tasks", status_code=202)
async def enqueue_opening_skeleton(
    db: DbSession,
    data: WorldOpeningSkeletonTaskRequest,
) -> dict:
    await require_active_project(db, data.novel_id)
    snapshot = await build_project_llm_execution_snapshot(db, data.novel_id)
    try:
        return await OpeningSkeletonService().submit_task(
            db,
            data,
            llm_snapshot=snapshot,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
