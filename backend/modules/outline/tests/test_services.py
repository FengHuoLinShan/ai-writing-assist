from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.sql.dml import Update
from sqlalchemy.sql.selectable import Select

from core.errors import NotFoundError
from modules.outline.schemas import (
    OutlineArcCreate,
    PlotThreadCreate,
    PlotThreadUpdate,
    SceneUpdate,
)
from modules.outline.services import (
    OutlineArcService,
    OutlineStructureCleanupService,
    PlotThreadService,
    SceneService,
)


def test_outline_facades_have_no_direct_http_exception_dependency() -> None:
    outline_dir = Path(__file__).resolve().parents[1]
    facade_files = [
        outline_dir / "facade.py",
        outline_dir / "scene_facade.py",
        outline_dir / "structure_dedup_facade.py",
        outline_dir / "deep_import_repair_facade.py",
        outline_dir / "foreshadowing_facade.py",
    ]

    for facade_file in facade_files:
        source = facade_file.read_text()
        assert "from fastapi import HTTPException" not in source
        assert "except HTTPException" not in source


def test_outline_facade_reexports_subfacade_functions_by_identity() -> None:
    from modules.outline import (
        deep_import_repair_facade,
        foreshadowing_facade,
        scene_facade,
        structure_dedup_facade,
    )
    from modules.outline import (
        facade as outline_facade,
    )

    assert outline_facade.create_scene is scene_facade.create_scene
    assert outline_facade.get_scene_contract is scene_facade.get_scene_contract
    assert outline_facade.suggest_structure_dedup is (
        structure_dedup_facade.suggest_structure_dedup
    )
    assert outline_facade.apply_structure_dedup is (
        structure_dedup_facade.apply_structure_dedup
    )
    assert outline_facade.apply_structure_dedup_group is (
        structure_dedup_facade.apply_structure_dedup_group
    )
    assert outline_facade.ensure_deep_import_structure_outputs is (
        deep_import_repair_facade.ensure_deep_import_structure_outputs
    )
    assert outline_facade.get_active_foreshadowing is (
        foreshadowing_facade.get_active_foreshadowing
    )


@pytest.mark.asyncio
async def test_deep_import_repair_service_resolves_world_entities_in_service() -> None:
    from modules.outline.deep_import_repair_service import (
        OutlineDeepImportRepairService,
    )

    calls: list[str] = []

    async def list_entities(_db, novel_id: str, *, limit: int):
        assert novel_id == "novel-1"
        assert limit == 20
        return [{"id": "entity-1", "name": "灯塔"}]

    def service_resolver(name: str):
        calls.append(name)
        if name == "world.list_entities":
            return list_entities
        raise KeyError(name)

    target = await OutlineDeepImportRepairService(
        service_resolver=service_resolver
    ).select_fallback_reveal_target(MagicMock(), "novel-1")

    assert calls == ["world.list_entities"]
    assert target == {"id": "entity-1", "name": "灯塔"}


@pytest.mark.asyncio
async def test_structure_cleanup_uses_unit_of_work_instead_of_per_asset_update() -> None:
    workflow_id = "wf-cleanup"
    asset = MagicMock()
    asset.provenance_meta = {
        "source": "deep_import",
        "workflow_id": workflow_id,
        "auto_ingested": True,
    }
    asset.status = "draft"

    class Result:
        def scalars(self):  # type: ignore[no-untyped-def]
            return self

        def all(self):  # type: ignore[no-untyped-def]
            return [asset]

    class Session:
        def __init__(self) -> None:
            self.statements: list[object] = []
            self.flushes = 0

        async def execute(self, stmt):  # type: ignore[no-untyped-def]
            self.statements.append(stmt)
            return Result()

        def add(self, item):  # type: ignore[no-untyped-def]
            assert item is asset

        async def flush(self) -> None:
            self.flushes += 1

    session = Session()
    cleanup_service = OutlineStructureCleanupService()

    deprecated = await cleanup_service.deprecate_deep_import_structure_assets_by_workflow(
        session,  # type: ignore[arg-type]
        str(uuid.uuid4()),
        workflow_id,
    )

    assert deprecated == 4
    assert session.flushes == 1
    assert all(isinstance(stmt, Select) for stmt in session.statements)
    assert not any(isinstance(stmt, Update) for stmt in session.statements)
    assert asset.status == "deprecated"
    assert asset.provenance_meta["cleanup_status"] == "deprecated"


@pytest.mark.asyncio
async def test_get_scene_contract_returns_none_for_domain_not_found(monkeypatch) -> None:
    from modules.outline.facade import get_scene_contract

    service = MagicMock()
    service.get = AsyncMock(side_effect=NotFoundError("Scene missing"))
    monkeypatch.setattr("modules.outline.services.SceneService", lambda: service)

    result = await get_scene_contract(MagicMock(), str(uuid.uuid4()), str(uuid.uuid4()))

    assert result is None


def test_scene_to_contract_preserves_shape_and_defaults() -> None:
    from modules.outline.contracts import SceneContract
    from modules.outline.services import scene_to_contract

    scene = _make_scene(
        scene_id="11111111-1111-1111-1111-111111111111",
        novel_id="22222222-2222-2222-2222-222222222222",
        title="伏笔 Scene",
        scene_index=7,
        scene_chunks=None,
        chapter_ids=None,
        structure_meta=None,
        status="canonical",
    )

    contract = scene_to_contract(scene)

    assert isinstance(contract, SceneContract)
    assert contract.id == "11111111-1111-1111-1111-111111111111"
    assert contract.novel_id == "22222222-2222-2222-2222-222222222222"
    assert contract.scene_index == 7
    assert contract.title == "伏笔 Scene"
    assert contract.scene_chunks == []
    assert contract.chapter_ids == []
    assert contract.structure_meta == {}
    assert contract.status == "canonical"


def _make_thread(
    *,
    thread_id: str | None = None,
    novel_id: str | None = None,
    name: str = "线",
    thread_type: str = "main",
    **overrides: object,
) -> MagicMock:
    thread = MagicMock()
    thread.id = uuid.UUID(thread_id) if thread_id else uuid.uuid4()
    thread.novel_id = uuid.UUID(novel_id) if novel_id else uuid.uuid4()
    thread.name = name
    thread.thread_type = thread_type
    thread.summary = None
    thread.visible_goal = None
    thread.hidden_truth = None
    thread.start_chapter = None
    thread.planned_payoff_chapter = None
    thread.current_stage = None
    thread.related_character_ids = []
    thread.related_entity_ids = []
    thread.related_memory_ids = []
    thread.reader_known_state = None
    thread.author_known_state = None
    thread.status = "draft"
    thread.created_at = datetime.now(UTC)
    thread.updated_at = datetime.now(UTC)
    for key, value in overrides.items():
        setattr(thread, key, value)
    return thread


def _make_arc(
    *,
    arc_id: str | None = None,
    novel_id: str | None = None,
    title: str = "卷",
    **overrides: object,
) -> MagicMock:
    arc = MagicMock()
    arc.id = uuid.UUID(arc_id) if arc_id else uuid.uuid4()
    arc.novel_id = uuid.UUID(novel_id) if novel_id else uuid.uuid4()
    arc.title = title
    arc.arc_index = None
    arc.start_chapter = None
    arc.end_chapter = None
    arc.arc_goal = None
    arc.core_conflict = None
    arc.main_opposition = None
    arc.entry_hook = None
    arc.midpoint_turn = None
    arc.climax = None
    arc.result = None
    arc.next_hook = None
    arc.related_thread_ids = []
    arc.related_character_ids = []
    arc.related_entity_ids = []
    arc.status = "draft"
    arc.created_at = datetime.now(UTC)
    arc.updated_at = datetime.now(UTC)
    for key, value in overrides.items():
        setattr(arc, key, value)
    return arc


def _make_scene(
    *,
    scene_id: str | None = None,
    novel_id: str | None = None,
    title: str = "Scene",
    **overrides: object,
) -> MagicMock:
    scene = MagicMock()
    scene.id = uuid.UUID(scene_id) if scene_id else uuid.uuid4()
    scene.novel_id = uuid.UUID(novel_id) if novel_id else uuid.uuid4()
    scene.scene_index = 1
    scene.title = title
    scene.goal = None
    scene.core_conflict = None
    scene.emotional_beat = None
    scene.must_happen = None
    scene.must_not_happen = None
    scene.narrative_tag = "draft"
    scene.source = "deep_import"
    scene.scene_chunks = []
    scene.chapter_ids = []
    scene.pov_character_id = None
    scene.structure_meta = {}
    scene.status = "draft"
    scene.created_at = datetime.now(UTC)
    scene.updated_at = datetime.now(UTC)
    for key, value in overrides.items():
        setattr(scene, key, value)
    return scene


class TestPlotThreadService:
    """T2: Service 层 — PlotThread（repo 用 AsyncMock 替换）"""

    @pytest.mark.asyncio
    async def test_create_returns_response(
        self,
        sample_novel_id: str,
        thread_data: PlotThreadCreate,
    ) -> None:
        thread = _make_thread(novel_id=sample_novel_id, name="主角成长之路")
        svc = PlotThreadService()
        svc.repo = MagicMock()
        svc.repo.create = AsyncMock(return_value=thread)
        db = MagicMock()

        result = await svc.create(db, sample_novel_id, thread_data)

        assert result.id == str(thread.id)
        assert result.name == "主角成长之路"
        assert result.thread_type == "main"
        assert isinstance(result.id, str)
        svc.repo.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_batch_delegates_to_repository_batch(
        self,
        sample_novel_id: str,
    ) -> None:
        threads = [
            _make_thread(novel_id=sample_novel_id, name="批量线 1"),
            _make_thread(novel_id=sample_novel_id, name="批量线 2"),
        ]
        svc = PlotThreadService()
        svc.repo = MagicMock()
        svc.repo.create = AsyncMock(side_effect=AssertionError("should use create_many"))
        svc.repo.create_many = AsyncMock(return_value=threads)
        db = MagicMock()

        result = await svc.create_batch(
            db,
            sample_novel_id,
            [
                PlotThreadCreate(name="批量线 1", thread_type="main"),
                PlotThreadCreate(name="批量线 2", thread_type="secondary"),
            ],
        )

        assert [item.name for item in result] == ["批量线 1", "批量线 2"]
        svc.repo.create.assert_not_awaited()
        svc.repo.create_many.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_list_returns_paginated(
        self,
        sample_novel_id: str,
    ) -> None:
        threads = [
            _make_thread(novel_id=sample_novel_id, name=f"线{i}", thread_type="secondary")
            for i in range(3)
        ]
        svc = PlotThreadService()
        svc.repo = MagicMock()
        svc.repo.get_by_novel = AsyncMock(return_value=(threads, 3))
        db = MagicMock()

        items, total = await svc.list(db, sample_novel_id)

        assert total == 3
        assert len(items) == 3
        assert all(isinstance(item.id, str) for item in items)

    @pytest.mark.parametrize(
        "operation",
        ["get", "delete"],
        ids=["get", "delete"],
    )
    @pytest.mark.asyncio
    async def test_plot_thread_wrong_novel_raises_404(
        self,
        sample_novel_id: str,
        other_novel_id: str,
        operation: str,
    ) -> None:
        thread = _make_thread(novel_id=sample_novel_id)
        svc = PlotThreadService()
        svc.repo = MagicMock()
        svc.repo.get = AsyncMock(return_value=thread)
        svc.repo.delete = AsyncMock(return_value=True)
        db = MagicMock()

        with pytest.raises(NotFoundError) as exc:
            if operation == "get":
                await svc.get(db, str(thread.id), novel_id=other_novel_id)
            else:
                await svc.delete(db, str(thread.id), novel_id=other_novel_id)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_returns_on_correct_novel(
        self,
        sample_novel_id: str,
    ) -> None:
        thread = _make_thread(novel_id=sample_novel_id, name="查询测试")
        svc = PlotThreadService()
        svc.repo = MagicMock()
        svc.repo.get = AsyncMock(return_value=thread)
        db = MagicMock()

        got = await svc.get(db, str(thread.id), novel_id=sample_novel_id)

        assert got is not None
        assert got.name == "查询测试"

    @pytest.mark.asyncio
    async def test_update_partial(
        self,
        sample_novel_id: str,
    ) -> None:
        thread = _make_thread(
            novel_id=sample_novel_id,
            name="原名称",
            thread_type="main",
            current_stage="初期",
        )
        updated = _make_thread(
            id=str(thread.id),
            novel_id=sample_novel_id,
            name="新名称",
            thread_type="main",
            current_stage="初期",
        )
        svc = PlotThreadService()
        svc.repo = MagicMock()
        svc.repo.get = AsyncMock(return_value=thread)
        svc.repo.update = AsyncMock(return_value=updated)
        db = MagicMock()

        result = await svc.update(
            db,
            str(thread.id),
            PlotThreadUpdate(name="新名称"),
            novel_id=sample_novel_id,
        )

        assert result is not None
        assert result.name == "新名称"
        assert result.current_stage == "初期"

    @pytest.mark.asyncio
    async def test_update_marks_auto_ingested_thread_user_edited(
        self,
        sample_novel_id: str,
    ) -> None:
        thread = _make_thread(
            novel_id=sample_novel_id,
            name="自动导入线",
            provenance_meta={
                "source": "deep_import",
                "workflow_id": "wf-edit",
                "auto_ingested": True,
                "user_edited": False,
            },
        )
        updated = _make_thread(
            id=str(thread.id),
            novel_id=sample_novel_id,
            name="人工编辑线",
            provenance_meta={
                **thread.provenance_meta,
                "user_edited": True,
            },
        )
        svc = PlotThreadService()
        svc.repo = MagicMock()
        svc.repo.get = AsyncMock(return_value=thread)
        svc.repo.update = AsyncMock(return_value=updated)
        db = MagicMock()

        await svc.update(
            db,
            str(thread.id),
            PlotThreadUpdate(name="人工编辑线"),
            novel_id=sample_novel_id,
        )

        update_data = svc.repo.update.await_args.args[2]
        assert update_data.provenance_meta["user_edited"] is True
        assert update_data.provenance_meta["edited_at"]

    @pytest.mark.asyncio
    async def test_delete_on_correct_novel(
        self,
        sample_novel_id: str,
    ) -> None:
        thread = _make_thread(novel_id=sample_novel_id, name="待删除")
        svc = PlotThreadService()
        svc.repo = MagicMock()
        svc.repo.get = AsyncMock(return_value=thread)
        db = MagicMock()
        db.flush = AsyncMock()

        await svc.delete(db, str(thread.id), novel_id=sample_novel_id)

        assert thread.status == "deprecated"
        db.flush.assert_awaited_once()


class TestSceneService:
    @pytest.mark.asyncio
    async def test_update_marks_auto_ingested_scene_user_edited(
        self,
        sample_novel_id: str,
    ) -> None:
        scene = _make_scene(
            novel_id=sample_novel_id,
            structure_meta={
                "workflow_id": "wf-scene-edit",
                "auto_ingested": True,
                "user_edited": False,
            },
        )
        updated = _make_scene(
            scene_id=str(scene.id),
            novel_id=sample_novel_id,
            title="人工编辑 Scene",
            structure_meta={
                **scene.structure_meta,
                "user_edited": True,
            },
        )
        svc = SceneService()
        svc.repo = MagicMock()
        svc.repo.get = AsyncMock(return_value=scene)
        svc.repo.update = AsyncMock(return_value=updated)
        db = MagicMock()

        await svc.update(
            db,
            str(scene.id),
            SceneUpdate(title="人工编辑 Scene"),
            novel_id=sample_novel_id,
        )

        update_data = svc.repo.update.await_args.args[2]
        assert update_data.structure_meta["user_edited"] is True
        assert update_data.structure_meta["edited_at"]

    @pytest.mark.asyncio
    async def test_get_active_contract(
        self,
        sample_novel_id: str,
    ) -> None:
        thread = _make_thread(
            novel_id=sample_novel_id,
            name="活跃线",
            thread_type="main",
            start_chapter=1,
            status="canonical",
        )
        svc = PlotThreadService()
        svc.repo = MagicMock()
        svc.repo.get_active = AsyncMock(return_value=[thread])
        db = MagicMock()

        threads = await svc.get_active(db, sample_novel_id, chapter_index=5)

        assert len(threads) == 1
        assert threads[0].name == "活跃线"
        assert threads[0].thread_type == "main"


class TestOutlineArcService:
    """T2: Service 层 — OutlineArc（repo 用 AsyncMock 替换）"""

    @pytest.mark.asyncio
    async def test_create_and_get(
        self,
        sample_novel_id: str,
        arc_data: OutlineArcCreate,
    ) -> None:
        arc = _make_arc(novel_id=sample_novel_id, title="第一卷：启程")
        svc = OutlineArcService()
        svc.repo = MagicMock()
        svc.repo.create = AsyncMock(return_value=arc)
        svc.repo.get = AsyncMock(return_value=arc)
        db = MagicMock()

        created = await svc.create(db, sample_novel_id, arc_data)
        assert created.id == str(arc.id)
        assert created.title == "第一卷：启程"

        fetched = await svc.get(db, str(arc.id), novel_id=sample_novel_id)
        assert fetched is not None
        assert fetched.title == "第一卷：启程"

    @pytest.mark.asyncio
    async def test_create_batch_delegates_to_repository_batch(
        self,
        sample_novel_id: str,
    ) -> None:
        arcs = [
            _make_arc(novel_id=sample_novel_id, title="批量篇章 1"),
            _make_arc(novel_id=sample_novel_id, title="批量篇章 2"),
        ]
        svc = OutlineArcService()
        svc.repo = MagicMock()
        svc.repo.create = AsyncMock(side_effect=AssertionError("should use create_many"))
        svc.repo.create_many = AsyncMock(return_value=arcs)
        db = MagicMock()

        result = await svc.create_batch(
            db,
            sample_novel_id,
            [
                OutlineArcCreate(title="批量篇章 1", arc_index=1),
                OutlineArcCreate(title="批量篇章 2", arc_index=2),
            ],
        )

        assert [item.title for item in result] == ["批量篇章 1", "批量篇章 2"]
        svc.repo.create.assert_not_awaited()
        svc.repo.create_many.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_by_chapter(
        self,
        sample_novel_id: str,
    ) -> None:
        arc = _make_arc(
            novel_id=sample_novel_id,
            title="卷一",
            start_chapter=1,
            end_chapter=5,
        )
        svc = OutlineArcService()
        svc.repo = MagicMock()
        svc.repo.get_by_chapter = AsyncMock(return_value=arc)
        db = MagicMock()

        result = await svc.get_by_chapter(db, sample_novel_id, chapter_index=3)

        assert result is not None
        assert result.title == "卷一"

    @pytest.mark.asyncio
    async def test_get_by_chapter_none(
        self,
        sample_novel_id: str,
    ) -> None:
        svc = OutlineArcService()
        svc.repo = MagicMock()
        svc.repo.get_by_chapter = AsyncMock(return_value=None)
        db = MagicMock()

        arc = await svc.get_by_chapter(db, sample_novel_id, chapter_index=99)

        assert arc is None

    @pytest.mark.asyncio
    async def test_novel_id_isolation(
        self,
        sample_novel_id: str,
        other_novel_id: str,
    ) -> None:
        arc = _make_arc(novel_id=sample_novel_id, title="仅A可见")
        svc = OutlineArcService()
        svc.repo = MagicMock()
        svc.repo.get = AsyncMock(return_value=arc)
        db = MagicMock()

        # wrong novel_id should raise 404
        with pytest.raises(NotFoundError) as exc:
            await svc.get(db, str(arc.id), novel_id=other_novel_id)
        assert exc.value.status_code == 404
        # correct novel_id returns the arc
        got = await svc.get(db, str(arc.id), novel_id=sample_novel_id)
        assert got is not None
        assert got.title == "仅A可见"
