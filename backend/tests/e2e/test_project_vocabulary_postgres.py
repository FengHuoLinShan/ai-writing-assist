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

    with pytest.raises(DBAPIError, match="fk_project_vocabulary_term_current_revision"):
        async with db.begin_nested():
            await db.execute(
                text(
                    "UPDATE project_vocabulary_terms SET current_revision_id=:r "
                    "WHERE id=:id"
                ),
                {"r": second.revision_id, "id": first.id},
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
                    previous_revision_id=second.revision_id,
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
