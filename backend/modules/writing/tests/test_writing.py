"""
Writing 模块测试

测试草稿 CRUD、版本管理、facade 和边界情况。
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.tasks.models import AsyncTask
from modules.outline.repositories import SceneRepository
from modules.outline.schemas import SceneCreate
from modules.writing.contracts import WritingDraftContract
from modules.writing.facade import (
    create_draft,
    get_draft,
    get_latest_draft_for_chapter,
    list_chapter_indices,
)
from modules.writing.repositories import WritingDraftRepository
from modules.writing.schemas import (
    WritingDraftCreate,
    WritingDraftUpdate,
)
from modules.writing.services import WritingDraftService
from tests.conftest import test_project_id  # noqa: F401

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
        assert draft.status == "draft"

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
        latest = await repo.get_latest_by_chapter(
            db_session, uuid.uuid4(), chapter_index=1
        )
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
        await repo.create(db_session, sample_draft_data)
        v2 = await repo.create(
            db_session,
            WritingDraftCreate(
                novel_id=sample_draft_data.novel_id,
                chapter_index=1,
                title="v2",
                content="v2",
            ),
        )
        await repo.create(
            db_session,
            WritingDraftCreate(
                novel_id=sample_draft_data.novel_id,
                chapter_index=1,
                title="v3",
                content="v3",
            ),
        )
        # Delete v2, v3 should become v2
        deleted = await repo.delete(db_session, v2.id)
        assert deleted is not None
        await repo.renumber_versions_after_delete(
            db_session,
            novel_id,
            1,
            deleted.version_number,
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
        await repo.create(
            db_session,
            WritingDraftCreate(
                novel_id=sample_draft_data.novel_id,
                chapter_index=1,
                title="v2",
                content="v2",
            ),
        )
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
                novel_id=novel_id,
                chapter_index=ch,
                title=f"第{ch}章",
                content="内容",
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
        fetched = await service.get_draft(
            db_session, created.id, sample_draft_data.novel_id
        )
        assert fetched.id == created.id

    @pytest.mark.asyncio
    async def test_get_draft_not_found(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        with pytest.raises(HTTPException) as exc_info:
            await service.get_draft(
                db_session, str(uuid.uuid4()), sample_draft_data.novel_id
            )
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
            db_session,
            created.id,
            update_data,
            sample_draft_data.novel_id,
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
            await service.update_draft(
                db_session, str(uuid.uuid4()), update_data, sample_draft_data.novel_id
            )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_update_draft_conflict_detection(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        v1 = await service.create_draft(db_session, sample_draft_data)
        v2_data = WritingDraftCreate(
            novel_id=sample_draft_data.novel_id,
            chapter_index=sample_draft_data.chapter_index,
            title="v2",
            content="v2 content",
        )
        await service.create_draft(db_session, v2_data)
        # 期望版本落后于章节最新版本时触发 409
        conflict_update = WritingDraftUpdate(
            title="conflict",
            expected_version=1,
        )
        with pytest.raises(HTTPException) as exc_info:
            await service.update_draft(
                db_session,
                v1.id,
                conflict_update,
                sample_draft_data.novel_id,
            )
        assert exc_info.value.status_code == 409
        assert "v2" in exc_info.value.detail or "2" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_update_draft_no_conflict_when_expected_version_matches(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        v1 = await service.create_draft(db_session, sample_draft_data)
        matched_update = WritingDraftUpdate(
            title="matched",
            expected_version=1,
        )
        updated = await service.update_draft(
            db_session,
            v1.id,
            matched_update,
            sample_draft_data.novel_id,
        )
        assert updated.title == "matched"
        assert updated.version_number == 1

    @pytest.mark.asyncio
    async def test_update_draft_no_conflict_when_no_expected_version(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        v1 = await service.create_draft(db_session, sample_draft_data)
        v2_data = WritingDraftCreate(
            novel_id=sample_draft_data.novel_id,
            chapter_index=sample_draft_data.chapter_index,
            title="v2",
            content="v2 content",
        )
        await service.create_draft(db_session, v2_data)
        no_check_update = WritingDraftUpdate(title="no check")
        updated = await service.update_draft(
            db_session,
            v1.id,
            no_check_update,
            sample_draft_data.novel_id,
        )
        assert updated.title == "no check"

    @pytest.mark.asyncio
    async def test_delete_draft(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        await service.create_draft(db_session, sample_draft_data)
        v2 = await service.create_draft(
            db_session,
            WritingDraftCreate(
                novel_id=sample_draft_data.novel_id,
                chapter_index=1,
                title="v2",
                content="v2",
            ),
        )
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
            await service.delete_draft(
                db_session, str(uuid.uuid4()), sample_draft_data.novel_id
            )
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
        await service.create_draft(
            db_session,
            WritingDraftCreate(
                novel_id=sample_draft_data.novel_id,
                chapter_index=1,
                title="第二版",
            ),
        )
        await service.create_draft(
            db_session,
            WritingDraftCreate(
                novel_id=sample_draft_data.novel_id,
                chapter_index=1,
                title="第三版",
            ),
        )
        history = await service.get_version_history(
            db_session, sample_draft_data.novel_id, 1
        )
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
            db_session,
            sample_draft_data.novel_id,
            1,
        )
        assert contract is not None

    @pytest.mark.asyncio
    async def test_get_latest_draft_contract_not_found(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
    ) -> None:
        contract = await service.get_latest_draft_contract(
            db_session, str(uuid.uuid4()), 1
        )
        assert contract is None

    @pytest.mark.asyncio
    async def test_list_chapter_indices(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
    ) -> None:
        novel_id = str(uuid.uuid4())
        for ch in (1, 1, 3, 5):
            await service.create_draft(
                db_session,
                WritingDraftCreate(
                    novel_id=novel_id,
                    chapter_index=ch,
                    title=f"第{ch}章",
                    content="内容",
                ),
            )
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
            db_session,
            sample_draft_data.novel_id,
            1,
        )
        assert count >= 1


@pytest.mark.asyncio
async def test_split_chapter_at_offset_creates_new_chapter_without_publish_task(
    service: WritingDraftService,
    db_session: AsyncSession,
) -> None:
    novel_id = str(uuid.uuid4())
    original = await service.create_draft(
        db_session,
        WritingDraftCreate(
            novel_id=novel_id,
            chapter_index=5,
            title="第五章",
            content="前半段内容。后半段内容。",
        ),
    )

    result = await service.split_chapter_at_offset(
        db_session,
        novel_id=novel_id,
        chapter_index=5,
        split_pos=5,
        source_scene_id=None,
    )

    tasks_result = await db_session.execute(select(AsyncTask))
    assert len(tasks_result.scalars().all()) == 0

    assert result.source_chapter_index == 5
    assert result.new_chapter_index == 6
    assert result.source_draft.content == "前半段内容"
    assert result.new_draft.content == "。后半段内容。"
    assert result.source_draft.version_number == original.version_number
    assert result.new_draft.version_number == 1


@pytest.mark.asyncio
async def test_split_chapter_shifts_later_chapters(
    service: WritingDraftService,
    db_session: AsyncSession,
) -> None:
    novel_id = str(uuid.uuid4())
    await service.create_draft(
        db_session,
        WritingDraftCreate(
            novel_id=novel_id, chapter_index=5, title="第五章", content="甲乙丙丁"
        ),
    )
    await service.create_draft(
        db_session,
        WritingDraftCreate(
            novel_id=novel_id, chapter_index=6, title="第六章", content="原第六章"
        ),
    )

    result = await service.split_chapter_at_offset(
        db_session,
        novel_id=novel_id,
        chapter_index=5,
        split_pos=2,
        source_scene_id=None,
    )

    assert result.new_chapter_index == 6
    indices = await service.list_chapter_indices(db_session, novel_id)
    assert indices == [5, 6, 7]
    shifted = await service.get_latest_draft(db_session, novel_id, 7)
    assert shifted.content == "原第六章"


@pytest.mark.asyncio
async def test_split_chapter_at_offset_syncs_scene_chunks(
    service: WritingDraftService,
    db_session: AsyncSession,
) -> None:
    """跨模块测试：切分章节时同步切分 source Scene 的 chunk 并新建 Scene"""
    novel_id = str(uuid.uuid4())
    await service.create_draft(
        db_session,
        WritingDraftCreate(
            novel_id=novel_id,
            chapter_index=1,
            title="第一章",
            content="一二三四五六七八九十",
        ),
    )

    repo = SceneRepository()
    nid = uuid.UUID(hex=novel_id)
    source_scene = await repo.create(
        db_session,
        nid,
        SceneCreate(
            scene_index=0,
            title="Source Scene",
            chapter_ids=["1"],
            scene_chunks=[
                {"chapter_id": "1", "chapter_index": 1, "start_pos": 0, "end_pos": 10}
            ],
            status="draft",
        ),
    )
    await db_session.flush()

    result = await service.split_chapter_at_offset(
        db_session,
        novel_id=novel_id,
        chapter_index=1,
        split_pos=4,
        source_scene_id=str(source_scene.id),
    )

    assert result.source_chapter_index == 1
    assert result.new_chapter_index == 2
    assert result.source_draft.content == "一二三四"
    assert result.new_draft.content == "五六七八九十"
    assert len(result.scenes) >= 2

    source_id = str(source_scene.id)
    source_item = next(item for item in result.scenes if item.id == source_id)
    assert source_item.scene_chunks[0]["end_pos"] == 4

    new_item = next(item for item in result.scenes if item.id != source_id)
    assert new_item.chapter_ids == ["2"]
    assert new_item.scene_chunks[0]["chapter_id"] == "2"
    assert new_item.scene_chunks[0]["chapter_index"] == 2
    assert new_item.scene_index == source_item.scene_index + 1


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
        draft, task_id = await create_draft(
            db_session,
            sample_draft_data.novel_id,
            sample_draft_data.chapter_index,
            sample_draft_data.title,
            sample_draft_data.content or "",
        )
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
        draft, _ = await create_draft(
            db_session,
            sample_draft_data.novel_id,
            sample_draft_data.chapter_index,
            sample_draft_data.title,
            sample_draft_data.content or "",
        )
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
        await create_draft(
            db_session,
            sample_draft_data.novel_id,
            sample_draft_data.chapter_index,
            sample_draft_data.title,
            sample_draft_data.content or "",
        )
        contract = await get_latest_draft_for_chapter(
            db_session,
            sample_draft_data.novel_id,
            1,
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
            await create_draft(db_session, novel_id, ch, f"第{ch}章", "内容")
        indices = await list_chapter_indices(db_session, novel_id)
        assert indices == [1, 3, 5]

    @pytest.mark.asyncio
    async def test_list_chapter_indices_empty(
        self,
        db_session: AsyncSession,
    ) -> None:
        indices = await list_chapter_indices(db_session, str(uuid.uuid4()))
        assert indices == []


# ============================================================
# API 路由测试
# ============================================================


class TestWritingSplitApi:
    @pytest.mark.asyncio
    async def test_split_chapter_endpoint(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """POST /api/writing/chapters/{chapter_index}/split 返回切分结果"""
        novel_id = str(uuid.uuid4())
        service = WritingDraftService()
        await service.create_draft(
            db_session,
            WritingDraftCreate(
                novel_id=novel_id,
                chapter_index=1,
                title="第一章",
                content="abcdefghij",
            ),
        )

        repo = SceneRepository()
        scene = await repo.create(
            db_session,
            uuid.UUID(hex=novel_id),
            SceneCreate(
                scene_index=0,
                title="Scene 1",
                chapter_ids=["1"],
                scene_chunks=[
                {"chapter_id": "1", "chapter_index": 1, "start_pos": 0, "end_pos": 10}
            ],
                status="draft",
            ),
        )
        await db_session.flush()

        response = await async_client.post(
            f"/api/writing/chapters/1/split?novel_id={novel_id}",
            json={"split_pos": 4, "source_scene_id": str(scene.id)},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["source_chapter_index"] == 1
        assert data["new_chapter_index"] == 2
        assert data["source_draft"]["content"] == "abcd"
        assert data["new_draft"]["content"] == "efghij"
        assert len(data["scenes"]) >= 2


class TestWritingPublishApi:
    @pytest.mark.asyncio
    async def test_publish_draft_increments_version_and_enqueues_task(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """POST /api/writing/drafts 发布时递增版本并入队任务"""
        novel_id = str(uuid.uuid4())

        response1 = await async_client.post(
            "/api/writing/drafts",
            json={
                "novel_id": novel_id,
                "chapter_index": 1,
                "title": "第一章",
                "content": "第一版内容",
            },
        )
        assert response1.status_code == 201
        data1 = response1.json()
        assert data1["draft"]["version_number"] == 1
        task_id_1 = data1["task_id"]
        assert task_id_1 is not None

        response2 = await async_client.post(
            "/api/writing/drafts",
            json={
                "novel_id": novel_id,
                "chapter_index": 1,
                "title": "第一章（修订）",
                "content": "第二版内容",
            },
        )
        assert response2.status_code == 201
        data2 = response2.json()
        assert data2["draft"]["version_number"] == 2
        task_id_2 = data2["task_id"]
        assert task_id_2 is not None
        assert task_id_2 != task_id_1

        task = await db_session.get(AsyncTask, uuid.UUID(hex=task_id_2))
        assert task is not None
        assert task.task_type == "publish_chapter"
        assert task.meta.get("novel_id") == novel_id
        assert task.meta.get("chapter_index") == 1

    @pytest.mark.asyncio
    async def test_update_draft_conflict_returns_409(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        """PUT /api/writing/drafts 在 expected_version 不匹配时返回 409"""
        novel_id = str(uuid.uuid4())
        service = WritingDraftService()

        v1 = await service.create_draft(
            db_session,
            WritingDraftCreate(
                novel_id=novel_id,
                chapter_index=1,
                title="第一章",
                content="第一版",
            ),
        )
        await service.create_draft(
            db_session,
            WritingDraftCreate(
                novel_id=novel_id,
                chapter_index=1,
                title="第一章",
                content="第二版",
            ),
        )

        response = await async_client.put(
            f"/api/writing/drafts/{v1.id}?novel_id={novel_id}",
            json={"title": "conflict", "expected_version": 1},
        )
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert "v2" in detail or "2" in detail


@pytest.mark.asyncio
async def test_publish_creates_rag_chunks(
    db_session: AsyncSession,
    test_project_id: str,  # noqa: F811
):
    """发布章节后应创建 RAG chunk，重新发布时应替换旧 chunk。"""
    import uuid as _uuid
    from unittest.mock import AsyncMock, patch

    from infrastructure.tasks.models import AsyncTask
    from modules.rag.repositories import RagChunkRepository
    from modules.writing.facade import create_draft
    from modules.writing.tasks import handle_publish_chapter

    rag_repo = RagChunkRepository()
    nid_uuid = uuid.UUID(hex=test_project_id)
    embed_exc = Exception("embedding down")

    with patch("infrastructure.llm.client.LLMClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.generate_embedding = AsyncMock(side_effect=embed_exc)
        mock_client_cls.return_value = mock_client

        draft, task_id = await create_draft(
            db_session,
            test_project_id,
            1,
            "第一章",
            "周明瑞从梦中醒来，发现一切都变得陌生。" * 20,
        )
        assert task_id is not None

        task = await db_session.get(AsyncTask, _uuid.UUID(hex=task_id))
        assert task is not None

        result = await handle_publish_chapter(db_session, task)
        assert result["rag_chunks"] > 0

    first_chunks = await rag_repo.find_by_chapter(db_session, nid_uuid, 1)
    assert len(first_chunks) == result["rag_chunks"]
    first_ids = {str(c.id) for c in first_chunks}

    # 重新发布同一章节
    with patch("infrastructure.llm.client.LLMClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.generate_embedding = AsyncMock(side_effect=embed_exc)
        mock_client_cls.return_value = mock_client

        _, task_id_2 = await create_draft(
            db_session,
            test_project_id,
            1,
            "第一章（修订）",
            "周明瑞从梦中醒来，发现世界已经完全不同。" * 20,
        )
        task_2 = await db_session.get(AsyncTask, _uuid.UUID(hex=task_id_2))
        result_2 = await handle_publish_chapter(db_session, task_2)
        assert result_2["rag_chunks"] > 0

    second_chunks = await rag_repo.find_by_chapter(db_session, nid_uuid, 1)
    second_ids = {str(c.id) for c in second_chunks}
    assert first_ids.isdisjoint(second_ids), "重新发布后旧 chunk 应被替换"
