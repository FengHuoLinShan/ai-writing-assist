"""Auto-draft review state survives PostgreSQL reloads and lock contention."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from core.errors import ConflictError
from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID
from modules.project.facade import require_active_project
from modules.project.models import Project
from modules.world.map_atlas_models import MapAtlasRevision
from modules.world.map_auto_draft_models import MapAutoDraftBatchRecord
from modules.world.map_auto_draft_schemas import (
    MapAutoDraftTrayPlacementPreviewRequest,
    MapAutoDraftTrayPlacementRequest,
)
from modules.world.map_auto_draft_service import (
    build_map_auto_drafts,
    place_map_auto_draft_tray_item,
    preview_map_auto_draft_tray_placement,
)
from modules.world.map_structure_schemas import MapPoint
from modules.world.tests.test_map_auto_draft_service import (
    _build_request,
    _stage_bound_clue,
)
from tests.e2e.config import require_e2e_database_url

pytestmark = pytest.mark.e2e


@pytest.mark.parametrize("kind", ["connection", "effective_change"])
async def test_tray_json_and_lineage_survive_reload_with_same_project_fk(
    db_session, kind
):
    novel_id, other_id = uuid4(), uuid4()
    db_session.add_all(
        [
            Project(
                id=novel_id, owner_id=BOOTSTRAP_ACCOUNT_ID, title="synthetic auto draft"
            ),
            Project(
                id=other_id, owner_id=BOOTSTRAP_ACCOUNT_ID, title="synthetic other draft"
            ),
        ]
    )
    await db_session.flush()
    scene, _start, _end, clue = await _stage_bound_clue(
        db_session,
        str(novel_id),
        modality="character_statement",
        effective=True,
        kind=kind,
    )
    built = await build_map_auto_drafts(
        db_session, str(novel_id), _build_request(scene, clue)
    )
    tray = built.tray_items[0]
    ref = next(item for item in built.revisions if item.node_id == tray.node_id)
    args = (
        db_session,
        str(novel_id),
        str(built.batch_id),
        str(tray.node_id),
        str(ref.revision_id),
        str(tray.item_id),
    )
    request = MapAutoDraftTrayPlacementPreviewRequest(
        expected_fingerprint=tray.fingerprint,
        point=MapPoint(x=120, y=180),
    )
    preview = await preview_map_auto_draft_tray_placement(*args, request)
    confirmed = MapAutoDraftTrayPlacementRequest(
        **request.model_dump(),
        preview_fingerprint=preview.preview_fingerprint,
        confirmed=True,
    )
    placed = await place_map_auto_draft_tray_item(*args, confirmed)
    await db_session.flush()
    db_session.expunge_all()
    batch = await db_session.get(MapAutoDraftBatchRecord, built.batch_id)
    old_ref = next(
        item for item in batch.result_refs if item["revision_id"] == str(ref.revision_id)
    )
    new_ref = next(
        item
        for item in batch.result_refs
        if item["revision_id"] == str(placed.revision_id)
    )
    assert old_ref["status"] == "superseded"
    assert new_ref["status"] == "candidate"
    assert str(tray.clue_id) in new_ref["source_clue_ids"]
    assert (
        next(item for item in batch.tray_items if item["item_id"] == str(tray.item_id))[
            "placed_feature_id"
        ]
        == placed.placed_feature_id
    )
    revision = await db_session.get(MapAtlasRevision, placed.revision_id)
    assert revision.base_revision_id == ref.revision_id
    assert revision.change_summary == {"auto_draft_review_base_revision_id": None}
    assert (revision.document["features"][0]["effective"] is not None) == (
        kind == "effective_change"
    )
    replay = await place_map_auto_draft_tray_item(*args, confirmed)
    assert replay.revision_id == placed.revision_id
    assert (
        len(
            (
                await db_session.scalars(
                    select(MapAtlasRevision).where(
                        MapAtlasRevision.node_id == tray.node_id,
                        MapAtlasRevision.status == "candidate",
                    )
                )
            ).all()
        )
        == 1
    )
    with pytest.raises(DBAPIError, match="fk_map_revision_node"):
        async with db_session.begin_nested():
            db_session.add(
                MapAtlasRevision(
                    novel_id=other_id,
                    node_id=tray.node_id,
                    status="candidate",
                    document={},
                    geometry_hash="a" * 64,
                    problems=[],
                )
            )
            await db_session.flush()


async def test_auto_build_share_lock_upgrade_is_retryable_and_replay_is_unique():
    engine = create_async_engine(require_e2e_database_url(), pool_size=3)
    novel_id = uuid4()
    try:
        async with AsyncSession(engine, expire_on_commit=False) as seed:
            seed.add(
                Project(
                    id=novel_id,
                    owner_id=BOOTSTRAP_ACCOUNT_ID,
                    title="synthetic auto lock",
                )
            )
            await seed.flush()
            scene, _start, _end, clue = await _stage_bound_clue(seed, str(novel_id))
            request = _build_request(scene, clue)
            await seed.commit()
        async with AsyncSession(engine) as first, AsyncSession(engine) as second:
            await require_active_project(first, str(novel_id))
            await require_active_project(second, str(novel_id))
            outcomes = await asyncio.wait_for(
                asyncio.gather(
                    build_map_auto_drafts(first, str(novel_id), request),
                    build_map_auto_drafts(second, str(novel_id), request),
                    return_exceptions=True,
                ),
                timeout=5,
            )
            assert all(isinstance(outcome, ConflictError) for outcome in outcomes), (
                outcomes
            )
            assert await first.scalar(text("SELECT 1")) == 1
            assert await second.scalar(text("SELECT 1")) == 1
            await first.rollback()
            await second.rollback()
        async with AsyncSession(engine, expire_on_commit=False) as retry:
            built = await build_map_auto_drafts(retry, str(novel_id), request)
            replay = await build_map_auto_drafts(retry, str(novel_id), request)
            assert replay.batch_id == built.batch_id
            assert replay.revisions == built.revisions
            await retry.commit()
        async with AsyncSession(engine) as fresh:
            batch = await fresh.get(MapAutoDraftBatchRecord, built.batch_id)
            assert batch.cursor == 1
            assert len(batch.result_refs) == 1
    finally:
        async with engine.begin() as cleanup:
            await cleanup.execute(
                text("DELETE FROM projects WHERE id=:id"), {"id": novel_id}
            )
        await engine.dispose()
