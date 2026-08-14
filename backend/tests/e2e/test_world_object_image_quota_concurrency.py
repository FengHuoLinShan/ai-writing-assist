from __future__ import annotations

import asyncio
import base64
import uuid

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.errors import ConflictError
from modules.project.models import Project
from modules.world.models import CoreEntity
from modules.world.world_object_images import WorldObjectImageService
from tests.e2e.config import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC"
)


class MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put_webp(self, key: str, payload: bytes) -> None:
        self.objects[key] = payload

    async def delete_object(self, key: str) -> None:
        self.objects.pop(key, None)


async def test_concurrent_account_quota_final_recount_allows_only_one_upload() -> None:
    engine = create_async_engine(DATABASE_URL, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    project_ids = [uuid.uuid4(), uuid.uuid4()]
    target_ids = [uuid.uuid4(), uuid.uuid4()]
    storage = MemoryStorage()
    try:
        async with sessions.begin() as db:
            db.add_all(
                [
                    Project(id=project_id, title="image quota race", settings={})
                    for project_id in project_ids
                ]
            )
            db.add_all(
                [
                    CoreEntity(
                        novel_id=project_ids[0],
                        entity_type="item",
                        name=f"occupied-{index}",
                        status="canonical",
                        image_version=uuid.uuid4(),
                    )
                    for index in range(49)
                ]
                + [
                    CoreEntity(
                        id=entity_id,
                        novel_id=project_ids[index],
                        entity_type="item",
                        name=f"target-{entity_id}",
                        status="canonical",
                    )
                    for index, entity_id in enumerate(target_ids)
                ]
            )

        async def upload(index: int, entity_id: uuid.UUID):
            async with sessions() as db:
                return await WorldObjectImageService(storage).upload(  # type: ignore[arg-type]
                    db,
                    novel_id=str(project_ids[index]),
                    entity_id=str(entity_id),
                    payload=_PNG,
                )

        results = await asyncio.gather(
            *(upload(index, entity_id) for index, entity_id in enumerate(target_ids)),
            return_exceptions=True,
        )
        assert sum(not isinstance(result, Exception) for result in results) == 1
        assert sum(isinstance(result, ConflictError) for result in results) == 1
        async with sessions() as db:
            assert (
                await db.scalar(
                    select(func.count(CoreEntity.id)).where(
                        CoreEntity.novel_id.in_(project_ids),
                        CoreEntity.image_version.is_not(None),
                        CoreEntity.entity_type != "character",
                    )
                )
                == 50
            )
        assert len(storage.objects) == 2
    finally:
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id.in_(project_ids)))
        await engine.dispose()
