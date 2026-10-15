"""Exercise spatial storage migrations against the dedicated PostgreSQL database."""

import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.e2e


async def test_superseded_map_migration_preserves_history_on_downgrade(db_session):
    db = db_session
    schema = f"map_draft_guard_{uuid4().hex}"
    await db.execute(text(f'CREATE SCHEMA "{schema}"'))
    await db.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
    await db.execute(
        text(
            "CREATE TABLE map_atlas_revisions (id uuid PRIMARY KEY, status text "
            "CONSTRAINT ck_map_revision_status CHECK "
            "(status IN ('candidate', 'saved', 'rejected')))"
        )
    )
    spec = importlib.util.spec_from_file_location(
        "map_draft_superseded_migration",
        Path(__file__).resolve().parents[2]
        / "alembic/versions/20261015_map_draft_superseded.py",
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    def run_migration(session, direction):
        migration.op = Operations(MigrationContext.configure(session.connection()))
        getattr(migration, direction)()

    await db.run_sync(run_migration, "upgrade")
    for status in ("candidate", "saved", "rejected", "superseded"):
        await db.execute(
            text("INSERT INTO map_atlas_revisions VALUES (:id, :status)"),
            {"id": uuid4(), "status": status},
        )
    with pytest.raises(DBAPIError, match="ck_map_revision_status"):
        async with db.begin_nested():
            await db.execute(
                text("INSERT INTO map_atlas_revisions VALUES (:id, 'unreviewed')"),
                {"id": uuid4()},
            )
    with pytest.raises(RuntimeError, match="downgrade would discard review history"):
        await db.run_sync(run_migration, "downgrade")
    assert await db.scalar(text("SELECT count(*) FROM map_atlas_revisions")) == 4
    await db.execute(text("DELETE FROM map_atlas_revisions WHERE status = 'superseded'"))
    await db.run_sync(run_migration, "downgrade")
    assert await db.scalar(text("SELECT count(*) FROM map_atlas_revisions")) == 3
    with pytest.raises(DBAPIError, match="ck_map_revision_status"):
        async with db.begin_nested():
            await db.execute(
                text("INSERT INTO map_atlas_revisions VALUES (:id, 'superseded')"),
                {"id": uuid4()},
            )


async def test_spatial_stage_share_lock_upgrade_is_retryable_and_replay_is_unique():
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from core.errors import ConflictError
    from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID
    from modules.project.facade import require_active_project
    from modules.project.models import Project
    from modules.world.map_spatial_clue_service import stage_spatial_discovery
    from modules.world.tests.test_map_spatial_clue_boundaries import _bound_batch, _source
    from tests.e2e.config import require_e2e_database_url

    engine = create_async_engine(require_e2e_database_url(), pool_size=3)
    novel_id = uuid4()
    try:
        async with AsyncSession(engine, expire_on_commit=False) as seed:
            seed.add(
                Project(
                    id=novel_id,
                    owner_id=BOOTSTRAP_ACCOUNT_ID,
                    title="synthetic spatial lock regression",
                )
            )
            await seed.flush()
            scene, _, _, binding, evidence = await _source(seed, str(novel_id))
            batch = _bound_batch(str(novel_id), scene, binding, evidence)
            await seed.commit()
        async with AsyncSession(engine) as first, AsyncSession(engine) as second:
            await require_active_project(first, str(novel_id))
            await require_active_project(second, str(novel_id))
            outcomes = await asyncio.wait_for(
                asyncio.gather(
                    stage_spatial_discovery(first, str(novel_id), batch),
                    stage_spatial_discovery(second, str(novel_id), batch),
                    return_exceptions=True,
                ),
                timeout=5,
            )
            assert all(isinstance(outcome, ConflictError) for outcome in outcomes), (
                outcomes
            )
            # Failed NOWAIT rolled back its savepoint; both callers can still query.
            assert await first.scalar(text("SELECT 1")) == 1
            assert await second.scalar(text("SELECT 1")) == 1
            await first.rollback()
            await second.rollback()
        async with AsyncSession(engine) as retry:
            result = await stage_spatial_discovery(retry, str(novel_id), batch)
            replay = await stage_spatial_discovery(retry, str(novel_id), batch)
            assert len(result.accepted) == 1, result.diagnostics
            assert result.result_refs == replay.result_refs
            assert (
                await retry.scalar(
                    text("SELECT count(*) FROM map_spatial_clues WHERE novel_id=:novel"),
                    {"novel": novel_id},
                )
                == 1
            )
            await retry.commit()
    finally:
        async with engine.begin() as cleanup:
            await cleanup.execute(
                text("DELETE FROM projects WHERE id=:novel"), {"novel": novel_id}
            )
        await engine.dispose()


async def test_spatial_clue_merge_same_novel_guard_and_project_delete_cascade(db_session):
    from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID
    from modules.project.models import Project
    from modules.world.map_spatial_clue_models import MapSpatialClueRecord
    from modules.world.map_spatial_clue_schemas import MapSpatialClueDecisionRequest
    from modules.world.map_spatial_clue_service import (
        review_spatial_clue,
        stage_spatial_discovery,
    )
    from modules.world.tests.test_map_spatial_clue_boundaries import _bound_batch, _source

    novel_id, other_novel_id = uuid4(), uuid4()
    db_session.add_all(
        [
            Project(
                id=novel_id, owner_id=BOOTSTRAP_ACCOUNT_ID, title="synthetic clue cascade"
            ),
            Project(
                id=other_novel_id,
                owner_id=BOOTSTRAP_ACCOUNT_ID,
                title="synthetic clue isolation",
            ),
        ]
    )
    await db_session.flush()
    scene, _, _, binding, evidence = await _source(db_session, str(novel_id))
    first = await stage_spatial_discovery(
        db_session, str(novel_id), _bound_batch(str(novel_id), scene, binding, evidence)
    )
    second = await stage_spatial_discovery(
        db_session,
        str(novel_id),
        _bound_batch(str(novel_id), scene, binding, evidence, key="b"),
    )
    source = await db_session.get(MapSpatialClueRecord, first.accepted[0].clue_id)
    target = await db_session.get(MapSpatialClueRecord, second.accepted[0].clue_id)
    merged = await review_spatial_clue(
        db_session,
        str(novel_id),
        str(source.id),
        MapSpatialClueDecisionRequest(
            action="merge",
            expected_fingerprint=source.fingerprint,
            confirmed=True,
            target_clue_id=target.id,
            target_fingerprint=target.fingerprint,
        ),
    )
    assert merged.status == "superseded"
    with pytest.raises(DBAPIError, match="fk_map_spatial_clues_merge_same_novel"):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE map_spatial_clues SET novel_id=:other WHERE id=:source"),
                {"other": other_novel_id, "source": source.id},
            )
    with pytest.raises(DBAPIError, match="uq_map_spatial_clues_attempt_key"):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE map_spatial_clues SET clue_key=:key WHERE id=:target"),
                {"key": source.clue_key, "target": target.id},
            )
    await db_session.execute(
        text("DELETE FROM projects WHERE id=:novel"), {"novel": novel_id}
    )
    assert (
        await db_session.scalar(
            text("SELECT count(*) FROM map_spatial_clues WHERE novel_id=:novel"),
            {"novel": novel_id},
        )
        == 0
    )
