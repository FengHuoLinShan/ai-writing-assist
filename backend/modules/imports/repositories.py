"""
Import Repository

数据访问层，操作 import_records 表。
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.models import ImportRecord


class ImportRecordRepository:
    """导入记录数据访问"""

    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        file_name: str,
        file_type: str,
        file_size: int,
    ) -> ImportRecord:
        """创建导入记录"""
        record = ImportRecord(
            novel_id=novel_id,
            file_name=file_name,
            file_type=file_type,
            file_size=file_size,
            status="processing",
        )
        db.add(record)
        await db.flush()
        await db.refresh(record)
        return record

    async def get(
        self,
        db: AsyncSession,
        record_id: uuid.UUID,
    ) -> ImportRecord | None:
        """按 ID 获取导入记录"""
        stmt = select(ImportRecord).where(ImportRecord.id == record_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[ImportRecord], int]:
        """获取项目的导入记录列表"""
        stmt = (
            select(ImportRecord)
            .where(ImportRecord.novel_id == novel_id)
            .order_by(ImportRecord.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        count_stmt = (
            select(func.count())
            .select_from(ImportRecord)
            .where(
                ImportRecord.novel_id == novel_id,
            )
        )
        items = (await db.execute(stmt)).scalars().all()
        total = (await db.execute(count_stmt)).scalar() or 0
        return list(items), int(total)

    async def update_status(
        self,
        db: AsyncSession,
        record_id: uuid.UUID,
        *,
        status: str,
        imported_chapters: int | None = None,
        total_chapters: int | None = None,
        error_message: str | None = None,
    ) -> ImportRecord | None:
        """更新导入记录状态"""
        record = await self.get(db, record_id)
        if record is None:
            return None
        record.status = status
        if imported_chapters is not None:
            record.imported_chapters = imported_chapters
        if total_chapters is not None:
            record.total_chapters = total_chapters
        if error_message is not None:
            record.error_message = error_message
        await db.flush()
        await db.refresh(record)
        return record
