from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.errors import ConflictError
from modules.project.models import Project
from modules.world.map_models import MapConfig, MapTile
from modules.world.map_schemas import MapConfigCreate, MapEditorApplyRequest
from modules.world.services.map.map_config_service import MapConfigService
from modules.world.services.map.map_editor_apply import MapEditorApplyService
from tests.e2e.config import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_concurrent_editor_apply_uses_revision_compare_and_swap() -> None:
    """Two sessions with one expected revision cannot both commit."""
    engine = create_async_engine(DATABASE_URL, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    novel_id = uuid.uuid4()
    first_applied = asyncio.Event()
    release_first = asyncio.Event()
    second_started = asyncio.Event()
    first_task: asyncio.Task[int] | None = None
    second_task: asyncio.Task[ConflictError] | None = None

    async def apply_first() -> int:
        async with sessions() as db:
            await db.begin()
            response = await MapEditorApplyService().apply(
                db,
                str(novel_id),
                map_id,
                MapEditorApplyRequest.model_validate(
                    {
                        "expected_revision": 0,
                        "commands": [
                            {
                                "type": "base_terrain_replace",
                                "changes": [
                                    {
                                        "hex_q": 0,
                                        "hex_r": 0,
                                        "terrain_type": "water",
                                    }
                                ],
                            }
                        ],
                    }
                ),
            )
            first_applied.set()
            await release_first.wait()
            await db.commit()
            return response.editor_revision

    async def apply_second() -> ConflictError:
        await first_applied.wait()
        try:
            async with sessions.begin() as db:
                second_started.set()
                await MapEditorApplyService().apply(
                    db,
                    str(novel_id),
                    map_id,
                    MapEditorApplyRequest.model_validate(
                        {
                            "expected_revision": 0,
                            "commands": [
                                {
                                    "type": "base_terrain_replace",
                                    "changes": [
                                        {
                                            "hex_q": 0,
                                            "hex_r": 0,
                                            "terrain_type": "forest",
                                        }
                                    ],
                                }
                            ],
                        }
                    ),
                )
        except ConflictError as exc:
            return exc
        raise AssertionError("the stale editor apply unexpectedly succeeded")

    try:
        async with sessions.begin() as setup_db:
            setup_db.add(Project(id=novel_id, title="map editor CAS concurrency"))
            config = await MapConfigService().create(
                setup_db,
                str(novel_id),
                MapConfigCreate(
                    name="concurrent editor map",
                    map_type="world",
                    grid_width=2,
                    grid_height=2,
                    template="blank",
                ),
            )
            map_id = config.id

        first_task = asyncio.create_task(apply_first())
        await asyncio.wait_for(first_applied.wait(), timeout=2.0)
        second_task = asyncio.create_task(apply_second())
        await asyncio.wait_for(second_started.wait(), timeout=2.0)

        done, _pending = await asyncio.wait({second_task}, timeout=0.1)
        assert not done, "the second apply must wait for the first map transaction"

        release_first.set()
        first_revision, conflict = await asyncio.gather(first_task, second_task)
        assert first_revision == 1
        assert conflict.code == "map_editor_revision_conflict"
        assert conflict.status_code == 409
        assert conflict.context == {
            "expected_revision": 0,
            "current_revision": 1,
            "map_id": map_id,
        }

        async with sessions() as verify_db:
            stored_map = await verify_db.scalar(
                select(MapConfig).where(MapConfig.id == uuid.UUID(map_id))
            )
            tile = await verify_db.scalar(
                select(MapTile).where(
                    MapTile.novel_id == novel_id,
                    MapTile.map_id == uuid.UUID(map_id),
                    MapTile.hex_q == 0,
                    MapTile.hex_r == 0,
                )
            )
            assert stored_map is not None
            assert stored_map.editor_revision == 1
            assert tile is not None
            assert tile.terrain_type == "water"
    finally:
        release_first.set()
        pending = [
            task
            for task in (first_task, second_task)
            if task is not None and not task.done()
        ]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        async with sessions.begin() as cleanup_db:
            await cleanup_db.execute(delete(Project).where(Project.id == novel_id))
        await engine.dispose()
