"""Map visual editor revision coordination."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError
from modules.world.map_models import MapConfig
from modules.world.map_repositories import MapConfigRepository
from modules.world.services.common import parse_uuid


class MapRevisionService:
    """Serialize visual writes and provide the editor compare-and-swap seam."""

    def __init__(self, config_repo: MapConfigRepository | None = None) -> None:
        self._config_repo = config_repo or MapConfigRepository()

    async def lock_visual_write(self, db: AsyncSession, map_id: str) -> None:
        """Use one lock order for legacy writes and atomic editor batches."""
        if db.get_bind().dialect.name != "postgresql":
            return
        await db.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(map_id, 1)))
        )

    async def lock_active(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        *,
        expected_revision: int | None = None,
    ) -> MapConfig:
        await self.lock_visual_write(db, map_id)
        nid = parse_uuid(novel_id, "novel_id")
        mid = parse_uuid(map_id, "map_id")
        config = await self._config_repo.get_in_novel(
            db,
            nid,
            mid,
            status="active",
            for_update=True,
        )
        if config is None:
            raise NotFoundError(f"地图 {map_id} 不存在", code="map_not_found")
        if expected_revision is not None and config.editor_revision != expected_revision:
            raise ConflictError(
                "地图已被其他编辑会话更新，请刷新后重新应用",
                code="map_editor_revision_conflict",
                context={
                    "expected_revision": expected_revision,
                    "current_revision": config.editor_revision,
                    "map_id": map_id,
                },
            )
        return config

    async def bump(
        self,
        db: AsyncSession,
        novel_id: str,
        map_id: str,
        *,
        locked_config: MapConfig | None = None,
    ) -> int:
        config = locked_config or await self.lock_active(db, novel_id, map_id)
        return await self._config_repo.bump_revision(db, config)
