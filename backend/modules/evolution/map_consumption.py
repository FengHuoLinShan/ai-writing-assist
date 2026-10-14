"""Evolution's read-only map consumption port; assembled by the application."""

from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession


class MapChapterConsumptionPort(Protocol):
    async def __call__(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        chapter_index: int,
        current_draft_id: str | None,
        current_source_hash: str | None,
    ) -> dict: ...
