"""Scene 模型 CRUD 单元测试"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError as DomainNotFoundError
from core.errors import ValidationError as DomainValidationError
from modules.story.outline_state.models import Scene, SceneChapterLink, SceneSpan
from modules.story.outline_state.schemas import SceneCreate, SceneUpdate


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
    from modules.story.outline_state.repositories import SceneRepository

    nid = uuid.UUID(hex=sample_novel_id)
    repo = SceneRepository()
    scene = await repo.create(db_session, nid, scene_data)
    await db_session.flush()
    return str(scene.id), scene_data


class TestSceneRepository:
    def test_scene_create_rejects_legacy_candidate_status_for_new_writes(self) -> None:
        with pytest.raises(PydanticValidationError):
            SceneCreate(scene_index=0, status="candidate")  # type: ignore[arg-type]

    """SceneRepository CRUD 测试"""

    @pytest.mark.asyncio
    async def test_create_scene(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
        scene_data: SceneCreate,
    ) -> None:
        from modules.story.outline_state.repositories import SceneRepository

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
        from modules.story.outline_state.repositories import SceneRepository

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
        from modules.story.outline_state.repositories import SceneRepository

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
    async def test_scene_chapter_links_drive_chapter_lookup(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        from modules.story.outline_state.repositories import SceneRepository

        repo = SceneRepository()
        nid = uuid.UUID(hex=sample_novel_id)
        scene = await repo.create(
            db_session,
            nid,
            SceneCreate(
                scene_index=0,
                title="跨章 Scene",
                chapter_ids=["1"],
                scene_chunks=[{"chapter_index": 2, "start_pos": 0, "end_pos": 100}],
            ),
        )

        rows = (
            (
                await db_session.execute(
                    select(SceneChapterLink).where(SceneChapterLink.scene_id == scene.id)
                )
            )
            .scalars()
            .all()
        )
        assert {row.chapter_index for row in rows} == {1, 2}

        by_chapter = await repo.get_by_chapter(db_session, nid, 2)
        assert [item.id for item in by_chapter] == [scene.id]
        assert (await repo.get_by_chapter_index(db_session, nid, 1)).id == scene.id

        updated = await repo.update(
            db_session,
            scene.id,
            SceneUpdate(chapter_ids=["3"], scene_chunks=[]),
        )
        assert updated is not None
        rows_after = (
            (
                await db_session.execute(
                    select(SceneChapterLink).where(SceneChapterLink.scene_id == scene.id)
                )
            )
            .scalars()
            .all()
        )
        assert {row.chapter_index for row in rows_after} == {3}
        assert await repo.get_by_chapter_index(db_session, nid, 1) is None
        assert (await repo.get_by_chapter_index(db_session, nid, 3)).id == scene.id

    @pytest.mark.asyncio
    async def test_scene_spans_sync_from_scene_chunks(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        from modules.story.outline_state.repositories import SceneRepository

        repo = SceneRepository()
        nid = uuid.UUID(hex=sample_novel_id)
        scene = await repo.create(
            db_session,
            nid,
            SceneCreate(
                scene_index=0,
                title="同章多段 Scene",
                source="deep_import",
                chapter_ids=["2"],
                scene_chunks=[
                    {"chapter_index": 2, "start_pos": 80, "end_pos": 120},
                    {
                        "chapter_index": 2,
                        "start_paragraph": 1,
                        "end_paragraph": 3,
                    },
                    {"chapter_index": 2, "start_offset": 10, "end_offset": 20},
                ],
                status="draft",
            ),
        )

        spans = await repo.get_scene_spans_by_chapter(db_session, nid, 2)

        assert [span.scene_id for span in spans] == [scene.id, scene.id, scene.id]
        assert [span.part_no for span in spans] == [0, 1, 2]
        assert [span.start_offset for span in spans] == [10, 80, None]
        assert [span.start_paragraph for span in spans] == [None, None, 1]
        assert {span.source for span in spans} == {"deep_import"}
        assert {span.status for span in spans} == {"draft"}

    @pytest.mark.asyncio
    async def test_scene_span_rebuilds_only_when_scene_chunks_change(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        from modules.story.outline_state.repositories import SceneRepository

        repo = SceneRepository()
        nid = uuid.UUID(hex=sample_novel_id)
        scene = await repo.create(
            db_session,
            nid,
            SceneCreate(
                scene_index=0,
                source="deep_import",
                chapter_ids=["1"],
                scene_chunks=[{"chapter_index": 1, "start_offset": 0, "end_offset": 10}],
            ),
        )
        span = (
            await db_session.execute(
                select(SceneSpan).where(SceneSpan.scene_id == scene.id)
            )
        ).scalar_one()
        original_span_id = span.id
        span.mapping_status = "exact"
        span.source_content_hash = "a" * 64
        span.anchor_hash = "b" * 64
        await db_session.flush()

        await repo.update(
            db_session,
            scene.id,
            SceneUpdate(
                chapter_ids=["1", "2"],
                source="manual",
                status="canonical",
            ),
        )
        preserved = (
            await db_session.execute(
                select(SceneSpan).where(SceneSpan.scene_id == scene.id)
            )
        ).scalar_one()
        assert preserved.id == original_span_id
        assert preserved.mapping_status == "exact"
        assert preserved.source_content_hash == "a" * 64
        assert preserved.anchor_hash == "b" * 64
        assert preserved.source == "manual"
        assert preserved.status == "canonical"

        await repo.update(
            db_session,
            scene.id,
            SceneUpdate(
                scene_chunks=[{"chapter_index": 1, "start_offset": 5, "end_offset": 15}]
            ),
        )
        rebuilt = (
            await db_session.execute(
                select(SceneSpan).where(SceneSpan.scene_id == scene.id)
            )
        ).scalar_one()
        assert rebuilt.id != original_span_id
        assert rebuilt.start_offset == 5
        assert rebuilt.end_offset == 15
        assert rebuilt.source_content_hash is None
        assert rebuilt.anchor_hash is None

    @pytest.mark.asyncio
    async def test_scene_spans_follow_status_and_clear_mapping(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        from modules.story.outline_state.repositories import SceneRepository

        repo = SceneRepository()
        nid = uuid.UUID(hex=sample_novel_id)
        keep = await repo.create(
            db_session,
            nid,
            SceneCreate(
                scene_index=0,
                chapter_ids=["1"],
                scene_chunks=[{"chapter_index": 1, "start_pos": 0, "end_pos": 10}],
                status="draft",
            ),
        )
        clear = await repo.create(
            db_session,
            nid,
            SceneCreate(
                scene_index=1,
                chapter_ids=["1"],
                scene_chunks=[{"chapter_index": 1, "start_pos": 10, "end_pos": 20}],
                status="draft",
            ),
        )

        await repo.update(db_session, keep.id, SceneUpdate(status="deprecated"))
        active_spans = await repo.get_scene_spans_by_chapter(db_session, nid, 1)
        assert [span.scene_id for span in active_spans] == [clear.id]
        deprecated_spans = await repo.get_scene_spans_for_scene(
            db_session,
            nid,
            keep.id,
            statuses=("deprecated",),
        )
        assert [span.status for span in deprecated_spans] == ["deprecated"]

        await repo.deprecate_with_reference(
            db_session,
            [clear],
            reference_field="merged_into_scene_id",
            reference_scene_id=keep.id,
            clear_mapping=True,
        )
        remaining = (
            (
                await db_session.execute(
                    select(SceneSpan).where(SceneSpan.scene_id == clear.id)
                )
            )
            .scalars()
            .all()
        )
        assert remaining == []

    @pytest.mark.asyncio
    async def test_chapter_lookup_with_multiple_scenes_has_stable_order(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        from modules.story.outline_state.repositories import SceneRepository

        repo = SceneRepository()
        nid = uuid.UUID(hex=sample_novel_id)
        later = await repo.create(
            db_session,
            nid,
            SceneCreate(scene_index=2, title="后置 Scene", chapter_ids=["8"]),
        )
        earlier = await repo.create(
            db_session,
            nid,
            SceneCreate(scene_index=1, title="前置 Scene", chapter_ids=["8"]),
        )

        first = await repo.get_by_chapter(db_session, nid, 8)
        second = await repo.get_by_chapter(db_session, nid, 8)
        selected = await repo.get_by_chapter_index(db_session, nid, 8)

        assert [scene.id for scene in first] == [earlier.id, later.id]
        assert [scene.id for scene in second] == [earlier.id, later.id]
        assert selected is not None
        assert selected.id == earlier.id

    @pytest.mark.asyncio
    async def test_scene_chapter_links_drive_chapter_range_lookup(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
        other_novel_id: str,
    ) -> None:
        from modules.story.outline_state.repositories import SceneRepository

        repo = SceneRepository()
        nid = uuid.UUID(hex=sample_novel_id)
        other_nid = uuid.UUID(hex=other_novel_id)
        outside = await repo.create(
            db_session,
            nid,
            SceneCreate(scene_index=0, title="范围外", chapter_ids=["1"]),
        )
        first = await repo.create(
            db_session,
            nid,
            SceneCreate(scene_index=2, title="范围内 B", chapter_ids=["2", "3"]),
        )
        second = await repo.create(
            db_session,
            nid,
            SceneCreate(scene_index=1, title="范围内 A", chapter_ids=["2"]),
        )
        deprecated = await repo.create(
            db_session,
            nid,
            SceneCreate(scene_index=3, title="已废弃", chapter_ids=["3"]),
        )
        await repo.update(
            db_session,
            deprecated.id,
            SceneUpdate(status="deprecated"),
        )
        await repo.create(
            db_session,
            other_nid,
            SceneCreate(scene_index=0, title="其他项目", chapter_ids=["3"]),
        )

        scenes = await repo.get_by_chapter_range(db_session, nid, 2, 3)

        assert [scene.id for scene in scenes] == [second.id, first.id]
        assert len({scene.id for scene in scenes}) == len(scenes)
        assert outside.id not in {scene.id for scene in scenes}
        assert deprecated.id not in {scene.id for scene in scenes}

    @pytest.mark.asyncio
    async def test_create_many_populates_chapter_links(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        from modules.story.outline_state.repositories import SceneRepository

        repo = SceneRepository()
        nid = uuid.UUID(hex=sample_novel_id)

        scenes = await repo.create_many(
            db_session,
            nid,
            [
                SceneCreate(scene_index=0, title="A", chapter_ids=["1"]),
                SceneCreate(
                    scene_index=1,
                    title="B",
                    scene_chunks=[{"chapter_index": 2}],
                ),
            ],
        )

        assert [scene.title for scene in scenes] == ["A", "B"]
        rows = (
            (
                await db_session.execute(
                    select(SceneChapterLink).where(
                        SceneChapterLink.scene_id.in_([scene.id for scene in scenes])
                    )
                )
            )
            .scalars()
            .all()
        )
        assert {(row.scene_id, row.chapter_index) for row in rows} == {
            (scenes[0].id, 1),
            (scenes[1].id, 2),
        }
        assert [scene.id for scene in await repo.get_by_chapter(db_session, nid, 2)] == [
            scenes[1].id
        ]
        await db_session.rollback()

    @pytest.mark.asyncio
    async def test_backfill_chapter_links_for_existing_scenes(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from modules.story.outline_state.repositories import SceneRepository

        repo = SceneRepository()
        nid = uuid.UUID(hex=sample_novel_id)
        scene = Scene(
            novel_id=nid,
            scene_index=0,
            title="旧数据 Scene",
            chapter_ids=["4"],
            scene_chunks=[{"chapter_index": 5}],
            status="draft",
        )
        db_session.add(scene)
        await db_session.flush()
        db_session.add(
            SceneChapterLink(
                novel_id=nid,
                scene_id=scene.id,
                chapter_index=99,
            )
        )
        await db_session.flush()

        existing_links = (
            (
                await db_session.execute(
                    select(SceneChapterLink).where(SceneChapterLink.scene_id == scene.id)
                )
            )
            .scalars()
            .all()
        )
        assert {row.chapter_index for row in existing_links} == {99}

        async def fail_sync(*_args, **_kwargs):
            raise AssertionError("backfill must rebuild links in bulk")

        monkeypatch.setattr(repo, "sync_chapter_links", fail_sync)

        assert await repo.backfill_chapter_links(db_session, nid) == 2
        rows = (
            (
                await db_session.execute(
                    select(SceneChapterLink).where(SceneChapterLink.scene_id == scene.id)
                )
            )
            .scalars()
            .all()
        )
        assert {row.chapter_index for row in rows} == {4, 5}

    @pytest.mark.asyncio
    async def test_sync_chapter_links_bulk_adds_link_rows(self) -> None:
        from modules.story.outline_state.repositories import SceneRepository

        class FakeSession:
            def __init__(self) -> None:
                self.add_calls = 0
                self.added_batches: list[list[SceneChapterLink]] = []
                self.flush_calls = 0

            async def execute(self, *_args, **_kwargs) -> None:
                return None

            def add(self, _item: object) -> None:
                self.add_calls += 1

            def add_all(self, items: list[SceneChapterLink]) -> None:
                self.added_batches.append(items)

            async def flush(self) -> None:
                self.flush_calls += 1

        repo = SceneRepository()
        scene = Scene(
            id=uuid.uuid4(),
            novel_id=uuid.uuid4(),
            scene_index=0,
            chapter_ids=["2"],
            scene_chunks=[{"chapter_index": 3}],
        )
        db = FakeSession()

        await repo.sync_chapter_links(db, scene)  # type: ignore[arg-type]

        assert db.add_calls == 0
        assert db.flush_calls == 1
        assert len(db.added_batches) == 1
        assert {link.chapter_index for link in db.added_batches[0]} == {2, 3}

    @pytest.mark.asyncio
    async def test_update_scene_reuses_loaded_scene(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from modules.story.outline_state.repositories import SceneRepository

        class FakeSession:
            def __init__(self) -> None:
                self.added: list[Scene] = []
                self.flush_calls = 0

            def add(self, item: Scene) -> None:
                self.added.append(item)

            async def flush(self) -> None:
                self.flush_calls += 1

        repo = SceneRepository()
        scene = Scene(
            id=uuid.uuid4(),
            novel_id=uuid.uuid4(),
            scene_index=0,
            title="旧标题",
        )
        get_calls = 0
        stale_calls = 0

        async def fake_get(_db: object, scene_id: uuid.UUID) -> Scene | None:
            nonlocal get_calls
            get_calls += 1
            assert scene_id == scene.id
            return scene

        async def fake_stale(_db: object, updated_scene: Scene) -> int:
            nonlocal stale_calls
            stale_calls += 1
            assert updated_scene is scene
            return 0

        monkeypatch.setattr(repo, "get", fake_get)
        monkeypatch.setattr(
            repo,
            "stale_fusion_suggestions_for_scene",
            fake_stale,
        )
        db = FakeSession()

        updated = await repo.update(
            db,  # type: ignore[arg-type]
            scene.id,
            SceneUpdate(title="更新标题", narrative_tag="climax"),
        )

        assert updated is scene
        assert get_calls == 1
        assert stale_calls == 1
        assert db.added == [scene]
        assert db.flush_calls == 1
        assert scene.title == "更新标题"
        assert scene.narrative_tag == "climax"

    @pytest.mark.asyncio
    async def test_deprecate_with_reference_clears_scene_mappings(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        from modules.story.outline_state.repositories import SceneRepository

        repo = SceneRepository()
        nid = uuid.UUID(hex=sample_novel_id)
        target = await repo.create(
            db_session,
            nid,
            SceneCreate(scene_index=0, title="目标 Scene", chapter_ids=["1"]),
        )
        first = await repo.create(
            db_session,
            nid,
            SceneCreate(
                scene_index=1,
                title="来源 A",
                chapter_ids=["2"],
                scene_chunks=[{"chapter_index": 3}],
                structure_meta={"existing": True},
            ),
        )
        second = await repo.create(
            db_session,
            nid,
            SceneCreate(
                scene_index=2,
                title="来源 B",
                chapter_ids=["4"],
            ),
        )

        assert (
            (
                await db_session.execute(
                    select(SceneChapterLink).where(
                        SceneChapterLink.scene_id.in_([first.id, second.id])
                    )
                )
            )
            .scalars()
            .all()
        )

        count = await repo.deprecate_with_reference(
            db_session,
            [first, second],
            reference_field="merged_into_scene_id",
            reference_scene_id=target.id,
            clear_mapping=True,
        )

        assert count == 2
        assert first.status == "deprecated"
        assert first.chapter_ids == []
        assert first.scene_chunks == []
        assert first.structure_meta == {
            "existing": True,
            "merged_into_scene_id": str(target.id),
        }
        assert second.status == "deprecated"
        assert second.chapter_ids == []
        assert second.scene_chunks == []
        assert second.structure_meta["merged_into_scene_id"] == str(target.id)
        rows = (
            (
                await db_session.execute(
                    select(SceneChapterLink).where(
                        SceneChapterLink.scene_id.in_([first.id, second.id])
                    )
                )
            )
            .scalars()
            .all()
        )
        assert rows == []

    @pytest.mark.asyncio
    async def test_reorder_updates_scene_indices_in_one_novel(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
        other_novel_id: str,
    ) -> None:
        from modules.story.outline_state.repositories import SceneRepository

        repo = SceneRepository()
        nid = uuid.UUID(hex=sample_novel_id)
        other_nid = uuid.UUID(hex=other_novel_id)
        first = await repo.create(
            db_session,
            nid,
            SceneCreate(scene_index=0, title="A"),
        )
        second = await repo.create(
            db_session,
            nid,
            SceneCreate(scene_index=1, title="B"),
        )
        third = await repo.create(
            db_session,
            nid,
            SceneCreate(scene_index=2, title="C"),
        )
        other = await repo.create(
            db_session,
            other_nid,
            SceneCreate(scene_index=9, title="Other"),
        )

        assert await repo.reorder(db_session, nid, []) == 0
        assert await repo.reorder(db_session, nid, [third.id, first.id, second.id]) == 3

        scenes = await repo.get_by_novel_ordered(db_session, nid)
        assert [(scene.title, scene.scene_index) for scene in scenes] == [
            ("C", 0),
            ("A", 1),
            ("B", 2),
        ]
        refreshed_other = await repo.get(db_session, other.id)
        assert refreshed_other is not None
        assert refreshed_other.scene_index == 9

    @pytest.mark.asyncio
    async def test_shift_scene_indices_after_updates_later_scenes_in_one_statement(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
        other_novel_id: str,
    ) -> None:
        from modules.story.outline_state.repositories import SceneRepository

        repo = SceneRepository()
        nid = uuid.UUID(hex=sample_novel_id)
        other_nid = uuid.UUID(hex=other_novel_id)
        source = await repo.create(
            db_session,
            nid,
            SceneCreate(scene_index=1, title="Source"),
        )
        inserted = await repo.create(
            db_session,
            nid,
            SceneCreate(scene_index=2, title="Inserted"),
        )
        later = await repo.create(
            db_session,
            nid,
            SceneCreate(scene_index=2, title="Later"),
        )
        earlier = await repo.create(
            db_session,
            nid,
            SceneCreate(scene_index=0, title="Earlier"),
        )
        other = await repo.create(
            db_session,
            other_nid,
            SceneCreate(scene_index=2, title="Other novel"),
        )

        updated = await repo.shift_scene_indices_after(
            db_session,
            nid,
            source.scene_index,
            exclude_ids={source.id, inserted.id},
        )

        assert updated == 1
        assert (await repo.get(db_session, inserted.id)).scene_index == 2
        assert (await repo.get(db_session, later.id)).scene_index == 3
        assert (await repo.get(db_session, earlier.id)).scene_index == 0
        assert (await repo.get(db_session, other.id)).scene_index == 2

    @pytest.mark.asyncio
    async def test_get_by_novel_with_pagination(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        from modules.story.outline_state.repositories import SceneRepository

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
        from modules.story.outline_state.repositories import SceneRepository

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
        from modules.story.outline_state.repositories import SceneRepository

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
        from modules.story.outline_state.repositories import SceneRepository

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
        from modules.story.outline_state.services import SceneService

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
        from modules.story.outline_state.services import SceneService

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
        from modules.story.outline_state.services import SceneService

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
    async def test_batch_create_models_uses_repository_bulk_create(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        from modules.story.outline_state.services import SceneService

        svc = SceneService()
        scene = Scene(
            id=uuid.uuid4(),
            novel_id=uuid.UUID(hex=sample_novel_id),
            scene_index=0,
            title="A",
        )
        svc.repo = AsyncMock()
        svc.repo.create.side_effect = AssertionError("batch path should use create_many")
        svc.repo.create_many.return_value = [scene]

        result = await svc.batch_create_models_from_dicts(
            db_session,
            sample_novel_id,
            [{"scene_index": 0, "title": "A"}],
        )

        assert result == [scene]
        svc.repo.create.assert_not_awaited()
        svc.repo.create_many.assert_awaited_once()
        assert svc.repo.create_many.await_args.args[1] == uuid.UUID(hex=sample_novel_id)
        assert svc.repo.create_many.await_args.args[2][0].title == "A"

    @pytest.mark.asyncio
    async def test_update_scene_fields(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        from modules.story.outline_state.services import SceneService

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
        from modules.story.outline_state.services import SceneService

        svc = SceneService()
        created = await svc.create(
            db_session,
            sample_novel_id,
            SceneCreate(
                scene_index=0,
                chapter_ids=["1"],
                scene_chunks=[{"chapter_index": 1, "start_offset": 0, "end_offset": 10}],
            ),
        )
        await svc.delete(db_session, created.id, novel_id=sample_novel_id)

        from modules.story.outline_state.repositories import SceneRepository

        repo = SceneRepository()
        nid = uuid.UUID(hex=sample_novel_id)
        scenes = await repo.get_by_novel_ordered(db_session, nid)
        assert len(scenes) == 0
        spans = await repo.get_scene_spans_for_scene(
            db_session,
            nid,
            uuid.UUID(created.id),
            statuses=("deprecated",),
        )
        assert len(spans) == 1
        assert spans[0].status == "deprecated"
        await db_session.rollback()

    @pytest.mark.asyncio
    async def test_reorder_scenes(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        from modules.story.outline_state.services import SceneService

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
    async def test_reorder_rejects_duplicate_incomplete_and_cross_novel_ids(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
        other_novel_id: str,
    ) -> None:
        from modules.story.outline_state.services import SceneService

        svc = SceneService()
        first = await svc.create(
            db_session,
            sample_novel_id,
            SceneCreate(scene_index=0, title="A"),
        )
        second = await svc.create(
            db_session,
            sample_novel_id,
            SceneCreate(scene_index=1, title="B"),
        )
        other = await svc.create(
            db_session,
            other_novel_id,
            SceneCreate(scene_index=0, title="Other"),
        )
        archived = await svc.create(
            db_session,
            sample_novel_id,
            SceneCreate(scene_index=2, title="Archived"),
        )
        await svc.delete(db_session, archived.id, novel_id=sample_novel_id)

        with pytest.raises(DomainValidationError) as duplicate_error:
            await svc.reorder(
                db_session,
                sample_novel_id,
                [first.id, first.id],
            )
        assert duplicate_error.value.code == "scene_reorder_duplicate_ids"

        with pytest.raises(DomainValidationError) as incomplete_error:
            await svc.reorder(db_session, sample_novel_id, [first.id])
        assert incomplete_error.value.code == "scene_reorder_incomplete"

        with pytest.raises(DomainValidationError) as cross_novel_error:
            await svc.reorder(
                db_session,
                sample_novel_id,
                [first.id, second.id, other.id],
            )
        assert cross_novel_error.value.code == "scene_reorder_invalid_scene_ids"

        with pytest.raises(DomainValidationError) as archived_error:
            await svc.reorder(
                db_session,
                sample_novel_id,
                [first.id, second.id, archived.id],
            )
        assert archived_error.value.code == "scene_reorder_invalid_scene_ids"

        result = await svc.reorder(
            db_session,
            sample_novel_id,
            [second.id, first.id],
        )
        assert result == {"updated": 2, "total": 2}

        ordered = await svc.get_ordered(db_session, sample_novel_id)
        assert [(scene.title, scene.scene_index) for scene in ordered] == [
            ("B", 0),
            ("A", 1),
        ]
        await db_session.rollback()

    @pytest.mark.asyncio
    async def test_split_chapters(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        from modules.story.outline_state.repositories import SceneRepository
        from modules.story.outline_state.scene_workbench import SceneWorkbenchService
        from modules.story.outline_state.services import SceneService

        svc = SceneService()
        repo = SceneRepository()

        source = await svc.create(
            db_session,
            sample_novel_id,
            SceneCreate(
                scene_index=0,
                title="Source",
                chapter_ids=["1", "2", "3"],
                scene_chunks=[
                    {
                        "chapter_index": 1,
                        "start_offset": 0,
                        "end_offset": 10,
                        "label": "source-1",
                    },
                    {
                        "chapter_index": 2,
                        "start_offset": 0,
                        "end_offset": 20,
                        "label": "source-2",
                    },
                    {
                        "chapter_index": 3,
                        "start_paragraph": 2,
                        "end_paragraph": 3,
                        "label": "source-3",
                    },
                ],
                status="canonical",
            ),
        )
        target = await svc.create(
            db_session,
            sample_novel_id,
            SceneCreate(
                scene_index=1,
                title="Target",
                chapter_ids=["2", "3", "4"],
                scene_chunks=[
                    {
                        "chapter_index": 2,
                        "start_offset": 50,
                        "end_offset": 60,
                        "label": "target-2",
                    },
                    {
                        "chapter_index": 3,
                        "start_paragraph": 9,
                        "end_paragraph": 10,
                        "label": "target-3",
                    },
                    {
                        "chapter_index": 4,
                        "start_offset": 0,
                        "end_offset": 40,
                        "label": "target-4",
                    },
                ],
                status="canonical",
            ),
        )

        responses = await SceneWorkbenchService().split_chapters_from_api(
            db_session,
            sample_novel_id,
            chapter_index=2,
            target_scene_id=target.id,
        )
        assert [response.id for response in responses] == [source.id, target.id]
        assert [response.chapter_ids for response in responses] == [
            ["1"],
            ["2", "3", "4"],
        ]

        updated_source = await repo.get(
            db_session,
            uuid.UUID(source.id),
        )
        assert updated_source is not None
        assert updated_source.chapter_ids == ["1"]
        assert [chunk["chapter_index"] for chunk in updated_source.scene_chunks] == [1]

        updated_target = await repo.get(
            db_session,
            uuid.UUID(target.id),
        )
        assert updated_target is not None
        assert updated_target.chapter_ids == ["2", "3", "4"]
        assert [chunk["label"] for chunk in updated_target.scene_chunks] == [
            "source-2",
            "target-2",
            "source-3",
            "target-3",
            "target-4",
        ]

        nid = uuid.UUID(hex=sample_novel_id)
        source_links = list(
            (
                await db_session.execute(
                    select(SceneChapterLink)
                    .where(SceneChapterLink.scene_id == uuid.UUID(source.id))
                    .order_by(SceneChapterLink.chapter_index)
                )
            )
            .scalars()
            .all()
        )
        target_links = list(
            (
                await db_session.execute(
                    select(SceneChapterLink)
                    .where(SceneChapterLink.scene_id == uuid.UUID(target.id))
                    .order_by(SceneChapterLink.chapter_index)
                )
            )
            .scalars()
            .all()
        )
        assert [link.chapter_index for link in source_links] == [1]
        assert [link.chapter_index for link in target_links] == [2, 3, 4]

        source_spans = await repo.get_scene_spans_for_scene(
            db_session,
            nid,
            uuid.UUID(source.id),
        )
        target_spans = await repo.get_scene_spans_for_scene(
            db_session,
            nid,
            uuid.UUID(target.id),
        )
        assert [span.chapter_index for span in source_spans] == [1]
        assert [span.chapter_index for span in target_spans] == [2, 2, 3, 3, 4]

        await db_session.rollback()

    @pytest.mark.asyncio
    async def test_split_chapters_validates_targets_before_mutating_source(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
        other_novel_id: str,
    ) -> None:
        from modules.story.outline_state.repositories import SceneRepository
        from modules.story.outline_state.services import SceneService

        svc = SceneService()
        repo = SceneRepository()
        source = await svc.create(
            db_session,
            sample_novel_id,
            SceneCreate(
                scene_index=0,
                title="Source",
                chapter_ids=["1", "2"],
                scene_chunks=[
                    {"chapter_index": 1, "start_offset": 0, "end_offset": 10},
                    {"chapter_index": 2, "start_offset": 0, "end_offset": 20},
                ],
                status="canonical",
            ),
        )
        archived = await svc.create(
            db_session,
            sample_novel_id,
            SceneCreate(scene_index=1, title="Archived", status="canonical"),
        )
        await svc.delete(db_session, archived.id, novel_id=sample_novel_id)
        cross_novel = await svc.create(
            db_session,
            other_novel_id,
            SceneCreate(scene_index=0, title="Other", status="canonical"),
        )

        with pytest.raises(DomainNotFoundError) as missing_source:
            await svc.split_chapters(db_session, sample_novel_id, chapter_index=99)
        assert missing_source.value.code == "scene_split_source_not_found"
        assert missing_source.value.status_code == 404

        with pytest.raises(DomainValidationError) as same_target:
            await svc.split_chapters(
                db_session,
                sample_novel_id,
                chapter_index=2,
                target_scene_id=source.id,
            )
        assert same_target.value.code == "scene_split_same_target"
        assert same_target.value.status_code == 400

        for target_id in (archived.id, cross_novel.id, uuid.uuid4().hex):
            with pytest.raises(DomainNotFoundError) as missing_target:
                await svc.split_chapters(
                    db_session,
                    sample_novel_id,
                    chapter_index=2,
                    target_scene_id=target_id,
                )
            assert missing_target.value.code == "scene_split_target_not_found"
            assert missing_target.value.status_code == 404

        unchanged = await repo.get(db_session, uuid.UUID(source.id))
        assert unchanged is not None
        assert unchanged.chapter_ids == ["1", "2"]
        assert [chunk["chapter_index"] for chunk in unchanged.scene_chunks] == [1, 2]

        nid = uuid.UUID(hex=sample_novel_id)
        links = list(
            (
                await db_session.execute(
                    select(SceneChapterLink)
                    .where(SceneChapterLink.scene_id == uuid.UUID(source.id))
                    .order_by(SceneChapterLink.chapter_index)
                )
            )
            .scalars()
            .all()
        )
        spans = await repo.get_scene_spans_for_scene(
            db_session,
            nid,
            uuid.UUID(source.id),
        )
        assert [link.chapter_index for link in links] == [1, 2]
        assert [span.chapter_index for span in spans] == [1, 2]

        await db_session.rollback()

    @pytest.mark.asyncio
    async def test_split_chapters_to_new_scene_shifts_indices_and_syncs_spans(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        from modules.story.outline_state.repositories import SceneRepository
        from modules.story.outline_state.services import SceneService

        svc = SceneService()
        repo = SceneRepository()
        source = await svc.create(
            db_session,
            sample_novel_id,
            SceneCreate(
                scene_index=0,
                title="Source",
                chapter_ids=["1", "2", "3"],
                scene_chunks=[
                    {"chapter_index": 1, "start_offset": 0, "end_offset": 10},
                    {"chapter_index": 2, "start_offset": 0, "end_offset": 20},
                    {"chapter_index": 3, "start_offset": 0, "end_offset": 30},
                ],
                status="canonical",
            ),
        )
        await svc.create(
            db_session,
            sample_novel_id,
            SceneCreate(scene_index=1, title="Later A"),
        )
        await svc.create(
            db_session,
            sample_novel_id,
            SceneCreate(scene_index=2, title="Later B"),
        )

        await svc.split_chapters(
            db_session,
            sample_novel_id,
            chapter_index=2,
        )

        nid = uuid.UUID(hex=sample_novel_id)
        ordered = await repo.get_by_novel_ordered(db_session, nid)
        assert [(scene.title, scene.scene_index) for scene in ordered] == [
            ("Source", 0),
            ("Scene (断章自 Ch.2)", 1),
            ("Later A", 2),
            ("Later B", 3),
        ]
        updated_source = ordered[0]
        new_scene = ordered[1]
        assert updated_source.chapter_ids == ["1"]
        assert new_scene.chapter_ids == ["2", "3"]
        assert [chunk["chapter_index"] for chunk in updated_source.scene_chunks] == [1]
        assert [chunk["chapter_index"] for chunk in new_scene.scene_chunks] == [2, 3]
        assert new_scene.status == "draft"
        assert new_scene.structure_meta["split_from_scene_id"] == source.id
        assert new_scene.structure_meta["split_at_chapter_index"] == 2

        links = list(
            (
                await db_session.execute(
                    select(SceneChapterLink)
                    .where(
                        SceneChapterLink.scene_id.in_([updated_source.id, new_scene.id])
                    )
                    .order_by(
                        SceneChapterLink.scene_id,
                        SceneChapterLink.chapter_index,
                    )
                )
            )
            .scalars()
            .all()
        )
        links_by_scene: dict[uuid.UUID, list[int]] = {}
        for link in links:
            links_by_scene.setdefault(link.scene_id, []).append(link.chapter_index)
        assert links_by_scene == {
            updated_source.id: [1],
            new_scene.id: [2, 3],
        }

        source_spans = await repo.get_scene_spans_for_scene(
            db_session,
            nid,
            uuid.UUID(source.id),
        )
        new_spans = await repo.get_scene_spans_for_scene(
            db_session,
            nid,
            new_scene.id,
        )
        assert [span.chapter_index for span in source_spans] == [1]
        assert [span.chapter_index for span in new_spans] == [2, 3]

        await db_session.rollback()

    @pytest.mark.asyncio
    async def test_split_chapters_builds_new_scene_before_mutating_source(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        from modules.story.outline_state.repositories import SceneRepository
        from modules.story.outline_state.services import SceneService

        svc = SceneService()
        repo = SceneRepository()
        source = await svc.create(
            db_session,
            sample_novel_id,
            SceneCreate(
                scene_index=0,
                title="Source",
                chapter_ids=["1", "2"],
                scene_chunks=[
                    {"chapter_index": 1, "start_offset": 0, "end_offset": 10},
                    {"chapter_index": 2, "start_offset": 0, "end_offset": 20},
                ],
                status="canonical",
            ),
        )
        later = await svc.create(
            db_session,
            sample_novel_id,
            SceneCreate(scene_index=1, title="Later", status="canonical"),
        )
        source_model = await repo.get(db_session, uuid.UUID(source.id))
        assert source_model is not None
        source_model.narrative_tag = "x" * 33
        db_session.add(source_model)
        await db_session.flush()

        with pytest.raises(PydanticValidationError):
            await svc.split_chapters(
                db_session,
                sample_novel_id,
                chapter_index=2,
            )

        unchanged_source = await repo.get(db_session, uuid.UUID(source.id))
        unchanged_later = await repo.get(db_session, uuid.UUID(later.id))
        assert unchanged_source is not None
        assert unchanged_later is not None
        assert unchanged_source.chapter_ids == ["1", "2"]
        assert [chunk["chapter_index"] for chunk in unchanged_source.scene_chunks] == [
            1,
            2,
        ]
        assert unchanged_later.scene_index == 1
        ordered = await repo.get_by_novel_ordered(
            db_session,
            uuid.UUID(sample_novel_id),
        )
        assert len(ordered) == 2

        await db_session.rollback()


class TestSceneSplitChunk:
    """SceneService.split_scene_chunk_to_new_chapter 及 facade 测试"""

    @pytest.mark.asyncio
    async def test_split_scene_chunk_happy_path(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        from modules.story.outline_state.repositories import SceneRepository
        from modules.story.outline_state.services import SceneService

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

    @pytest.mark.asyncio
    async def test_split_scene_chunk_supports_offset_contract_and_persists_spans(
        self,
        db_session: AsyncSession,
        sample_novel_id: str,
    ) -> None:
        from modules.story.outline_state.repositories import SceneRepository
        from modules.story.outline_state.services import SceneService

        nid = uuid.UUID(hex=sample_novel_id)
        repo = SceneRepository()
        source = await repo.create(
            db_session,
            nid,
            SceneCreate(
                scene_index=1,
                title="Offset source",
                chapter_ids=["5"],
                scene_chunks=[
                    {
                        "chapter_id": "5",
                        "chapter_index": 5,
                        "start_offset": 0,
                        "end_offset": 100,
                    }
                ],
                status="draft",
            ),
        )

        result = await SceneService().split_scene_chunk_to_new_chapter(
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

        source_id = source.id
        new_scene = next(scene for scene in result if scene.id != source_id)
        new_scene_id = new_scene.id
        db_session.expire_all()
        stored_source = await repo.get(db_session, source_id)
        stored_new = await repo.get(db_session, new_scene_id)
        assert stored_source is not None
        assert stored_new is not None
        assert stored_source.scene_chunks[0]["end_offset"] == 40
        assert stored_new.scene_chunks[0]["start_offset"] == 0
        assert stored_new.scene_chunks[0]["end_offset"] == 60

        source_spans = await repo.get_scene_spans_for_scene(
            db_session,
            nid,
            source_id,
        )
        new_spans = await repo.get_scene_spans_for_scene(
            db_session,
            nid,
            new_scene_id,
        )
        assert [(span.start_offset, span.end_offset) for span in source_spans] == [
            (0, 40)
        ]
        assert [(span.start_offset, span.end_offset) for span in new_spans] == [(0, 60)]

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
        from modules.story.outline_state.repositories import SceneRepository
        from modules.story.outline_state.services import SceneService

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
        from modules.story.outline_state.facade import split_scene_chunk_to_new_chapter
        from modules.story.outline_state.repositories import SceneRepository

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
