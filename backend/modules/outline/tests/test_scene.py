"""Scene 模型 CRUD 单元测试"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.schemas import SceneCreate, SceneUpdate


@pytest.fixture
def sample_novel_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def other_novel_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def scene_data() -> SceneCreate:
    return SceneCreate(
        scene_index=0,
        title="初入江湖",
        goal="主角踏入江湖",
        core_conflict="新旧势力冲突",
        emotional_beat="紧张→释然",
        must_happen="主角获得入门功法",
        must_not_happen="主角死",
        narrative_tag="inciting_incident",
        source="manual",
        scene_chunks=[{"chapter_id": "ch-1", "start_pos": 0, "end_pos": 3000}],
        chapter_ids=["ch-1"],
        pov_character_id=None,
        status="draft",
    )


@pytest.fixture
def scene_data_2() -> SceneCreate:
    return SceneCreate(
        scene_index=1,
        title="师门冲突",
        goal="主角面对同门挑战",
        narrative_tag="rising_action",
        status="canonical",
    )


@pytest_asyncio.fixture
async def sample_scene(
    db_session: AsyncSession,
    sample_novel_id: str,
    scene_data: SceneCreate,
) -> tuple[str, SceneCreate]:
    from modules.outline.repositories import SceneRepository

    nid = uuid.UUID(hex=sample_novel_id)
    repo = SceneRepository()
    scene = await repo.create(db_session, nid, scene_data)
    await db_session.flush()
    return str(scene.id), scene_data


class TestSceneRepository:
    """SceneRepository CRUD 测试"""

    @pytest.mark.asyncio
    async def test_create_scene(
        self, db_session: AsyncSession, sample_novel_id: str, scene_data: SceneCreate,
    ) -> None:
        from modules.outline.repositories import SceneRepository

        repo = SceneRepository()
        nid = uuid.UUID(hex=sample_novel_id)
        scene = await repo.create(db_session, nid, scene_data)

        assert scene.id is not None
        assert str(scene.novel_id) == sample_novel_id
        assert scene.scene_index == 0
        assert scene.title == "初入江湖"
        assert scene.narrative_tag == "inciting_incident"
        assert scene.source == "manual"
        assert scene.status == "draft"
        assert len(scene.scene_chunks) == 1
        assert len(scene.chapter_ids) == 1
        await db_session.rollback()

    @pytest.mark.asyncio
    async def test_get_scene(
        self, db_session: AsyncSession, sample_novel_id: str,
    ) -> None:
        from modules.outline.repositories import SceneRepository

        repo = SceneRepository()
        nid = uuid.UUID(hex=sample_novel_id)
        data = SceneCreate(scene_index=0, title="测试Scene")
        scene = await repo.create(db_session, nid, data)
        await db_session.flush()

        found = await repo.get(db_session, scene.id)
        assert found is not None
        assert found.title == "测试Scene"
        assert found.scene_index == 0
        await db_session.rollback()

    @pytest.mark.asyncio
    async def test_get_by_novel_ordered(
        self, db_session: AsyncSession, sample_novel_id: str,
    ) -> None:
        from modules.outline.repositories import SceneRepository

        repo = SceneRepository()
        nid = uuid.UUID(hex=sample_novel_id)
        await repo.create(db_session, nid, SceneCreate(scene_index=2, title="Scene C"))
        await repo.create(db_session, nid, SceneCreate(scene_index=0, title="Scene A"))
        await repo.create(db_session, nid, SceneCreate(scene_index=1, title="Scene B"))
        await db_session.flush()

        scenes = await repo.get_by_novel_ordered(db_session, nid)
        assert len(scenes) == 3
        assert scenes[0].title == "Scene A"
        assert scenes[1].title == "Scene B"
        assert scenes[2].title == "Scene C"
        await db_session.rollback()

    @pytest.mark.asyncio
    async def test_get_by_novel_with_pagination(
        self, db_session: AsyncSession, sample_novel_id: str,
    ) -> None:
        from modules.outline.repositories import SceneRepository

        repo = SceneRepository()
        nid = uuid.UUID(hex=sample_novel_id)
        for i in range(5):
            await repo.create(db_session, nid, SceneCreate(scene_index=i))
        await db_session.flush()

        items, total = await repo.get_by_novel(db_session, nid, skip=0, limit=2)
        assert total == 5
        assert len(items) == 2
        await db_session.rollback()

    @pytest.mark.asyncio
    async def test_update_scene(
        self, db_session: AsyncSession, sample_novel_id: str,
    ) -> None:
        from modules.outline.repositories import SceneRepository

        repo = SceneRepository()
        nid = uuid.UUID(hex=sample_novel_id)
        scene = await repo.create(db_session, nid, SceneCreate(scene_index=0))
        await db_session.flush()

        updated = await repo.update(
            db_session, scene.id,
            SceneUpdate(title="更新标题", narrative_tag="climax"),
        )
        assert updated is not None
        assert updated.title == "更新标题"
        assert updated.narrative_tag == "climax"
        await db_session.rollback()

    @pytest.mark.asyncio
    async def test_soft_delete_scene(
        self, db_session: AsyncSession, sample_novel_id: str,
    ) -> None:
        from modules.outline.repositories import SceneRepository

        repo = SceneRepository()
        nid = uuid.UUID(hex=sample_novel_id)
        scene = await repo.create(db_session, nid, SceneCreate(scene_index=0))
        await db_session.flush()

        updated = await repo.update(
            db_session, scene.id, SceneUpdate(status="deprecated"),
        )
        assert updated is not None
        assert updated.status == "deprecated"

        ordered = await repo.get_by_novel_ordered(db_session, nid)
        assert len(ordered) == 0
        await db_session.rollback()

    @pytest.mark.asyncio
    async def test_novel_id_isolation(
        self, db_session: AsyncSession, sample_novel_id: str, other_novel_id: str,
    ) -> None:
        from modules.outline.repositories import SceneRepository

        repo = SceneRepository()
        nid1 = uuid.UUID(hex=sample_novel_id)
        nid2 = uuid.UUID(hex=other_novel_id)
        await repo.create(db_session, nid1, SceneCreate(scene_index=0, title="Novel 1"))
        await repo.create(db_session, nid2, SceneCreate(scene_index=0, title="Novel 2"))
        await db_session.flush()

        items1, total1 = await repo.get_by_novel(db_session, nid1)
        items2, total2 = await repo.get_by_novel(db_session, nid2)
        assert total1 == 1
        assert total2 == 1
        assert items1[0].title == "Novel 1"
        assert items2[0].title == "Novel 2"
        await db_session.rollback()


class TestSceneService:
    """SceneService 业务逻辑测试"""

    @pytest.mark.asyncio
    async def test_create_and_get(
        self, db_session: AsyncSession, sample_novel_id: str,
    ) -> None:
        from modules.outline.services import SceneService

        svc = SceneService()
        data = SceneCreate(scene_index=0, title="Service Scene")
        resp = await svc.create(db_session, sample_novel_id, data)
        assert resp.title == "Service Scene"
        assert resp.scene_index == 0

        got = await svc.get(db_session, resp.id, novel_id=sample_novel_id)
        assert got.id == resp.id
        await db_session.rollback()

    @pytest.mark.asyncio
    async def test_get_ordered(
        self, db_session: AsyncSession, sample_novel_id: str,
    ) -> None:
        from modules.outline.services import SceneService

        svc = SceneService()
        await svc.create(
            db_session, sample_novel_id,
            SceneCreate(
                scene_index=2, title="C",
                status="canonical",
            ),
        )
        await svc.create(
            db_session, sample_novel_id,
            SceneCreate(
                scene_index=0, title="A",
                status="canonical",
            ),
        )
        await svc.create(
            db_session, sample_novel_id,
            SceneCreate(
                scene_index=1, title="B",
                status="canonical",
            ),
        )

        contracts = await svc.get_ordered(db_session, sample_novel_id)
        assert len(contracts) == 3
        assert contracts[0].title == "A"
        assert contracts[1].title == "B"
        assert contracts[2].title == "C"
        await db_session.rollback()

    @pytest.mark.asyncio
    async def test_update_scene_fields(
        self, db_session: AsyncSession, sample_novel_id: str,
    ) -> None:
        from modules.outline.services import SceneService

        svc = SceneService()
        created = await svc.create(
            db_session, sample_novel_id,
            SceneCreate(scene_index=0),
        )
        updated = await svc.update(
            db_session, created.id,
            SceneUpdate(
                title="新标题",
                goal="新目标",
                narrative_tag="climax",
                must_not_happen="禁止事件",
            ),
            novel_id=sample_novel_id,
        )
        assert updated.title == "新标题"
        assert updated.goal == "新目标"
        assert updated.narrative_tag == "climax"
        assert updated.must_not_happen == "禁止事件"
        await db_session.rollback()

    @pytest.mark.asyncio
    async def test_delete_scene(
        self, db_session: AsyncSession, sample_novel_id: str,
    ) -> None:
        from modules.outline.services import SceneService

        svc = SceneService()
        created = await svc.create(
            db_session, sample_novel_id,
            SceneCreate(scene_index=0),
        )
        await svc.delete(db_session, created.id, novel_id=sample_novel_id)

        from modules.outline.repositories import SceneRepository
        repo = SceneRepository()
        nid = uuid.UUID(hex=sample_novel_id)
        scenes = await repo.get_by_novel_ordered(db_session, nid)
        assert len(scenes) == 0
        await db_session.rollback()
