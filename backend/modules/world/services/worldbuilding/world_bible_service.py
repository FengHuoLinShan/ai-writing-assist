"""World Bible page and projection service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.redaction import redact_diagnostic
from infrastructure.llm.token_estimation import estimate_token_count
from infrastructure.tasks.facade import (
    enqueue_coalesced_task,
    get_latest_coalesced_task,
)
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
        scope = ("page_projection", str(page.id), projection_type)
        latest = await get_latest_coalesced_task(
            db,
            task_type="world_bible_projection_refresh",
            novel_id=str(page.novel_id),
            scope=scope,
        )
        if latest and latest.status in {"pending", "running"} and not force:
            return latest.task_id, latest.status, True
        if latest and latest.status in {"done", "failed"} and not force:
            raise ProjectionRefreshConflictError(latest.task_id, latest.status)
        enqueued = await enqueue_coalesced_task(
            db,
            task_type="world_bible_projection_refresh",
            novel_id=str(page.novel_id),
            scope=scope,
            meta={
                "novel_id": str(page.novel_id),
                "page_id": str(page.id),
                "projection_type": projection_type,
            },
            mode="one_pending_follower" if force else "reuse_active",
        )
        await db.flush()
        return enqueued.task_id, enqueued.status, enqueued.reused

    async def refresh_projection_now(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        page_id: str,
        projection_type: str,
    ) -> WorldBibleProjectionResponse:
        # The page row is the stable serialization point even when the projection
        # row does not exist yet.  Locking it prevents concurrent force-refresh
        # tasks from racing into the projection uniqueness constraint.
        page = await self._get_page_model(db, novel_id, page_id, for_update=True)
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
            projection.error_kind = exc.__class__.__name__[:64]
            projection.error_summary = redact_diagnostic(exc, limit=500)
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
