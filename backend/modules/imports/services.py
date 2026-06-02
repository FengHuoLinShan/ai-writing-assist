"""
Import 业务逻辑层

负责文件解析、分章写入 WritingDraft、记录导入结果。
跨模块调用均通过 facade 完成。
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.tasks.models import AsyncTask
from shared.enums import TaskStatus as TaskStatusEnum
from modules.imports.models import ImportRecord
from modules.imports.parsers import ALLOWED_EXTENSIONS, MAX_FILE_SIZE, parse_file
from modules.imports.repositories import ImportRecordRepository
from modules.imports.schemas import ImportChapterItem, ImportListResponse, ImportResponse
from modules.writing.facade import create_draft
from shared.utils import parse_uuid
from modules.writing.schemas import WritingDraftCreate


class ImportService:
    """小说文件导入服务"""

    def __init__(self) -> None:
        self._repo = ImportRecordRepository()

    async def upload_and_import(
        self,
        db: AsyncSession,
        novel_id: str,
        file_name: str,
        file_content: bytes,
    ) -> ImportResponse:
        """上传并导入小说文件

        流程：
        1. 校验文件类型和大小
        2. 创建导入记录
        3. 解析文件内容
        4. 逐章写入 WritingDraft
        5. 更新导入记录为完成
        """
        nid = parse_uuid(novel_id, "novel_id")
        file_type = self._validate_file(file_name, len(file_content))

        # 创建导入记录
        record = await self._repo.create(db, nid, file_name, file_type, len(file_content))

        try:
            # 解析文件
            chapters = parse_file(file_content, file_type)
            total = len(chapters)

            if total == 0:
                await self._repo.update_status(
                    db, record.id,
                    status="failed",
                    error_message="文件中未解析出任何章节",
                )
                raise HTTPException(
                    status_code=http_status.HTTP_400_BAD_REQUEST,
                    detail="文件中未解析出任何章节",
                )

            # 逐章创建 WritingDraft + 排 RAG 索引任务
            imported = 0
            for idx, ch in enumerate(chapters, start=1):
                draft_data = WritingDraftCreate(
                    novel_id=novel_id,
                    chapter_index=idx,
                    title=ch.get("title") or f"第{idx}章",
                    content=ch.get("content", ""),
                )
                _, __ = await create_draft(db, draft_data)
                imported += 1

                task = AsyncTask(
                    id=uuid.uuid4(),
                    task_type="rag_index_chapter",
                    status=TaskStatusEnum.pending.value,
                    meta={"novel_id": novel_id, "chapter_index": idx},
                    progress=0.0,
                )
                db.add(task)

            # 更新记录为完成
            record = await self._repo.update_status(
                db, record.id,
                status="done",
                total_chapters=total,
                imported_chapters=imported,
            )
            if record is None:
                raise HTTPException(status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR)
            return ImportResponse(
                id=str(record.id),
                novel_id=str(record.novel_id),
                file_name=record.file_name,
                file_type=record.file_type,
                file_size=record.file_size,
                total_chapters=record.total_chapters,
                imported_chapters=record.imported_chapters,
                status=record.status,
                error_message=record.error_message,
                created_at=record.created_at,
            )

        except HTTPException:
            raise
        except ValueError as exc:
            await self._repo.update_status(
                db, record.id,
                status="failed",
                error_message=str(exc)[:1000],
            )
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"导入参数错误: {exc}",
            ) from exc
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error("导入失败: %s", exc, exc_info=True)
            await self._repo.update_status(
                db, record.id,
                status="failed",
                error_message=str(exc)[:1000],
            )
            raise HTTPException(
                status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="导入过程中发生服务器错误，请查看日志",
            ) from exc

    async def get_import_record(
        self,
        db: AsyncSession,
        novel_id: str,
        record_id: str,
    ) -> ImportResponse:
        """获取单条导入记录详情"""
        nid = parse_uuid(novel_id, "novel_id")
        rid = parse_uuid(record_id, "record_id")
        record = await self._repo.get(db, rid)
        if record is None or record.novel_id != nid:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"ImportRecord {record_id} not found",
            )
        return _record_to_response(record)

    async def list_import_records(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        skip: int = 0,
        limit: int = 20,
    ) -> ImportListResponse:
        """获取项目的导入记录列表"""
        nid = parse_uuid(novel_id, "novel_id")
        limit = min(limit, 50)
        items, total = await self._repo.get_by_novel(db, nid, skip=skip, limit=limit)
        return ImportListResponse(
            items=[_record_to_response(r) for r in items],
            total=total,
        )

    @staticmethod
    def _validate_file(file_name: str, file_size: int) -> str:
        """校验文件类型和大小，返回文件类型"""
        ext = _get_extension(file_name)
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"不支持的文件类型: {ext}。仅支持: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
            )
        if file_size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=http_status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"文件过大（{file_size} bytes），最大允许 {MAX_FILE_SIZE} bytes（50MB）",
            )
        # 文件类型去掉点号
        return ext.lstrip(".")


def _record_to_response(record: ImportRecord) -> ImportResponse:
    """将 ORM ImportRecord 转为 Pydantic ImportResponse"""
    return ImportResponse(
        id=str(record.id),
        novel_id=str(record.novel_id),
        file_name=record.file_name,
        file_type=record.file_type,
        file_size=record.file_size,
        total_chapters=record.total_chapters,
        imported_chapters=record.imported_chapters,
        status=record.status,
        error_message=record.error_message,
        created_at=record.created_at,
    )


def _get_extension(file_name: str) -> str:
    """安全提取文件扩展名，防止路径穿越"""
    import os
    safe_name = os.path.basename(file_name)
    if not safe_name:
        return ""
    _, ext = os.path.splitext(safe_name)
    return ext.lower()
