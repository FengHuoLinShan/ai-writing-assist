"""
Project 模块测试

测试 CRUD 各路径、service 和边界情况。
使用 pytest-asyncio 测试异步数据库操作。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.tasks.models import AsyncTask
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

    @pytest.mark.parametrize(
        "operation,expected",
        [
            ("get", None),
            ("update", None),
            ("soft_delete", False),
            ("restore", False),
            ("permanent_delete", False),
        ],
        ids=["get", "update", "soft_delete", "restore", "permanent_delete"],
    )
    @pytest.mark.asyncio
    async def test_not_found(
        self,
        db_session: AsyncSession,
        update_data: ProjectUpdate,
        operation: str,
        expected: None | bool,
    ) -> None:
        """测试对不存在的项目执行各类操作"""
        fake_id = uuid.uuid4()
        if operation == "get":
            result = await _repo.get(db_session, fake_id)
        elif operation == "update":
            result = await _repo.update(db_session, fake_id, update_data)
        elif operation == "soft_delete":
            result = await _repo.soft_delete(db_session, fake_id)
        elif operation == "restore":
            result = await _repo.restore(db_session, fake_id)
        else:
            result = await _repo.permanent_delete(db_session, fake_id)
        assert result is expected

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

    # --------------------------------------------------------
    # 软删除
    # --------------------------------------------------------

    @pytest.mark.asyncio
    async def test_soft_delete_hides_from_get_and_list(
        self,
        db_session: AsyncSession,
        sample_create_data: ProjectCreate,
    ) -> None:
        created = await _repo.create(db_session, sample_create_data)

        deleted = await _repo.soft_delete(db_session, created.id)

        assert deleted is True
        assert await _repo.get(db_session, created.id) is None
        deleted_project = await _repo.get_deleted(db_session, created.id)
        assert deleted_project is not None
        assert deleted_project.deleted_at is not None

        items, _total = await _repo.list(db_session, skip=0, limit=10)
        assert all(item.id != created.id for item in items)

    @pytest.mark.asyncio
    async def test_soft_delete_already_deleted(
        self,
        db_session: AsyncSession,
        sample_create_data: ProjectCreate,
    ) -> None:
        """测试对已软删除的项目再次软删除返回 False"""
        created = await _repo.create(db_session, sample_create_data)
        first = await _repo.soft_delete(db_session, created.id)
        assert first is True

        second = await _repo.soft_delete(db_session, created.id)
        assert second is False

    # --------------------------------------------------------
    # 恢复
    # --------------------------------------------------------

    @pytest.mark.asyncio
    async def test_restore(
        self,
        db_session: AsyncSession,
        sample_create_data: ProjectCreate,
    ) -> None:
        """测试软删除后恢复项目"""
        created = await _repo.create(db_session, sample_create_data)
        await _repo.soft_delete(db_session, created.id)

        restored = await _repo.restore(db_session, created.id)
        assert restored is True

        # 恢复后重新出现在 list 中
        items, total = await _repo.list(db_session, skip=0, limit=10)
        assert any(item.id == created.id for item in items)

    @pytest.mark.asyncio
    async def test_restore_not_in_recycle_bin(
        self,
        db_session: AsyncSession,
        sample_create_data: ProjectCreate,
    ) -> None:
        """测试对未删除的项目恢复返回 False"""
        created = await _repo.create(db_session, sample_create_data)
        restored = await _repo.restore(db_session, created.id)
        assert restored is False

    # --------------------------------------------------------
    # 回收站列表
    # --------------------------------------------------------

    @pytest.mark.asyncio
    async def test_list_deleted(
        self,
        db_session: AsyncSession,
        sample_create_data: ProjectCreate,
    ) -> None:
        """测试回收站列表包含已删除项目"""
        created = await _repo.create(db_session, sample_create_data)
        await _repo.soft_delete(db_session, created.id)

        items, total = await _repo.list_deleted(db_session, skip=0, limit=10)
        assert total >= 1
        assert any(item.id == created.id for item in items)

    @pytest.mark.asyncio
    async def test_list_deleted_empty(
        self,
        db_session: AsyncSession,
    ) -> None:
        """测试无删除项目时回收站返回空列表"""
        items, total = await _repo.list_deleted(db_session, skip=0, limit=10)
        assert total == 0
        assert items == []

    @pytest.mark.asyncio
    async def test_list_deleted_pagination(
        self,
        db_session: AsyncSession,
    ) -> None:
        """测试回收站分页"""
        for i in range(5):
            proj = await _repo.create(
                db_session,
                ProjectCreate(title=f"待删项目{i}"),
            )
            await _repo.soft_delete(db_session, proj.id)
        await db_session.flush()

        items, total = await _repo.list_deleted(db_session, skip=0, limit=2)
        assert total == 5
        assert len(items) == 2

    # --------------------------------------------------------
    # 永久删除
    # --------------------------------------------------------

    @pytest.mark.asyncio
    async def test_permanent_delete(
        self,
        db_session: AsyncSession,
        sample_create_data: ProjectCreate,
    ) -> None:
        """测试软删除后永久删除项目"""
        created = await _repo.create(db_session, sample_create_data)
        await _repo.soft_delete(db_session, created.id)

        result = await _repo.permanent_delete(db_session, created.id)
        assert result is True

        # 彻底消失
        fetched = await _repo.get(db_session, created.id)
        assert fetched is None

    @pytest.mark.asyncio
    async def test_permanent_delete_without_soft_delete(
        self,
        db_session: AsyncSession,
        sample_create_data: ProjectCreate,
    ) -> None:
        """测试未软删除的项目不能直接永久删除"""
        created = await _repo.create(db_session, sample_create_data)
        result = await _repo.permanent_delete(db_session, created.id)
        assert result is False

    @pytest.mark.asyncio
    async def test_permanent_delete_project_removes_async_tasks(
        self,
        db_session: AsyncSession,
        sample_create_data: ProjectCreate,
    ) -> None:
        """永久删除项目时清理 JSON meta.novel_id 关联的异步任务。"""
        created = await _repo.create(db_session, sample_create_data)
        other_project_id = uuid.uuid4()
        task_for_project = AsyncTask(
            task_type="publish_chapter",
            status="pending",
            meta={"novel_id": str(created.id), "chapter_index": 1},
        )
        task_for_other_project = AsyncTask(
            task_type="publish_chapter",
            status="pending",
            meta={"novel_id": str(other_project_id), "chapter_index": 1},
        )
        db_session.add_all([task_for_project, task_for_other_project])
        await _repo.soft_delete(db_session, created.id)
        await db_session.flush()

        await ProjectService().permanent_delete_project(
            db_session,
            str(created.id),
            confirmed=True,
        )

        result = await db_session.execute(select(AsyncTask))
        tasks = result.scalars().all()
        assert [task.id for task in tasks] == [task_for_other_project.id]


# ============================================================
# Service 测试
# ============================================================


def _make_project(**overrides: object) -> MagicMock:
    project = MagicMock()
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "title": "测试小说",
        "genre": "玄幻",
        "tone": "严肃",
        "language": "zh",
        "target_length": "novel",
        "current_stage": "world_building",
        "default_reveal_policy": "author_safe",
        "settings": {},
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
        "deleted_at": None,
    }
    defaults.update(overrides)
    for key, value in defaults.items():
        setattr(project, key, value)
    return project


class TestProjectService:
    """测试业务逻辑层 — repo 用 AsyncMock 替换"""

    @pytest.mark.asyncio
    async def test_create_project(
        self,
        sample_create_data: ProjectCreate,
    ) -> None:
        project = _make_project()
        repo = MagicMock()
        repo.create = AsyncMock(return_value=project)
        service = ProjectService(repo=repo)
        db = MagicMock()

        resp = await service.create_project(db, sample_create_data)

        assert resp.id == str(project.id)
        assert resp.title == "测试小说"
        repo.create.assert_awaited_once_with(db, sample_create_data)

    @pytest.mark.parametrize(
        "operation",
        [
            "get_project",
            "delete_project",
            "restore_project",
            "permanent_delete_project",
        ],
        ids=["get", "delete", "restore", "permanent_delete"],
    )
    @pytest.mark.asyncio
    async def test_service_not_found(
        self,
        operation: str,
    ) -> None:
        """测试服务层对不存在的项目执行各类操作"""
        fake_id = str(uuid.uuid4())
        repo = MagicMock()
        repo.get = AsyncMock(return_value=None)
        repo.soft_delete = AsyncMock(return_value=False)
        repo.restore = AsyncMock(return_value=False)
        repo.permanent_delete = AsyncMock(return_value=False)
        service = ProjectService(repo=repo)
        db = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            if operation == "get_project":
                await service.get_project(db, fake_id)
            elif operation == "delete_project":
                await service.delete_project(db, fake_id)
            elif operation == "restore_project":
                await service.restore_project(db, fake_id)
            else:
                await service.permanent_delete_project(db, fake_id, confirmed=True)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_project(self) -> None:
        """测试服务层软删除项目成功"""
        project_id = str(uuid.uuid4())
        project = _make_project(id=uuid.UUID(project_id))
        repo = MagicMock()
        repo.get = AsyncMock(return_value=project)
        repo.soft_delete = AsyncMock(return_value=True)
        service = ProjectService(repo=repo)
        db = MagicMock()

        result = await service.delete_project(db, project_id)

        assert result is None
        repo.soft_delete.assert_awaited_once_with(db, uuid.UUID(project_id))

    @pytest.mark.asyncio
    async def test_restore_project(self) -> None:
        """测试服务层恢复项目成功"""
        project_id = str(uuid.uuid4())
        project = _make_project(id=uuid.UUID(project_id))
        repo = MagicMock()
        repo.restore = AsyncMock(return_value=True)
        repo.get = AsyncMock(return_value=project)
        service = ProjectService(repo=repo)
        db = MagicMock()

        resp = await service.restore_project(db, project_id)

        assert resp.id == project_id
        assert resp.deleted_at is None
        repo.restore.assert_awaited_once_with(db, uuid.UUID(project_id))

    @pytest.mark.asyncio
    async def test_list_deleted_projects(self) -> None:
        """测试服务层回收站列表"""
        project = _make_project(deleted_at=datetime.now(UTC))
        repo = MagicMock()
        repo.list_deleted = AsyncMock(return_value=([project], 1))
        service = ProjectService(repo=repo)
        db = MagicMock()

        resp = await service.list_deleted_projects(db, skip=0, limit=10)

        assert resp.total == 1
        assert resp.items[0].id == str(project.id)

    @pytest.mark.asyncio
    async def test_permanent_delete_project(self) -> None:
        """测试服务层永久删除项目成功"""
        project_id = str(uuid.uuid4())
        repo = MagicMock()
        repo.permanent_delete = AsyncMock(return_value=True)
        repo.delete_async_tasks_for_project = AsyncMock(return_value=1)
        service = ProjectService(repo=repo)
        db = MagicMock()

        result = await service.permanent_delete_project(
            db,
            project_id,
            confirmed=True,
        )

        assert result is None
        repo.permanent_delete.assert_awaited_once_with(db, uuid.UUID(project_id))
        repo.delete_async_tasks_for_project.assert_awaited_once_with(
            db,
            uuid.UUID(project_id),
        )

    @pytest.mark.asyncio
    async def test_get_project_context(self) -> None:
        """测试获取项目上下文"""
        project_id = str(uuid.uuid4())
        project = _make_project(id=uuid.UUID(project_id))
        repo = MagicMock()
        repo.get = AsyncMock(return_value=project)
        service = ProjectService(repo=repo)
        db = MagicMock()

        ctx = await service.get_project_context(db, project_id)

        assert ctx is not None
        assert ctx.novel_id == project_id
        assert ctx.title == "测试小说"
        assert ctx.genre == "玄幻"
        assert ctx.tone == "严肃"
        assert ctx.language == "zh"
        assert ctx.target_length == "novel"
        assert ctx.current_stage == "world_building"
        assert ctx.default_reveal_policy == "author_safe"

    @pytest.mark.asyncio
    async def test_get_project_context_not_found(self) -> None:
        """测试获取不存在的项目上下文"""
        fake_id = str(uuid.uuid4())
        repo = MagicMock()
        repo.get = AsyncMock(return_value=None)
        service = ProjectService(repo=repo)
        db = MagicMock()

        ctx = await service.get_project_context(db, fake_id)

        assert ctx is None

    @pytest.mark.asyncio
    async def test_invalid_uuid(self) -> None:
        """测试无效 UUID 格式"""
        service = ProjectService()
        db = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            await service.get_project(db, "not-a-uuid")
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_create_project_empty_title(self) -> None:
        """测试空字符串标题创建时返回 422"""
        with pytest.raises(ValidationError):
            ProjectCreate(title="")

    @pytest.mark.asyncio
    async def test_get_project_not_found(self) -> None:
        """测试获取不存在的项目返回 404"""
        project_id = str(uuid.uuid4())
        repo = MagicMock()
        repo.get = AsyncMock(return_value=None)
        service = ProjectService(repo=repo)
        db = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await service.get_project(db, project_id)
        assert exc_info.value.status_code == 404


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
