"""
Import API 路由

提供小说文件上传与导入的 REST API。
"""

from __future__ import annotations

from fastapi import APIRouter, File, Form, Query, UploadFile

from core.dependencies import DbSession
from modules.imports.schemas import ImportListResponse, ImportResponse
from modules.imports.services import ImportService
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

router = APIRouter(prefix="/api/imports", tags=["imports"])
_service = ImportService()


@router.post("/upload", response_model=ImportResponse, status_code=201)
async def upload_file(
    db: DbSession,
    novel_id: str = Form(..., description="小说项目 ID"),
    file: UploadFile = File(..., description="小说文件（txt/epub/html/mobi）"),
) -> ImportResponse:
    """上传小说文件并自动导入

    支持 txt / epub / html / mobi / azw3 格式。
    文件最大 50MB。
    解析后自动分章写入正文草稿。
    """
    content = await file.read()
    return await _service.upload_and_import(db, novel_id, file.filename or "unknown", content)


@router.get("", response_model=ImportListResponse)
async def list_imports(
    db: DbSession,
    novel_id: str = Query(..., description="小说项目 ID"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
) -> ImportListResponse:
    """获取导入记录列表"""
    return await _service.list_import_records(db, novel_id, skip=skip, limit=limit)


@router.get("/{record_id}", response_model=ImportResponse)
async def get_import(
    db: DbSession,
    record_id: str,
    novel_id: str = Query(..., description="小说项目 ID"),
) -> ImportResponse:
    """获取单条导入记录详情"""
    return await _service.get_import_record(db, novel_id, record_id)
