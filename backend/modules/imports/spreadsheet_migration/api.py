"""表格迁移 HTTP 路由（计划 §3.6）— /api/imports/migrations。"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from core.api_params import NovelIdForm, NovelIdQuery
from core.dependencies import DbSession
from modules.account.facade import current_account_id
from modules.imports.spreadsheet_migration.constants import MAX_FILE_BYTES
from modules.imports.spreadsheet_migration.schemas import (
    MigrationAiRunRequest,
    MigrationApplyRequest,
    MigrationDecisionsRequest,
    MigrationMappingRequest,
    MigrationRollbackRequest,
)
from modules.imports.spreadsheet_migration.service import SpreadsheetMigrationService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/imports/migrations", tags=["imports"])
_service = SpreadsheetMigrationService()
UPLOAD_READ_CHUNK_SIZE = 1024 * 1024

_ERROR_MESSAGES = {
    "migration_rows_cleared": "该迁移的表格内容已随采用清除",
    "migration_preview_stale": "预览已过期，请重新确认",
    "migration_revision_stale": "迁移会话已更新，请刷新后重试",
    "migration_already_applied": "该迁移已采用过，不能重复采用",
    "migration_not_applied": "只有已采用的迁移才能撤销",
}


def _error_message(code: str | None) -> str:
    if not code:
        return "迁移记录暂时不可用"
    return _ERROR_MESSAGES.get(code, "迁移记录暂时不可用")


async def _read_spreadsheet_in_chunks(file: UploadFile) -> bytes:
    chunks: list[bytes] = []
    file_size = 0
    while chunk := await file.read(UPLOAD_READ_CHUNK_SIZE):
        file_size += len(chunk)
        if file_size > MAX_FILE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"单个表格文件不能超过 {MAX_FILE_BYTES // (1024 * 1024)}MB",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _sheet_entry(
    manifest_sheet: dict[str, Any],
    mapping_sheet: dict[str, Any] | None,
    rows: list[list[str]] | None,
) -> dict[str, Any]:
    suggested = manifest_sheet.get("suggested", {}) or {}
    kind = mapping_sheet.get("kind") if mapping_sheet else suggested.get("kind", "skip")
    header_row = (
        mapping_sheet.get("header_row")
        if mapping_sheet
        else suggested.get("header_row", 0)
    )
    headers: list[str] = manifest_sheet.get("headers", []) or []
    columns_map: dict[str, str] = dict(
        (mapping_sheet or {}).get("columns", {}) or suggested.get("columns", {})
    )
    column_keys = [f"c{index}" for index in range(len(headers))]
    columns = [
        {
            "column_key": column_keys[index] if index < len(column_keys) else f"c{index}",
            "header": headers[index] if index < len(headers) else "",
            "target": columns_map.get(
                column_keys[index] if index < len(column_keys) else f"c{index}",
                "ignore",
            ),
            "target_suggested": columns_map.get(
                column_keys[index] if index < len(column_keys) else f"c{index}"
            )
            == (suggested.get("columns", {}) or {}).get(
                column_keys[index] if index < len(column_keys) else f"c{index}"
            ),
        }
        for index in range(max(len(headers), len(columns_map)))
    ]
    warnings = [
        {"code": "sheet_warning", "message": message}
        for message in manifest_sheet.get("warnings", [])
    ]
    sample_rows: list[list[str]] = []
    if rows:
        start = int(header_row or 0) + 1
        sample_rows = [row for row in rows[start : start + 5] if row]
    return {
        "sheet_key": manifest_sheet["sheet_key"],
        "file_key": "",
        "name": manifest_sheet["name"],
        "hidden": bool(manifest_sheet.get("hidden")),
        "kind": kind,
        "kind_suggested": kind == suggested.get("kind"),
        "header_row": int(header_row or 0),
        "default_entity_type": (mapping_sheet or {}).get("default_entity_type"),
        "row_count": int(manifest_sheet.get("row_count", 0)),
        "columns": columns,
        "sample_rows": sample_rows,
        "warnings": warnings,
    }


def _serialize_session(
    session: Any,
    *,
    with_preview: bool = True,
) -> dict[str, Any]:
    mapping_sheets = {
        sheet.get("sheet_key"): sheet
        for sheet in session.mapping_json.get("sheets", [])
    }
    sheets: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    for file in session.file_manifest:
        for manifest_sheet in file.get("sheets", []):
            key = manifest_sheet["sheet_key"]
            entry = _sheet_entry(
                manifest_sheet,
                mapping_sheets.get(key),
                session.rows_json.get(key),
            )
            entry["file_key"] = file.get("file_key", "")
            sheets.append(entry)
        files.append(
            {
                "file_key": file.get("file_key", ""),
                "file_name": file.get("file_name", ""),
                "file_type": file.get("file_type", ""),
                "size": int(file.get("size", 0)),
            }
        )

    ai_authorization = session.ai_authorization or {}
    ai_blocked = 0
    for operation in ("outline", "cleanup"):
        for group in (session.ai_result_json or {}).get(operation, []) or []:
            if isinstance(group, dict) and (group.get("governance") or {}).get(
                "status"
            ) != "passed":
                ai_blocked += 1

    preview = None
    if with_preview and session.plan_json:
        stored = session.plan_json.get("preview")
        if isinstance(stored, dict):
            preview = dict(stored)
            preview["preview_hash"] = session.preview_hash or ""

    receipt = session.receipt_json or {}
    receipt_summary = None
    if receipt:
        counts = receipt.get("counts", {})
        receipt_summary = {
            **{key: int(value) for key, value in counts.items()},
            "outline": bool(counts.get("outline")),
            "can_rollback": session.status == "applied",
        }

    return {
        "id": str(session.id),
        "status": session.status,
        "revision": session.revision,
        "created_at": session.created_at.isoformat() if session.created_at else "",
        "applied_at": session.applied_at.isoformat() if session.applied_at else None,
        "rolled_back_at": session.rolled_back_at.isoformat()
        if session.rolled_back_at
        else None,
        "files": files,
        "sheets": sheets,
        "options": session.mapping_json.get(
            "options",
            {
                "written_chapter_policy": "reference_only",
                "outline_head_policy": "create_if_missing",
            },
        ),
        "preview": preview,
        "ai": {
            "status": session.ai_status,
            "task_id": str(session.ai_task_id) if session.ai_task_id else None,
            "estimate": ai_authorization.get("estimate"),
            "blocked_count": ai_blocked,
        },
        "receipt_summary": receipt_summary,
        "error": (
            {"code": session.error_code, "message": _error_message(session.error_code)}
            if session.error_code
            else None
        ),
    }


def _list_item(session: Any) -> dict[str, Any]:
    receipt = session.receipt_json or {}
    counts = receipt.get("counts", {}) if session.status != "draft" else {}
    return {
        "id": str(session.id),
        "status": session.status,
        "file_names": [
            file.get("file_name", "") for file in session.file_manifest
        ],
        "counts": {key: int(value) for key, value in counts.items()},
        "created_at": session.created_at.isoformat() if session.created_at else "",
        "applied_at": session.applied_at.isoformat() if session.applied_at else None,
        "can_rollback": session.status == "applied",
    }


async def _load_session(
    db: DbSession,
    *,
    session_id: str,
    novel_id: str,
    for_update: bool = False,
):
    await _require_active_project(db, novel_id)
    owner_id = str(current_account_id())
    return await _service.get_session(
        db,
        session_id=session_id,
        novel_id=novel_id,
        owner_id=owner_id,
        for_update=for_update,
    )


@router.post("", status_code=201)
async def create_migration(
    db: DbSession,
    *,
    novel_id: NovelIdForm,
    files: list[UploadFile] = File(..., description="表格文件（.xlsx/.csv，1–5 个）"),
) -> dict[str, Any]:
    await _require_active_project(db, novel_id)
    owner_id = str(current_account_id())
    payload: list[tuple[str, bytes]] = []
    for file in files:
        data = await _read_spreadsheet_in_chunks(file)
        payload.append((os.path.basename(file.filename or "unknown"), data))
    session = await _service.create_session(
        db, novel_id=novel_id, owner_id=owner_id, files=payload
    )
    return _serialize_session(session, with_preview=False)


@router.get("")
async def list_migrations(
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    await _require_active_project(db, novel_id)
    owner_id = str(current_account_id())
    items, total = await _service.list_sessions(
        db, novel_id=novel_id, owner_id=owner_id, limit=limit, offset=offset
    )
    return {"items": [_list_item(session) for session in items], "total": total}


@router.get("/{session_id}")
async def get_migration(
    db: DbSession,
    *,
    session_id: str,
    novel_id: NovelIdQuery,
) -> dict[str, Any]:
    session = await _load_session(db, session_id=session_id, novel_id=novel_id)
    await _service.reconcile_ai_status(db, session)
    return _serialize_session(session)


@router.get("/{session_id}/rows")
async def get_migration_rows(
    db: DbSession,
    *,
    session_id: str,
    novel_id: NovelIdQuery,
    sheet_key: str = Query(..., min_length=1, max_length=32),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    session = await _load_session(db, session_id=session_id, novel_id=novel_id)
    return await _service.get_rows(
        session=session,
        sheet_key=sheet_key,
        offset=offset,
        limit=limit,
    )


@router.put("/{session_id}/mapping")
async def save_migration_mapping(
    db: DbSession,
    *,
    session_id: str,
    body: MigrationMappingRequest,
) -> dict[str, Any]:
    session = await _load_session(
        db, session_id=session_id, novel_id=body.novel_id, for_update=True
    )
    session = await _service.save_mapping(
        db,
        session=session,
        expected_revision=body.expected_revision,
        sheets=[sheet.model_dump() for sheet in body.sheets],
        options=body.options.model_dump(),
    )
    return _serialize_session(session)


@router.post("/{session_id}/ai-runs", status_code=202)
async def start_migration_ai(
    db: DbSession,
    *,
    session_id: str,
    body: MigrationAiRunRequest,
) -> dict[str, Any]:
    session = await _load_session(
        db, session_id=session_id, novel_id=body.novel_id, for_update=True
    )
    return await _service.submit_ai(
        db,
        session=session,
        expected_revision=body.expected_revision,
        scope=body.scope.model_dump(),
        operation_id=body.operation_id,
    )


@router.put("/{session_id}/decisions")
async def save_migration_decisions(
    db: DbSession,
    *,
    session_id: str,
    body: MigrationDecisionsRequest,
) -> dict[str, Any]:
    session = await _load_session(
        db, session_id=session_id, novel_id=body.novel_id, for_update=True
    )
    session = await _service.save_decisions(
        db,
        session=session,
        expected_revision=body.expected_revision,
        decisions=[item.model_dump() for item in body.decisions],
        relation_kind_groups=body.relation_kind_groups,
    )
    return _serialize_session(session)


@router.get("/{session_id}/rollback-preview")
async def get_migration_rollback_preview(
    db: DbSession,
    *,
    session_id: str,
    novel_id: NovelIdQuery,
) -> dict[str, Any]:
    session = await _load_session(
        db, session_id=session_id, novel_id=novel_id, for_update=True
    )
    return await _service.rollback_session(db, session=session, dry_run=True)


@router.post("/{session_id}/apply")
async def apply_migration(
    db: DbSession,
    *,
    session_id: str,
    body: MigrationApplyRequest,
) -> dict[str, Any]:
    session = await _load_session(
        db, session_id=session_id, novel_id=body.novel_id, for_update=True
    )
    counts = await _service.apply_session(
        db,
        session=session,
        expected_preview_hash=body.expected_preview_hash,
        authorized_by=str(current_account_id()),
    )
    await db.refresh(session)
    return {
        "status": session.status,
        "counts": counts,
        "receipt_summary": _serialize_session(session)["receipt_summary"],
    }


@router.post("/{session_id}/rollback")
async def rollback_migration(
    db: DbSession,
    *,
    session_id: str,
    body: MigrationRollbackRequest,
) -> dict[str, Any]:
    session = await _load_session(
        db, session_id=session_id, novel_id=body.novel_id, for_update=True
    )
    result = await _service.rollback_session(db, session=session, dry_run=False)
    await db.refresh(session)
    return {
        "status": session.status,
        "reverted_count": len(result["revertible"]),
        "kept": result["kept"],
    }


@router.delete("/{session_id}", status_code=204)
async def delete_migration(
    db: DbSession,
    *,
    session_id: str,
    novel_id: NovelIdQuery,
    confirmed: bool = Query(...),
) -> None:
    if not confirmed:
        raise HTTPException(status_code=400, detail="删除迁移记录需要二次确认")
    session = await _load_session(
        db, session_id=session_id, novel_id=novel_id, for_update=True
    )
    await _service.delete_session(db, session=session)


async def _require_active_project(db: DbSession, novel_id: str) -> None:
    from modules.project.facade import require_active_project

    await require_active_project(db, novel_id)


__all__ = ["router"]
