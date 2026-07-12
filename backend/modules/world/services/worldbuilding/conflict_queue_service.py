"""Worldbuilding conflict queue service."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError
from modules.world.models import (
    ConflictCheckQueueItem,
)
from modules.world.schemas import (
    ConflictQueueResponse,
)
from shared.utils import parse_uuid


class ConflictQueueService:
    async def list(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        status: str | None = None,
        conflict_type: str | None = None,
    ) -> tuple[list[ConflictQueueResponse], int]:
        nid = parse_uuid(novel_id, "novel_id")
        stmt = select(ConflictCheckQueueItem).where(
            ConflictCheckQueueItem.novel_id == nid
        )
        if status:
            stmt = stmt.where(ConflictCheckQueueItem.status == status)
        if conflict_type:
            stmt = stmt.where(ConflictCheckQueueItem.conflict_type == conflict_type)
        result = await db.execute(stmt.order_by(ConflictCheckQueueItem.created_at.desc()))
        items = [
            ConflictQueueResponse.model_validate(item) for item in result.scalars().all()
        ]
        return items, len(items)

    async def resolve(
        self,
        db: AsyncSession,
        novel_id: str,
        item_id: str,
        *,
        status: str,
        resolution_json: dict[str, Any],
    ) -> ConflictQueueResponse:
        nid = parse_uuid(novel_id, "novel_id")
        iid = parse_uuid(item_id, "conflict_id")
        result = await db.execute(
            select(ConflictCheckQueueItem).where(
                ConflictCheckQueueItem.id == iid,
                ConflictCheckQueueItem.novel_id == nid,
            )
        )
        item = result.scalar_one_or_none()
        if item is None:
            raise NotFoundError("Conflict item not found")
        item.status = status
        item.resolution_json = resolution_json
        await db.flush()
        return ConflictQueueResponse.model_validate(item)


__all__ = ["ConflictQueueService"]
