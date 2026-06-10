"""
Project 模块测试

测试 CRUD 各路径、service 和边界情况。
使用 pytest-asyncio 测试异步数据库操作。
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from modules.project.contracts import ProjectContext
from modules.project.facade import get_project_context
from modules.project.repositories import ProjectRepository
from modules.project.schemas import (
    ProjectCreate,
    ProjectUpdate,
)
from modules.project.services import ProjectService

_repo = ProjectRepository()


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def service() -> ProjectService:
    return ProjectService()


@pytest.fixture
def sample_create_data() -> ProjectCreate:
    return ProjectCreate(
        title="测试小说",
        genre="玄幻",
        tone="严肃",
        language="zh",
        target_length="novel",
        current_stage="world_building",
        default_reveal_policy="author_safe",
    )


@pytest.fixture
def minimal_create_data() -> ProjectCreate:
    return ProjectCreate(title="最小测试项目")


@pytest.fixture
def update_data() -> ProjectUpdate:
    return ProjectUpdate(
        title="更新后的标题",
        current_stage="outlining",
    )


# ============================================================
# CRUD 测试（直接测试模块级函数）
# ============================================================

class TestProjectCrud:
    """测试模块级 CRUD 函数"""

    @pytest.mark.asyncio
    async def test_create(
        self,
        db_session: AsyncSession,
        sample_create_data: ProjectCreate,
    ) -> None:
        """测试创建项目"""
        project = await _repo.create(db_session, sample_create_data)
        assert project.id is not None
        assert project.title == "测试小说"
        assert project.genre == "玄幻"
        assert project.tone == "严肃"
        assert project.language == "zh"
        assert project.target_length == "novel"
        assert project.current_stage == "world_building"
        assert project.default_reveal_policy == "author_safe"

    @pytest.mark.asyncio
    async def test_create_with_defaults(
        self,
        db_session: AsyncSession,
        minimal_create_data: ProjectCreate,
    ) -> None:
        """测试使用默认值创建项目"""
        project = await _repo.create(db_session, minimal_create_data)
        assert project.title == "最小测试项目"
        assert project.genre is None
        assert project.tone is None
        assert project.language == "zh"
        assert project.default_reveal_policy == "author_safe"

    @pytest.mark.asyncio
    async def test_get(
        self,
        db_session: AsyncSession,
        sample_create_data: ProjectCreate,
    ) -> None:
        """测试根据 ID 获取项目"""
        created = await _repo.create(db_session, sample_create_data)
        fetched = await _repo.get(db_session, created.id)
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.title == "测试小说"

    @pytest.mark.asyncio
    async def test_get_not_found(
        self,
        db_session: AsyncSession,
    ) -> None:
        """测试获取不存在的项目"""
        fake_id = uuid.uuid4()
        fetched = await _repo.get(db_session, fake_id)
        assert fetched is None

    @pytest.mark.asyncio
    async def test_list(
        self,
        db_session: AsyncSession,
    ) -> None:
        """测试分页获取项目列表"""
        for i in range(3):
            await _repo.create(
                db_session,
                ProjectCreate(title=f"项目{i}"),
            )
        await db_session.flush()

        items, total = await _repo.list(db_session, skip=0, limit=10)
        assert total >= 3
        assert len(items) >= 3

    @pytest.mark.asyncio
    async def test_list_with_pagination(
        self,
        db_session: AsyncSession,
    ) -> None:
        """测试分页限制"""
        for i in range(5):
            await _repo.create(
                db_session,
                ProjectCreate(title=f"项目{i}"),
            )
        await db_session.flush()

        items, total = await _repo.list(db_session, skip=0, limit=2)
        assert total == 5
        assert len(items) == 2

    @pytest.mark.asyncio
    async def test_update(
        self,
        db_session: AsyncSession,
        sample_create_data: ProjectCreate,
        update_data: ProjectUpdate,
    ) -> None:
        """测试更新项目"""
        created = await _repo.create(db_session, sample_create_data)

        updated = await _repo.update(db_session, created.id, update_data)
        assert updated is not None
        assert updated.title == "更新后的标题"
        assert updated.current_stage == "outlining"
        # 未更新的字段保持不变
        assert updated.genre == "玄幻"

    @pytest.mark.asyncio
    async def test_update_not_found(
        self,
        db_session: AsyncSession,
        update_data: ProjectUpdate,
    ) -> None:
        """测试更新不存在的项目"""
        fake_id = uuid.uuid4()
        updated = await _repo.update(db_session, fake_id, update_data)
        assert updated is None

    @pytest.mark.asyncio
    async def test_update_empty(
        self,
        db_session: AsyncSession,
        sample_create_data: ProjectCreate,
    ) -> None:
        """测试空更新（没有字段变化）"""
        created = await _repo.create(db_session, sample_create_data)
        empty_update = ProjectUpdate()
        updated = await _repo.update(db_session, created.id, empty_update)
        assert updated is not None
        assert updated.title == "测试小说"

    @pytest.mark.asyncio
    async def test_delete(
        self,
        db_session: AsyncSession,
        sample_create_data: ProjectCreate,
    ) -> None:
        """测试删除项目"""
        created = await _repo.create(db_session, sample_create_data)
        deleted = await _repo.delete(db_session, created.id)
        assert deleted is True

        # 验证已被删除
        fetched = await _repo.get(db_session, created.id)
        assert fetched is None

    @pytest.mark.asyncio
    async def test_delete_not_found(
        self,
        db_session: AsyncSession,
    ) -> None:
        """测试删除不存在的项目"""
        fake_id = uuid.uuid4()
        deleted = await _repo.delete(db_session, fake_id)
        assert deleted is False


# ============================================================
# Service 测试
# ============================================================

class TestProjectService:
    """测试业务逻辑层"""

    @pytest.mark.asyncio
    async def test_create_project(
        self,
        service: ProjectService,
        db_session: AsyncSession,
        sample_create_data: ProjectCreate,
    ) -> None:
        """测试服务层创建"""
        resp = await service.create_project(db_session, sample_create_data)
        assert resp.id is not None
        assert resp.title == "测试小说"
        assert resp.created_at is not None
        assert resp.updated_at is not None

    @pytest.mark.asyncio
    async def test_get_project_not_found(
        self,
        service: ProjectService,
        db_session: AsyncSession,
    ) -> None:
        """测试服务层获取不存在的项目"""
        fake_id = str(uuid.uuid4())
        with pytest.raises(HTTPException) as exc_info:
            await service.get_project(db_session, fake_id)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_project_not_found(
        self,
        service: ProjectService,
        db_session: AsyncSession,
    ) -> None:
        """测试服务层删除不存在的项目"""
        fake_id = str(uuid.uuid4())
        with pytest.raises(HTTPException) as exc_info:
            await service.delete_project(db_session, fake_id)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_project_context(
        self,
        service: ProjectService,
        db_session: AsyncSession,
        sample_create_data: ProjectCreate,
    ) -> None:
        """测试获取项目上下文"""
        created = await service.create_project(db_session, sample_create_data)
        ctx = await service.get_project_context(db_session, created.id)
        assert ctx is not None
        assert ctx.novel_id == created.id
        assert ctx.title == "测试小说"
        assert ctx.genre == "玄幻"
        assert ctx.tone == "严肃"
        assert ctx.language == "zh"
        assert ctx.target_length == "novel"
        assert ctx.current_stage == "world_building"
        assert ctx.default_reveal_policy == "author_safe"

    @pytest.mark.asyncio
    async def test_get_project_context_not_found(
        self,
        service: ProjectService,
        db_session: AsyncSession,
    ) -> None:
        """测试获取不存在的项目上下文"""
        fake_id = str(uuid.uuid4())
        ctx = await service.get_project_context(db_session, fake_id)
        assert ctx is None

    @pytest.mark.asyncio
    async def test_invalid_uuid(
        self,
        service: ProjectService,
        db_session: AsyncSession,
    ) -> None:
        """测试无效 UUID 格式"""
        with pytest.raises(HTTPException) as exc_info:
            await service.get_project(db_session, "not-a-uuid")
        assert exc_info.value.status_code == 422


# ============================================================
# Facade 测试
# ============================================================

class TestProjectFacade:
    """测试对外入口"""

    @pytest.mark.asyncio
    async def test_get_project_context(
        self,
        db_session: AsyncSession,
        sample_create_data: ProjectCreate,
    ) -> None:
        """测试 facade.get_project_context"""
        # 先创建项目
        project = await _repo.create(db_session, sample_create_data)

        ctx = await get_project_context(db_session, str(project.id))
        assert ctx is not None
        assert isinstance(ctx, ProjectContext)
        assert ctx.novel_id == str(project.id)
        assert ctx.title == "测试小说"

    @pytest.mark.asyncio
    async def test_get_project_context_not_found(
        self,
        db_session: AsyncSession,
    ) -> None:
        """测试 facade 获取不存在的项目"""
        ctx = await get_project_context(db_session, str(uuid.uuid4()))
        assert ctx is None
