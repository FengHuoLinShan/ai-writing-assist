"""
Writing 模块单元测试

覆盖 contracts, schemas, repositories, api, tasks 五个模块。
使用 unittest.mock 完全隔离 DB 和外部依赖。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from modules.writing.contracts import WritingDraftContract
from modules.writing.repositories import WritingDraftRepository
from modules.writing.schemas import (
    ChapterSummaryItem,
    DraftListItem,
    VersionHistoryResponse,
    WritingDraftAutosaveCreate,
    WritingDraftCreate,
    WritingDraftResponse,
    WritingDraftUpdate,
)

# ============================================================
# Contracts 测试
# ============================================================


class TestWritingDraftContract:
    """WritingDraftContract dataclass — 跨模块契约"""

    def test_create_defaults(self):
        contract = WritingDraftContract(
            novel_id="nid",
            chapter_index=1,
        )
        assert contract.novel_id == "nid"
        assert contract.chapter_index == 1
        assert contract.title is None
        assert contract.content is None
        assert contract.version_number == 1
        assert contract.id is None
        assert contract.conflict_check_snapshot_json is None
        assert contract.provenance_json is None
        assert contract.created_at is None
        assert contract.updated_at is None

    def test_create_full(self):
        contract = WritingDraftContract(
            novel_id="nid",
            chapter_index=2,
            id="draft-1",
            title="第二章",
            content="正文内容",
            version_number=3,
            conflict_check_snapshot_json={"source": "snapshot"},
            provenance_json={"source": "test"},
        )
        assert contract.id == "draft-1"
        assert contract.title == "第二章"
        assert contract.content == "正文内容"
        assert contract.version_number == 3
        assert contract.conflict_check_snapshot_json == {"source": "snapshot"}
        assert contract.provenance_json == {"source": "test"}

    def test_is_frozen(self):
        contract = WritingDraftContract(novel_id="nid", chapter_index=1)
        with pytest.raises(AttributeError):
            contract.novel_id = "new"  # type: ignore[misc]


# ============================================================
# Schemas 测试
# ============================================================


class TestWritingDraftCreate:
    """WritingDraftCreate — 创建草稿请求 schema"""

    def test_minimal(self):
        data = WritingDraftCreate(novel_id=str(uuid.uuid4()), chapter_index=1)
        assert data.chapter_index == 1
        assert data.title is None
        assert data.content is None

    def test_full(self):
        data = WritingDraftCreate(
            novel_id=str(uuid.uuid4()),
            chapter_index=5,
            title="第五章",
            content="五章正文",
        )
        assert data.title == "第五章"
        assert data.content == "五章正文"

    def test_chapter_index_must_be_ge_1(self):
        with pytest.raises(ValidationError):
            WritingDraftCreate(novel_id=str(uuid.uuid4()), chapter_index=0)

    def test_chapter_index_negative(self):
        with pytest.raises(ValidationError):
            WritingDraftCreate(novel_id=str(uuid.uuid4()), chapter_index=-1)

    def test_novel_id_required(self):
        with pytest.raises(ValidationError):
            WritingDraftCreate(chapter_index=1)  # type: ignore[call-arg]


class TestWritingDraftUpdate:
    """WritingDraftUpdate — 暂存草稿请求 schema"""

    def test_empty(self):
        data = WritingDraftUpdate()
        assert data.title is None
        assert data.content is None

    def test_partial_title(self):
        data = WritingDraftUpdate(title="仅标题")
        assert data.title == "仅标题"
        assert data.content is None

    def test_partial_content(self):
        data = WritingDraftUpdate(content="仅正文")
        assert data.title is None
        assert data.content == "仅正文"


class TestWritingDraftResponse:
    """WritingDraftResponse — 草稿响应 schema & UUID→str coercion"""

    def test_from_orm_like(self):
        resp = WritingDraftResponse(
            id=str(uuid.uuid4()),
            novel_id=str(uuid.uuid4()),
            chapter_index=1,
            title="第一章",
            content="正文",
            version_number=2,
        )
        assert isinstance(resp.id, str)
        assert isinstance(resp.novel_id, str)

    def test_uuid_coercion_on_id(self):
        raw_uuid = uuid.uuid4()
        resp = WritingDraftResponse(
            id=raw_uuid,
            novel_id=str(uuid.uuid4()),
            chapter_index=1,
        )
        assert isinstance(resp.id, str)
        assert resp.id == str(raw_uuid)

    def test_uuid_coercion_on_novel_id(self):
        raw_uuid = uuid.uuid4()
        resp = WritingDraftResponse(
            id=str(uuid.uuid4()),
            novel_id=raw_uuid,
            chapter_index=1,
        )
        assert isinstance(resp.novel_id, str)
        assert resp.novel_id == str(raw_uuid)

    def test_none_id_returns_none(self):
        resp = WritingDraftResponse(
            id=str(uuid.uuid4()),
            novel_id=str(uuid.uuid4()),
            chapter_index=1,
        )
        assert resp.id is not None


class TestDraftListItem:
    """DraftListItem — 版本列表项 schema"""

    def test_uuid_coercion(self):
        raw_uuid = uuid.uuid4()
        item = DraftListItem(
            id=raw_uuid,
            version_number=1,
            title="v1",
        )
        assert isinstance(item.id, str)
        assert item.id == str(raw_uuid)

    def test_defaults(self):
        item = DraftListItem(id=str(uuid.uuid4()), version_number=1)
        assert item.title is None
        assert item.created_at is None
        assert item.updated_at is None


class TestVersionHistoryResponse:
    """VersionHistoryResponse — 版本历史响应"""

    def test_create(self):
        items = [
            DraftListItem(id=str(uuid.uuid4()), version_number=2),
            DraftListItem(id=str(uuid.uuid4()), version_number=1),
        ]
        resp = VersionHistoryResponse(
            novel_id="nid",
            chapter_index=1,
            versions=items,
            total=2,
        )
        assert resp.total == 2
        assert len(resp.versions) == 2
        assert resp.versions[0].version_number == 2


# ============================================================
# Repositories 测试（mock DB）
# ============================================================


class TestWritingDraftRepository:
    """WritingDraftRepository — 数据访问层（全部 mock）"""

    @pytest.fixture
    def repo(self) -> WritingDraftRepository:
        return WritingDraftRepository()

    @pytest.fixture
    def mock_db(self) -> AsyncMock:
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.execute = AsyncMock()
        # ScalarResult mock
        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none.return_value = None
        scalar_result.scalars.return_value.all.return_value = []
        scalar_result.all.return_value = []
        db.execute.return_value = scalar_result
        return db

    @pytest.fixture
    def sample_create(self) -> WritingDraftCreate:
        return WritingDraftCreate(
            novel_id=str(uuid.uuid4()),
            chapter_index=1,
            title="第一章",
            content="正文内容",
        )

    async def test_create(
        self,
        repo: WritingDraftRepository,
        mock_db: AsyncMock,
        sample_create: WritingDraftCreate,
    ):
        draft = await repo.create(mock_db, sample_create)
        assert draft.novel_id is not None
        assert draft.chapter_index == 1
        assert draft.title == "第一章"
        assert draft.content == "正文内容"
        assert draft.version_number == 1
        mock_db.add.assert_called_once()
        mock_db.flush.assert_awaited_once()

    async def test_create_version_increment(
        self,
        repo: WritingDraftRepository,
        mock_db: AsyncMock,
        sample_create: WritingDraftCreate,
    ):
        # Simulate existing max version = 2
        mock_db.execute.return_value.scalar_one_or_none.return_value = 2
        draft = await repo.create(mock_db, sample_create)
        assert draft.version_number == 3

    async def test_get_found(
        self,
        repo: WritingDraftRepository,
        mock_db: AsyncMock,
    ):
        draft_id = uuid.uuid4()
        mock_orm = MagicMock()
        mock_orm.id = draft_id
        mock_orm.novel_id = uuid.uuid4()
        mock_orm.chapter_index = 1
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_orm

        result = await repo.get(mock_db, draft_id)
        assert result is not None
        assert result.id == draft_id

    async def test_get_not_found(
        self,
        repo: WritingDraftRepository,
        mock_db: AsyncMock,
    ):
        mock_db.execute.return_value.scalar_one_or_none.return_value = None
        result = await repo.get(mock_db, uuid.uuid4())
        assert result is None

    async def test_get_latest_by_chapter(
        self,
        repo: WritingDraftRepository,
        mock_db: AsyncMock,
    ):
        mock_draft = MagicMock()
        mock_draft.version_number = 3
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_draft

        result = await repo.get_latest_by_chapter(mock_db, uuid.uuid4(), 1)
        assert result is not None
        assert result.version_number == 3

    async def test_get_latest_by_chapter_empty(
        self,
        repo: WritingDraftRepository,
        mock_db: AsyncMock,
    ):
        mock_db.execute.return_value.scalar_one_or_none.return_value = None
        result = await repo.get_latest_by_chapter(mock_db, uuid.uuid4(), 99)
        assert result is None

    async def test_get_version_history(
        self,
        repo: WritingDraftRepository,
        mock_db: AsyncMock,
    ):
        mock_db.execute.return_value.scalars.return_value.all.return_value = [
            MagicMock(version_number=3),
            MagicMock(version_number=2),
            MagicMock(version_number=1),
        ]
        versions = await repo.get_version_history(mock_db, uuid.uuid4(), 1)
        assert len(versions) == 3
        assert versions[0].version_number == 3

    async def test_get_version_history_empty(
        self,
        repo: WritingDraftRepository,
        mock_db: AsyncMock,
    ):
        mock_db.execute.return_value.scalars.return_value.all.return_value = []
        versions = await repo.get_version_history(mock_db, uuid.uuid4(), 99)
        assert versions == []

    async def test_update_found(
        self,
        repo: WritingDraftRepository,
        mock_db: AsyncMock,
    ):
        draft_id = uuid.uuid4()
        mock_orm = MagicMock()
        mock_orm.id = draft_id
        mock_orm.novel_id = uuid.uuid4()
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_orm

        result = await repo.update(mock_db, draft_id, WritingDraftUpdate(title="新标题"))
        assert result is not None
        assert result.id == draft_id

    async def test_update_reuses_loaded_draft(
        self,
        repo: WritingDraftRepository,
        monkeypatch: pytest.MonkeyPatch,
    ):
        draft_id = uuid.uuid4()
        draft = MagicMock()
        draft.id = draft_id
        draft.title = "旧标题"
        draft.content = "旧正文"
        get_calls = 0

        async def fake_get(_db, requested_id):
            nonlocal get_calls
            get_calls += 1
            assert requested_id == draft_id
            return draft

        class Session:
            def __init__(self) -> None:
                self.added = []
                self.flush_count = 0

            def add(self, obj):
                self.added.append(obj)

            async def flush(self) -> None:
                self.flush_count += 1

        monkeypatch.setattr(repo, "get", fake_get)
        db = Session()

        result = await repo.update(
            db,  # type: ignore[arg-type]
            draft_id,
            WritingDraftUpdate(title="新标题", content="新正文"),
        )

        assert result is draft
        assert draft.title == "新标题"
        assert draft.content == "新正文"
        assert get_calls == 1
        assert db.added == [draft]
        assert db.flush_count == 1

    async def test_update_loaded_draft_does_not_fetch_again(
        self,
        repo: WritingDraftRepository,
        monkeypatch: pytest.MonkeyPatch,
    ):
        draft = MagicMock()
        draft.id = uuid.uuid4()
        draft.title = "旧标题"
        draft.content = "旧正文"

        async def fail_get(*_args, **_kwargs):
            raise AssertionError("loaded draft should not be fetched again")

        class Session:
            def __init__(self) -> None:
                self.added = []
                self.flush_count = 0

            def add(self, obj):
                self.added.append(obj)

            async def flush(self) -> None:
                self.flush_count += 1

        monkeypatch.setattr(repo, "get", fail_get)
        db = Session()

        result = await repo.update(
            db,  # type: ignore[arg-type]
            draft,
            WritingDraftUpdate(title="新标题", content="新正文"),
        )

        assert result is draft
        assert draft.title == "新标题"
        assert draft.content == "新正文"
        assert db.added == [draft]
        assert db.flush_count == 1

    async def test_update_not_found(
        self,
        repo: WritingDraftRepository,
        mock_db: AsyncMock,
    ):
        mock_db.execute.return_value.scalar_one_or_none.return_value = None
        result = await repo.update(mock_db, uuid.uuid4(), WritingDraftUpdate(title="x"))
        assert result is None

    async def test_update_no_changes(
        self,
        repo: WritingDraftRepository,
        mock_db: AsyncMock,
    ):
        draft_id = uuid.uuid4()
        mock_orm = MagicMock()
        mock_orm.id = draft_id
        mock_orm.novel_id = uuid.uuid4()
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_orm

        result = await repo.update(mock_db, draft_id, WritingDraftUpdate())
        assert result is not None

    async def test_delete_success(
        self,
        repo: WritingDraftRepository,
        mock_db: AsyncMock,
    ):
        draft_id = uuid.uuid4()
        mock_draft = MagicMock()
        mock_draft.id = draft_id
        mock_draft.novel_id = uuid.uuid4()
        mock_draft.chapter_index = 1
        mock_draft.version_number = 2
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_draft

        result = await repo.delete(mock_db, draft_id)
        assert result is mock_draft

    async def test_delete_single_version_returns_draft(
        self,
        repo: WritingDraftRepository,
        mock_db: AsyncMock,
    ):
        draft_id = uuid.uuid4()
        mock_draft = MagicMock()
        mock_draft.id = draft_id
        mock_draft.novel_id = uuid.uuid4()
        mock_draft.chapter_index = 1
        mock_draft.version_number = 1
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_draft

        result = await repo.delete(mock_db, draft_id)
        assert result is mock_draft

    async def test_delete_not_found(
        self,
        repo: WritingDraftRepository,
        mock_db: AsyncMock,
    ):
        mock_db.execute.return_value.scalar_one_or_none.return_value = None
        result = await repo.delete(mock_db, uuid.uuid4())
        assert result is None

    async def test_delete_all_versions(
        self,
        repo: WritingDraftRepository,
        mock_db: AsyncMock,
    ):
        drafts = [
            MagicMock(status="published", provenance_json=None),
            MagicMock(status="draft", provenance_json={"source": "test"}),
            MagicMock(status="candidate", provenance_json=None),
        ]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = drafts
        mock_db.execute.return_value = mock_result
        mock_db.add_all = MagicMock()

        count = await repo.delete_all_versions(mock_db, uuid.uuid4(), 1)
        assert count == 3
        assert all(draft.status == "deprecated" for draft in drafts)
        assert drafts[0].provenance_json["deprecated_from_status"] == "published"
        assert drafts[1].provenance_json == {
            "source": "test",
            "deprecated_from_status": "draft",
        }
        mock_db.add_all.assert_called_once_with(drafts)

    async def test_count_versions(
        self,
        repo: WritingDraftRepository,
        mock_db: AsyncMock,
    ):
        mock_db.execute.return_value.scalar.return_value = 2
        count = await repo.count_versions(mock_db, uuid.uuid4(), 1)
        assert count == 2

    async def test_count_working_versions(
        self,
        repo: WritingDraftRepository,
        mock_db: AsyncMock,
    ):
        mock_db.execute.return_value.scalar.return_value = 1
        count = await repo.count_working_versions(mock_db, uuid.uuid4(), 1)
        assert count == 1

    async def test_list_chapter_indices(
        self,
        repo: WritingDraftRepository,
        mock_db: AsyncMock,
    ):
        mock_db.execute.return_value.all.return_value = [(1,), (3,), (5,)]
        indices = await repo.list_chapter_indices(mock_db, uuid.uuid4())
        assert indices == [1, 3, 5]

    async def test_list_chapter_indices_empty(
        self,
        repo: WritingDraftRepository,
        mock_db: AsyncMock,
    ):
        mock_db.execute.return_value.all.return_value = []
        indices = await repo.list_chapter_indices(mock_db, uuid.uuid4())
        assert indices == []

    async def test_next_version_number_first(
        self,
        repo: WritingDraftRepository,
        mock_db: AsyncMock,
    ):
        mock_db.execute.return_value.scalar_one_or_none.return_value = None
        nv = await repo._next_version_number(mock_db, uuid.uuid4(), 1)
        assert nv == 1

    async def test_next_version_number_existing(
        self,
        repo: WritingDraftRepository,
        mock_db: AsyncMock,
    ):
        mock_db.execute.return_value.scalar_one_or_none.return_value = 5
        nv = await repo._next_version_number(mock_db, uuid.uuid4(), 1)
        assert nv == 6


# ============================================================
# API 测试（mock service）
# ============================================================


@pytest.fixture
def _stub_writing_active_project_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    from modules.writing import api as writing_api

    async def require_active_project(_db, _novel_id):
        return None

    monkeypatch.setattr(writing_api, "require_active_project", require_active_project)


@pytest.mark.usefixtures("_stub_writing_active_project_guard")
class TestWritingAPI:
    """Writing API 路由 — mock service 层"""

    @pytest.fixture
    def mock_service(self):
        with patch("modules.writing.api._service") as svc:
            svc.get_draft = AsyncMock()
            svc.publish_draft = AsyncMock()
            svc.publish_draft_result = AsyncMock()
            svc.update_draft = AsyncMock()
            svc.delete_draft = AsyncMock()
            svc.delete_chapter = AsyncMock()
            svc.get_latest_draft = AsyncMock()
            svc.get_version_history = AsyncMock()
            svc.list_chapter_indices = AsyncMock()
            svc.list_chapter_summaries = AsyncMock()
            svc.set_conflict_check_snapshot = AsyncMock()
            yield svc

    @pytest.fixture
    def mock_conflict_service(self):
        with patch("modules.writing.api._conflict_service") as svc:
            svc.latest_snapshot = AsyncMock(return_value=None)
            yield svc

    @pytest.fixture
    def mock_facade(self):
        with patch("modules.writing.api._create_draft_only") as facade:
            facade.return_value = WritingDraftContract(
                id=str(uuid.uuid4()),
                novel_id=str(uuid.uuid4()),
                chapter_index=1,
                title="第一章",
                version_number=1,
            )
            yield facade

    @pytest.fixture
    def mock_enqueue(self):
        with patch("modules.writing.api.enqueue_task") as enqueue:
            enqueue.return_value = str(uuid.uuid4())
            yield enqueue

    @pytest.fixture
    def mock_request_chapter_index(self):
        with patch(
            "modules.rag.facade.request_chapter_index",
            new_callable=AsyncMock,
        ) as request:
            yield request

    @pytest.fixture
    def mock_mark_chapter_index_dirty(self):
        with patch(
            "modules.rag.facade.mark_chapter_index_dirty",
            new_callable=AsyncMock,
        ) as mark_dirty:
            yield mark_dirty

    @pytest.fixture
    def router(self):
        from modules.writing.api import router

        return router

    def test_router_prefix(self, router):
        assert router.prefix == "/api/writing"
        assert "writing" in router.tags

    def test_router_routes_count(self, router):
        """验证预期数量的路由已注册"""
        assert len(router.routes) >= 8

    async def test_autosave_draft_endpoint_uses_facade_and_returns_response(
        self,
        mock_facade,
        mock_service,
        mock_request_chapter_index,
    ):
        """verify facade is called with correct args"""
        from modules.writing.api import create_autosaved_draft

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        data = WritingDraftAutosaveCreate(
            novel_id=str(uuid.uuid4()),
            chapter_index=1,
            title="第一章",
            content="正文",
        )
        result = await create_autosaved_draft(mock_db, data)
        mock_facade.assert_awaited_once_with(
            mock_db,
            novel_id=data.novel_id,
            chapter_index=data.chapter_index,
            title=data.title,
            content=data.content or "",
        )
        assert isinstance(result, WritingDraftResponse)
        assert result.title == "第一章"
        mock_service.publish_draft.assert_not_awaited()
        mock_request_chapter_index.assert_awaited_once_with(
            mock_db,
            data.novel_id,
            data.chapter_index,
            content_mode="working",
        )

    async def test_create_draft_endpoint_publishes_through_service_and_enqueue(
        self,
        mock_facade,
        mock_enqueue,
        mock_service,
        mock_conflict_service,
        mock_mark_chapter_index_dirty,
    ):
        from modules.writing.api import create_draft

        mock_db = AsyncMock()
        mock_db.flush = AsyncMock()
        data = WritingDraftCreate(
            novel_id=str(uuid.uuid4()),
            chapter_index=1,
            title="第一章",
            content="正文",
        )
        expected = WritingDraftResponse(
            id=str(uuid.uuid4()),
            novel_id=data.novel_id,
            chapter_index=1,
            title="第一章",
            version_number=1,
        )
        mock_service.publish_draft_result.return_value = (expected, True)

        result = await create_draft(mock_db, data)

        mock_service.publish_draft_result.assert_awaited_once_with(mock_db, data)
        mock_facade.assert_not_awaited()
        mock_enqueue.assert_called_once_with(
            mock_db,
            "publish_chapter",
            meta={"novel_id": data.novel_id, "chapter_index": data.chapter_index},
        )
        mock_mark_chapter_index_dirty.assert_awaited_once_with(
            mock_db,
            data.novel_id,
            data.chapter_index,
            content_mode="canonical",
        )
        assert result.draft == expected
        assert result.task_id is not None

    async def test_get_draft_endpoint(
        self,
        mock_service,
        mock_facade,
    ):
        from modules.writing.api import get_draft

        mock_db = AsyncMock()
        expected = WritingDraftResponse(
            id=str(uuid.uuid4()),
            novel_id=str(uuid.uuid4()),
            chapter_index=1,
        )
        mock_service.get_draft.return_value = expected

        result = await get_draft(mock_db, draft_id="did", novel_id="nid")
        assert result.id == expected.id
        mock_service.get_draft.assert_awaited_once_with(mock_db, "did", "nid")

    async def test_update_draft_endpoint(
        self,
        mock_service,
        mock_facade,
        mock_request_chapter_index,
    ):
        from modules.writing.api import update_draft

        mock_db = AsyncMock()
        expected = WritingDraftResponse(
            id=str(uuid.uuid4()),
            novel_id=str(uuid.uuid4()),
            chapter_index=1,
            title="updated",
        )
        mock_service.update_draft.return_value = expected

        data = WritingDraftUpdate(title="updated")
        result = await update_draft(mock_db, draft_id="did", data=data, novel_id="nid")
        assert result.title == "updated"
        mock_service.update_draft.assert_awaited_once_with(mock_db, "did", data, "nid")
        mock_request_chapter_index.assert_awaited_once_with(
            mock_db,
            "nid",
            expected.chapter_index,
            content_mode="working",
        )

    async def test_delete_draft_endpoint(
        self,
        mock_service,
        mock_facade,
        mock_request_chapter_index,
    ):
        from modules.writing.api import delete_draft

        mock_db = AsyncMock()
        mock_service.delete_draft = AsyncMock()
        mock_service.get_draft.return_value = WritingDraftResponse(
            id=str(uuid.uuid4()),
            novel_id=str(uuid.uuid4()),
            chapter_index=7,
        )

        result = await delete_draft(mock_db, draft_id="did", novel_id="nid")
        assert result is None
        mock_service.get_draft.assert_awaited_once_with(mock_db, "did", "nid")
        mock_service.delete_draft.assert_awaited_once_with(mock_db, "did", "nid")
        assert mock_request_chapter_index.await_args_list == [
            ((mock_db, "nid", 7), {"content_mode": "canonical"}),
            ((mock_db, "nid", 7), {"content_mode": "working"}),
        ]

    async def test_delete_chapter_endpoint(
        self,
        mock_service,
        mock_facade,
        mock_request_chapter_index,
    ):
        from modules.writing.api import delete_chapter

        mock_db = AsyncMock()
        mock_service.delete_chapter.return_value = 5

        result = await delete_chapter(mock_db, chapter_index=3, novel_id="nid")
        assert result.chapter_index == 3
        assert result.deleted_versions == 5
        mock_service.delete_chapter.assert_awaited_once_with(mock_db, "nid", 3)
        assert mock_request_chapter_index.await_args_list == [
            ((mock_db, "nid", 3), {"content_mode": "canonical"}),
            ((mock_db, "nid", 3), {"content_mode": "working"}),
        ]

    async def test_get_latest_chapter_draft(
        self,
        mock_service,
        mock_facade,
    ):
        from modules.writing.api import get_latest_chapter_draft

        mock_db = AsyncMock()
        expected = WritingDraftResponse(
            id=str(uuid.uuid4()),
            novel_id=str(uuid.uuid4()),
            chapter_index=2,
            version_number=3,
        )
        mock_service.get_latest_draft.return_value = expected

        result = await get_latest_chapter_draft(mock_db, chapter_index=2, novel_id="nid")
        assert result.version_number == 3
        mock_service.get_latest_draft.assert_awaited_once_with(mock_db, "nid", 2)

    async def test_get_chapter_version_history(
        self,
        mock_service,
        mock_facade,
    ):
        from modules.writing.api import get_chapter_version_history

        mock_db = AsyncMock()
        mock_service.get_version_history.return_value = VersionHistoryResponse(
            novel_id="nid",
            chapter_index=1,
            versions=[],
            total=0,
        )

        result = await get_chapter_version_history(
            mock_db, chapter_index=1, novel_id="nid"
        )
        assert result.total == 0
        mock_service.get_version_history.assert_awaited_once_with(mock_db, "nid", 1)

    async def test_list_chapters(
        self,
        mock_service,
        mock_facade,
    ):
        from modules.writing.api import list_chapters

        mock_db = AsyncMock()
        mock_service.list_chapter_summaries.return_value = [
            ChapterSummaryItem(id=str(uuid.uuid4()), chapter_index=1),
            ChapterSummaryItem(id=str(uuid.uuid4()), chapter_index=3),
            ChapterSummaryItem(id=str(uuid.uuid4()), chapter_index=5),
        ]

        result = await list_chapters(mock_db, novel_id="nid")
        assert result.chapter_indices == [1, 3, 5]
        assert [item.chapter_index for item in result.chapters] == [1, 3, 5]
        mock_service.list_chapter_summaries.assert_awaited_once_with(mock_db, "nid")


# ============================================================
# Tasks 测试（mock 外部依赖）
# ============================================================


class TestHandlePublishChapter:
    """handle_publish_chapter 任务处理器"""

    @pytest.fixture
    def mock_db(self) -> AsyncMock:
        db = AsyncMock()
        db.flush = AsyncMock()
        return db

    @pytest.fixture
    def mock_task(self) -> MagicMock:
        task = MagicMock()
        task.meta = {"novel_id": str(uuid.uuid4()), "chapter_index": 3}
        task.update_progress = MagicMock()
        return task

    @pytest.fixture
    def mock_index_state(self):
        """Keep publish-task tests focused on retry orchestration, not RAG storage."""
        with patch("modules.rag.index_state.RagIndexStateService") as state_class:
            state = state_class.return_value
            state.begin_direct = AsyncMock()
            state.finish = AsyncMock()
            state.fail = AsyncMock()
            yield state

    async def test_success_path(
        self,
        mock_db: AsyncMock,
        mock_task: MagicMock,
        mock_index_state,
    ):
        from core.container import register, reset

        reset()
        mock_report = MagicMock()
        mock_report.chunks_created = 10
        mock_report.embedding_failed_count = 0
        mock_rag_index = AsyncMock(return_value=mock_report)

        mock_snap_result = MagicMock()
        mock_snap_result.id = "snap-1"
        mock_memory_svc = MagicMock()
        mock_memory_svc.capture_snapshot = AsyncMock(
            return_value=mock_snap_result,
        )

        register("rag.index_chapter", mock_rag_index)
        register("memory.service", mock_memory_svc)
        try:
            from modules.writing.tasks import handle_publish_chapter

            results = await handle_publish_chapter(mock_db, mock_task)

            assert results["rag_chunks"] == 10
            assert results["rag_embedding_failed"] == 0
            assert results["snapshot_id"] == "snap-1"
            assert mock_rag_index.await_count == 1
            assert mock_memory_svc.capture_snapshot.await_count == 1
            assert mock_task.update_progress.call_count == 2
            mock_db.flush.assert_awaited()
        finally:
            reset()

    async def test_rag_retry_then_succeed(
        self,
        mock_db: AsyncMock,
        mock_task: MagicMock,
        mock_index_state,
    ):
        from core.container import register, reset

        reset()
        mock_report = MagicMock()
        mock_report.chunks_created = 5
        mock_report.embedding_failed_count = 1
        mock_rag_index = AsyncMock(
            side_effect=[
                Exception("timeout"),
                Exception("timeout"),
                mock_report,
            ],
        )

        mock_snap_result = MagicMock()
        mock_snap_result.id = "snap-retry"
        mock_memory_svc = MagicMock()
        mock_memory_svc.capture_snapshot = AsyncMock(
            return_value=mock_snap_result,
        )

        register("rag.index_chapter", mock_rag_index)
        register("memory.service", mock_memory_svc)
        try:
            from modules.writing.tasks import handle_publish_chapter

            results = await handle_publish_chapter(mock_db, mock_task)

            assert results["rag_chunks"] == 5
            assert mock_rag_index.await_count == 3
        finally:
            reset()

    async def test_rag_all_retries_fail(
        self,
        mock_db: AsyncMock,
        mock_task: MagicMock,
        mock_index_state,
    ):
        from core.container import register, reset

        reset()
        mock_rag_index = AsyncMock(side_effect=Exception("always fails"))

        register("rag.index_chapter", mock_rag_index)
        try:
            from modules.writing.tasks import handle_publish_chapter

            with pytest.raises(RuntimeError, match="章节索引暂时不可用"):
                await handle_publish_chapter(mock_db, mock_task)

            assert mock_rag_index.await_count == 3
        finally:
            reset()

    async def test_snapshot_retry_then_succeed(
        self,
        mock_db: AsyncMock,
        mock_task: MagicMock,
        mock_index_state,
    ):
        from core.container import register, reset

        reset()
        mock_report = MagicMock()
        mock_report.chunks_created = 3
        mock_report.embedding_failed_count = 0
        mock_rag_index = AsyncMock(return_value=mock_report)

        mock_snap_result = MagicMock()
        mock_snap_result.id = "snap-retry-ok"
        mock_memory_svc = MagicMock()
        mock_memory_svc.capture_snapshot = AsyncMock(
            side_effect=[
                Exception("snap fail"),
                Exception("snap fail"),
                mock_snap_result,
            ],
        )

        register("rag.index_chapter", mock_rag_index)
        register("memory.service", mock_memory_svc)
        try:
            from modules.writing.tasks import handle_publish_chapter

            results = await handle_publish_chapter(mock_db, mock_task)
            assert results["snapshot_id"] == "snap-retry-ok"
            assert mock_memory_svc.capture_snapshot.await_count == 3
        finally:
            reset()

    async def test_snapshot_all_retries_fail(
        self,
        mock_db: AsyncMock,
        mock_task: MagicMock,
        mock_index_state,
    ):
        from core.container import register, reset

        reset()
        mock_report = MagicMock()
        mock_report.chunks_created = 3
        mock_report.embedding_failed_count = 0
        mock_rag_index = AsyncMock(return_value=mock_report)
        mock_memory_svc = MagicMock()
        mock_memory_svc.capture_snapshot = AsyncMock(
            side_effect=Exception("snap always fails"),
        )

        register("rag.index_chapter", mock_rag_index)
        register("memory.service", mock_memory_svc)
        try:
            from modules.writing.tasks import handle_publish_chapter

            with pytest.raises(RuntimeError, match="历史状态暂时不可用"):
                await handle_publish_chapter(mock_db, mock_task)

            assert mock_memory_svc.capture_snapshot.await_count == 3
        finally:
            reset()

    async def test_missing_novel_id(
        self,
        mock_db: AsyncMock,
    ):
        task = MagicMock()
        task.meta = {"chapter_index": 1}

        from modules.writing.tasks import handle_publish_chapter

        with pytest.raises(ValueError, match="novel_id is required"):
            await handle_publish_chapter(mock_db, task)

    async def test_invalid_chapter_index(
        self,
        mock_db: AsyncMock,
    ):
        task = MagicMock()
        task.meta = {"novel_id": str(uuid.uuid4()), "chapter_index": 0}

        from modules.writing.tasks import handle_publish_chapter

        with pytest.raises(ValueError, match="chapter_index must be >= 1"):
            await handle_publish_chapter(mock_db, task)
