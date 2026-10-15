"""Read-only linkage between a map guide and an independently authorized run."""

from uuid import UUID

from sqlalchemy import select

from core.errors import ConflictError, NotFoundError
from modules.evolution.models import EvolutionRun
from modules.evolution.workflow import reading_status


async def read_map_cold_start_status(db, novel_id: str, run_key: str, operation_id: str):
    status = await reading_status(db, novel_id, run_key)
    row = await db.scalar(
        select(EvolutionRun).where(
            EvolutionRun.novel_id == UUID(str(novel_id)), EvolutionRun.run_key == run_key
        )
    )
    if row is None:
        raise NotFoundError("没有找到本作品的演化阅读")
    plan = row.reading_plan_json or {}
    segment = next(
        (
            item
            for item in plan.get("segments", [])
            if item.get("operation_id") == operation_id
        ),
        None,
    )
    rescan = next(
        (
            item
            for item in status["run"].get("spatial_rescans", [])
            if item.get("operation_id") == operation_id
        ),
        None,
    )
    rescan_entry = next(
        (
            item
            for item in plan.get("spatial_rescans", [])
            if item.get("operation_id") == operation_id
        ),
        {},
    )
    if segment is None and rescan is None:
        raise ConflictError("这次演化授权不属于当前地图流程，请在演化页核对")
    if segment is not None and not (segment.get("request") or {}).get("discover_spatial"):
        raise ConflictError("这次阅读没有授权空间发现")
    return {
        "run_key": run_key,
        "operation_id": operation_id,
        "status": rescan["status"] if rescan else status["run"]["status"],
        "request": (segment or {}).get("request"),
        "spatial_rescan": rescan,
        "authorization_request_hash": rescan_entry.get("request_hash"),
        "completed_scenes": status["run"]["completed_scenes"],
        "total_scenes": status["run"]["total_scenes"],
        "coverage": status["run"].get("optional_step_coverage", {}),
        "authorization_required": False,
        "can_start_or_resume": False,
    }
