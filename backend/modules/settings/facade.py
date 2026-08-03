"""
Settings Facade — 对外入口

其他模块只能从 facade 导入，不得直接 import services.py / repositories.py /
models.py。
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError
from modules.settings.schemas import (
    AccountLLMRuntimeProfile,
    EffectiveAuthorPrefsResponse,
    EffectiveLLMSettingsResponse,
    ProjectsUsingDefaultsResponse,
)
from modules.settings.services import SettingsService

_service = SettingsService()


async def resolve_account_llm_runtime_profile(
    db: AsyncSession,
    *,
    owner_id: uuid.UUID | None = None,
    provider_id: str | None = None,
) -> AccountLLMRuntimeProfile:
    """Resolve one verified account connection without exposing storage details."""

    return await _service.resolve_account_llm_runtime_profile(
        db,
        owner_id=owner_id,
        provider_id=provider_id,
    )


async def get_effective_llm_settings(
    db: AsyncSession,
    project_id: uuid.UUID | str,
) -> EffectiveLLMSettingsResponse:
    """获取项目 effective LLM 配置（含全局/系统默认回退与 source 标签）。

    供 project 模块在 GET /api/projects/{id}/effective-llm-settings 路由
    中委托调用。
    """
    from modules.project.facade import get_project_context, require_active_project

    await require_active_project(db, str(project_id))
    context = await get_project_context(db, str(project_id))
    if context is None:
        raise NotFoundError(f"Project {project_id} not found")
    owner_id = uuid.UUID(context.owner_id) if context.owner_id else None
    return await _service.get_effective_llm_settings_for_project_settings(
        db,
        context.settings,
        owner_id,
    )


async def get_effective_author_prefs(
    db: AsyncSession,
    project_id: uuid.UUID | str,
) -> EffectiveAuthorPrefsResponse:
    """获取项目 effective 作者偏好（含全局/系统默认回退与 source 标签）。

    供 project 模块在 GET /api/projects/{id}/effective-author-preferences
    路由中委托调用。
    """
    from modules.project.facade import require_active_project

    await require_active_project(db, str(project_id))
    return await _service.get_effective_author_prefs(db, project_id)


async def resolve_effective_llm_settings_for_project_settings(
    db: AsyncSession,
    project_settings: dict | None,
    owner_id: uuid.UUID | None = None,
) -> EffectiveLLMSettingsResponse:
    """Resolve field values and provenance for project-owned raw settings."""
    return await _service.get_effective_llm_settings_for_project_settings(
        db,
        project_settings,
        owner_id,
    )


async def list_projects_using_defaults(
    db: AsyncSession,
    limit: int = 50,
    offset: int = 0,
) -> ProjectsUsingDefaultsResponse:
    """列出继承任一作者偏好默认值的项目。"""
    from modules.project.facade import list_active_project_summaries

    projects, total = await list_active_project_summaries(
        db,
        limit=limit,
        offset=offset,
        exclude_project_ids=_service.fully_overridden_project_ids_subquery(),
    )
    return _service.build_projects_using_defaults_response(projects, total)
