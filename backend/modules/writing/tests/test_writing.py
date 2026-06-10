"""
Writing 模块测试

测试草稿 CRUD、版本管理、facade 和边界情况。
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from modules.writing.facade import (
    create_draft,
    get_draft,
    get_latest_draft_for_chapter,
    list_chapter_indices,
)
from modules.writing.repositories import WritingDraftRepository
from modules.writing.contracts import WritingDraftContract
from modules.writing.schemas import (
    DraftListItem,
    WritingDraftCreate,
    WritingDraftUpdate,
)
from modules.writing.services import WritingDraftService


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def repo() -> WritingDraftRepository:
    return WritingDraftRepository()


@pytest.fixture
def service() -> WritingDraftService:
    return WritingDraftService()


@pytest.fixture
def sample_draft_data() -> WritingDraftCreate:
    return WritingDraftCreate(
        novel_id=str(uuid.uuid4()),
        chapter_index=1,
        title="第一章：开端",
        content="这是一个测试正文的段落。",
    )


@pytest.fixture
def update_data() -> WritingDraftUpdate:
    return WritingDraftUpdate(
        title="更新后的标题",
        content="更新后的正文内容。",
    )


# ============================================================
# Repository 测试
# ============================================================

class TestWritingDraftRepository:

    @pytest.mark.asyncio
    async def test_create(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        draft = await repo.create(db_session, sample_draft_data)
        assert draft.id is not None
        assert draft.novel_id is not None
        assert draft.chapter_index == 1
        assert draft.title == "第一章：开端"
        assert draft.content == "这是一个测试正文的段落。"
        assert draft.version_number == 1

    @pytest.mark.asyncio
    async def test_create_auto_increment_version(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        v1 = await repo.create(db_session, sample_draft_data)
        assert v1.version_number == 1

        v2_data = WritingDraftCreate(
            novel_id=sample_draft_data.novel_id,
            chapter_index=sample_draft_data.chapter_index,
            title="第二章",
            content="第二版本内容",
        )
        v2 = await repo.create(db_session, v2_data)
        assert v2.version_number == 2

        v3_data = WritingDraftCreate(
            novel_id=sample_draft_data.novel_id,
            chapter_index=sample_draft_data.chapter_index,
            title="第三版",
            content="第三版本内容",
        )
        v3 = await repo.create(db_session, v3_data)
        assert v3.version_number == 3

    @pytest.mark.asyncio
    async def test_create_different_chapters_independent_versions(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        novel_id = sample_draft_data.novel_id
        await repo.create(db_session, sample_draft_data)

        ch1_v2 = WritingDraftCreate(
            novel_id=novel_id,
            chapter_index=1,
            title="第一章第二版",
        )
        v2 = await repo.create(db_session, ch1_v2)
        assert v2.version_number == 2

        ch2_v1 = WritingDraftCreate(
            novel_id=novel_id,
            chapter_index=2,
            title="第二章",
        )
        v1_ch2 = await repo.create(db_session, ch2_v1)
        assert v1_ch2.version_number == 1

    @pytest.mark.asyncio
    async def test_get(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        created = await repo.create(db_session, sample_draft_data)
        fetched = await repo.get(db_session, created.id)
        assert fetched is not None
        assert fetched.id == created.id

    @pytest.mark.asyncio
    async def test_get_not_found(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
    ) -> None:
        fetched = await repo.get(db_session, uuid.uuid4())
        assert fetched is None

    @pytest.mark.asyncio
    async def test_get_latest_by_chapter(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        novel_id = uuid.UUID(hex=sample_draft_data.novel_id)
        await repo.create(db_session, sample_draft_data)
        v2_data = WritingDraftCreate(
            novel_id=sample_draft_data.novel_id,
            chapter_index=1,
            title="最新版本",
            content="最新内容",
        )
        await repo.create(db_session, v2_data)

        latest = await repo.get_latest_by_chapter(db_session, novel_id, chapter_index=1)
        assert latest is not None
        assert latest.version_number == 2

    @pytest.mark.asyncio
    async def test_get_latest_by_chapter_no_draft(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
    ) -> None:
        latest = await repo.get_latest_by_chapter(db_session, uuid.uuid4(), chapter_index=1)
        assert latest is None

    @pytest.mark.asyncio
    async def test_get_version_history(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        novel_id = uuid.UUID(hex=sample_draft_data.novel_id)
        await repo.create(db_session, sample_draft_data)
        v2_data = WritingDraftCreate(
            novel_id=sample_draft_data.novel_id,
            chapter_index=1,
            title="第二版",
        )
        await repo.create(db_session, v2_data)

        versions = await repo.get_version_history(db_session, novel_id, chapter_index=1)
        assert len(versions) == 2
        assert versions[0].version_number == 2
        assert versions[1].version_number == 1

    @pytest.mark.asyncio
    async def test_update(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
        update_data: WritingDraftUpdate,
    ) -> None:
        created = await repo.create(db_session, sample_draft_data)
        updated = await repo.update(db_session, created.id, update_data)
        assert updated is not None
        assert updated.title == "更新后的标题"
        assert updated.content == "更新后的正文内容。"
        assert updated.version_number == 1

    @pytest.mark.asyncio
    async def test_update_partial(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        created = await repo.create(db_session, sample_draft_data)
        partial = WritingDraftUpdate(title="仅更新标题")
        updated = await repo.update(db_session, created.id, partial)
        assert updated is not None
        assert updated.title == "仅更新标题"
        assert updated.content == "这是一个测试正文的段落。"

    @pytest.mark.asyncio
    async def test_update_not_found(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
        update_data: WritingDraftUpdate,
    ) -> None:
        updated = await repo.update(db_session, uuid.uuid4(), update_data)
        assert updated is None

    @pytest.mark.asyncio
    async def test_delete(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        created = await repo.create(db_session, sample_draft_data)
        # 需要至少 2 个版本才能删
        v2_data = WritingDraftCreate(
            novel_id=sample_draft_data.novel_id,
            chapter_index=1,
            title="第二版",
        )
        await repo.create(db_session, v2_data)

        deleted = await repo.delete(db_session, created.id)
        assert deleted is not None
        fetched = await repo.get(db_session, created.id)
        assert fetched is None

    @pytest.mark.asyncio
    async def test_delete_last_version_allowed_in_repo(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        """Repository 层不检查"至少保留 1 个版本"，该规则在 Service 层处理"""
        created = await repo.create(db_session, sample_draft_data)
        deleted = await repo.delete(db_session, created.id)
        assert deleted is not None

    @pytest.mark.asyncio
    async def test_delete_renumbers_versions(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        novel_id = uuid.UUID(hex=sample_draft_data.novel_id)
        v1 = await repo.create(db_session, sample_draft_data)
        v2 = await repo.create(db_session, WritingDraftCreate(
            novel_id=sample_draft_data.novel_id, chapter_index=1,
            title="v2", content="v2",
        ))
        v3 = await repo.create(db_session, WritingDraftCreate(
            novel_id=sample_draft_data.novel_id, chapter_index=1,
            title="v3", content="v3",
        ))
        # Delete v2, v3 should become v2
        deleted = await repo.delete(db_session, v2.id)
        assert deleted is not None
        await repo.renumber_versions_after_delete(
            db_session, novel_id, 1, deleted.version_number,
        )
        versions = await repo.get_version_history(db_session, novel_id, chapter_index=1)
        assert len(versions) == 2
        version_numbers = sorted([v.version_number for v in versions])
        assert version_numbers == [1, 2]

    @pytest.mark.asyncio
    async def test_delete_not_found(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
    ) -> None:
        deleted = await repo.delete(db_session, uuid.uuid4())
        assert deleted is None

    @pytest.mark.asyncio
    async def test_delete_all_versions(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        novel_id = uuid.UUID(hex=sample_draft_data.novel_id)
        await repo.create(db_session, sample_draft_data)
        v2 = await repo.create(db_session, WritingDraftCreate(
            novel_id=sample_draft_data.novel_id, chapter_index=1,
            title="v2", content="v2",
        ))
        count = await repo.delete_all_versions(db_session, novel_id, 1)
        assert count == 2

    @pytest.mark.asyncio
    async def test_list_chapter_indices(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
    ) -> None:
        novel_id = str(uuid.uuid4())
        nid = uuid.UUID(hex=novel_id)
        for ch in (1, 1, 3, 5):
            data = WritingDraftCreate(
                novel_id=novel_id, chapter_index=ch,
                title=f"第{ch}章", content="内容",
            )
            await repo.create(db_session, data)
        indices = await repo.list_chapter_indices(db_session, nid)
        assert indices == [1, 3, 5]

    @pytest.mark.asyncio
    async def test_list_chapter_indices_empty(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
    ) -> None:
        indices = await repo.list_chapter_indices(db_session, uuid.uuid4())
        assert indices == []


# ============================================================
# Service 测试
# ============================================================

class TestWritingDraftService:

    @pytest.mark.asyncio
    async def test_create_draft(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        resp = await service.create_draft(db_session, sample_draft_data)
        assert resp.id is not None
        assert resp.novel_id == sample_draft_data.novel_id
        assert resp.chapter_index == 1
        assert resp.title == "第一章：开端"
        assert resp.version_number == 1

    @pytest.mark.asyncio
    async def test_get_draft(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        created = await service.create_draft(db_session, sample_draft_data)
        fetched = await service.get_draft(db_session, created.id, sample_draft_data.novel_id)
        assert fetched.id == created.id

    @pytest.mark.asyncio
    async def test_get_draft_not_found(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await service.get_draft(db_session, str(uuid.uuid4()), sample_draft_data.novel_id)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_update_draft(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
        update_data: WritingDraftUpdate,
    ) -> None:
        created = await service.create_draft(db_session, sample_draft_data)
        updated = await service.update_draft(
            db_session, created.id, update_data, sample_draft_data.novel_id,
        )
        assert updated.title == "更新后的标题"

    @pytest.mark.asyncio
    async def test_update_draft_not_found(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
        update_data: WritingDraftUpdate,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await service.update_draft(db_session, str(uuid.uuid4()), update_data, sample_draft_data.novel_id)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_draft(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        await service.create_draft(db_session, sample_draft_data)
        v2 = await service.create_draft(db_session, WritingDraftCreate(
            novel_id=sample_draft_data.novel_id, chapter_index=1,
            title="v2", content="v2",
        ))
        await service.delete_draft(db_session, v2.id, sample_draft_data.novel_id)

    @pytest.mark.asyncio
    async def test_delete_draft_last_version_rejected(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        created = await service.create_draft(db_session, sample_draft_data)
        with pytest.raises(HTTPException) as exc_info:
            await service.delete_draft(db_session, created.id, sample_draft_data.novel_id)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_delete_draft_not_found(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await service.delete_draft(db_session, str(uuid.uuid4()), sample_draft_data.novel_id)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_latest_draft(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        await service.create_draft(db_session, sample_draft_data)
        v2 = WritingDraftCreate(
            novel_id=sample_draft_data.novel_id,
            chapter_index=1,
            title="最新版本",
            content="最新正文",
        )
        await service.create_draft(db_session, v2)
        latest = await service.get_latest_draft(db_session, sample_draft_data.novel_id, 1)
        assert latest.version_number == 2

    @pytest.mark.asyncio
    async def test_get_latest_draft_not_found(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
    ) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await service.get_latest_draft(db_session, str(uuid.uuid4()), 1)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_version_history(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        await service.create_draft(db_session, sample_draft_data)
        await service.create_draft(db_session, WritingDraftCreate(
            novel_id=sample_draft_data.novel_id, chapter_index=1, title="第二版",
        ))
        await service.create_draft(db_session, WritingDraftCreate(
            novel_id=sample_draft_data.novel_id, chapter_index=1, title="第三版",
        ))
        history = await service.get_version_history(db_session, sample_draft_data.novel_id, 1)
        assert history.total == 3
        assert history.versions[0].version_number == 3

    @pytest.mark.asyncio
    async def test_get_version_history_empty(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
    ) -> None:
        history = await service.get_version_history(db_session, str(uuid.uuid4()), 1)
        assert history.total == 0

    @pytest.mark.asyncio
    async def test_invalid_uuid(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await service.get_draft(db_session, "not-a-uuid", sample_draft_data.novel_id)
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_get_draft_contract(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        created = await service.create_draft(db_session, sample_draft_data)
        contract = await service.get_draft_contract(db_session, created.id)
        assert contract is not None
        assert isinstance(contract, WritingDraftContract)
        assert contract.novel_id == sample_draft_data.novel_id
        assert contract.chapter_index == 1
        assert contract.title == "第一章：开端"

    @pytest.mark.asyncio
    async def test_get_draft_contract_not_found(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
    ) -> None:
        contract = await service.get_draft_contract(db_session, str(uuid.uuid4()))
        assert contract is None

    @pytest.mark.asyncio
    async def test_get_latest_draft_contract(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        await service.create_draft(db_session, sample_draft_data)
        contract = await service.get_latest_draft_contract(
            db_session, sample_draft_data.novel_id, 1,
        )
        assert contract is not None

    @pytest.mark.asyncio
    async def test_get_latest_draft_contract_not_found(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
    ) -> None:
        contract = await service.get_latest_draft_contract(db_session, str(uuid.uuid4()), 1)
        assert contract is None

    @pytest.mark.asyncio
    async def test_list_chapter_indices(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
    ) -> None:
        novel_id = str(uuid.uuid4())
        for ch in (1, 1, 3, 5):
            await service.create_draft(db_session, WritingDraftCreate(
                novel_id=novel_id, chapter_index=ch,
                title=f"第{ch}章", content="内容",
            ))
        indices = await service.list_chapter_indices(db_session, novel_id)
        assert indices == [1, 3, 5]

    @pytest.mark.asyncio
    async def test_list_chapter_indices_empty(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
    ) -> None:
        indices = await service.list_chapter_indices(db_session, str(uuid.uuid4()))
        assert indices == []

    @pytest.mark.asyncio
    async def test_delete_chapter(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        await service.create_draft(db_session, sample_draft_data)
        count = await service.delete_chapter(
            db_session, sample_draft_data.novel_id, 1,
        )
        assert count >= 1


# ============================================================
# Facade 测试
# ============================================================

class TestWritingFacade:

    @pytest.mark.asyncio
    async def test_create_draft(
        self,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        draft, task_id = await create_draft(db_session, sample_draft_data)
        assert draft.id is not None
        assert task_id is not None  # 发布任务也应创建
        assert draft.title == "第一章：开端"
        assert draft.chapter_index == 1

    @pytest.mark.asyncio
    async def test_get_draft(
        self,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        draft, _ = await create_draft(db_session, sample_draft_data)
        contract = await get_draft(db_session, draft.id)
        assert contract is not None
        assert isinstance(contract, WritingDraftContract)
        assert contract.novel_id == sample_draft_data.novel_id

    @pytest.mark.asyncio
    async def test_get_draft_not_found(
        self,
        db_session: AsyncSession,
    ) -> None:
        contract = await get_draft(db_session, str(uuid.uuid4()))
        assert contract is None

    @pytest.mark.asyncio
    async def test_get_latest_draft_for_chapter(
        self,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        await create_draft(db_session, sample_draft_data)
        contract = await get_latest_draft_for_chapter(
            db_session, sample_draft_data.novel_id, 1,
        )
        assert contract is not None

    @pytest.mark.asyncio
    async def test_get_latest_draft_for_chapter_not_found(
        self,
        db_session: AsyncSession,
    ) -> None:
        contract = await get_latest_draft_for_chapter(db_session, str(uuid.uuid4()), 1)
        assert contract is None

    @pytest.mark.asyncio
    async def test_list_chapter_indices(
        self,
        db_session: AsyncSession,
    ) -> None:
        novel_id = str(uuid.uuid4())
        for ch in (1, 1, 3, 5):
            await create_draft(db_session, WritingDraftCreate(
                novel_id=novel_id, chapter_index=ch,
                title=f"第{ch}章", content="内容",
            ))
        indices = await list_chapter_indices(db_session, novel_id)
        assert indices == [1, 3, 5]

    @pytest.mark.asyncio
    async def test_list_chapter_indices_empty(
        self,
        db_session: AsyncSession,
    ) -> None:
        indices = await list_chapter_indices(db_session, str(uuid.uuid4()))
        assert indices == []
