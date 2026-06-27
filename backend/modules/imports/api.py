"""
Import API 路由

提供小说文件上传与导入的 REST API。
"""

from __future__ import annotations

from fastapi import APIRouter, Body, File, Form, Query, UploadFile

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
    """上传小说文件并自动导入"""
    content = await file.read()
    return await _service.upload_and_import(
        db, novel_id, file.filename or "unknown", content
    )


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


# ====================================================================
# 深度导入
# ====================================================================


@router.post("/deep", status_code=201)
async def submit_deep_import(
    db: DbSession,
    body: dict = Body(..., description="深度导入参数"),
) -> dict:
    """提交深度导入任务

    从章节正文中自动执行世界对象抽取、人物同步和剧情结构生成三步流水线。

    请求体：
    - novel_id: 项目 ID（必填）
    - start_chapter: 起始章节（默认 1）
    - end_chapter: 结束章节（必填）

    返回 task_id，前端可通过 GET /api/tasks/{task_id} 查询状态。
    """
    from modules.imports.facade import start_deep_import as _start

    novel_id = body.get("novel_id", "")
    start_chapter = int(body.get("start_chapter", 1))
    end_chapter = int(body.get("end_chapter", 0))

    if not novel_id:
        from fastapi import HTTPException

        raise HTTPException(400, detail="novel_id is required")
    if end_chapter < start_chapter:
        from fastapi import HTTPException

        raise HTTPException(400, detail="end_chapter must be >= start_chapter")

    # 自动检测最后章节
    if end_chapter == 0:
        from modules.writing.facade import list_chapter_indices

        indices = await list_chapter_indices(db, novel_id)
        end_chapter = max(indices) if indices else 1

    result = await _start(db, novel_id, start_chapter, end_chapter)
    return result


@router.post("/deep/resume", status_code=201)
async def resume_deep_import(
    db: DbSession,
    body: dict = Body(..., description="继续深度导入参数"),
) -> dict:
    """继续深度导入流程

    用户确认所有世界对象候选后，调用此接口继续执行人物同步和剧情结构生成。

    请求体：
    - task_id: 前一个 deep_import 任务的 ID（必填）
    """
    from modules.imports.facade import resume_deep_import as _resume

    prev_task_id = body.get("task_id", "")
    if not prev_task_id:
        from fastapi import HTTPException

        raise HTTPException(400, detail="task_id is required")

    result = await _resume(db, prev_task_id)
    return result
