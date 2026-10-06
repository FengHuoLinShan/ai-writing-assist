"""P1-8 回归测试：公开项目门禁在无 principal 时失败关闭。

浏览器路径的 ``require_active_project`` / ``require_active_project_exclusive``
必须始终带 owner 过滤；仅 worker/system 执行范围允许显式无主身份。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.errors import DomainError, NotFoundError
from core.execution_context import is_system_execution, system_execution_scope
from modules.project.models import Project
from modules.project.repositories import ProjectRepository
from modules.project.services import ProjectService

pytestmark = pytest.mark.asyncio

_FOREIGN_OWNER_ID = uuid.uuid4()


@pytest.fixture
def public_auth_mode(monkeypatch: pytest.MonkeyPatch):
    """Force public auth mode: a missing principal no longer falls back."""
    monkeypatch.setenv("AUTH_MODE", "public")
    monkeypatch.setenv("AUTH_SECRET_KEY", "x" * 32)
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


async def test_require_active_project_rejects_unauthenticated_public_caller(
    public_auth_mode,
) -> None:
    """Public HTTP caller without a bound principal fails closed at 401."""
    repo = AsyncMock(spec=ProjectRepository)
    service = ProjectService(repo=repo)

    with pytest.raises(DomainError) as exc_info:
        await service.require_active_project(object(), str(uuid.uuid4()))

    assert exc_info.value.status_code == 401
    repo.get_active_for_share.assert_not_awaited()


async def test_require_active_project_exclusive_rejects_unauthenticated_public_caller(
    public_auth_mode,
) -> None:
    """The exclusive finalizer gate fails closed the same way."""
    repo = AsyncMock(spec=ProjectRepository)
    service = ProjectService(repo=repo)

    with pytest.raises(DomainError) as exc_info:
        await service.require_active_project_exclusive(object(), str(uuid.uuid4()))

    assert exc_info.value.status_code == 401
    repo.get_active_for_update.assert_not_awaited()


async def test_require_active_project_worker_scope_keeps_system_identity(
    public_auth_mode,
) -> None:
    """Inside the worker/system scope the unowned query stays available."""
    repo = AsyncMock(spec=ProjectRepository)
    project_id = uuid.uuid4()
    repo.get_active_for_share.return_value = SimpleNamespace(
        id=project_id,
        owner_id=_FOREIGN_OWNER_ID,
        project_kind="author",
    )
    service = ProjectService(repo=repo)

    with system_execution_scope():
        await service.require_active_project(object(), str(project_id))

    repo.get_active_for_share.assert_awaited_once()
    args, kwargs = repo.get_active_for_share.await_args
    # explicit worker/system identity: the unowned branch omits owner_id
    assert len(args) == 2
    assert kwargs == {"project_kind": "author"}


async def test_require_active_project_exclusive_worker_scope_keeps_system_identity(
    public_auth_mode,
) -> None:
    """The exclusive gate keeps worker semantics inside the scope."""
    repo = AsyncMock(spec=ProjectRepository)
    project_id = uuid.uuid4()
    repo.get_active_for_update.return_value = SimpleNamespace(
        id=project_id,
        owner_id=_FOREIGN_OWNER_ID,
        project_kind="author",
    )
    service = ProjectService(repo=repo)

    with system_execution_scope():
        await service.require_active_project_exclusive(object(), str(project_id))

    repo.get_active_for_update.assert_awaited_once()
    args, kwargs = repo.get_active_for_update.await_args
    # explicit worker/system identity: the unowned branch omits owner_id
    assert len(args) == 2
    assert kwargs == {"project_kind": "author"}


async def test_system_execution_scope_does_not_leak() -> None:
    """The scope marker resets after the worker/system block exits."""
    assert is_system_execution() is False
    with system_execution_scope():
        assert is_system_execution() is True
    assert is_system_execution() is False


async def test_local_mode_without_principal_still_filters_by_owner(
    db_session: AsyncSession,
) -> None:
    """Non-public modes keep resolving the bootstrap owner for the filter."""
    project = Project(title="他人工件", owner_id=_FOREIGN_OWNER_ID)
    db_session.add(project)
    await db_session.flush()

    service = ProjectService()

    with pytest.raises(NotFoundError):
        await service.require_active_project(db_session, str(project.id))
