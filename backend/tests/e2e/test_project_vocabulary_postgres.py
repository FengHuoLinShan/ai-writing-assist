"""Real database guards and competing author edits for the project vocabulary."""

import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, insert, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.errors import ConflictError
from modules.project.models import Project
from modules.world.project_vocabulary_models import (
    ProjectVocabularyRevision,
    ProjectVocabularyTerm,
)
from modules.world.project_vocabulary_schemas import (
    VocabularyTermCreate,
    VocabularyTermUpdate,
)
from modules.world.project_vocabulary_service import (
    create_project_vocabulary_term,
    update_project_vocabulary_term,
)
from tests.e2e.config import DATABASE_URL
from tests.utils import _create_project

pytestmark = pytest.mark.e2e


async def test_history_rejects_mutation_and_cross_term_revision_links(
    db_session, test_project_id
):
    db = db_session
    first = await create_project_vocabulary_term(
        db, test_project_id, VocabularyTermCreate(kind="feature", name="星门")
    )
    second = await create_project_vocabulary_term(
        db, test_project_id, VocabularyTermCreate(kind="feature", name="浮城")
    )
    for statement, identity in (
        (
            "UPDATE project_vocabulary_revisions SET change_reason='tampered' "
            "WHERE id=:id",
            first.revision_id,
        ),
        ("DELETE FROM project_vocabulary_revisions WHERE id=:id", first.revision_id),
        ("DELETE FROM project_vocabulary_terms WHERE id=:id", first.id),
    ):
        with pytest.raises(DBAPIError, match="history is immutable"):
            async with db.begin_nested():
                await db.execute(text(statement), {"id": identity})

    foreign_novel = uuid4()
    await _create_project(db, str(foreign_novel))
    foreign = await create_project_vocabulary_term(
        db, str(foreign_novel), VocabularyTermCreate(kind="feature", name="异项目词条")
    )
    for other_term in (second, foreign):
        with pytest.raises(
            DBAPIError, match="fk_project_vocabulary_term_current_revision"
        ):
            async with db.begin_nested():
                await db.execute(
                    text(
                        "UPDATE project_vocabulary_terms SET current_revision_id=:r "
                        "WHERE id=:id"
                    ),
                    {"r": other_term.revision_id, "id": first.id},
                )
                await db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

        with pytest.raises(DBAPIError, match="revision_previous_same_novel"):
            async with db.begin_nested():
                await db.execute(
                    insert(ProjectVocabularyRevision).values(
                        id=uuid4(),
                        novel_id=UUID(test_project_id),
                        term_id=first.id,
                        revision_number=2,
                        previous_revision_id=other_term.revision_id,
                        snapshot_json={},
                        content_hash="f" * 64,
                        change_reason="invalid_previous",
                    )
                )


async def test_competing_creates_and_updates_serialize_without_losing_history():
    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    novel_id = uuid4()
    try:
        async with sessions.begin() as db:
            await _create_project(db, str(novel_id))

        async def create(name):
            try:
                async with sessions.begin() as db:
                    return await create_project_vocabulary_term(
                        db, str(novel_id), VocabularyTermCreate(kind="feature", name=name)
                    )
            except ConflictError:
                return None

        created = await asyncio.wait_for(
            asyncio.gather(create("星门"), create("星 门")), timeout=20
        )
        winners = [result for result in created if result is not None]
        assert len(winners) == 1
        original = winners[0]

        async def edit(name):
            try:
                async with sessions.begin() as db:
                    return await update_project_vocabulary_term(
                        db,
                        str(novel_id),
                        str(original.id),
                        VocabularyTermUpdate(
                            expected_revision_id=original.revision_id, name=name
                        ),
                    )
            except ConflictError:
                return None

        edited = await asyncio.wait_for(
            asyncio.gather(edit("东星门"), edit("西星门")), timeout=20
        )
        assert sum(result is not None for result in edited) == 1
        async with sessions() as db:
            history = (
                await db.scalars(
                    select(ProjectVocabularyRevision)
                    .where(ProjectVocabularyRevision.term_id == original.id)
                    .order_by(ProjectVocabularyRevision.revision_number)
                )
            ).all()
            assert [row.revision_number for row in history] == [1, 2]
            assert history[0].snapshot_json["name"] in {"星门", "星 门"}
            assert history[1].previous_revision_id == original.revision_id
    finally:
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id == novel_id))
            assert not (
                await db.scalars(
                    select(ProjectVocabularyTerm.id).where(
                        ProjectVocabularyTerm.novel_id == novel_id
                    )
                )
            ).all()
        await engine.dispose()


async def test_migration_history_guard_only_allows_real_project_cascade(db_session):
    """Exercise the actual migration in an isolated schema of the dedicated DB."""
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    db = db_session
    schema = f"vocabulary_guard_{uuid4().hex}"
    await db.execute(text(f'CREATE SCHEMA "{schema}"'))
    await db.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
    await db.execute(text("CREATE TABLE projects (id uuid PRIMARY KEY)"))
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "alembic/versions/20261015_project_vocabulary.py"
    )
    spec = importlib.util.spec_from_file_location(
        "vocabulary_guard_migration", migration_path
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    def run_migration(session, direction):
        migration.op = Operations(MigrationContext.configure(session.connection()))
        getattr(migration, direction)()

    await db.run_sync(run_migration, "upgrade")
    project_id, term_id, revision_id = uuid4(), uuid4(), uuid4()
    await db.execute(text("INSERT INTO projects (id) VALUES (:id)"), {"id": project_id})
    await db.execute(
        text(
            "INSERT INTO project_vocabulary_terms "
            "(id, novel_id, kind, source, status, author_confirmed, "
            "created_at, updated_at) "
            "VALUES (:term, :novel, 'feature', 'author', 'active', true, now(), now())"
        ),
        {"term": term_id, "novel": project_id},
    )
    await db.execute(
        text(
            "INSERT INTO project_vocabulary_revisions "
            "(id, novel_id, term_id, revision_number, snapshot_json, "
            "content_hash, change_reason, created_at) "
            "VALUES (:revision, :novel, :term, 1, '{}', :hash, 'author_created', now())"
        ),
        {"revision": revision_id, "novel": project_id, "term": term_id, "hash": "a" * 64},
    )
    await db.execute(
        text(
            "UPDATE project_vocabulary_terms SET current_revision_id=:revision "
            "WHERE id=:term"
        ),
        {"revision": revision_id, "term": term_id},
    )
    await db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    with pytest.raises(RuntimeError, match="downgrade would discard author data"):
        await db.run_sync(run_migration, "downgrade")

    # An unrelated trigger raises trigger depth too. It is not project deletion.
    await db.execute(text("CREATE TEMP TABLE vocabulary_delete_probe (id uuid)"))
    await db.execute(
        text("""CREATE FUNCTION pg_temp.delete_vocabulary_probe()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
        DELETE FROM project_vocabulary_terms WHERE id=NEW.id;
        RETURN NEW; END $$""")
    )
    await db.execute(
        text("""CREATE TRIGGER vocabulary_delete_probe
        AFTER INSERT ON vocabulary_delete_probe FOR EACH ROW
        EXECUTE FUNCTION pg_temp.delete_vocabulary_probe()""")
    )
    with pytest.raises(DBAPIError, match="history is immutable"):
        async with db.begin_nested():
            await db.execute(
                text("INSERT INTO vocabulary_delete_probe VALUES (:id)"), {"id": term_id}
            )
    assert await db.scalar(text("SELECT count(*) FROM project_vocabulary_terms")) == 1
    assert await db.scalar(text("SELECT count(*) FROM project_vocabulary_revisions")) == 1

    # A caller's temporary table must not impersonate the owning project table.
    with pytest.raises(DBAPIError, match="history is immutable"):
        async with db.begin_nested():
            await db.execute(text("CREATE TEMP TABLE projects (id uuid PRIMARY KEY)"))
            await db.execute(
                text("DELETE FROM project_vocabulary_terms WHERE id=:id"),
                {"id": term_id},
            )

    # The supported permanent project deletion still removes both tables' rows.
    await db.execute(text("DELETE FROM projects WHERE id=:id"), {"id": project_id})
    assert await db.scalar(text("SELECT count(*) FROM project_vocabulary_terms")) == 0
    assert await db.scalar(text("SELECT count(*) FROM project_vocabulary_revisions")) == 0
    await db.run_sync(run_migration, "downgrade")
    for table in ("project_vocabulary_terms", "project_vocabulary_revisions"):
        assert (
            await db.scalar(
                text("SELECT to_regclass(:name)"), {"name": f"{schema}.{table}"}
            )
            is None
        )
