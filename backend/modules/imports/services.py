"""
Import 业务逻辑层

负责文件解析、分章写入 WritingDraft、记录导入结果。
跨模块调用均通过 facade 完成。
"""

from __future__ import annotations

import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import DomainError, NotFoundError
from core.errors import ValidationError as DomainValidationError
from infrastructure.tasks.enqueuer import enqueue_task
from modules.imports.models import ImportRecord
from modules.imports.parsers import ALLOWED_EXTENSIONS, MAX_FILE_SIZE, parse_file
from modules.imports.repositories import ImportRecordRepository
from modules.imports.schemas import ImportChapterItem, ImportListResponse, ImportResponse
from modules.writing.facade import create_published_draft_only
from shared.utils import parse_uuid

logger = logging.getLogger(__name__)

NO_EFFECTIVE_CHAPTERS_MESSAGE = "文件中未检测到有效章节"


class _NoEffectiveChaptersError(Exception):
    """文件解析后无有效章节的内部标记异常"""


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

        # 检查重复导入：同项目 + 同文件名 + 已成功
        existing = await self._repo.get_done_by_file_name(db, nid, file_name)
        if existing is not None:
            raise DomainValidationError(f"文件已导入: {file_name}")

        # 创建导入记录
        record = await self._repo.create(db, nid, file_name, file_type, len(file_content))

        try:
            # 使用 savepoint 隔离解析/写入过程，失败时只回滚内部操作，
            # 保留外层导入记录，便于更新为 failed 状态。
            async with db.begin_nested():
                chapters = parse_file(file_content, file_type)
                total = len(chapters)

                if total == 0:
                    raise _NoEffectiveChaptersError()

                # 逐章创建已发布 WritingDraft + 排发布任务；发布任务统一负责 RAG 索引。
                imported = 0
                imported_chapters: list[ImportChapterItem] = []
                for idx, ch in enumerate(chapters, start=1):
                    draft = await create_published_draft_only(
                        db,
                        novel_id=novel_id,
                        chapter_index=idx,
                        title=ch.get("title"),
                        content=ch.get("content", ""),
                    )
                    imported_chapters.append(
                        ImportChapterItem(
                            chapter_index=draft.chapter_index,
                            title=draft.title,
                            word_count=len(draft.content or ""),
                            draft_id=draft.id,
                        )
                    )
                    imported += 1

                    enqueue_task(
                        db,
                        "publish_chapter",
                        meta={"novel_id": novel_id, "chapter_index": idx},
                    )

        except _NoEffectiveChaptersError:
            await self._repo.update_status(
                db,
                record.id,
                status="failed",
                error_message=NO_EFFECTIVE_CHAPTERS_MESSAGE,
            )
            raise DomainValidationError(NO_EFFECTIVE_CHAPTERS_MESSAGE)
        except ValueError as exc:
            logger.warning("导入参数错误: %s", exc)
            error_message = str(exc)[:1000]
            await self._repo.update_status(
                db,
                record.id,
                status="failed",
                error_message=error_message,
            )
            raise DomainValidationError(
                error_message,
                status_code=422,
            ) from exc
        except Exception as exc:
            logger.error("导入失败: %s", exc, exc_info=True)
            error_message = "导入过程中发生服务器错误，请查看日志"
            try:
                await self._repo.update_status(
                    db,
                    record.id,
                    status="failed",
                    error_message=str(exc)[:1000],
                )
            except Exception as update_exc:
                # 事务可能已被底层数据库错误污染，标记失败状态也可能失败。
                # 记录日志，避免二次异常掩盖原始业务错误。
                logger.error("标记导入记录失败状态时出错: %s", update_exc, exc_info=True)
            raise DomainError(
                error_message,
                code="import_failed",
                status_code=500,
            ) from exc

        # 更新记录为完成（带并发去重保护：若同项目同名文件已有成功记录，
        # 数据库 partial unique index 会抛出 IntegrityError，此时将当前记录标记为失败）
        try:
            record = await self._repo.update_status(
                db,
                record.id,
                status="done",
                total_chapters=total,
                imported_chapters=imported,
            )
        except IntegrityError as exc:
            logger.warning("并发重复导入被数据库约束拦截: %s", exc)
            await db.rollback()
            raise DomainValidationError(f"文件已导入: {file_name}") from exc
        if record is None:
            raise DomainError(
                "导入记录状态更新失败",
                code="import_record_update_failed",
                status_code=500,
            )
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
            chapters=imported_chapters,
        )

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
            raise NotFoundError(f"ImportRecord {record_id} not found")
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
            allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
            raise DomainValidationError(f"不支持的文件类型: {ext}。仅支持: {allowed}")
        if file_size > MAX_FILE_SIZE:
            raise DomainValidationError(
                (
                    f"文件过大（{file_size} bytes），"
                    f"最大允许 {MAX_FILE_SIZE} bytes（50MB）"
                ),
                status_code=413,
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
