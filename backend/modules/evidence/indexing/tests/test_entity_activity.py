from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.evidence.indexing.entity_activity import EntityActivityService
from modules.evidence.indexing.models import RagEntityAppearance, RagIndexState
from modules.evidence.indexing.repositories import RagChunkRepository
from modules.evidence.indexing.schemas import RagChunkCreate


@pytest.mark.asyncio
async def test_replace_appearances_deduplicates_scene_and_chapter_fallback(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    repo = RagChunkRepository()
    entity_id = uuid.uuid4()
    scene_id = uuid.uuid4()
    chunks = [
        RagChunkCreate(
            source_type="chapter_text",
            content_mode="canonical",
            source_content_hash="1" * 64,
            chapter_index=1,
            chunk_index=index,
            text=f"片段 {index}",
            entity_ids=[str(entity_id)],
            scene_id=str(scene_id),
        )
        for index in range(2)
    ]
    await repo.replace_entity_appearances(
        db_session,
        uuid.UUID(test_project_id),
        chapter_index=1,
        content_mode="canonical",
        chunks=chunks,
    )

    rows = list((await db_session.execute(select(RagEntityAppearance))).scalars())
    assert len(rows) == 1
    assert rows[0].occurrence_key == f"scene:{scene_id}"
    assert rows[0].chunk_count == 2

    fallback_chunks = [
        RagChunkCreate(
            source_type="chapter_text",
            content_mode="canonical",
            source_content_hash="2" * 64,
            chapter_index=2,
            chunk_index=index,
            text=f"无场景片段 {index}",
            character_ids=[str(entity_id)],
        )
        for index in range(2)
    ]
    await repo.replace_entity_appearances(
        db_session,
        uuid.UUID(test_project_id),
        chapter_index=2,
        content_mode="canonical",
        chunks=fallback_chunks,
    )
    rows = list(
        (
            await db_session.execute(
                select(RagEntityAppearance).order_by(
                    RagEntityAppearance.chapter_index
                )
            )
        ).scalars()
    )
    assert [row.occurrence_key for row in rows] == [
        f"scene:{scene_id}",
        "chapter:2",
    ]


@pytest.mark.asyncio
async def test_replace_appearances_deduplicates_scene_across_chapters(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    repo = RagChunkRepository()
    novel_id = uuid.UUID(test_project_id)
    entity_id = uuid.uuid4()
    scene_id = uuid.uuid4()
    for chapter_index in (1, 2):
        await repo.replace_entity_appearances(
            db_session,
            novel_id,
            chapter_index=chapter_index,
            content_mode="canonical",
            chunks=[
                RagChunkCreate(
                    source_type="chapter_text",
                    content_mode="canonical",
                    source_content_hash=str(chapter_index) * 64,
                    chapter_index=chapter_index,
                    chunk_index=0,
                    text="同一个跨章 Scene",
                    entity_ids=[str(entity_id)],
                    scene_id=str(scene_id),
                )
            ],
        )

    rows = list((await db_session.execute(select(RagEntityAppearance))).scalars())
    assert len(rows) == 1
    assert rows[0].occurrence_key == f"scene:{scene_id}"
    assert rows[0].chapter_index == 2


@pytest.mark.asyncio
async def test_chapter_replacement_rebuilds_cross_chapter_scene_once(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    repo = RagChunkRepository()
    novel_id = uuid.UUID(test_project_id)
    entity_id = uuid.uuid4()
    scene_id = uuid.uuid4()
    first_hash = "a" * 64
    second_hash = "b" * 64

    await repo.replace_chapter_chunks(
        db_session,
        novel_id,
        source_type="chapter_text",
        chapter_index=1,
        content_mode="canonical",
        items=[
            RagChunkCreate(
                source_type="chapter_text",
                content_mode="canonical",
                source_content_hash=first_hash,
                chapter_index=1,
                chunk_index=0,
                text="跨章 Scene 的前半段",
                entity_ids=[str(entity_id)],
                scene_id=str(scene_id),
            )
        ],
    )
    db_session.add(
        RagIndexState(
            novel_id=novel_id,
            chapter_index=1,
            content_mode="canonical",
            requested_hash=first_hash,
            indexed_hash=first_hash,
            status="succeeded",
        )
    )
    await db_session.flush()

    await repo.replace_chapter_chunks(
        db_session,
        novel_id,
        source_type="chapter_text",
        chapter_index=2,
        content_mode="canonical",
        items=[
            RagChunkCreate(
                source_type="chapter_text",
                content_mode="canonical",
                source_content_hash=second_hash,
                chapter_index=2,
                chunk_index=0,
                text="跨章 Scene 的后半段",
                entity_ids=[str(entity_id)],
                scene_id=str(scene_id),
            )
        ],
    )

    rows = list((await db_session.execute(select(RagEntityAppearance))).scalars())
    assert len(rows) == 1
    assert rows[0].occurrence_key == f"scene:{scene_id}"
    assert rows[0].chapter_index == 2
    assert rows[0].chunk_count == 2


@pytest.mark.asyncio
async def test_project_reannotation_rows_tolerate_legacy_mixed_hashes(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    entity_id = uuid.uuid4()
    scene_id = uuid.uuid4()
    chunks = [
        RagChunkCreate(
            source_type="chapter_text",
            content_mode="canonical",
            source_content_hash=hash_char * 64,
            chapter_index=1,
            chunk_index=index,
            text="legacy",
            entity_ids=[str(entity_id)],
            scene_id=str(scene_id),
        )
        for index, hash_char in enumerate(("a", "b"))
    ]

    await RagChunkRepository().replace_project_entity_appearances(
        db_session,
        uuid.UUID(test_project_id),
        chunks=chunks,  # type: ignore[arg-type]
    )

    rows = list((await db_session.execute(select(RagEntityAppearance))).scalars())
    assert len(rows) == 1
    assert rows[0].chunk_count == 2


@pytest.mark.asyncio
async def test_activity_prefers_fresh_working_and_ignores_stale_hash_and_other_novel(
    db_session: AsyncSession,
    test_project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id = uuid.UUID(test_project_id)
    entity_id = uuid.uuid4()
    other_novel_id = uuid.uuid4()
    from modules.project.models import Project

    db_session.add(Project(id=other_novel_id, title="另一个项目"))
    db_session.add_all(
        [
            RagIndexState(
                novel_id=novel_id,
                chapter_index=1,
                content_mode="canonical",
                requested_hash="canonical-1",
                indexed_hash="canonical-1",
                status="succeeded",
            ),
            RagIndexState(
                novel_id=novel_id,
                chapter_index=1,
                content_mode="working",
                requested_hash="working-1",
                indexed_hash="working-1",
                status="succeeded",
            ),
            RagIndexState(
                novel_id=novel_id,
                chapter_index=2,
                content_mode="canonical",
                requested_hash="new-hash",
                indexed_hash="old-hash",
                status="succeeded",
            ),
        ]
    )
    for scene_id in (uuid.uuid4(), uuid.uuid4()):
        db_session.add(
            RagEntityAppearance(
                novel_id=novel_id,
                entity_id=entity_id,
                content_mode="working",
                chapter_index=1,
                scene_id=scene_id,
                occurrence_key=f"scene:{scene_id}",
                source_content_hash="working-1",
                chunk_count=1,
            )
        )
    db_session.add_all(
        [
            RagEntityAppearance(
                novel_id=novel_id,
                entity_id=entity_id,
                content_mode="canonical",
                chapter_index=1,
                occurrence_key="chapter:1",
                source_content_hash="canonical-1",
                chunk_count=1,
            ),
            RagEntityAppearance(
                novel_id=novel_id,
                entity_id=entity_id,
                content_mode="canonical",
                chapter_index=2,
                occurrence_key="chapter:2",
                source_content_hash="old-hash",
                chunk_count=1,
            ),
            RagEntityAppearance(
                novel_id=other_novel_id,
                entity_id=entity_id,
                content_mode="working",
                chapter_index=1,
                occurrence_key="chapter:1",
                source_content_hash="working-1",
                chunk_count=1,
            ),
        ]
    )
    await db_session.flush()

    async def list_indices(_db, _novel_id):
        return [1, 2]

    monkeypatch.setattr(
        "modules.evidence.indexing.entity_activity._container_get",
        lambda _name: list_indices,
    )
    result = await EntityActivityService().get_stats(db_session, test_project_id)

    assert result.status == "partial"
    assert result.as_of_chapter == 2
    assert result.covered_chapters == 1
    assert len(result.items) == 1
    assert result.items[0].entity_id == str(entity_id)
    assert result.items[0].appearance_chapters == [1, 1]


@pytest.mark.asyncio
async def test_reannotation_coalesces_per_project(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    service = EntityActivityService()

    first = await service.request_reannotation(db_session, test_project_id)
    second = await service.request_reannotation(db_session, test_project_id)

    assert second == first
    from infrastructure.tasks.models import AsyncTask

    tasks = list(
        (
            await db_session.execute(
                select(AsyncTask).where(
                    AsyncTask.task_type == "rag_reannotate_entities"
                )
            )
        ).scalars()
    )
    assert len(tasks) == 1
    assert tasks[0].meta == {"novel_id": test_project_id}


@pytest.mark.asyncio
async def test_reannotation_queues_one_follower_while_task_is_running(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    from infrastructure.tasks.models import AsyncTask

    service = EntityActivityService()
    first = await service.request_reannotation(db_session, test_project_id)
    task = await db_session.get(AsyncTask, uuid.UUID(first))
    assert task is not None
    task.mark_running()
    await db_session.flush()

    follower = await service.request_reannotation(db_session, test_project_id)
    duplicate = await service.request_reannotation(db_session, test_project_id)

    assert follower != first
    assert duplicate == follower
    tasks = list(
        (
            await db_session.execute(
                select(AsyncTask)
                .where(AsyncTask.task_type == "rag_reannotate_entities")
                .order_by(AsyncTask.created_at, AsyncTask.id)
            )
        ).scalars()
    )
    assert [item.status for item in tasks] == ["running", "pending"]


@pytest.mark.asyncio
async def test_reannotation_updates_terms_and_appearances_without_embedding(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    from modules.world.models import CoreEntity

    novel_id = uuid.UUID(test_project_id)
    entity_id = uuid.uuid4()
    db_session.add(
        CoreEntity(
            id=entity_id,
            novel_id=novel_id,
            entity_type="item",
            name="王冠碎片",
            status="canonical",
        )
    )
    chunk = await RagChunkRepository().create(
        db_session,
        novel_id,
        RagChunkCreate(
            source_type="chapter_text",
            content_mode="canonical",
            source_content_hash="a" * 64,
            chapter_index=3,
            chunk_index=0,
            text="信使带着王冠碎片离开王都。",
            embedding_status="succeeded",
        ),
    )
    chunk.embedding = [0.1] * 768  # type: ignore[assignment]
    db_session.add(
        RagIndexState(
            novel_id=novel_id,
            chapter_index=3,
            content_mode="canonical",
            requested_hash="a" * 64,
            indexed_hash="a" * 64,
            status="succeeded",
        )
    )
    await db_session.flush()

    result = await EntityActivityService().reannotate_project(
        db_session,
        test_project_id,
    )

    assert result == {
        "chunks_scanned": 1,
        "chunks_changed": 1,
        "chapter_modes_rebuilt": 1,
    }
    assert chunk.entity_ids == [str(entity_id)]
    assert list(chunk.embedding) == [0.1] * 768
    assert chunk.embedding_status == "succeeded"
    appearances = list(
        (
            await db_session.execute(
                select(RagEntityAppearance).where(
                    RagEntityAppearance.novel_id == novel_id
                )
            )
        ).scalars()
    )
    assert len(appearances) == 1
    assert appearances[0].entity_id == entity_id
    assert appearances[0].occurrence_key == "chapter:3"


@pytest.mark.asyncio
async def test_reannotation_term_load_failure_preserves_existing_projection(
    db_session: AsyncSession,
    test_project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id = uuid.UUID(test_project_id)
    entity_id = uuid.uuid4()
    chunk = await RagChunkRepository().create(
        db_session,
        novel_id,
        RagChunkCreate(
            source_type="chapter_text",
            content_mode="canonical",
            source_content_hash="c" * 64,
            chapter_index=4,
            chunk_index=0,
            text="旧关联必须保留",
            entity_ids=[str(entity_id)],
        ),
    )
    appearance = RagEntityAppearance(
        novel_id=novel_id,
        entity_id=entity_id,
        content_mode="canonical",
        chapter_index=4,
        occurrence_key="chapter:4",
        source_content_hash="c" * 64,
        chunk_count=1,
    )
    db_session.add(appearance)
    await db_session.flush()

    async def fail_terms(*_args, **_kwargs):
        raise RuntimeError("world term port unavailable")

    monkeypatch.setattr(
        "modules.evidence.indexing.entity_activity._load_project_terms",
        fail_terms,
    )
    with pytest.raises(RuntimeError, match="term port unavailable"):
        await EntityActivityService().reannotate_project(
            db_session,
            test_project_id,
        )

    assert chunk.entity_ids == [str(entity_id)]
    rows = list((await db_session.execute(select(RagEntityAppearance))).scalars())
    assert [row.id for row in rows] == [appearance.id]
