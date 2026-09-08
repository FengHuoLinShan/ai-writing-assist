from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.errors import ConflictError
from modules.project.models import Project
from modules.world.map_atlas_models import MapAtlasNode, MapAtlasRevision, MapAtlasRun
from modules.world.map_structure_schemas import MapDocument, MapNodeCreate, MapSaveRequest
from modules.world.map_structure_service import MapStructureService
from tests.e2e.config import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_concurrent_map_saves_have_exactly_one_winner():
    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    project_id = uuid.uuid4()
    try:
        async with sessions.begin() as db:
            db.add(Project(id=project_id, title="map revision concurrency", settings={}))
            await db.flush()
            node = await MapStructureService().create_node(
                db, str(project_id), MapNodeCreate(title="区域")
            )
        gate = asyncio.Event()

        async def save(label):
            await gate.wait()
            try:
                async with sessions.begin() as db:
                    document = MapDocument.model_validate(
                        {
                            "features": [
                                {
                                    "id": "city",
                                    "label": label,
                                    "kind": "location",
                                    "points": [{"x": 100, "y": 100}],
                                }
                            ]
                        }
                    )
                    result = await MapStructureService().save(
                        db,
                        str(project_id),
                        node["id"],
                        MapSaveRequest(
                            base_revision_id=node["current_revision_id"],
                            document=document,
                        ),
                    )
                    return result.id
            except ConflictError:
                return None

        first, second = asyncio.create_task(save("甲")), asyncio.create_task(save("乙"))
        gate.set()
        results = await asyncio.gather(first, second)
        assert sum(result is not None for result in results) == 1
        async with sessions() as db:
            current = await db.get(MapAtlasNode, uuid.UUID(node["id"]))
            assert str(current.current_revision_id) in results
            revisions = (
                await db.scalars(
                    select(MapAtlasRevision).where(
                        MapAtlasRevision.novel_id == project_id
                    )
                )
            ).all()
            assert len(revisions) == 2
    finally:
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id == project_id))
        await engine.dispose()


async def test_map_revision_payload_is_immutable_and_head_cannot_cross_nodes():
    engine = create_async_engine(DATABASE_URL, pool_size=2, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    project_id = uuid.uuid4()
    try:
        async with sessions.begin() as db:
            db.add(Project(id=project_id, title="map revision constraints", settings={}))
            await db.flush()
            first = await MapStructureService().create_node(
                db, str(project_id), MapNodeCreate(title="甲区域")
            )
            second = await MapStructureService().create_node(
                db, str(project_id), MapNodeCreate(title="乙区域")
            )
        async with sessions.begin() as db:
            with pytest.raises(DBAPIError, match="immutable"):
                async with db.begin_nested():
                    await db.execute(
                        update(MapAtlasRevision)
                        .where(
                            MapAtlasRevision.id == uuid.UUID(first["current_revision_id"])
                        )
                        .values(document={"changed": True})
                    )
            with pytest.raises(DBAPIError):
                async with db.begin_nested():
                    await db.execute(
                        update(MapAtlasNode)
                        .where(MapAtlasNode.id == uuid.UUID(first["id"]))
                        .values(
                            current_revision_id=uuid.UUID(second["current_revision_id"])
                        )
                    )
                    await db.execute(
                        text("SET CONSTRAINTS fk_map_node_current_revision IMMEDIATE")
                    )
        async with sessions() as db:
            current = await db.get(MapAtlasNode, uuid.UUID(first["id"]))
            assert str(current.current_revision_id) == first["current_revision_id"]
    finally:
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id == project_id))
        await engine.dispose()


async def test_image_run_removal_preserves_map_and_project_delete_cascades_revisions():
    engine = create_async_engine(DATABASE_URL, pool_size=2, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    project_id = uuid.uuid4()
    try:
        async with sessions.begin() as db:
            db.add(Project(id=project_id, title="map node lifetime", settings={}))
            await db.flush()
            run = MapAtlasRun(novel_id=project_id, run_kind="initial", status="completed")
            db.add(run)
            await db.flush()
            node = MapAtlasNode(
                novel_id=project_id,
                created_by_run_id=run.id,
                semantic_key="region",
                title="区域",
                level="region",
                status="adopted",
            )
            db.add(node)
            await db.flush()
            await MapStructureService().save(
                db,
                str(project_id),
                str(node.id),
                MapSaveRequest(base_revision_id=None, document=MapDocument()),
            )
            node_id, run_id = node.id, run.id
        async with sessions.begin() as db:
            await db.execute(delete(MapAtlasRun).where(MapAtlasRun.id == run_id))
        async with sessions() as db:
            remaining = await db.get(MapAtlasNode, node_id)
            assert remaining.created_by_run_id is None
            assert remaining.current_revision_id is not None
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id == project_id))
        async with sessions() as db:
            assert await db.get(MapAtlasNode, node_id) is None
            assert (
                await db.scalars(
                    select(MapAtlasRevision).where(
                        MapAtlasRevision.novel_id == project_id
                    )
                )
            ).all() == []
    finally:
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id == project_id))
        await engine.dispose()
