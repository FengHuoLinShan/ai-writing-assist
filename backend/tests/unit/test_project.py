"""
Project 模块单元测试

覆盖 contracts.py 导出的 ProjectContext，以及 schemas、Repository、
Service 和 get_project_context 对外接口。
使用 mocks 隔离数据库层，聚焦业务逻辑和边界条件。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from modules.project.contracts import ProjectContext
from modules.project.facade import get_project_context
from modules.project.models import Project
from modules.project.repositories import ProjectRepository
from modules.project.schemas import (
    ProjectCreate,
    ProjectResponse,
    ProjectUpdate,
)
from modules.project.services import ProjectService
from shared.constants import MAX_PAGE_SIZE

_repo = ProjectRepository()


# ============================================================
# Schema 验证（纯 Pydantic，无需 DB）
# ============================================================


class TestProjectCreateSchema:
    """ProjectCreate 请求验证"""

    def test_valid_full(self) -> None:
        data = ProjectCreate(
            title="测试小说",
            genre="玄幻",
            tone="严肃",
            language="en",
            target_length="novel",
            current_stage="world_building",
        )
        assert data.title == "测试小说"
        assert data.genre == "玄幻"
        assert data.tone == "严肃"
        assert data.language == "en"
        assert data.target_length == "novel"

    def test_default_language_is_zh(self) -> None:
        data = ProjectCreate(title="测试")
        assert data.language == "zh"

    def test_default_reveal_policy(self) -> None:
        data = ProjectCreate(title="测试")
        assert data.default_reveal_policy == "author_safe"

    def test_default_settings_is_empty(self) -> None:
        data = ProjectCreate(title="测试")
        assert data.settings == {}

    def test_title_min_length_validation(self) -> None:
        with pytest.raises(ValidationError):
            ProjectCreate(title="")


class TestProjectUpdateSchema:
    """ProjectUpdate 请求验证——所有字段可选"""

    def test_empty_update(self) -> None:
        data = ProjectUpdate()
        assert data.title is None
        assert data.genre is None
        assert data.settings is None

    def test_partial_update_title_only(self) -> None:
        data = ProjectUpdate(title="新标题")
        assert data.title == "新标题"
        assert data.genre is None


class TestProjectResponseSchema:
    """ProjectResponse 响应序列化"""

    def test_uuid_coercion_to_str(self) -> None:
        uid = uuid.uuid4()
        resp = ProjectResponse(id=uid, title="测试")
        assert isinstance(resp.id, str)
        assert resp.id == str(uid)

    def test_str_id_passthrough(self) -> None:
        uid_str = str(uuid.uuid4())
        resp = ProjectResponse(id=uid_str, title="测试")
        assert resp.id == uid_str

    def test_default_fields(self) -> None:
        resp = ProjectResponse(id=str(uuid.uuid4()), title="测试")
        assert resp.language == "zh"
        assert resp.default_reveal_policy == "author_safe"
        assert resp.settings == {}


# ============================================================
# ProjectContext 数据模型
# ============================================================


class TestProjectContextModel:
    """ProjectContext——供其他模块读取的项目信息"""

    def test_valid_construction(self) -> None:
        nid = str(uuid.uuid4())
        ctx = ProjectContext(novel_id=nid, title="测试")
        assert ctx.novel_id == nid
        assert ctx.title == "测试"

    def test_default_language_is_zh(self) -> None:
        ctx = ProjectContext(novel_id=str(uuid.uuid4()), title="测试")
        assert ctx.language == "zh"

    def test_default_safe_policy(self) -> None:
        ctx = ProjectContext(novel_id=str(uuid.uuid4()), title="测试")
        assert ctx.default_reveal_policy == "author_safe"


# ============================================================
# CRUD 函数（mock AsyncSession）
# ============================================================


class TestCRUDFunctions:
    """模块级 CRUD 函数——使用 AsyncMock 隔离 DB"""

    async def test_create_adds_and_flushes(self) -> None:
        db = AsyncMock(spec=AsyncSession)
        data = ProjectCreate(title="测试小说", genre="玄幻")
        project = await _repo.create(db, data)
        assert project.title == "测试小说"
        assert project.genre == "玄幻"
        assert project.language == "zh"
        db.add.assert_called_once_with(project)
        db.flush.assert_awaited_once()

    async def test_create_minimal(self) -> None:
        db = AsyncMock(spec=AsyncSession)
        data = ProjectCreate(title="最小")
        project = await _repo.create(db, data)
        assert project.title == "最小"
        assert project.genre is None
        assert project.language == "zh"

    async def test_get_returns_project_when_found(self) -> None:
        uid = uuid.uuid4()
        db = AsyncMock(spec=AsyncSession)
        expected = Project(id=uid, title="测试")
        result = MagicMock()
        result.scalar_one_or_none.return_value = expected
        db.execute.return_value = result

        got = await _repo.get(db, uid)
        assert got is expected

    async def test_get_returns_none_when_missing(self) -> None:
        db = AsyncMock(spec=AsyncSession)
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute.return_value = result

        got = await _repo.get(db, uuid.uuid4())
        assert got is None

    @patch("modules.project.repositories.ProjectRepository.get")
    async def test_update_returns_project_when_found(
        self,
        mock_get: MagicMock,
    ) -> None:
        uid = uuid.uuid4()
        original = Project(id=uid, title="原始标题")
        mock_get.return_value = original
        db = AsyncMock(spec=AsyncSession)
        updated = await _repo.update(db, uid, ProjectUpdate(title="新标题"))
        assert updated is not None

    @patch("modules.project.repositories.ProjectRepository.get")
    async def test_update_returns_none_when_missing(
        self,
        mock_get: MagicMock,
    ) -> None:
        mock_get.return_value = None
        db = AsyncMock(spec=AsyncSession)
        result = await _repo.update(db, uuid.uuid4(), ProjectUpdate(title="x"))
        assert result is None

    async def test_soft_delete_returns_true_when_found(self) -> None:
        db = AsyncMock(spec=AsyncSession)
        result = MagicMock()
        result.rowcount = 1
        db.execute.return_value = result
        assert await _repo.soft_delete(db, uuid.uuid4()) is True

    async def test_soft_delete_returns_false_when_missing(self) -> None:
        db = AsyncMock(spec=AsyncSession)
        result = MagicMock()
        result.rowcount = 0
        db.execute.return_value = result
        assert await _repo.soft_delete(db, uuid.uuid4()) is False


# ============================================================
# Service 层（mock CRUD 函数）
# ============================================================


class TestProjectService:
    """ProjectService——mock 底层 CRUD 函数"""

    @patch("modules.project.repositories.ProjectRepository.create")
    async def test_create_returns_project_response(
        self,
        mock_create: MagicMock,
    ) -> None:
        now = datetime.now(UTC)
        mock_create.return_value = Project(
            id=uuid.uuid4(),
            title="测试小说",
            genre="玄幻",
            language="zh",
            default_reveal_policy="author_safe",
            settings={},
            created_at=now,
            updated_at=now,
        )
        svc = ProjectService()
        resp = await svc.create_project(
            AsyncMock(spec=AsyncSession),
            ProjectCreate(title="测试小说", genre="玄幻"),
        )
        assert isinstance(resp, ProjectResponse)
        assert resp.title == "测试小说"
        assert resp.genre == "玄幻"

    @patch("modules.project.repositories.ProjectRepository.get")
    async def test_get_raises_404_when_missing(
        self,
        mock_get: MagicMock,
    ) -> None:
        mock_get.return_value = None
        svc = ProjectService()
        with pytest.raises(HTTPException) as exc:
            await svc.get_project(
                AsyncMock(spec=AsyncSession),
                str(uuid.uuid4()),
            )
        assert exc.value.status_code == 404

    @patch("modules.project.repositories.ProjectRepository.update")
    async def test_update_raises_404_when_missing(
        self,
        mock_update: MagicMock,
    ) -> None:
        mock_update.return_value = None
        svc = ProjectService()
        with pytest.raises(HTTPException) as exc:
            await svc.update_project(
                AsyncMock(spec=AsyncSession),
                str(uuid.uuid4()),
                ProjectUpdate(title="x"),
            )
        assert exc.value.status_code == 404

    @patch("modules.project.repositories.ProjectRepository.soft_delete")
    async def test_delete_raises_404_when_missing(
        self,
        mock_soft_delete: MagicMock,
    ) -> None:
        mock_soft_delete.return_value = False
        svc = ProjectService()
        with pytest.raises(HTTPException) as exc:
            await svc.delete_project(
                AsyncMock(spec=AsyncSession),
                str(uuid.uuid4()),
            )
        assert exc.value.status_code == 404

    async def test_invalid_uuid_raises_422(self) -> None:
        svc = ProjectService()
        with pytest.raises(HTTPException) as exc:
            await svc.get_project(AsyncMock(spec=AsyncSession), "not-a-uuid")
        assert exc.value.status_code == 422

    @patch("modules.project.repositories.ProjectRepository.list")
    async def test_list_clamps_limit_to_max(
        self,
        mock_list: MagicMock,
    ) -> None:
        mock_list.return_value = ([], 0)
        svc = ProjectService()
        await svc.list_projects(AsyncMock(spec=AsyncSession), limit=999)
        mock_list.assert_called_once()
        _args = mock_list.call_args
        _limit = _args.kwargs.get("limit")
        if _limit is None:
            _limit = _args[0][2]  # positional: db, skip, limit
        assert _limit == MAX_PAGE_SIZE


# ============================================================
# get_project_context 对外接口
# ============================================================


class TestGetProjectContextFacade:
    """get_project_context——供其他模块使用的项目上下文"""

    @patch("modules.project.repositories.ProjectRepository.get")
    async def test_found_returns_context(
        self,
        mock_get: MagicMock,
    ) -> None:
        uid = uuid.uuid4()
        mock_get.return_value = Project(
            id=uid,
            title="测试小说",
            genre="玄幻",
            language="zh",
            default_reveal_policy="author_safe",
            settings={},
        )
        ctx = await get_project_context(AsyncMock(spec=AsyncSession), str(uid))
        assert isinstance(ctx, ProjectContext)
        assert ctx.novel_id == str(uid)
        assert ctx.title == "测试小说"
        assert ctx.genre == "玄幻"

    @patch("modules.project.repositories.ProjectRepository.get")
    async def test_not_found_returns_none(
        self,
        mock_get: MagicMock,
    ) -> None:
        mock_get.return_value = None
        ctx = await get_project_context(
            AsyncMock(spec=AsyncSession),
            str(uuid.uuid4()),
        )
        assert ctx is None
