from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.models import StoryOutlineHead, StoryOutlineRevision


class StoryOutlineRepository:
    async def get_head(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
    ) -> StoryOutlineHead | None:
        return await db.scalar(
            select(StoryOutlineHead).where(StoryOutlineHead.novel_id == novel_id)
        )

    async def lock_or_create_head(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
    ) -> StoryOutlineHead:
        bind = db.get_bind()
        if bind.dialect.name == "postgresql":
            digest = hashlib.sha256(b"story-outline:" + novel_id.bytes).digest()
            advisory_key = int.from_bytes(digest[:8], "big", signed=True)
            await db.execute(select(func.pg_advisory_xact_lock(advisory_key)))

        head = await db.scalar(
            select(StoryOutlineHead)
            .where(StoryOutlineHead.novel_id == novel_id)
            .with_for_update()
        )
        if head is None:
            head = StoryOutlineHead(novel_id=novel_id)
            db.add(head)
            await db.flush()
        return head

    async def get_revision(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        revision_id: uuid.UUID,
    ) -> StoryOutlineRevision | None:
        return await db.scalar(
            select(StoryOutlineRevision).where(
                StoryOutlineRevision.id == revision_id,
                StoryOutlineRevision.novel_id == novel_id,
            )
        )

    async def get_revision_by_idempotency_key(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        idempotency_key: str,
    ) -> StoryOutlineRevision | None:
        return await db.scalar(
            select(StoryOutlineRevision).where(
                StoryOutlineRevision.novel_id == novel_id,
                StoryOutlineRevision.idempotency_key == idempotency_key,
            )
        )

    async def next_version_number(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
    ) -> int:
        current_max = await db.scalar(
            select(func.max(StoryOutlineRevision.version_number)).where(
                StoryOutlineRevision.novel_id == novel_id
            )
        )
        return int(current_max or 0) + 1

    async def create_revision(
        self,
        db: AsyncSession,
        revision: StoryOutlineRevision,
    ) -> StoryOutlineRevision:
        db.add(revision)
        await db.flush()
        return revision

    async def list_revisions(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        skip: int,
        limit: int,
    ) -> tuple[list[StoryOutlineRevision], int]:
        total = await db.scalar(
            select(func.count(StoryOutlineRevision.id)).where(
                StoryOutlineRevision.novel_id == novel_id
            )
        )
        result = await db.scalars(
            select(StoryOutlineRevision)
            .where(StoryOutlineRevision.novel_id == novel_id)
            .order_by(StoryOutlineRevision.version_number.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.all()), int(total or 0)
