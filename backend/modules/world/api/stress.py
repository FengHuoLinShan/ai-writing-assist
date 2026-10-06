"""团队压力测试报告路由。"""

from __future__ import annotations

from fastapi import HTTPException

from core.api_params import NovelIdQuery
from core.dependencies import DbSession
from modules.project.facade import require_active_project
from modules.world.api._shared import router
from modules.world.team_stress import StressDecision


@router.get("/stress-reports/{report_id}")
async def get_world_stress_report(db: DbSession, report_id: str, novel_id: NovelIdQuery):
    from modules.account.facade import is_demo_readonly_principal
    from modules.world.team_stress import read_stress_report

    await require_active_project(db, novel_id)
    if is_demo_readonly_principal():
        raise HTTPException(status_code=404, detail="报告不存在")
    return await read_stress_report(db, novel_id, report_id)


@router.post("/stress-reports/{report_id}/decisions")
async def decide_world_stress_report(
    db: DbSession, report_id: str, data: StressDecision, novel_id: NovelIdQuery
):
    from modules.account.facade import is_demo_readonly_principal
    from modules.world.team_stress import decide_stress_scenario

    await require_active_project(db, novel_id)
    if is_demo_readonly_principal():
        raise HTTPException(status_code=404, detail="报告不存在")
    return await decide_stress_scenario(db, novel_id, report_id, data)
