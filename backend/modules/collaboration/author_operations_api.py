"""Author-facing HTTP bindings for the Collaboration operation catalog.

Composition registers ``assistant_tools.OPERATIONS_SPEC`` before mounting this
router so the shared operation trace adapter can validate every route binding.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from core.dependencies import DbSession
from core.errors import ConflictError
from modules.collaboration import assistant_tools as ops
from modules.project.facade import (
    require_active_project,
    require_active_project_exclusive,
)

router = APIRouter(
    prefix="/api/collaboration/author-operations",
    tags=["collaboration-author-operations"],
)


async def _active_project(db: DbSession, novel_id: UUID):
    await require_active_project(db, str(novel_id))


def _hash_preview(preview: dict) -> str:
    return preview.get("preview_hash") or ops._hash(preview)


async def _prepare(db, novel_id: UUID, op_id: str, data):
    spec = ops.OPERATIONS_SPEC[op_id]
    args = spec["schema"].model_validate(data)
    if getattr(args, "confirmed", False):
        raise ConflictError("准备阶段不能确认或执行操作", code="PREPARE_ONLY")
    preview = await spec["prepare"](db, str(novel_id), args, context=None)
    return {
        "operation_id": op_id,
        "preview": preview,
        "preview_hash": _hash_preview(preview),
    }


async def _confirm(db, novel_id: UUID, op_id: str, data):
    spec = ops.OPERATIONS_SPEC[op_id]
    if spec.get("apply") is None:
        raise ConflictError("该操作没有执行阶段", code="OPERATION_NOT_EXECUTABLE")
    args = spec["schema"].model_validate(data)
    if not getattr(args, "confirmed", False):
        raise ConflictError("执行前需要明确确认", code="CONFIRMATION_REQUIRED")
    if not args.expected_preview_hash:
        raise ConflictError("缺少本次预览指纹", code="PREVIEW_REQUIRED")
    await require_active_project_exclusive(db, str(novel_id))
    if op_id in {
        "collaboration.workspace.create",
        "collaboration.workspace.check",
        "collaboration.workspace.atomic_adopt",
    }:
        # Each domain service checks its immutable operation receipt first.
        # Recomputing a preview here would reject a successful retry after
        # the workspace, check, or adopted sources changed.
        result = await spec["apply"](db, str(novel_id), args, None, context=None)
        return {"operation_id": op_id, "result": result}
    preview = await spec["prepare"](db, str(novel_id), args, context=None)
    if _hash_preview(preview) != args.expected_preview_hash:
        raise ConflictError("预览已变化，请重新核对", code="PREVIEW_STALE")
    result = await spec["apply"](db, str(novel_id), args, preview, context=None)
    return {"operation_id": op_id, "result": result}


async def _read_result(db, novel_id: UUID, op_id: str, data):
    spec = ops.OPERATIONS_SPEC[op_id]
    reader = spec.get("read_result")
    if reader is None:
        raise ConflictError("该操作没有回执查询", code="RESULT_UNAVAILABLE")
    args = spec["schema"].model_validate(data)
    await require_active_project(db, str(novel_id))
    return await reader(db, str(novel_id), args, context=None)


def _trace_fields(schema):
    return {name: f"data.{name}" for name in schema.model_fields}


@router.post(
    "/workspaces/create/prepare",
    dependencies=[Depends(_active_project)],
    openapi_extra={
        "x-novelcraft-operation-id": "collaboration.workspace.create",
        "x-novelcraft-operation-phase": "prepare",
        "x-novelcraft-operation-trace-fields": _trace_fields(ops.CreateWorkspaceArgs),
    },
)
async def prepare_workspace_create(
    db: DbSession, novel_id: UUID, data: ops.CreateWorkspaceArgs
):
    return await _prepare(
        db, novel_id, "collaboration.workspace.create", data.model_dump()
    )


@router.post(
    "/workspaces/create/confirm",
    openapi_extra={
        "x-novelcraft-operation-id": "collaboration.workspace.create",
        "x-novelcraft-operation-confirmation-field": "data.confirmed",
        "x-novelcraft-operation-trace-fields": _trace_fields(ops.CreateWorkspaceArgs),
    },
)
async def confirm_workspace_create(
    db: DbSession, novel_id: UUID, data: ops.CreateWorkspaceArgs
):
    return await _confirm(
        db, novel_id, "collaboration.workspace.create", data.model_dump()
    )


@router.post(
    "/workspaces/inspect",
    dependencies=[Depends(_active_project)],
    openapi_extra={
        "x-novelcraft-operation-id": "collaboration.workspace.inspect",
        "x-novelcraft-operation-phase": "prepare",
        "x-novelcraft-operation-trace-fields": _trace_fields(ops.WorkspaceInspectArgs),
    },
)
async def inspect_workspace(
    db: DbSession, novel_id: UUID, data: ops.WorkspaceInspectArgs
):
    return await _prepare(
        db, novel_id, "collaboration.workspace.inspect", data.model_dump()
    )


@router.post(
    "/workspaces/edit/prepare",
    dependencies=[Depends(_active_project)],
    openapi_extra={
        "x-novelcraft-operation-id": "collaboration.workspace.edit",
        "x-novelcraft-operation-phase": "prepare",
        "x-novelcraft-operation-trace-fields": _trace_fields(ops.WorkspaceEditArgs),
    },
)
async def prepare_workspace_edit(
    db: DbSession, novel_id: UUID, data: ops.WorkspaceEditArgs
):
    return await _prepare(db, novel_id, "collaboration.workspace.edit", data.model_dump())


@router.post(
    "/workspaces/edit/confirm",
    openapi_extra={
        "x-novelcraft-operation-id": "collaboration.workspace.edit",
        "x-novelcraft-operation-confirmation-field": "data.confirmed",
        "x-novelcraft-operation-trace-fields": _trace_fields(ops.WorkspaceEditArgs),
    },
)
async def confirm_workspace_edit(
    db: DbSession, novel_id: UUID, data: ops.WorkspaceEditArgs
):
    return await _confirm(db, novel_id, "collaboration.workspace.edit", data.model_dump())


@router.post(
    "/workspaces/seal/prepare",
    dependencies=[Depends(_active_project)],
    openapi_extra={
        "x-novelcraft-operation-id": "collaboration.workspace.seal",
        "x-novelcraft-operation-phase": "prepare",
        "x-novelcraft-operation-trace-fields": _trace_fields(ops.WorkspaceSealArgs),
    },
)
async def prepare_workspace_seal(
    db: DbSession, novel_id: UUID, data: ops.WorkspaceSealArgs
):
    return await _prepare(db, novel_id, "collaboration.workspace.seal", data.model_dump())


@router.post(
    "/workspaces/seal/confirm",
    openapi_extra={
        "x-novelcraft-operation-id": "collaboration.workspace.seal",
        "x-novelcraft-operation-confirmation-field": "data.confirmed",
        "x-novelcraft-operation-trace-fields": _trace_fields(ops.WorkspaceSealArgs),
    },
)
async def confirm_workspace_seal(
    db: DbSession, novel_id: UUID, data: ops.WorkspaceSealArgs
):
    return await _confirm(db, novel_id, "collaboration.workspace.seal", data.model_dump())


@router.post(
    "/workspaces/check/prepare",
    dependencies=[Depends(_active_project)],
    openapi_extra={
        "x-novelcraft-operation-id": "collaboration.workspace.check",
        "x-novelcraft-operation-phase": "prepare",
        "x-novelcraft-operation-trace-fields": _trace_fields(ops.WorkspaceCheckArgs),
    },
)
async def prepare_workspace_check(
    db: DbSession, novel_id: UUID, data: ops.WorkspaceCheckArgs
):
    return await _prepare(
        db, novel_id, "collaboration.workspace.check", data.model_dump()
    )


@router.post(
    "/workspaces/check/confirm",
    openapi_extra={
        "x-novelcraft-operation-id": "collaboration.workspace.check",
        "x-novelcraft-operation-confirmation-field": "data.confirmed",
        "x-novelcraft-operation-trace-fields": _trace_fields(ops.WorkspaceCheckArgs),
    },
)
async def confirm_workspace_check(
    db: DbSession, novel_id: UUID, data: ops.WorkspaceCheckArgs
):
    return await _confirm(
        db, novel_id, "collaboration.workspace.check", data.model_dump()
    )


@router.post(
    "/workspaces/check/result",
    dependencies=[Depends(_active_project)],
    openapi_extra={
        "x-novelcraft-operation-id": "collaboration.workspace.check",
        "x-novelcraft-operation-phase": "prepare",
        "x-novelcraft-operation-trace-fields": _trace_fields(ops.WorkspaceCheckArgs),
    },
)
async def read_workspace_check_result(
    db: DbSession, novel_id: UUID, data: ops.WorkspaceCheckArgs
):
    return await _read_result(
        db, novel_id, "collaboration.workspace.check", data.model_dump()
    )


@router.post(
    "/workspaces/adoption/prepare",
    dependencies=[Depends(_active_project)],
    openapi_extra={
        "x-novelcraft-operation-id": "collaboration.workspace.atomic_adopt",
        "x-novelcraft-operation-phase": "prepare",
        "x-novelcraft-operation-trace-fields": _trace_fields(ops.AtomicAdoptionArgs),
    },
)
async def prepare_workspace_adoption(
    db: DbSession, novel_id: UUID, data: ops.AtomicAdoptionArgs
):
    return await _prepare(
        db, novel_id, "collaboration.workspace.atomic_adopt", data.model_dump()
    )


@router.post(
    "/workspaces/adoption/confirm",
    openapi_extra={
        "x-novelcraft-operation-id": "collaboration.workspace.atomic_adopt",
        "x-novelcraft-operation-confirmation-field": "data.confirmed",
        "x-novelcraft-operation-trace-fields": _trace_fields(ops.AtomicAdoptionArgs),
    },
)
async def confirm_workspace_adoption(
    db: DbSession, novel_id: UUID, data: ops.AtomicAdoptionArgs
):
    return await _confirm(
        db, novel_id, "collaboration.workspace.atomic_adopt", data.model_dump()
    )


@router.post(
    "/workspaces/adoption/result",
    dependencies=[Depends(_active_project)],
    openapi_extra={
        "x-novelcraft-operation-id": "collaboration.workspace.atomic_adopt",
        "x-novelcraft-operation-phase": "prepare",
        "x-novelcraft-operation-trace-fields": _trace_fields(ops.AtomicAdoptionArgs),
    },
)
async def read_workspace_adoption_result(
    db: DbSession, novel_id: UUID, data: ops.AtomicAdoptionArgs
):
    return await _read_result(
        db, novel_id, "collaboration.workspace.atomic_adopt", data.model_dump()
    )
