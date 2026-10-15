"""Read frozen Scene evidence for one actual spatial authorization."""

from copy import deepcopy
from uuid import UUID

from sqlalchemy import select

from core.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.tasks.facade import list_task_lifecycle_contracts
from modules.evolution.models import (
    EvolutionFrozenAttempt,
    EvolutionReceiptRecord,
    EvolutionRun,
)
from modules.project.facade import require_active_project


async def read_map_spatial_evaluation_receipts(
    db, novel_id, run_key, operation_id, scene_ids
):
    scenes = list(dict.fromkeys(str(UUID(str(value))) for value in scene_ids))
    if not scenes or len(scenes) > 200:
        raise ValidationError("评测须指定 1–200 个场景")
    with db.no_autoflush:
        await require_active_project(db, novel_id)
        run = await db.scalar(
            select(EvolutionRun).where(
                EvolutionRun.novel_id == UUID(str(novel_id)),
                EvolutionRun.run_key == run_key,
            )
        )
        if run is None:
            raise NotFoundError("没有找到本作品的演化运行")
        plan = run.reading_plan_json or {}
        segment = next(
            (
                item
                for item in plan.get("segments", [])
                if item.get("operation_id") == str(operation_id)
            ),
            None,
        )
        rescan = next(
            (
                item
                for item in plan.get("spatial_rescans", [])
                if item.get("operation_id") == str(operation_id)
            ),
            None,
        )
        if segment is None and rescan is None:
            raise ConflictError("授权操作不属于本次演化运行")
        if segment and not (segment.get("request") or {}).get("discover_spatial"):
            raise ConflictError("该授权未开启空间发现")
        authorization = rescan or segment
        first = authorization.get("from_scene_index" if rescan else "first_scene_index")
        last = authorization.get("through_scene_index" if rescan else "last_scene_index")
        steps = [
            item for item in plan.get("steps", []) if str(item.get("scene_id")) in scenes
        ]
        if {str(item["scene_id"]) for item in steps} != set(scenes) or any(
            first is None or last is None or not first <= item["scene_index"] <= last
            for item in steps
        ):
            raise ConflictError("请求场景不在这次冻结授权范围内")
        attempts = (
            await db.scalars(
                select(EvolutionFrozenAttempt)
                .where(
                    EvolutionFrozenAttempt.novel_id == run.novel_id,
                    EvolutionFrozenAttempt.run_key == run_key,
                    EvolutionFrozenAttempt.payload_json["scene_id"]
                    .as_string()
                    .in_(scenes),
                )
                .order_by(EvolutionFrozenAttempt.created_at, EvolutionFrozenAttempt.id)
            )
        ).all()
        if rescan:
            attempts = [
                item
                for item in attempts
                if item.attempt_key in rescan.get("attempt_ids", [])
            ]
        keys = [item.attempt_key for item in attempts]
        receipts = (
            (
                await db.scalars(
                    select(EvolutionReceiptRecord).where(
                        EvolutionReceiptRecord.novel_id == run.novel_id,
                        EvolutionReceiptRecord.run_key == run_key,
                        EvolutionReceiptRecord.attempt_key.in_(keys),
                    )
                )
            ).all()
            if keys
            else []
        )
        request = (segment or {}).get("request") or {}
        task_id = (rescan or {}).get("task_id") or plan.get("task_id")
        lifecycle = (
            (
                await list_task_lifecycle_contracts(
                    db, task_ids=[task_id], novel_id=str(novel_id), max_heartbeat_gap=120
                )
            ).get(task_id)
            if task_id
            else None
        )
        return {
            "schema_version": 1,
            "novel_id": str(run.novel_id),
            "run_key": run_key,
            "operation_id": str(operation_id),
            "scene_ids": scenes,
            "status": run.status,
            "committed_scene_index": run.committed_scene_index,
            "task_id": task_id,
            "task_lifecycle": {
                key: getattr(lifecycle, key)
                for key in (
                    "task_id",
                    "task_type",
                    "status",
                    "attempt",
                    "stale",
                    "recovery_required",
                )
            }
            if lifecycle
            else None,
            "request": {
                key: deepcopy(request.get(key))
                for key in (
                    "operation_id",
                    "mode",
                    "run_key",
                    "end_chapter",
                    "from_scene_index",
                    "request_limit",
                    "budget_mode",
                    "discover_details",
                    "discover_spatial",
                    "expected_fingerprint",
                    "authorization_confirmed",
                )
            },
            "authorization_range": {"first_scene_index": first, "last_scene_index": last},
            "spatial_rescan": {
                key: deepcopy(rescan.get(key))
                for key in (
                    "operation_id",
                    "request_hash",
                    "task_id",
                    "status",
                    "attempt_ids",
                    "from_scene_index",
                    "through_scene_index",
                    "scene_count",
                )
            }
            if rescan
            else None,
            "steps": [
                {
                    key: deepcopy(item.get(key))
                    for key in (
                        "scene_id",
                        "scene_index",
                        "source_binding",
                        "source_content_mode",
                    )
                }
                for item in steps
            ],
            "attempts": [
                {
                    "id": str(item.id),
                    "attempt_id": item.attempt_key,
                    "status": item.status,
                    "operation_binding_status": "known" if rescan else "unknown",
                    "source_manifest_hash": item.source_manifest_hash,
                    **{
                        key: deepcopy(item.payload_json.get(key))
                        for key in (
                            "scene_id",
                            "scene_index",
                            "source_binding",
                            "source_content_mode",
                            "spatial_method_fingerprint",
                            "optional_stage_version",
                            "optional_scene_stage",
                            "optional_step_coverage",
                            "spatial_discovery_result",
                            "spatial_stage_result",
                        )
                    },
                    "journals": {
                        key: {
                            field: deepcopy((item.payload_json.get(key) or {}).get(field))
                            for field in ("stage", "input_hash", "paid_call_receipt")
                        }
                        for key in ("scene_spatial_discovery", "scene_spatial_review")
                    },
                }
                for item in attempts
            ],
            "receipts": [
                {
                    "id": str(item.id),
                    "attempt_id": item.attempt_key,
                    "execution_status": item.execution_status,
                    "committed_scene_index": item.committed_scene_index,
                    **{
                        key: deepcopy(item.receipt_json.get(key))
                        for key in (
                            "run_id",
                            "source_manifest_hash",
                            "coverage",
                            "committed_prefix",
                            "world_result_refs",
                            "outcome_status",
                            "freshness",
                        )
                    },
                }
                for item in receipts
            ],
            "coverage": [
                {
                    "scene_id": scene,
                    "status": "recorded"
                    if any(
                        str(item.payload_json.get("scene_id")) == scene
                        for item in attempts
                    )
                    else "unknown",
                }
                for scene in scenes
            ],
            "truncated": False,
            "omitted_count": 0,
            "human_validated": False,
        }
