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
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
        scene_data: SceneCreate,
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
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
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
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
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
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
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
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        from modules.outline.repositories import SceneRepository

        repo = SceneRepository()
        nid = uuid.UUID(hex=sample_novel_id)
        scene = await repo.create(db_session, nid, SceneCreate(scene_index=0))
        await db_session.flush()

        updated = await repo.update(
            db_session,
            scene.id,
            SceneUpdate(title="更新标题", narrative_tag="climax"),
        )
        assert updated is not None
        assert updated.title == "更新标题"
        assert updated.narrative_tag == "climax"
        await db_session.rollback()

    @pytest.mark.asyncio
    async def test_soft_delete_scene(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        from modules.outline.repositories import SceneRepository

        repo = SceneRepository()
        nid = uuid.UUID(hex=sample_novel_id)
        scene = await repo.create(db_session, nid, SceneCreate(scene_index=0))
        await db_session.flush()

        updated = await repo.update(
            db_session,
            scene.id,
            SceneUpdate(status="deprecated"),
        )
        assert updated is not None
        assert updated.status == "deprecated"

        ordered = await repo.get_by_novel_ordered(db_session, nid)
        assert len(ordered) == 0
        await db_session.rollback()

    @pytest.mark.asyncio
    async def test_novel_id_isolation(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
        other_novel_id: str,
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
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
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
    async def test_get_next_scene_index_advances_from_zero(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        from modules.outline.services import SceneService

        svc = SceneService()
        await svc.create(
            db_session,
            sample_novel_id,
            SceneCreate(scene_index=0, title="First"),
        )
        await db_session.flush()

        assert await svc.get_next_scene_index(db_session, sample_novel_id) == 1
        await db_session.rollback()

    @pytest.mark.asyncio
    async def test_get_ordered(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        from modules.outline.services import SceneService

        svc = SceneService()
        await svc.create(
            db_session,
            sample_novel_id,
            SceneCreate(
                scene_index=2,
                title="C",
                status="canonical",
            ),
        )
        await svc.create(
            db_session,
            sample_novel_id,
            SceneCreate(
                scene_index=0,
                title="A",
                status="canonical",
            ),
        )
        await svc.create(
            db_session,
            sample_novel_id,
            SceneCreate(
                scene_index=1,
                title="B",
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
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        from modules.outline.services import SceneService

        svc = SceneService()
        created = await svc.create(
            db_session,
            sample_novel_id,
            SceneCreate(scene_index=0),
        )
        updated = await svc.update(
            db_session,
            created.id,
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
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        from modules.outline.services import SceneService

        svc = SceneService()
        created = await svc.create(
            db_session,
            sample_novel_id,
            SceneCreate(scene_index=0),
        )
        await svc.delete(db_session, created.id, novel_id=sample_novel_id)

        from modules.outline.repositories import SceneRepository

        repo = SceneRepository()
        nid = uuid.UUID(hex=sample_novel_id)
        scenes = await repo.get_by_novel_ordered(db_session, nid)
        assert len(scenes) == 0
        await db_session.rollback()

    @pytest.mark.asyncio
    async def test_reorder_scenes(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        from modules.outline.services import SceneService

        svc = SceneService()
        scene1 = await svc.create(
            db_session,
            sample_novel_id,
            SceneCreate(scene_index=0, title="A", status="canonical"),
        )
        scene2 = await svc.create(
            db_session,
            sample_novel_id,
            SceneCreate(scene_index=1, title="B", status="canonical"),
        )
        scene3 = await svc.create(
            db_session,
            sample_novel_id,
            SceneCreate(scene_index=2, title="C", status="canonical"),
        )

        result = await svc.reorder(
            db_session,
            sample_novel_id,
            [scene3.id, scene1.id, scene2.id],
        )
        assert result["updated"] == 3
        assert result["total"] == 3

        contracts = await svc.get_ordered(db_session, sample_novel_id)
        assert len(contracts) == 3
        assert contracts[0].title == "C"
        assert contracts[1].title == "A"
        assert contracts[2].title == "B"
        assert contracts[0].scene_index == 0
        assert contracts[1].scene_index == 1
        assert contracts[2].scene_index == 2
        await db_session.rollback()

    @pytest.mark.asyncio
    async def test_split_chapters(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        from modules.outline.repositories import SceneRepository
        from modules.outline.services import SceneService

        svc = SceneService()
        repo = SceneRepository()

        source = await svc.create(
            db_session,
            sample_novel_id,
            SceneCreate(
                scene_index=0,
                title="Source",
                chapter_ids=["1", "2", "3"],
                status="canonical",
            ),
        )
        target = await svc.create(
            db_session,
            sample_novel_id,
            SceneCreate(
                scene_index=1,
                title="Target",
                chapter_ids=[],
                status="canonical",
            ),
        )

        await svc.split_chapters(
            db_session,
            sample_novel_id,
            chapter_index=2,
            target_scene_id=target.id,
        )

        updated_source = await repo.get(
            db_session,
            uuid.UUID(source.id),
        )
        assert updated_source is not None
        assert "2" not in (updated_source.chapter_ids or [])

        updated_target = await repo.get(
            db_session,
            uuid.UUID(target.id),
        )
        assert updated_target is not None
        assert "2" in (updated_target.chapter_ids or [])

        await db_session.rollback()


class TestSceneSplitChunk:
    """SceneService.split_scene_chunk_to_new_chapter 及 facade 测试"""

    @pytest.mark.asyncio
    async def test_split_scene_chunk_happy_path(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        from modules.outline.repositories import SceneRepository
        from modules.outline.services import SceneService

        nid = uuid.UUID(hex=sample_novel_id)
        repo = SceneRepository()
        source = await repo.create(
            db_session,
            nid,
            SceneCreate(
                scene_index=1,
                title="Source",
                chapter_ids=["5"],
                scene_chunks=[
                    {
                        "chapter_id": "5",
                        "chapter_index": 5,
                        "start_pos": 0,
                        "end_pos": 100,
                    }
                ],
                status="draft",
            ),
        )
        later = await repo.create(
            db_session,
            nid,
            SceneCreate(
                scene_index=2,
                title="Later",
                chapter_ids=["6"],
                status="draft",
            ),
        )
        await db_session.flush()

        svc = SceneService()
        result = await svc.split_scene_chunk_to_new_chapter(
            db_session,
            sample_novel_id,
            source_scene_id=str(source.id),
            source_chapter_id="5",
            source_chapter_index=5,
            new_chapter_id="6",
            new_chapter_index=6,
            split_pos=40,
            new_chapter_length=60,
        )

        assert len(result) == 3
        source_orm = next(s for s in result if s.id == source.id)
        later_orm = next(s for s in result if s.id == later.id)
        new_orm = next(s for s in result if s.id not in (source.id, later.id))

        assert source_orm.scene_chunks[0]["end_pos"] == 40
        assert new_orm.scene_index == 2
        assert new_orm.chapter_ids == ["6"]
        assert new_orm.scene_chunks[0]["chapter_id"] == "6"
        assert new_orm.scene_chunks[0]["chapter_index"] == 6
        assert new_orm.scene_chunks[0]["end_pos"] == 60
        assert later_orm.scene_index == 3

    @pytest.mark.parametrize(
        "source_chapter_id,source_chapter_index,split_pos,match",
        [
            ("999", 999, 40, "Chapter 999 not found"),
            ("5", 5, 0, "split_pos 0 must be inside chunk range"),
        ],
        ids=["not_found", "pos_out_of_range"],
    )
    @pytest.mark.asyncio
    async def test_split_scene_chunk_boundary_errors(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
        source_chapter_id: str,
        source_chapter_index: int,
        split_pos: int,
        match: str,
    ) -> None:
        from modules.outline.repositories import SceneRepository
        from modules.outline.services import SceneService

        nid = uuid.UUID(hex=sample_novel_id)
        repo = SceneRepository()
        source = await repo.create(
            db_session,
            nid,
            SceneCreate(
                scene_index=1,
                title="Source",
                chapter_ids=["5"],
                scene_chunks=[
                    {
                        "chapter_id": "5",
                        "chapter_index": 5,
                        "start_pos": 0,
                        "end_pos": 100,
                    }
                ],
                status="draft",
            ),
        )
        await db_session.flush()

        svc = SceneService()
        with pytest.raises(ValueError, match=match):
            await svc.split_scene_chunk_to_new_chapter(
                db_session,
                sample_novel_id,
                source_scene_id=str(source.id),
                source_chapter_id=source_chapter_id,
                source_chapter_index=source_chapter_index,
                new_chapter_id="6",
                new_chapter_index=6,
                split_pos=split_pos,
                new_chapter_length=60,
            )

    @pytest.mark.asyncio
    async def test_facade_split_scene_chunk_to_new_chapter(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        from modules.outline.facade import split_scene_chunk_to_new_chapter
        from modules.outline.repositories import SceneRepository

        nid = uuid.UUID(hex=sample_novel_id)
        repo = SceneRepository()
        source = await repo.create(
            db_session,
            nid,
            SceneCreate(
                scene_index=1,
                title="Source",
                chapter_ids=["5"],
                scene_chunks=[
                    {
                        "chapter_id": "5",
                        "chapter_index": 5,
                        "start_pos": 0,
                        "end_pos": 100,
                    }
                ],
                status="draft",
            ),
        )
        await db_session.flush()

        result = await split_scene_chunk_to_new_chapter(
            db_session,
            sample_novel_id,
            source_scene_id=str(source.id),
            source_chapter_id="5",
            source_chapter_index=5,
            new_chapter_id="6",
            new_chapter_index=6,
            split_pos=40,
            new_chapter_length=60,
        )

        assert isinstance(result, list)
        source_dict = next(item for item in result if item["id"] == str(source.id))
        assert source_dict["scene_chunks"][0]["end_pos"] == 40
        new_dict = next(item for item in result if item["id"] != str(source.id))
        assert new_dict["chapter_ids"] == ["6"]
        assert new_dict["scene_chunks"][0]["chapter_id"] == "6"
