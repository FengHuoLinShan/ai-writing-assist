"""
Settings Facade — 对外入口

其他模块只能从 facade 导入，不得直接 import services.py / repositories.py /
models.py。
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from modules.settings.schemas import (
    EffectiveAuthorPrefsResponse,
    EffectiveLLMSettingsResponse,
    ProjectsUsingDefaultsResponse,
)
from modules.settings.services import SettingsService

_service = SettingsService()


async def get_effective_llm_settings(
    db: AsyncSession,
    project_id: uuid.UUID | str,
) -> EffectiveLLMSettingsResponse:
    """获取项目 effective LLM 配置（含全局/系统默认回退与 source 标签）。

    供 project 模块在 GET /api/projects/{id}/effective-llm-settings 路由
    中委托调用。
    """
    from modules.project.facade import get_project_by_id

    project = await get_project_by_id(db, project_id)
    if project is None:
        raise LookupError(f"project {project_id} not found")
    return await _service.get_effective_llm_settings_for_project_settings(
        db,
        project.settings,
    )


async def get_effective_author_prefs(
    db: AsyncSession,
    project_id: uuid.UUID | str,
) -> EffectiveAuthorPrefsResponse:
    """获取项目 effective 作者偏好（含全局/系统默认回退与 source 标签）。

    供 project 模块在 GET /api/projects/{id}/effective-author-preferences
    路由中委托调用。
    """
    return await _service.get_effective_author_prefs(db, project_id)


async def materialize_effective_project_settings(
    db: AsyncSession,
    project_settings: dict | None,
) -> dict:
    """把项目 raw settings 转为运行时 effective settings。"""
    return await _service.materialize_effective_project_settings(db, project_settings)


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
