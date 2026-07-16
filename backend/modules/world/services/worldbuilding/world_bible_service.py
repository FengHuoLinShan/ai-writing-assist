"""World Bible page and projection service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.token_estimation import estimate_token_count
from infrastructure.tasks.enqueuer import enqueue_task
from infrastructure.tasks.models import AsyncTask
from modules.world.models import (
    WorldBiblePage,
    WorldBiblePageProjection,
)
from modules.world.schemas import (
    WorldBiblePageCreate,
    WorldBiblePageResponse,
    WorldBiblePageUpdate,
    WorldBibleProjectionResponse,
)
from modules.world.services.worldbuilding.world_bible_lifecycle_service import (
    WorldBibleLifecycleService,
)
from shared.utils import parse_uuid


class ProjectionRefreshConflictError(Exception):
    def __init__(self, task_id: str, status: str) -> None:
        self.task_id = task_id
        self.status = status
        super().__init__(f"projection refresh already finished with status {status}")


class WorldBibleService:
    def __init__(
        self,
        lifecycle_service: WorldBibleLifecycleService | None = None,
    ) -> None:
        self._lifecycle = lifecycle_service or WorldBibleLifecycleService()

    async def list_pages(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        page_type: str | None = None,
    ) -> tuple[list[WorldBiblePageResponse], int]:
        nid = parse_uuid(novel_id, "novel_id")
        stmt = select(WorldBiblePage).where(WorldBiblePage.novel_id == nid)
        if page_type:
            stmt = stmt.where(WorldBiblePage.page_type == page_type)
        result = await db.execute(
            stmt.order_by(WorldBiblePage.sort_order, WorldBiblePage.title)
        )
        pages = list(result.scalars().all())
        return [WorldBiblePageResponse.model_validate(page) for page in pages], len(pages)

    async def create_page(
        self,
        db: AsyncSession,
        data: WorldBiblePageCreate,
    ) -> WorldBiblePageResponse:
        return await self._lifecycle.create_page(db, data)

    async def get_page(
        self,
        db: AsyncSession,
        novel_id: str,
        page_id: str,
    ) -> WorldBiblePageResponse:
        page = await self._get_page_model(db, novel_id, page_id)
        return WorldBiblePageResponse.model_validate(page)

    async def update_page(
        self,
        db: AsyncSession,
        novel_id: str,
        page_id: str,
        data: WorldBiblePageUpdate,
    ) -> WorldBiblePageResponse:
        return await self._lifecycle.update_page(db, novel_id, page_id, data)

    async def refresh_projection_task(
        self,
        db: AsyncSession,
        novel_id: str,
        page_id: str,
        *,
        projection_type: str = "context_brief",
        force: bool = False,
    ) -> tuple[str, str, bool]:
        page = await self._get_page_model(db, novel_id, page_id)
        existing = await self._find_projection_task(db, page, projection_type)
        if existing and existing.status in {"pending", "running"} and not force:
            return str(existing.id), existing.status, True
        if existing and existing.status in {"done", "failed"} and not force:
            raise ProjectionRefreshConflictError(str(existing.id), existing.status)
        task_id = enqueue_task(
            db,
            "world_bible_projection_refresh",
            meta={
                "novel_id": str(page.novel_id),
                "page_id": str(page.id),
                "projection_type": projection_type,
            },
        )
        await db.flush()
        return task_id, "pending", False

    async def refresh_projection_now(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        page_id: str,
        projection_type: str,
    ) -> WorldBibleProjectionResponse:
        page = await self._get_page_model(db, novel_id, page_id)
        projection = await self._get_projection_model(db, page, projection_type)
        if projection is None:
            projection = WorldBiblePageProjection(
                novel_id=page.novel_id,
                page_id=page.id,
                projection_type=projection_type,
            )
            db.add(projection)
        try:
            content = self._build_projection_content(page, projection_type)
            projection.content = content
            projection.source_page_version = page.version_number
            projection.source_hash = self._lifecycle.projection_source_hash(page)
            projection.token_estimate = estimate_token_count(content)
            projection.source_spans_json = self._lifecycle.projection_source_spans(page)
            projection.omitted_reasons_json = []
            projection.status = "ready"
            projection.stale = False
            projection.stale_checked_at = datetime.now(UTC)
            projection.error_kind = None
            projection.error_summary = None
        except Exception as exc:
            projection.status = "failed"
            projection.stale = True
            projection.stale_checked_at = datetime.now(UTC)
            projection.error_kind = exc.__class__.__name__
            projection.error_summary = str(exc)[:500]
        await db.flush()
        return WorldBibleProjectionResponse.model_validate(projection)

    async def list_templates(self) -> list[dict[str, Any]]:
        return [
            {"key": "world_basic", "title": "世界基本背景", "page_type": "background"},
            {"key": "species_index", "title": "种族", "page_type": "species"},
            {"key": "factions_index", "title": "势力", "page_type": "faction"},
            {"key": "locations_index", "title": "地点与地图", "page_type": "location"},
            {"key": "rules_index", "title": "规则体系", "page_type": "rule"},
            {"key": "secrets_index", "title": "秘密与伏笔", "page_type": "secret"},
        ]

    async def _get_page_model(
        self,
        db: AsyncSession,
        novel_id: str,
        page_id: str,
        *,
        for_update: bool = False,
    ) -> WorldBiblePage:
        return await self._lifecycle.get_page_model(
            db,
            novel_id,
            page_id,
            for_update=for_update,
        )

    async def _get_projection_model(
        self,
        db: AsyncSession,
        page: WorldBiblePage,
        projection_type: str,
    ) -> WorldBiblePageProjection | None:
        result = await db.execute(
            select(WorldBiblePageProjection).where(
                WorldBiblePageProjection.novel_id == page.novel_id,
                WorldBiblePageProjection.page_id == page.id,
                WorldBiblePageProjection.projection_type == projection_type,
            )
        )
        return result.scalar_one_or_none()

    async def _find_projection_task(
        self,
        db: AsyncSession,
        page: WorldBiblePage,
        projection_type: str,
    ) -> AsyncTask | None:
        result = await db.execute(
            select(AsyncTask)
            .where(AsyncTask.task_type == "world_bible_projection_refresh")
            .order_by(AsyncTask.created_at.desc())
            .limit(50)
        )
        for task in result.scalars().all():
            meta = task.meta or {}
            if (
                str(meta.get("novel_id")) == str(page.novel_id)
                and str(meta.get("page_id")) == str(page.id)
                and str(meta.get("projection_type")) == projection_type
            ):
                return task
        return None

    def _build_projection_content(
        self,
        page: WorldBiblePage,
        projection_type: str,
    ) -> str:
        content_parts = [(page.free_text or "").strip()]
        content_parts.extend(
            str(section.get("body_markdown") or "").strip()
            for section in sorted(
                page.sections_json or [],
                key=lambda item: (item.get("sort_order", 0), item.get("section_id", "")),
            )
            if section.get("projection_policy", "eligible") == "eligible"
        )
        text = "\n\n".join(part for part in content_parts if part)
        if not text:
            return ""
        if projection_type == "excerpt":
            return text[:4000]
        if projection_type == "style_notes":
            lines = (line.strip() for line in text.splitlines()[:20])
            return "\n".join(line for line in lines if line)
        if projection_type == "fact_candidates":
            lines = (line.strip() for line in text.splitlines())
            return "\n".join(line for line in lines if line)[:3000]
        return text[:2400]


__all__ = ["ProjectionRefreshConflictError", "WorldBibleService"]
