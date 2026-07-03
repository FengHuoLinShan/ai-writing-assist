"""
Project Service
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.profiles import (
    LLM_API_KEY_FIELD,
    LLM_SETTINGS_KEY,
    get_llm_profile,
    list_provider_templates,
    sanitize_llm_profile,
)
from modules.project.repositories import ProjectRepository
from modules.project.schemas import (
    LLMProviderTemplateListResponse,
    ProjectContext,
    ProjectCreate,
    ProjectListResponse,
    ProjectLLMSettingsResponse,
    ProjectLLMSettingsUpdate,
    ProjectResponse,
    ProjectUpdate,
)
from modules.writing.contracts import WritingProjectStatsContract
from modules.writing.facade import get_project_writing_stats
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from shared.utils import parse_uuid


class ProjectService:
    """业务服务层 — project 为根聚合，只做 response 转换与 404 抛错"""

    def __init__(
        self,
        repo: ProjectRepository | None = None,
        writing_stats_provider: Callable[
            [AsyncSession, str],
            Awaitable[WritingProjectStatsContract],
        ]
        | None = None,
    ) -> None:
        self._repo = repo or ProjectRepository()
        self._writing_stats_provider = writing_stats_provider or (
            get_project_writing_stats if repo is None else _empty_project_writing_stats
        )

    def list_llm_provider_templates(self) -> LLMProviderTemplateListResponse:
        return LLMProviderTemplateListResponse(items=list_provider_templates())

    async def create_project(
        self, db: AsyncSession, data: ProjectCreate
    ) -> ProjectResponse:
        project = await self._repo.create(db, data)
        return await self._response_with_stats(db, project)

    async def get_project(self, db: AsyncSession, project_id: str) -> ProjectResponse:
        pid = parse_uuid(project_id, "project_id")
        project = await self._repo.get(db, pid)
        if project is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found",
            )
        return await self._response_with_stats(db, project)

    async def list_projects(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> ProjectListResponse:
        limit = min(limit, MAX_PAGE_SIZE)
        items, total = await self._repo.list(db, skip=skip, limit=limit)
        return ProjectListResponse(
            items=[await self._response_with_stats(db, p) for p in items],
            total=total,
        )

    async def update_project(
        self,
        db: AsyncSession,
        project_id: str,
        data: ProjectUpdate,
    ) -> ProjectResponse:
        pid = parse_uuid(project_id, "project_id")
        project = await self._repo.update(db, pid, data)
        if project is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found",
            )
        return await self._response_with_stats(db, project)

    async def get_llm_settings(
        self,
        db: AsyncSession,
        project_id: str,
    ) -> ProjectLLMSettingsResponse:
        project = await self._get_existing_project(db, project_id)
        profile = sanitize_llm_profile(get_llm_profile(project.settings))
        return ProjectLLMSettingsResponse.model_validate(profile)

    async def update_llm_settings(
        self,
        db: AsyncSession,
        project_id: str,
        data: ProjectLLMSettingsUpdate,
    ) -> ProjectLLMSettingsResponse:
        project = await self._get_existing_project(db, project_id)
        settings = dict(project.settings or {})
        existing_profile = get_llm_profile(settings)

        next_profile = {
            "provider_id": data.provider_id,
            "label": data.label,
            "base_url": data.base_url,
            "model": data.model,
        }
        if data.timeout is not None:
            next_profile["timeout"] = data.timeout
        if data.max_tokens is not None:
            next_profile["max_tokens"] = data.max_tokens
        if data.temperature is not None:
            next_profile["temperature"] = data.temperature
        if data.top_p is not None:
            next_profile["top_p"] = data.top_p
        if data.extra:
            next_profile["extra"] = data.extra

        if data.clear_api_key:
            pass
        elif data.api_key:
            next_profile[LLM_API_KEY_FIELD] = data.api_key
        elif existing_profile.get(LLM_API_KEY_FIELD):
            next_profile[LLM_API_KEY_FIELD] = existing_profile[LLM_API_KEY_FIELD]

        settings[LLM_SETTINGS_KEY] = {
            key: value
            for key, value in next_profile.items()
            if value is not None and value != ""
        }
        update_data = ProjectUpdate(settings=settings)
        project = await self._repo.update(db, project.id, update_data)
        if project is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found",
            )
        profile = sanitize_llm_profile(get_llm_profile(project.settings))
        return ProjectLLMSettingsResponse.model_validate(profile)

    async def delete_project(self, db: AsyncSession, project_id: str) -> None:
        """软删除：标记项目为已删除（移至回收站）"""
        pid = parse_uuid(project_id, "project_id")
        deleted = await self._repo.soft_delete(db, pid)
        if not deleted:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found or already deleted",
            )

    async def restore_project(self, db: AsyncSession, project_id: str) -> ProjectResponse:
        """从回收站恢复项目"""
        pid = parse_uuid(project_id, "project_id")
        restored = await self._repo.restore(db, pid)
        if not restored:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found in recycle bin",
            )
        project = await self._repo.get(db, pid)
        if project is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found after restore",
            )
        return await self._response_with_stats(db, project)

    async def permanent_delete_project(
        self,
        db: AsyncSession,
        project_id: str,
        *,
        confirmed: bool = False,
    ) -> None:
        """永久删除项目（级联删除所有关联数据，不可恢复）"""
        if not confirmed:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="permanent delete requires confirmed=true",
            )
        pid = parse_uuid(project_id, "project_id")
        deleted = await self._repo.permanent_delete(db, pid)
        if not deleted:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found in recycle bin",
            )
        await self._repo.delete_async_tasks_for_project(db, pid)

    async def list_deleted_projects(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> ProjectListResponse:
        """列出回收站中的项目"""
        limit = min(limit, MAX_PAGE_SIZE)
        items, total = await self._repo.list_deleted(db, skip=skip, limit=limit)
        return ProjectListResponse(
            items=[await self._response_with_stats(db, p) for p in items],
            total=total,
        )

    async def get_project_context(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> ProjectContext | None:
        pid = parse_uuid(novel_id, "novel_id")
        project = await self._repo.get(db, pid)
        if project is None:
            return None
        return ProjectContext(
            novel_id=str(project.id),
            title=project.title,
            genre=project.genre,
            tone=project.tone,
            language=project.language,
            target_length=project.target_length,
            current_stage=project.current_stage,
            default_reveal_policy=project.default_reveal_policy,
            settings=project.settings,
        )

    async def _get_existing_project(self, db: AsyncSession, project_id: str):
        pid = parse_uuid(project_id, "project_id")
        project = await self._repo.get(db, pid)
        if project is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found",
            )
        return project

    async def _response_with_stats(
        self,
        db: AsyncSession,
        project: object,
    ) -> ProjectResponse:
        response = ProjectResponse.model_validate(project)
        stats = await self._writing_stats_provider(db, response.id)
        return response.model_copy(
            update={
                "word_count": stats.word_count,
                "total_words": stats.word_count,
                "chapter_count": stats.chapter_count,
                "total_chapters": stats.chapter_count,
                "stats": {
                    "word_count": stats.word_count,
                    "total_words": stats.word_count,
                    "chapter_count": stats.chapter_count,
                    "total_chapters": stats.chapter_count,
                },
            },
        )


async def _empty_project_writing_stats(
    _db: AsyncSession,
    novel_id: str,
) -> WritingProjectStatsContract:
    return WritingProjectStatsContract(novel_id=novel_id)
