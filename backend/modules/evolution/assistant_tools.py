"""Assistant-owned previews for Evolution authorization; never starts work."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from modules.evolution import spatial_rescan, workflow


class PrepareSpatialReading(workflow.ReadingRequest):
    @model_validator(mode="after")
    def spatial_enabled(self):
        if not self.discover_spatial:
            raise ValueError("助手只准备已开启空间发现的演化阅读预览")
        return self


class PrepareReading(workflow.ReadingRequest):
    """Prepare any existing Evolution read mode without starting its run."""


class PrepareSpatialRescan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_key: str = Field(min_length=1, max_length=120)
    operation_id: UUID
    from_scene_index: int = Field(ge=0)
    through_scene_index: int = Field(ge=0)
    request_limit: int | None = Field(default=None, ge=1, le=1000)

    @model_validator(mode="after")
    def valid_range(self):
        if self.through_scene_index < self.from_scene_index:
            raise ValueError("请选择有效的空间补扫范围")
        return self


async def _reading_preview(db, novel_id, args, *, context=None):
    preview = await workflow.preview_reading(db, novel_id, args)
    return {
        "operation_id": str(args.operation_id),
        "request": args.model_dump(mode="json"),
        "authorization_preview": preview,
        "effect": "仅计算阅读范围、请求次数和预算预览；不会开始阅读或产生模型请求",
    }


async def _reading_apply(db, novel_id, args, preview, *, context=None):
    if await _reading_preview(db, novel_id, args, context=context) != preview:
        from core.errors import ConflictError

        raise ConflictError("演化阅读范围或预算已变化，请重新准备预览")
    return {
        "type": "evolution_reading_authorization_preview",
        "operation_id": str(args.operation_id),
        "page": "evolution",
        "authorization_preview": preview["authorization_preview"],
        "authorization_required": True,
    }


async def _rescan_preview(db, novel_id, args, *, context=None):
    request = spatial_rescan.SpatialRescanRequest(
        operation_id=args.operation_id,
        from_scene_index=args.from_scene_index,
        through_scene_index=args.through_scene_index,
        request_limit=args.request_limit,
    )
    preview = await spatial_rescan.preview_spatial_rescan(
        db, novel_id, args.run_key, request
    )
    return {
        "run_key": args.run_key,
        "request": request.model_dump(mode="json"),
        "authorization_preview": preview,
        "effect": "仅计算已读范围的空间补扫请求和预算；不会开始补扫或产生模型请求",
    }


async def _rescan_apply(db, novel_id, args, preview, *, context=None):
    if await _rescan_preview(db, novel_id, args, context=context) != preview:
        from core.errors import ConflictError

        raise ConflictError("空间补扫范围或预算已变化，请重新准备预览")
    return {
        "type": "evolution_spatial_rescan_authorization_preview",
        "run_key": args.run_key,
        "operation_id": str(args.operation_id),
        "page": "evolution",
        "authorization_preview": preview["authorization_preview"],
        "authorization_required": True,
    }


OPERATIONS_SPEC = {
    "evolution.prepare_reading": {
        "label": "准备演化阅读授权预览",
        "schema": PrepareReading,
        "prepare": _reading_preview,
        "apply": _reading_apply,
        "permission": "confirm",
        "op_version": "1",
        "description": (
            "为初读、追加、续读或重读计算演化范围与预算；"
            "作者仍须在演化工作台单独确认，助手不会启动运行。"
        ),
        "risk_level": "R4",
        "fee_category": "free",
        "reversibility": "discard_preview",
        "preconditions": ("作品正文和原运行基线仍有效",),
        "produces": ("reading_authorization_preview",),
        "target_type": "evolution_reading",
        "ai_available": True,
        "transaction_mode": "single_transaction",
        "trace_rule": {
            "parameter_fields": (
                "operation_id",
                "mode",
                "run_key",
                "from_scene_index",
                "entity_id",
                "observation_id",
                "end_chapter",
                "request_limit",
                "budget_mode",
                "discover_details",
                "discover_spatial",
            ),
            "mode": "per_call",
            "parameter_policy": "schema_safe",
        },
    },
    "evolution.prepare_spatial_reading": {
        "label": "准备空间发现阅读授权预览",
        "schema": PrepareSpatialReading,
        "prepare": _reading_preview,
        "apply": _reading_apply,
    },
    "evolution.prepare_spatial_rescan": {
        "label": "准备空间补扫授权预览",
        "schema": PrepareSpatialRescan,
        "prepare": _rescan_preview,
        "apply": _rescan_apply,
    },
}
