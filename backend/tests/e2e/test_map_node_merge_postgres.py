"""PostgreSQL merge CAS, historical redirects and cached writer isolation."""

import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.errors import ConflictError
from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID
from modules.project.models import Project
from modules.world.map_atlas_models import MapAtlasNode, MapAtlasRevision
from modules.world.map_atlas_schemas import MapAtlasNodeUpdate
from modules.world.map_atlas_service import MapAtlasService
from modules.world.map_merge_lineage import excluded_merge_targets
from modules.world.map_node_merge import (
    MapNodeMergeApplyRequest,
    MapNodeMergeService,
    MapNodeMergeUndoRequest,
)
from modules.world.map_structure_schemas import MapNodeCreate
from modules.world.map_structure_service import MapStructureService
from tests.e2e.config import require_e2e_database_url

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_merge_one_winner_cached_writer_rejects_tombstone_and_undo_appends():
    engine = create_async_engine(require_e2e_database_url(), pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    nid, other_id = uuid4(), uuid4()
    try:
        async with sessions.begin() as db:
            db.add_all(
                [
                    Project(
                        id=value,
                        title="synthetic merge CAS",
                        owner_id=BOOTSTRAP_ACCOUNT_ID,
                    )
                    for value in (nid, other_id)
                ]
            )
            await db.flush()
            structure = MapStructureService()
            source = await structure.create_node(
                db, str(nid), MapNodeCreate(title="来源地图")
            )
            target = await structure.create_node(
                db, str(nid), MapNodeCreate(title="目标地图")
            )
            foreign = await structure.create_node(
                db, str(other_id), MapNodeCreate(title="隔离地图")
            )
            service = MapNodeMergeService()
            preview = await service.preview(db, str(nid), source["id"], target["id"])
        async with sessions() as cached:
            cached_source = await cached.get(MapAtlasNode, UUID(source["id"]))
            stale_time = cached_source.updated_at
            await (
                cached.commit()
            )  # Keep the identity map while releasing the read transaction.
            gate = asyncio.Event()
            request = MapNodeMergeApplyRequest(
                source_node_id=source["id"],
                target_node_id=target["id"],
                preview_fingerprint=preview.fingerprint,
                confirmed_source_disposition=True,
            )

            async def merge():
                await gate.wait()
                try:
                    async with sessions.begin() as db:
                        return await service.apply(db, str(nid), request)
                except ConflictError:
                    return None

            tasks = [asyncio.create_task(merge()) for _ in range(2)]
            gate.set()
            results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=10)
            assert sum(value is not None for value in results) == 1
            with pytest.raises(ConflictError, match="已合并"):
                await MapAtlasService().update_node(
                    cached,
                    str(nid),
                    source["id"],
                    MapAtlasNodeUpdate(
                        title="缓存不能复活墓碑", expected_updated_at=stale_time
                    ),
                )
            await cached.rollback()
        async with sessions.begin() as db:
            source_revision_id = await db.scalar(
                select(MapAtlasNode.current_revision_id).where(
                    MapAtlasNode.novel_id == nid,
                    MapAtlasNode.id == UUID(source["id"]),
                )
            )
            node_ids = [UUID(source["id"]), UUID(target["id"])]
            for excluded_nodes, excluded_revisions in (
                ({source["id"]}, set()),
                (set(), {str(source_revision_id)}),
            ):
                assert await excluded_merge_targets(
                    db,
                    nid,
                    node_ids,
                    excluded_nodes=excluded_nodes,
                    excluded_revisions=excluded_revisions,
                ) == {target["id"]}
                assert not await excluded_merge_targets(
                    db,
                    other_id,
                    node_ids,
                    excluded_nodes=excluded_nodes,
                    excluded_revisions=excluded_revisions,
                )
            with pytest.raises(
                DBAPIError, match="fk_map_atlas_node_merged_into_same_novel"
            ):
                async with db.begin_nested():
                    await db.execute(
                        update(MapAtlasNode)
                        .where(MapAtlasNode.id == UUID(source["id"]))
                        .values(merged_into_node_id=UUID(foreign["id"]))
                    )
            with pytest.raises(
                DBAPIError, match="ck_map_atlas_node_not_merged_into_self"
            ):
                async with db.begin_nested():
                    await db.execute(
                        update(MapAtlasNode)
                        .where(MapAtlasNode.id == UUID(source["id"]))
                        .values(merged_into_node_id=UUID(source["id"]))
                    )
            undo = await service.preview_undo(db, str(nid), source["id"], target["id"])
            assert undo.can_undo, undo.blockers
            restored = await service.undo(
                db,
                str(nid),
                MapNodeMergeUndoRequest(
                    source_node_id=source["id"],
                    target_node_id=target["id"],
                    preview_fingerprint=undo.fingerprint,
                    confirmed=True,
                ),
            )
        async with sessions() as db:
            revisions = list(
                (
                    await db.scalars(
                        select(MapAtlasRevision).where(MapAtlasRevision.novel_id == nid)
                    )
                ).all()
            )
            assert (
                len(revisions) == 4
            )  # Two original heads plus immutable merge and undo.
            assert (
                str((await db.get(MapAtlasNode, UUID(target["id"]))).current_revision_id)
                == restored["restored_revision_id"]
            )
            assert (
                await db.get(MapAtlasNode, UUID(source["id"]))
            ).merged_into_node_id is None
    finally:
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id.in_([nid, other_id])))
        await engine.dispose()
