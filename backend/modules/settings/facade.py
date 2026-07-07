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
    return await _service.get_effective_llm_settings(db, project_id)


async def get_effective_author_prefs(
    db: AsyncSession,
    project_id: uuid.UUID | str,
) -> EffectiveAuthorPrefsResponse:
    """获取项目 effective 作者偏好（含全局/系统默认回退与 source 标签）。

    供 project 模块在 GET /api/projects/{id}/effective-author-preferences
    路由中委托调用。
    """
    return await _service.get_effective_author_prefs(db, project_id)
