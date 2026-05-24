"""
Memory 数据访问层

封装 memory_records 和 memory_update_proposals 表的所有数据库操作。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.memory.models import MemoryRecord, MemoryUpdateProposal
from modules.memory.schemas import MemoryRecordCreate, MemoryRecordUpdate
from shared.constants import DEFAULT_PAGE_SIZE


class MemoryRecordRepository:
    """记忆记录数据访问"""

    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        data: MemoryRecordCreate,
    ) -> MemoryRecord:
        """创建新的记忆记录"""
        record = MemoryRecord(
            novel_id=novel_id,
            memory_type=data.memory_type,
            target_type=data.target_type,
            target_id=uuid.UUID(hex=data.target_id) if data.target_id else None,
            chapter_index=data.chapter_index,
            title=data.title,
            summary=data.summary,
            content_json=data.content_json or {},
            visibility=data.visibility or "reader_known",
            known_by_character_ids=data.known_by_character_ids or [],
            related_entity_ids=data.related_entity_ids or [],
            related_character_ids=data.related_character_ids or [],
            related_thread_ids=data.related_thread_ids or [],
            importance=data.importance if data.importance is not None else 0.5,
            status=data.status or "canonical",
            source_text_excerpt=data.source_text_excerpt,
        )
        db.add(record)
        await db.flush()
        return record

    async def get(
        self,
        db: AsyncSession,
        record_id: uuid.UUID,
    ) -> MemoryRecord | None:
        """根据 ID 获取记忆记录"""
        stmt = select(MemoryRecord).where(MemoryRecord.id == record_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_multi(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
        memory_type: str | None = None,
        status: str | None = None,
        before_chapter_index: int | None = None,
    ) -> tuple[list[MemoryRecord], int]:
        """获取记忆记录列表（支持过滤和分页）"""
        conditions = [MemoryRecord.novel_id == novel_id]

        if memory_type:
            conditions.append(MemoryRecord.memory_type == memory_type)
        if status:
            conditions.append(MemoryRecord.status == status)
        if before_chapter_index is not None:
            conditions.append(
                MemoryRecord.chapter_index <= before_chapter_index
            )

        # 计数
        count_stmt = select(MemoryRecord.id).where(*conditions)
        count_result = await db.execute(count_stmt)
        total = len(count_result.all())

        # 分页查询
        stmt = (
            select(MemoryRecord)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(MemoryRecord.chapter_index.desc().nullslast())
        )
        result = await db.execute(stmt)
        items: Sequence[MemoryRecord] = result.scalars().all()
        return list(items), total

    async def get_by_entity(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        entity_id: uuid.UUID,
        *,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> list[MemoryRecord]:
        """获取与某实体关联的记忆记录"""
        # 使用 JSONB containment 查询
        stmt = (
            select(MemoryRecord)
            .where(
                MemoryRecord.novel_id == novel_id,
                MemoryRecord.related_entity_ids.contains([str(entity_id)]),
            )
            .order_by(MemoryRecord.created_at.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        items: Sequence[MemoryRecord] = result.scalars().all()
        return list(items)

    async def update(
        self,
        db: AsyncSession,
        record_id: uuid.UUID,
        data: MemoryRecordUpdate,
    ) -> MemoryRecord | None:
        """更新记忆记录"""
        record = await self.get(db, record_id)
        if record is None:
            return None

        update_values: dict[str, object] = {}
        for field in (
            "title",
            "summary",
            "content_json",
            "visibility",
            "importance",
            "status",
        ):
            value = getattr(data, field, None)
            if value is not None:
                update_values[field] = value

        if data.known_by_character_ids is not None:
            update_values["known_by_character_ids"] = data.known_by_character_ids

        if update_values:
            stmt = (
                update(MemoryRecord)
                .where(MemoryRecord.id == record_id)
                .values(**update_values)
            )
            await db.execute(stmt)
            await db.flush()
            record = await self.get(db, record_id)

        return record

    async def delete(
        self,
        db: AsyncSession,
        record_id: uuid.UUID,
    ) -> bool:
        """删除记忆记录"""
        stmt = delete(MemoryRecord).where(MemoryRecord.id == record_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0


class MemoryProposalRepository:
    """记忆提案数据访问"""

    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        proposal_type: str,
        payload: dict[str, Any],
        *,
        chapter_id: uuid.UUID | None = None,
        chapter_index: int | None = None,
        confidence: float = 0.5,
        reason: str | None = None,
        source_text_excerpt: str | None = None,
    ) -> MemoryUpdateProposal:
        """创建新的记忆提案"""
        proposal = MemoryUpdateProposal(
            novel_id=novel_id,
            chapter_id=chapter_id,
            chapter_index=chapter_index,
            proposal_type=proposal_type,
            payload=payload,
            confidence=confidence,
            reason=reason,
            source_text_excerpt=source_text_excerpt,
            decision="pending",
        )
        db.add(proposal)
        await db.flush()
        return proposal

    async def get(
        self,
        db: AsyncSession,
        proposal_id: uuid.UUID,
    ) -> MemoryUpdateProposal | None:
        """根据 ID 获取提案"""
        stmt = select(MemoryUpdateProposal).where(
            MemoryUpdateProposal.id == proposal_id
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_pending(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[MemoryUpdateProposal], int]:
        """获取待处理的提案列表"""
        conditions = [
            MemoryUpdateProposal.novel_id == novel_id,
            MemoryUpdateProposal.decision == "pending",
        ]

        count_stmt = select(MemoryUpdateProposal.id).where(*conditions)
        count_result = await db.execute(count_stmt)
        total = len(count_result.all())

        stmt = (
            select(MemoryUpdateProposal)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(MemoryUpdateProposal.created_at.asc())
        )
        result = await db.execute(stmt)
        items: Sequence[MemoryUpdateProposal] = result.scalars().all()
        return list(items), total

    async def decide(
        self,
        db: AsyncSession,
        proposal_id: uuid.UUID,
        decision: str,
        decided_by: str | None = None,
    ) -> MemoryUpdateProposal | None:
        """审批提案（approved / rejected）"""
        proposal = await self.get(db, proposal_id)
        if proposal is None:
            return None

        stmt = (
            update(MemoryUpdateProposal)
            .where(MemoryUpdateProposal.id == proposal_id)
            .values(
                decision=decision,
                decided_by=decided_by,
                decided_at=datetime.now(timezone.utc),
            )
        )
        await db.execute(stmt)
        await db.flush()
        return await self.get(db, proposal_id)
