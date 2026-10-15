"""HTTP bindings for the author-side Interaction operation catalog.

This router is exported separately so the application composition root can
register the module's ``OPERATIONS_SPEC`` before mounting route trace adapters.
"""

from __future__ import annotations

from fastapi import APIRouter

from core.dependencies import DbSession
from core.errors import ConflictError
from modules.interaction import author_operations as ops
from modules.project.facade import require_active_project_exclusive

router = APIRouter(prefix="/api/interactions/author", tags=["interaction-author"])


async def _prepare(db, op_id: str, data):
    spec = ops.OPERATIONS_SPEC[op_id]
    args = spec["schema"].model_validate(data)
    if getattr(args, "confirmed", False):
        raise ConflictError("准备阶段不能确认或执行操作", code="PREPARE_ONLY")
    preview = await spec["prepare"](
        db,
        str(args.author_project_id),
        args,
        context=None,
    )
    digest = preview.get("preview_hash") or ops._fingerprint(preview)
    return {"operation_id": op_id, "preview": preview, "preview_hash": digest}


async def _confirm(db, op_id: str, data):
    spec = ops.OPERATIONS_SPEC[op_id]
    if spec.get("apply") is None:
        raise ConflictError("该操作没有执行阶段", code="OPERATION_NOT_EXECUTABLE")
    args = spec["schema"].model_validate(data)
    if not getattr(args, "confirmed", False):
        raise ConflictError("执行前需要明确确认", code="CONFIRMATION_REQUIRED")
    await require_active_project_exclusive(db, str(args.author_project_id))
    preview = await spec["prepare"](
        db,
        str(args.author_project_id),
        args,
        context=None,
    )
    digest = preview.get("preview_hash") or ops._fingerprint(preview)
    if not args.expected_preview_hash or args.expected_preview_hash != digest:
        raise ConflictError("预览已变化，请重新核对", code="PREVIEW_STALE")
    result = await spec["apply"](
        db,
        str(args.author_project_id),
        args,
        preview,
        context=None,
    )
    return {"operation_id": op_id, "result": result}


@router.post(
    "/journeys/list",
    openapi_extra={
        "x-novelcraft-operation-id": "interaction.author.journeys.list",
        "x-novelcraft-operation-phase": "prepare",
        "x-novelcraft-operation-trace-fields": {
            "author_project_id": "data.author_project_id",
            "status": "data.status",
        },
    },
)
async def list_author_journeys(db: DbSession, data: ops.ListAuthorJourneysArgs):
    return await _prepare(db, "interaction.author.journeys.list", data.model_dump())


@router.post(
    "/journeys/settings/prepare",
    openapi_extra={
        "x-novelcraft-operation-id": "interaction.author.journey.settings",
        "x-novelcraft-operation-phase": "prepare",
        "x-novelcraft-operation-trace-fields": {
            name: f"data.{name}" for name in ops.UpdateJourneySettingsArgs.model_fields
        },
    },
)
async def prepare_journey_settings(db: DbSession, data: ops.UpdateJourneySettingsArgs):
    return await _prepare(db, "interaction.author.journey.settings", data.model_dump())


@router.post(
    "/journeys/settings/confirm",
    openapi_extra={
        "x-novelcraft-operation-id": "interaction.author.journey.settings",
        "x-novelcraft-operation-phase": "execute",
        "x-novelcraft-operation-confirmation-field": "data.confirmed",
        "x-novelcraft-operation-trace-fields": {
            name: f"data.{name}" for name in ops.UpdateJourneySettingsArgs.model_fields
        },
    },
)
async def confirm_journey_settings(db: DbSession, data: ops.UpdateJourneySettingsArgs):
    return await _confirm(db, "interaction.author.journey.settings", data.model_dump())


@router.post(
    "/journeys/title/prepare",
    openapi_extra={
        "x-novelcraft-operation-id": "interaction.author.journey.rename",
        "x-novelcraft-operation-phase": "prepare",
        "x-novelcraft-operation-trace-fields": {
            name: f"data.{name}" for name in ops.RenameJourneyArgs.model_fields
        },
    },
)
async def prepare_journey_title(db: DbSession, data: ops.RenameJourneyArgs):
    return await _prepare(db, "interaction.author.journey.rename", data.model_dump())


@router.post(
    "/journeys/title/confirm",
    openapi_extra={
        "x-novelcraft-operation-id": "interaction.author.journey.rename",
        "x-novelcraft-operation-phase": "execute",
        "x-novelcraft-operation-confirmation-field": "data.confirmed",
        "x-novelcraft-operation-trace-fields": {
            name: f"data.{name}" for name in ops.RenameJourneyArgs.model_fields
        },
    },
)
async def confirm_journey_title(db: DbSession, data: ops.RenameJourneyArgs):
    return await _confirm(db, "interaction.author.journey.rename", data.model_dump())


@router.post(
    "/journeys/archive/prepare",
    openapi_extra={
        "x-novelcraft-operation-id": "interaction.author.journey.archive",
        "x-novelcraft-operation-phase": "prepare",
        "x-novelcraft-operation-trace-fields": {
            name: f"data.{name}" for name in ops.JourneyStateArgs.model_fields
        },
    },
)
async def prepare_journey_archive(db: DbSession, data: ops.JourneyStateArgs):
    if data.expected_status != "active":
        raise ConflictError("归档操作只接受 active 旅程", code="INVALID_OPERATION_STATE")
    return await _prepare(db, "interaction.author.journey.archive", data.model_dump())


@router.post(
    "/journeys/archive/confirm",
    openapi_extra={
        "x-novelcraft-operation-id": "interaction.author.journey.archive",
        "x-novelcraft-operation-phase": "execute",
        "x-novelcraft-operation-confirmation-field": "data.confirmed",
        "x-novelcraft-operation-trace-fields": {
            name: f"data.{name}" for name in ops.JourneyStateArgs.model_fields
        },
    },
)
async def confirm_journey_archive(db: DbSession, data: ops.JourneyStateArgs):
    if data.expected_status != "active":
        raise ConflictError("归档操作只接受 active 旅程", code="INVALID_OPERATION_STATE")
    return await _confirm(db, "interaction.author.journey.archive", data.model_dump())


@router.post(
    "/journeys/restore/prepare",
    openapi_extra={
        "x-novelcraft-operation-id": "interaction.author.journey.restore",
        "x-novelcraft-operation-phase": "prepare",
        "x-novelcraft-operation-trace-fields": {
            name: f"data.{name}" for name in ops.JourneyStateArgs.model_fields
        },
    },
)
async def prepare_journey_restore(db: DbSession, data: ops.JourneyStateArgs):
    if data.expected_status != "archived":
        raise ConflictError(
            "恢复操作只接受 archived 旅程", code="INVALID_OPERATION_STATE"
        )
    return await _prepare(db, "interaction.author.journey.restore", data.model_dump())


@router.post(
    "/journeys/restore/confirm",
    openapi_extra={
        "x-novelcraft-operation-id": "interaction.author.journey.restore",
        "x-novelcraft-operation-phase": "execute",
        "x-novelcraft-operation-confirmation-field": "data.confirmed",
        "x-novelcraft-operation-trace-fields": {
            name: f"data.{name}" for name in ops.JourneyStateArgs.model_fields
        },
    },
)
async def confirm_journey_restore(db: DbSession, data: ops.JourneyStateArgs):
    if data.expected_status != "archived":
        raise ConflictError(
            "恢复操作只接受 archived 旅程", code="INVALID_OPERATION_STATE"
        )
    return await _confirm(db, "interaction.author.journey.restore", data.model_dump())


@router.post(
    "/journeys/summary/prepare",
    openapi_extra={
        "x-novelcraft-operation-id": "interaction.summary.refresh",
        "x-novelcraft-operation-phase": "prepare",
        "x-novelcraft-operation-trace-fields": {
            name: f"data.{name}" for name in ops.SummaryRefreshArgs.model_fields
        },
    },
)
async def prepare_summary_refresh(db: DbSession, data: ops.SummaryRefreshArgs):
    if data.operation_id is None:
        raise ConflictError("准备摘要刷新需要操作标识", code="OPERATION_ID_REQUIRED")
    return await _prepare(db, "interaction.summary.refresh", data.model_dump())


@router.post(
    "/journeys/summary/confirm",
    openapi_extra={
        "x-novelcraft-operation-id": "interaction.summary.refresh",
        "x-novelcraft-operation-phase": "execute",
        "x-novelcraft-operation-confirmation-field": "data.confirmed",
        "x-novelcraft-operation-trace-fields": {
            name: f"data.{name}" for name in ops.SummaryRefreshArgs.model_fields
        },
    },
)
async def confirm_summary_refresh(db: DbSession, data: ops.SummaryRefreshArgs):
    if data.operation_id is None:
        raise ConflictError("确认摘要刷新需要原操作标识", code="OPERATION_ID_REQUIRED")
    return await _confirm(db, "interaction.summary.refresh", data.model_dump())


@router.post(
    "/journeys/summary/result",
    openapi_extra={
        "x-novelcraft-operation-id": "interaction.summary.refresh",
        "x-novelcraft-operation-phase": "prepare",
        "x-novelcraft-operation-trace-fields": {
            name: f"data.{name}" for name in ops.SummaryRefreshArgs.model_fields
        },
    },
)
async def read_summary_refresh_result(db: DbSession, data: ops.SummaryRefreshArgs):
    return await ops._summary_read_result(
        db,
        str(data.author_project_id),
        data,
        context=None,
    )
