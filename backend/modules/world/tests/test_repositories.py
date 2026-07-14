"""World 模块 repository 层集成测试。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from modules.project.models import Project
from modules.world.models import Character, CoreEntity
from modules.world.repositories import CharacterRepository, CoreEntityRepository


@pytest.fixture
def repo() -> CoreEntityRepository:
    return CoreEntityRepository()


class _PostgresDialectSessionProxy:
    """Run the PostgreSQL branch against SQLite's real transaction machinery."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.execute_count = 0
        self.nested_count = 0

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    async def connection(self):
        connection = await self._session.connection()
        owner = self

        class _ConnectionProxy:
            def begin_nested(self):
                owner.nested_count += 1
                return connection.begin_nested()

        return _ConnectionProxy()

    async def execute(self, statement):
        self.execute_count += 1
        return await self._session.execute(statement)


@pytest.mark.asyncio
async def test_fuzzy_entity_fallback_uses_savepoint_before_python_query(
    repo: CoreEntityRepository,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4()
    other_novel_id = uuid.uuid4()
    db_session.add_all(
        [
            Project(id=novel_id, title="target"),
            Project(id=other_novel_id, title="other"),
            CoreEntity(
                novel_id=novel_id,
                entity_type="organization",
                name="塔罗会",
                importance=0.9,
                status="canonical",
            ),
            CoreEntity(
                novel_id=novel_id,
                entity_type="organization",
                name="塔罗会",
                importance=0.5,
                status="canonical",
            ),
            CoreEntity(
                novel_id=other_novel_id,
                entity_type="organization",
                name="塔罗会",
                importance=1.0,
                status="canonical",
            ),
        ]
    )
    await db_session.flush()
    pending_project = Project(id=uuid.uuid4(), title="must-stay-pending")
    db_session.add(pending_project)
    db = _PostgresDialectSessionProxy(db_session)

    with db_session.no_autoflush:
        items, total = await repo._fuzzy_entities_by_novel(
            db,  # type: ignore[arg-type]
            conditions=[
                CoreEntity.novel_id == novel_id,
                CoreEntity.status == "canonical",
            ],
            query="塔罗会",
            skip=0,
            limit=1,
        )

    assert len(items) == 1
    assert items[0].novel_id == novel_id
    assert items[0].importance == 0.9
    assert total == 2
    assert db.nested_count == 1
    assert db.execute_count == 2
    assert db_session.in_transaction()
    assert pending_project in db_session.new
    assert (
        await db_session.scalar(select(Project.id).where(Project.id == novel_id))
    ) == novel_id


@pytest.mark.asyncio
async def test_search_text_fallback_uses_savepoint_before_ilike_query(
    repo: CoreEntityRepository,
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4()
    other_novel_id = uuid.uuid4()
    entity_id = uuid.uuid4()
    db_session.add_all(
        [
            Project(id=novel_id, title="target"),
            Project(id=other_novel_id, title="other"),
            CoreEntity(
                id=entity_id,
                novel_id=novel_id,
                entity_type="organization",
                name="塔罗会",
                importance=0.8,
                status="canonical",
            ),
            CoreEntity(
                novel_id=novel_id,
                entity_type="character",
                name="塔罗会成员",
                importance=1.0,
                status="canonical",
            ),
            CoreEntity(
                novel_id=other_novel_id,
                entity_type="organization",
                name="塔罗会",
                importance=1.0,
                status="canonical",
            ),
        ]
    )
    await db_session.flush()
    pending_project = Project(id=uuid.uuid4(), title="must-stay-pending")
    db_session.add(pending_project)
    db = _PostgresDialectSessionProxy(db_session)

    with db_session.no_autoflush:
        result = await repo.find_similar_by_search_text(
            db,  # type: ignore[arg-type]
            novel_id,
            "塔罗会",
            entity_type="organization",
            status_filter=["canonical"],
            top_k=1,
        )

    assert [(item.id, score) for item, score in result] == [(entity_id, 0.0)]
    assert db.nested_count == 1
    assert db.execute_count == 2
    assert db_session.in_transaction()
    assert pending_project in db_session.new
    assert (
        await db_session.scalar(select(Project.id).where(Project.id == novel_id))
    ) == novel_id


@pytest.mark.asyncio
async def test_embedding_similarity_uses_labelable_pgvector_expression(
    repo: CoreEntityRepository,
) -> None:
    class EmptyResult:
        def all(self) -> list[object]:
            return []

    class CapturingSession:
        statement = None

        async def execute(self, statement):
            self.statement = statement
            return EmptyResult()

    db = CapturingSession()
    result = await repo.find_similar_by_embedding(
        db,  # type: ignore[arg-type]
        uuid.uuid4(),
        [0.0] * 768,
    )

    assert result == []
    assert db.statement is not None
    compiled = str(db.statement.compile(dialect=postgresql.dialect()))
    assert "<=>" in compiled
    assert "similarity" in compiled


@pytest.mark.asyncio
async def test_repo_count_entities(
    db_session: AsyncSession,
    repo: CoreEntityRepository,
) -> None:
    novel_id = str(uuid.uuid4())
    db_session.add(
        Project(
            id=uuid.UUID(novel_id),
            title="t",
            genre="fantasy",
            language="zh",
            target_length="novel",
            current_stage="worldbuilding",
        )
    )

    await repo.create_raw(
        db_session,
        novel_id=uuid.UUID(novel_id),
        entity_type="character",
        name="A",
        status="canonical",
    )
    await repo.create_raw(
        db_session,
        novel_id=uuid.UUID(novel_id),
        entity_type="location",
        name="B",
        status="draft",
    )
    await repo.create_raw(
        db_session,
        novel_id=uuid.UUID(novel_id),
        entity_type="item",
        name="C",
        status="deprecated",
    )

    total = await repo.count_entities(db_session, uuid.UUID(novel_id))
    assert total == 3

    canonical_only = await repo.count_entities(
        db_session,
        uuid.UUID(novel_id),
        status_filter=["canonical"],
    )
    assert canonical_only == 1


@pytest.mark.asyncio
async def test_list_by_novel_uses_stable_pagination_for_tied_candidates(
    db_session: AsyncSession,
    repo: CoreEntityRepository,
) -> None:
    novel_id = uuid.uuid4()
    db_session.add(
        Project(
            id=novel_id,
            title="stable pagination",
            genre="fantasy",
            language="zh",
            target_length="novel",
            current_stage="worldbuilding",
        )
    )

    for _ in range(4):
        entity = await repo.create_raw(
            db_session,
            novel_id=novel_id,
            entity_type="faction",
            name="塔罗会",
            status="candidate",
        )
        entity.importance = 0.85
        db_session.add(entity)
    await db_session.flush()

    page1 = await repo.list_by_novel(
        db_session,
        novel_id,
        status="candidate",
        skip=0,
        limit=2,
    )
    page2 = await repo.list_by_novel(
        db_session,
        novel_id,
        status="candidate",
        skip=2,
        limit=2,
    )

    page1_ids = {item.id for item in page1}
    page2_ids = {item.id for item in page2}
    assert len(page1_ids) == 2
    assert len(page2_ids) == 2
    assert page1_ids.isdisjoint(page2_ids)


@pytest.mark.asyncio
async def test_find_characters_by_location_filters_in_database(
    db_session: AsyncSession,
) -> None:
    novel_id = uuid.uuid4()
    other_novel_id = uuid.uuid4()
    location_id = uuid.uuid4()
    other_location_id = uuid.uuid4()
    target_character_id = uuid.uuid4()
    other_location_character_id = uuid.uuid4()
    other_novel_character_id = uuid.uuid4()
    deprecated_character_id = uuid.uuid4()
    db_session.add_all(
        [
            Project(
                id=novel_id,
                title="location query",
                genre="fantasy",
                language="zh",
                target_length="novel",
                current_stage="worldbuilding",
            ),
            Project(
                id=other_novel_id,
                title="other novel",
                genre="fantasy",
                language="zh",
                target_length="novel",
                current_stage="worldbuilding",
            ),
            CoreEntity(
                id=target_character_id,
                novel_id=novel_id,
                entity_type="character",
                name="目标人物",
                status="canonical",
            ),
            CoreEntity(
                id=other_location_character_id,
                novel_id=novel_id,
                entity_type="character",
                name="其他地点人物",
                status="canonical",
            ),
            CoreEntity(
                id=other_novel_character_id,
                novel_id=other_novel_id,
                entity_type="character",
                name="其他小说人物",
                status="canonical",
            ),
            CoreEntity(
                id=deprecated_character_id,
                novel_id=novel_id,
                entity_type="character",
                name="废弃人物",
                status="canonical",
            ),
            Character(
                entity_id=target_character_id,
                novel_id=novel_id,
                name="目标人物",
                status="canonical",
                current_state="在目标地点",
                meta={"location_id": str(location_id)},
            ),
            Character(
                entity_id=other_location_character_id,
                novel_id=novel_id,
                name="其他地点人物",
                status="canonical",
                current_state="在其他地点",
                meta={"location_id": str(other_location_id)},
            ),
            Character(
                entity_id=other_novel_character_id,
                novel_id=other_novel_id,
                name="其他小说人物",
                status="canonical",
                current_state="跨 novel 泄漏候选",
                meta={"location_id": str(location_id)},
            ),
            Character(
                entity_id=deprecated_character_id,
                novel_id=novel_id,
                name="废弃人物",
                status="deprecated",
                current_state="不应返回",
                meta={"location_id": str(location_id)},
            ),
        ]
    )
    await db_session.flush()

    result = await CharacterRepository().find_characters_by_location(
        db_session,
        novel_id,
        location_id,
    )

    assert result == [
        {
            "id": str(target_character_id),
            "name": "目标人物",
            "current_state": "在目标地点",
        }
    ]


@pytest.mark.asyncio
async def test_has_embeddings_checks_current_novel_only(
    db_session: AsyncSession,
    repo: CoreEntityRepository,
) -> None:
    novel_id = uuid.uuid4()
    other_novel_id = uuid.uuid4()
    embedding = [0.1] * 768
    db_session.add_all(
        [
            Project(
                id=novel_id,
                title="embedding gate",
                genre="fantasy",
                language="zh",
                target_length="novel",
                current_stage="worldbuilding",
            ),
            Project(
                id=other_novel_id,
                title="other embedding gate",
                genre="fantasy",
                language="zh",
                target_length="novel",
                current_stage="worldbuilding",
            ),
            CoreEntity(
                id=uuid.uuid4(),
                novel_id=other_novel_id,
                entity_type="location",
                name="其他 novel embedding",
                status="canonical",
                embedding=embedding,
            ),
        ]
    )
    await db_session.flush()

    assert await repo.has_embeddings(db_session, novel_id) is False

    db_session.add(
        CoreEntity(
            id=uuid.uuid4(),
            novel_id=novel_id,
            entity_type="location",
            name="当前 novel embedding",
            status="canonical",
            embedding=embedding,
        )
    )
    await db_session.flush()

    assert await repo.has_embeddings(db_session, novel_id) is True


@pytest.mark.asyncio
async def test_get_recent_auto_ingested_filters_json_bool_and_keeps_order_limit(
    db_session: AsyncSession,
    repo: CoreEntityRepository,
) -> None:
    novel_id = uuid.uuid4()
    other_novel_id = uuid.uuid4()
    base_time = datetime(2026, 7, 7, tzinfo=UTC)
    db_session.add_all(
        [
            Project(
                id=novel_id,
                title="auto ingest",
                genre="fantasy",
                language="zh",
                target_length="novel",
                current_stage="worldbuilding",
            ),
            Project(
                id=other_novel_id,
                title="other auto ingest",
                genre="fantasy",
                language="zh",
                target_length="novel",
                current_stage="worldbuilding",
            ),
            CoreEntity(
                id=uuid.uuid4(),
                novel_id=novel_id,
                entity_type="location",
                name="较早真值",
                status="canonical",
                content_json={"_meta": {"auto_ingested": True}},
                created_at=base_time,
            ),
            CoreEntity(
                id=uuid.uuid4(),
                novel_id=novel_id,
                entity_type="location",
                name="较新真值",
                status="canonical",
                content_json={"_meta": {"auto_ingested": True}},
                created_at=base_time + timedelta(minutes=1),
            ),
            CoreEntity(
                id=uuid.uuid4(),
                novel_id=novel_id,
                entity_type="location",
                name="最新真值",
                status="canonical",
                content_json={"_meta": {"auto_ingested": True}},
                created_at=base_time + timedelta(minutes=2),
            ),
            CoreEntity(
                id=uuid.uuid4(),
                novel_id=novel_id,
                entity_type="location",
                name="布尔 false",
                status="canonical",
                content_json={"_meta": {"auto_ingested": False}},
                created_at=base_time + timedelta(minutes=3),
            ),
            CoreEntity(
                id=uuid.uuid4(),
                novel_id=novel_id,
                entity_type="location",
                name="字符串 true",
                status="canonical",
                content_json={"_meta": {"auto_ingested": "true"}},
                created_at=base_time + timedelta(minutes=4),
            ),
            CoreEntity(
                id=uuid.uuid4(),
                novel_id=novel_id,
                entity_type="location",
                name="非 canonical",
                status="draft",
                content_json={"_meta": {"auto_ingested": True}},
                created_at=base_time + timedelta(minutes=5),
            ),
            CoreEntity(
                id=uuid.uuid4(),
                novel_id=other_novel_id,
                entity_type="location",
                name="其他 novel",
                status="canonical",
                content_json={"_meta": {"auto_ingested": True}},
                created_at=base_time + timedelta(minutes=6),
            ),
        ]
    )
    await db_session.flush()

    result = await repo.get_recent_auto_ingested(db_session, novel_id, limit=2)

    assert [entity.name for entity in result] == ["最新真值", "较新真值"]
