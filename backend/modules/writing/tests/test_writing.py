"""
Writing 模块测试

测试草稿 CRUD、版本管理、facade 和边界情况。
使用 pytest-asyncio 测试异步数据库操作。
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from modules.writing.facade import get_draft, get_latest_draft_for_chapter, list_chapter_indices
from modules.writing.repositories import WritingDraftRepository
from modules.writing.contracts import WritingDraftContract
from modules.writing.schemas import (
    DraftListItem,
    WritingDraftCreate,
    WritingDraftUpdate,
)
from modules.writing.services import WritingDraftService, WritingAnalysisService


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
    """测试数据访问层"""

    @pytest.mark.asyncio
    async def test_create(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        """测试创建草稿"""
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
        """测试版本号自动递增"""
        # 创建第一个版本
        v1 = await repo.create(db_session, sample_draft_data)
        assert v1.version_number == 1

        # 创建第二个版本
        v2_data = WritingDraftCreate(
            novel_id=sample_draft_data.novel_id,
            chapter_index=sample_draft_data.chapter_index,
            title="第二章",
            content="第二版本内容",
        )
        v2 = await repo.create(db_session, v2_data)
        assert v2.version_number == 2

        # 创建第三个版本
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
        """测试不同章节版本号独立"""
        novel_id = sample_draft_data.novel_id

        # 第一章版本 1
        await repo.create(db_session, sample_draft_data)

        # 第一章版本 2
        ch1_v2 = WritingDraftCreate(
            novel_id=novel_id,
            chapter_index=1,
            title="第一章第二版",
        )
        v2 = await repo.create(db_session, ch1_v2)
        assert v2.version_number == 2

        # 第二章版本 1（应从 1 开始）
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
        """测试根据 ID 获取草稿"""
        created = await repo.create(db_session, sample_draft_data)
        fetched = await repo.get(db_session, created.id)
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.title == "第一章：开端"

    @pytest.mark.asyncio
    async def test_get_not_found(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
    ) -> None:
        """测试获取不存在的草稿"""
        fake_id = uuid.uuid4()
        fetched = await repo.get(db_session, fake_id)
        assert fetched is None

    @pytest.mark.asyncio
    async def test_get_latest_by_chapter(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        """测试获取章节最新草稿"""
        novel_id = uuid.UUID(hex=sample_draft_data.novel_id)

        # 创建两个版本
        await repo.create(db_session, sample_draft_data)
        v2_data = WritingDraftCreate(
            novel_id=sample_draft_data.novel_id,
            chapter_index=1,
            title="最新版本",
            content="最新内容",
        )
        await repo.create(db_session, v2_data)

        # 获取最新版本
        latest = await repo.get_latest_by_chapter(
            db_session, novel_id, chapter_index=1,
        )
        assert latest is not None
        assert latest.version_number == 2
        assert latest.title == "最新版本"

    @pytest.mark.asyncio
    async def test_get_latest_by_chapter_no_draft(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
    ) -> None:
        """测试获取没有草稿的章节"""
        novel_id = uuid.uuid4()
        latest = await repo.get_latest_by_chapter(
            db_session, novel_id, chapter_index=1,
        )
        assert latest is None

    @pytest.mark.asyncio
    async def test_get_version_history(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        """测试版本历史"""
        novel_id = uuid.UUID(hex=sample_draft_data.novel_id)

        # 创建两个版本
        await repo.create(db_session, sample_draft_data)
        v2_data = WritingDraftCreate(
            novel_id=sample_draft_data.novel_id,
            chapter_index=1,
            title="第二版",
        )
        await repo.create(db_session, v2_data)

        # 获取版本历史
        versions = await repo.get_version_history(
            db_session, novel_id, chapter_index=1,
        )
        assert len(versions) == 2
        # 按版本降序排列
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
        """测试更新草稿"""
        created = await repo.create(db_session, sample_draft_data)

        updated = await repo.update(db_session, created.id, update_data)
        assert updated is not None
        assert updated.title == "更新后的标题"
        assert updated.content == "更新后的正文内容。"
        # 版本号不应改变
        assert updated.version_number == 1

    @pytest.mark.asyncio
    async def test_update_partial(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        """测试部分更新（只更新标题）"""
        created = await repo.create(db_session, sample_draft_data)

        partial = WritingDraftUpdate(title="仅更新标题")
        updated = await repo.update(db_session, created.id, partial)
        assert updated is not None
        assert updated.title == "仅更新标题"
        # 其他字段不变
        assert updated.content == "这是一个测试正文的段落。"
        assert updated.status == "draft"

    @pytest.mark.asyncio
    async def test_update_status(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        """测试更新状态"""
        created = await repo.create(db_session, sample_draft_data)

        status_update = WritingDraftUpdate(status="canonical")
        updated = await repo.update(db_session, created.id, status_update)
        assert updated is not None
        assert updated.status == "canonical"

    @pytest.mark.asyncio
    async def test_update_not_found(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
        update_data: WritingDraftUpdate,
    ) -> None:
        """测试更新不存在的草稿"""
        fake_id = uuid.uuid4()
        updated = await repo.update(db_session, fake_id, update_data)
        assert updated is None

    @pytest.mark.asyncio
    async def test_delete(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        """测试删除草稿"""
        created = await repo.create(db_session, sample_draft_data)
        deleted = await repo.delete(db_session, created.id)
        assert deleted is True

        # 验证已被删除
        fetched = await repo.get(db_session, created.id)
        assert fetched is None

    @pytest.mark.asyncio
    async def test_delete_not_found(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
    ) -> None:
        """测试删除不存在的草稿"""
        fake_id = uuid.uuid4()
        deleted = await repo.delete(db_session, fake_id)
        assert deleted is False

    @pytest.mark.asyncio
    async def test_list_chapter_indices(
        self,
        repo: WritingDraftRepository,
        db_session: AsyncSession,
    ) -> None:
        """测试列出有草稿的章节索引"""
        novel_id = str(uuid.uuid4())
        nid = uuid.UUID(hex=novel_id)

        # 创建三个章节的草稿
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
        """测试无草稿时返回空列表"""
        nid = uuid.uuid4()
        indices = await repo.list_chapter_indices(db_session, nid)
        assert indices == []


# ============================================================
# Service 测试
# ============================================================

class TestWritingDraftService:
    """测试业务逻辑层"""

    @pytest.mark.asyncio
    async def test_create_draft(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        """测试服务层创建草稿"""
        resp = await service.create_draft(db_session, sample_draft_data)
        assert resp.id is not None
        assert resp.novel_id == sample_draft_data.novel_id
        assert resp.chapter_index == 1
        assert resp.title == "第一章：开端"
        assert resp.version_number == 1
        assert resp.status == "draft"
        assert resp.created_at is not None
        assert resp.updated_at is not None

    @pytest.mark.asyncio
    async def test_get_draft(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        """测试获取草稿"""
        created = await service.create_draft(db_session, sample_draft_data)
        fetched = await service.get_draft(db_session, created.id, sample_draft_data.novel_id)
        assert fetched.id == created.id
        assert fetched.title == "第一章：开端"

    @pytest.mark.asyncio
    async def test_get_draft_not_found(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        """测试获取不存在的草稿"""
        fake_id = str(uuid.uuid4())
        with pytest.raises(HTTPException) as exc_info:
            await service.get_draft(db_session, fake_id, sample_draft_data.novel_id)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_update_draft(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
        update_data: WritingDraftUpdate,
    ) -> None:
        """测试更新草稿"""
        created = await service.create_draft(db_session, sample_draft_data)
        updated = await service.update_draft(
            db_session, created.id, update_data, sample_draft_data.novel_id,
        )
        assert updated.title == "更新后的标题"
        assert updated.content == "更新后的正文内容。"

    @pytest.mark.asyncio
    async def test_update_draft_not_found(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
        update_data: WritingDraftUpdate,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        """测试更新不存在的草稿"""
        fake_id = str(uuid.uuid4())
        with pytest.raises(HTTPException) as exc_info:
            await service.update_draft(db_session, fake_id, update_data, sample_draft_data.novel_id)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_draft(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        """测试删除草稿"""
        created = await service.create_draft(db_session, sample_draft_data)
        await service.delete_draft(db_session, created.id, sample_draft_data.novel_id)
        # 验证已删除
        with pytest.raises(HTTPException) as exc_info:
            await service.get_draft(db_session, created.id, sample_draft_data.novel_id)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_draft_not_found(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        """测试删除不存在的草稿"""
        fake_id = str(uuid.uuid4())
        with pytest.raises(HTTPException) as exc_info:
            await service.delete_draft(db_session, fake_id, sample_draft_data.novel_id)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_latest_draft(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        """测试获取章节最新草稿"""
        # 创建两个版本
        await service.create_draft(db_session, sample_draft_data)
        v2 = WritingDraftCreate(
            novel_id=sample_draft_data.novel_id,
            chapter_index=1,
            title="最新版本",
            content="最新正文",
        )
        await service.create_draft(db_session, v2)

        latest = await service.get_latest_draft(
            db_session, sample_draft_data.novel_id, 1,
        )
        assert latest.version_number == 2
        assert latest.title == "最新版本"

    @pytest.mark.asyncio
    async def test_get_latest_draft_not_found(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
    ) -> None:
        """测试获取不存在的章节草稿"""
        fake_novel = str(uuid.uuid4())
        with pytest.raises(HTTPException) as exc_info:
            await service.get_latest_draft(db_session, fake_novel, 1)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_version_history(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        """测试版本历史"""
        # 创建三个版本
        await service.create_draft(db_session, sample_draft_data)
        v2 = WritingDraftCreate(
            novel_id=sample_draft_data.novel_id,
            chapter_index=1,
            title="第二版",
        )
        await service.create_draft(db_session, v2)
        v3 = WritingDraftCreate(
            novel_id=sample_draft_data.novel_id,
            chapter_index=1,
            title="第三版",
        )
        await service.create_draft(db_session, v3)

        history = await service.get_version_history(
            db_session, sample_draft_data.novel_id, 1,
        )
        assert history.total == 3
        assert len(history.versions) == 3
        # 版本降序
        assert history.versions[0].version_number == 3
        assert history.versions[1].version_number == 2
        assert history.versions[2].version_number == 1

    @pytest.mark.asyncio
    async def test_get_version_history_empty(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
    ) -> None:
        """测试空版本历史"""
        fake_novel = str(uuid.uuid4())
        history = await service.get_version_history(
            db_session, fake_novel, 1,
        )
        assert history.total == 0
        assert len(history.versions) == 0

    @pytest.mark.asyncio
    async def test_invalid_uuid(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        """测试无效 UUID 格式"""
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
        """测试获取草稿契约"""
        created = await service.create_draft(db_session, sample_draft_data)
        contract = await service.get_draft_contract(db_session, created.id)
        assert contract is not None
        assert isinstance(contract, WritingDraftContract)
        assert contract.novel_id == sample_draft_data.novel_id
        assert contract.chapter_index == 1
        assert contract.title == "第一章：开端"
        assert contract.content == "这是一个测试正文的段落。"
        assert contract.version_number == 1
        assert contract.status == "draft"

    @pytest.mark.asyncio
    async def test_get_draft_contract_not_found(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
    ) -> None:
        """测试获取不存在的草稿契约"""
        fake_id = str(uuid.uuid4())
        contract = await service.get_draft_contract(db_session, fake_id)
        assert contract is None

    @pytest.mark.asyncio
    async def test_get_latest_draft_contract(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        """测试获取章节最新草稿契约"""
        await service.create_draft(db_session, sample_draft_data)
        contract = await service.get_latest_draft_contract(
            db_session, sample_draft_data.novel_id, 1,
        )
        assert contract is not None
        assert contract.chapter_index == 1
        assert contract.version_number == 1

    @pytest.mark.asyncio
    async def test_get_latest_draft_contract_not_found(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
    ) -> None:
        """测试获取不存在的章节最新草稿契约"""
        fake_novel = str(uuid.uuid4())
        contract = await service.get_latest_draft_contract(
            db_session, fake_novel, 1,
        )
        assert contract is None

    @pytest.mark.asyncio
    async def test_list_chapter_indices(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
    ) -> None:
        """测试列出有草稿的章节索引"""
        novel_id = str(uuid.uuid4())
        for ch in (1, 1, 3, 5):
            data = WritingDraftCreate(
                novel_id=novel_id, chapter_index=ch,
                title=f"第{ch}章", content="内容",
            )
            await service.create_draft(db_session, data)

        indices = await service.list_chapter_indices(db_session, novel_id)
        assert indices == [1, 3, 5]

    @pytest.mark.asyncio
    async def test_list_chapter_indices_empty(
        self,
        service: WritingDraftService,
        db_session: AsyncSession,
    ) -> None:
        """测试无草稿时返回空列表"""
        indices = await service.list_chapter_indices(
            db_session, str(uuid.uuid4()),
        )
        assert indices == []


# ============================================================
# Facade 测试
# ============================================================

class TestWritingFacade:
    """测试对外入口"""

    @pytest.mark.asyncio
    async def test_get_draft(
        self,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        """测试 facade.get_draft"""
        # 先创建草稿
        repo = WritingDraftRepository()
        draft = await repo.create(db_session, sample_draft_data)

        contract = await get_draft(db_session, str(draft.id))
        assert contract is not None
        assert isinstance(contract, WritingDraftContract)
        assert contract.novel_id == sample_draft_data.novel_id
        assert contract.chapter_index == 1
        assert contract.title == "第一章：开端"

    @pytest.mark.asyncio
    async def test_get_draft_not_found(
        self,
        db_session: AsyncSession,
    ) -> None:
        """测试 facade 获取不存在的草稿"""
        contract = await get_draft(db_session, str(uuid.uuid4()))
        assert contract is None

    @pytest.mark.asyncio
    async def test_get_latest_draft_for_chapter(
        self,
        db_session: AsyncSession,
        sample_draft_data: WritingDraftCreate,
    ) -> None:
        """测试 facade.get_latest_draft_for_chapter"""
        # 创建两个版本
        repo = WritingDraftRepository()
        await repo.create(db_session, sample_draft_data)
        v2 = WritingDraftCreate(
            novel_id=sample_draft_data.novel_id,
            chapter_index=1,
            title="第二版",
        )
        await repo.create(db_session, v2)

        contract = await get_latest_draft_for_chapter(
            db_session, sample_draft_data.novel_id, 1,
        )
        assert contract is not None
        assert contract.version_number == 2
        assert contract.title == "第二版"

    @pytest.mark.asyncio
    async def test_get_latest_draft_for_chapter_not_found(
        self,
        db_session: AsyncSession,
    ) -> None:
        """测试 facade 获取不存在的章节草稿"""
        contract = await get_latest_draft_for_chapter(
            db_session, str(uuid.uuid4()), 1,
        )
        assert contract is None

    @pytest.mark.asyncio
    async def test_list_chapter_indices(
        self,
        db_session: AsyncSession,
    ) -> None:
        """测试 facade.list_chapter_indices"""
        novel_id = str(uuid.uuid4())
        repo = WritingDraftRepository()
        for ch in (1, 1, 3, 5):
            data = WritingDraftCreate(
                novel_id=novel_id, chapter_index=ch,
                title=f"第{ch}章", content="内容",
            )
            await repo.create(db_session, data)

        indices = await list_chapter_indices(db_session, novel_id)
        assert indices == [1, 3, 5]

    @pytest.mark.asyncio
    async def test_list_chapter_indices_empty(
        self,
        db_session: AsyncSession,
    ) -> None:
        """测试 facade 无草稿时返回空列表"""
        indices = await list_chapter_indices(
            db_session, str(uuid.uuid4()),
        )
        assert indices == []


# ============================================================
# SaveAndAnalyze 测试
# ============================================================

class TestSaveAndAnalyze:

    @pytest.mark.asyncio
    async def test_save_and_analyze_captures_snapshot(
        self,
        db_session: AsyncSession,
    ) -> None:
        """analyze_chapter 调用 memory.capture_snapshot 并返回成功"""
        from unittest.mock import AsyncMock, patch

        novel_id = str(uuid.uuid4())
        content = "李明御剑飞往北境，天剑宗全面控制了北境。"

        mock_snapshot = AsyncMock()
        mock_snapshot.id = "snap-1"

        with patch(
            "modules.memory.facade.capture_snapshot",
            new_callable=AsyncMock,
            return_value=mock_snapshot,
        ) as mock_capture:
            service = WritingAnalysisService()
            result = await service.analyze_chapter(
                db_session, novel_id, 1, content,
            )
            assert result == (True, "success")
            mock_capture.assert_called_once_with(
                db_session, novel_id, 1,
            )

    @pytest.mark.asyncio
    async def test_save_and_analyze_llm_failure_graceful(
        self,
        db_session: AsyncSession,
    ) -> None:
        from unittest.mock import AsyncMock, patch
        from modules.writing.api import SaveAndAnalyzeRequest, save_and_analyze

        novel_id = str(uuid.uuid4())
        content = "平静的一章，没有任何变化。"

        with patch(
            "infrastructure.llm.client.LLMClient.generate_structured",
            new_callable=AsyncMock,
            side_effect=Exception("LLM service unavailable"),
        ):
            data = SaveAndAnalyzeRequest(
                novel_id=novel_id,
                chapter_index=1,
                content=content,
            )
            response = await save_and_analyze(db_session, data)
            assert response.draft_id is not None
            # 新版 analyze_chapter 不依赖 LLM，快照成功则 proposal_created=True
            assert response.proposal_created is True
