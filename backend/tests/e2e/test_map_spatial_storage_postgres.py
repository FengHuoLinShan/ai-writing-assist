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
