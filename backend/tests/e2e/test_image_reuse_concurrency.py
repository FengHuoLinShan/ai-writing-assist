"""Real PostgreSQL uniqueness races must not roll back generated caller assets."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from modules.project.models import Project
from modules.world.image_request_reuse import find_reusable_asset, record_reusable_asset
from modules.world.models import CoreEntity
from modules.world.models.image_candidate import WorldObjectImageCandidate
from modules.world.models.image_request_reuse import ImageRequestReuse
from tests.e2e.config import require_e2e_database_url

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_registry_insert_race_preserves_both_callers(monkeypatch):
    engine = create_async_engine(require_e2e_database_url())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    novel_id, entity_id = uuid.uuid4(), uuid.uuid4()
    candidate_ids = [uuid.uuid4(), uuid.uuid4()]
    barrier = asyncio.Barrier(2)

    async def finish(candidate_id):
        async with sessions.begin() as db:
            candidate = await db.get(WorldObjectImageCandidate, candidate_id)
            candidate.status = "review_ready"
            candidate.image_data = b"synthetic-image"
            first_lookup = True
            execute = db.execute

            async def at_lookup(statement, *args, **kwargs):
                nonlocal first_lookup
                result = await execute(statement, *args, **kwargs)
                if first_lookup and ImageRequestReuse.__tablename__ in str(statement):
                    first_lookup = False
                    await asyncio.wait_for(barrier.wait(), timeout=10)
                return result

            monkeypatch.setattr(db, "execute", at_lookup)
            row = await record_reusable_asset(
                db,
                novel_id=str(novel_id),
                owner_id=str(candidate.owner_id),
                request_hash="f" * 64,
                source_type="world_object",
                object_key=f"world-object-candidate:{candidate_id}",
            )
            assert (
                candidate.status == "review_ready"
                and candidate.image_data == b"synthetic-image"
            )
            return row.id

    try:
        async with sessions.begin() as db:
            project = Project(id=novel_id, title="image reuse synthetic race")
            db.add(project)
            await db.flush()
            db.add(
                CoreEntity(
                    id=entity_id,
                    novel_id=novel_id,
                    entity_type="character",
                    name="合成角色",
                )
            )
            await db.flush()
            db.add_all(
                [
                    WorldObjectImageCandidate(
                        id=id_,
                        novel_id=novel_id,
                        entity_id=entity_id,
                        owner_id=project.owner_id,
                        status="generating",
                        prompt="合成图",
                    )
                    for id_ in candidate_ids
                ]
            )
        first, second = await asyncio.wait_for(
            asyncio.gather(*(finish(id_) for id_ in candidate_ids)), timeout=20
        )
        assert first == second
        async with sessions() as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(ImageRequestReuse)
                    .where(ImageRequestReuse.novel_id == novel_id)
                )
                == 1
            )
            for id_ in candidate_ids:
                candidate = await db.get(WorldObjectImageCandidate, id_)
                assert (
                    candidate.status == "review_ready"
                    and candidate.image_data == b"synthetic-image"
                )

            async def validate_asset(row):
                return b"synthetic-image", "", 1, 1

            hit = await find_reusable_asset(
                db,
                novel_id=str(novel_id),
                owner_id=str(candidate.owner_id),
                request_hash="f" * 64,
                validate_asset=validate_asset,
            )
            assert hit is not None
            await db.commit()
            row = await db.get(ImageRequestReuse, first)
            assert row.reused_at.tzinfo is not None and row.reuse_count == 1
            owner_id = str(candidate.owner_id)

        async def reuse_once():
            async def validate_asset(row):
                await asyncio.sleep(0)
                return b"synthetic-image", "", 1, 1

            async with sessions.begin() as db:
                return await find_reusable_asset(
                    db,
                    novel_id=str(novel_id),
                    owner_id=owner_id,
                    request_hash="f" * 64,
                    validate_asset=validate_asset,
                )

        hits = await asyncio.wait_for(
            asyncio.gather(*(reuse_once() for _ in range(8))), timeout=20
        )
        assert all(hit is not None for hit in hits)
        async with sessions() as db:
            row = await db.get(ImageRequestReuse, first)
            assert row.reuse_count == 9
            # 同一 session 已缓存登记时，也要回读其他事务刚提交的计数。
            assert await reuse_once() is not None
            assert (
                await find_reusable_asset(
                    db,
                    novel_id=str(novel_id),
                    owner_id=owner_id,
                    request_hash="f" * 64,
                    validate_asset=validate_asset,
                )
                is not None
            )
            await db.commit()
            await db.refresh(row)
            assert row.reuse_count == 11
    finally:
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id == novel_id))
        await engine.dispose()
