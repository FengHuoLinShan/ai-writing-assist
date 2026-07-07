"""
Project Service
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError, ValidationError
from infrastructure.llm.profiles import (
    LLM_API_KEY_FIELD,
    LLM_SETTINGS_KEY,
    get_llm_profile,
    list_provider_templates,
    sanitize_llm_profile,
)
from modules.project.repositories import ProjectRepository
from modules.project.schemas import (
    LLMFieldResetResponse,
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
from modules.writing.facade import (
    get_project_writing_stats,
    list_project_writing_stats,
)
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from shared.deep_import_settings import (
    DEEP_IMPORT_SETTINGS_KEY,
    clean_deep_import_settings,
    deep_import_settings_for_response,
)
from shared.utils import parse_uuid as _shared_parse_uuid


def _parse_uuid(value: str, field_name: str = "id") -> uuid.UUID:
    return _shared_parse_uuid(value, field_name)


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
        writing_stats_batch_provider: Callable[
            [AsyncSession, list[str]],
            Awaitable[dict[str, WritingProjectStatsContract]],
        ]
        | None = None,
    ) -> None:
        self._repo = repo or ProjectRepository()
        self._writing_stats_provider = writing_stats_provider or (
            get_project_writing_stats if repo is None else _empty_project_writing_stats
        )
        self._writing_stats_batch_provider = writing_stats_batch_provider or (
            list_project_writing_stats
            if repo is None
            else _empty_project_writing_stats_batch
        )

    def list_llm_provider_templates(self) -> LLMProviderTemplateListResponse:
        return LLMProviderTemplateListResponse(items=list_provider_templates())

    async def create_project(
        self, db: AsyncSession, data: ProjectCreate
    ) -> ProjectResponse:
        project = await self._repo.create(db, data)
        return await self._response_with_stats(db, project)

    async def get_project(self, db: AsyncSession, project_id: str) -> ProjectResponse:
        pid = _parse_uuid(project_id, "project_id")
        project = await self._repo.get(db, pid)
        if project is None:
            raise NotFoundError(f"Project {project_id} not found")
        return await self._response_with_stats(db, project)

    async def list_projects(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> ProjectListResponse:
        limit = min(limit, MAX_PAGE_SIZE)
        items, total = await self._repo.list(db, skip=skip, limit=limit)
        stats_by_project_id = await self._writing_stats_batch_provider(
            db,
            [str(project.id) for project in items],
        )
        return ProjectListResponse(
            items=[
                self._response_with_known_stats(
                    project,
                    stats_by_project_id.get(str(project.id)),
                )
                for project in items
            ],
            total=total,
        )

    async def update_project(
        self,
        db: AsyncSession,
        project_id: str,
        data: ProjectUpdate,
    ) -> ProjectResponse:
        pid = _parse_uuid(project_id, "project_id")
        project = await self._repo.update(db, pid, data)
        if project is None:
            raise NotFoundError(f"Project {project_id} not found")
        return await self._response_with_stats(db, project)

    async def get_llm_settings(
        self,
        db: AsyncSession,
        project_id: str,
    ) -> ProjectLLMSettingsResponse:
        project = await self._get_existing_project(db, project_id)
        profile = sanitize_llm_profile(get_llm_profile(project.settings))
        profile[DEEP_IMPORT_SETTINGS_KEY] = deep_import_settings_for_response(
            project.settings
        )
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

        next_profile: dict[str, object] = {}
        if data.provider_id is not None and data.provider_id != "":
            next_profile["provider_id"] = data.provider_id
        if data.label is not None:
            next_profile["label"] = data.label
        if data.base_url is not None and data.base_url != "":
            next_profile["base_url"] = data.base_url
        if data.model is not None and data.model != "":
            next_profile["model"] = data.model
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

        if next_profile:
            settings[LLM_SETTINGS_KEY] = next_profile
        else:
            settings.pop(LLM_SETTINGS_KEY, None)
        # D6: deep_import 是 atomic unit。空 dict 视为「恢复继承」，应清除 key；
        # 非空才走 clean_deep_import_settings 写入整体覆盖。
        if data.deep_import:
            settings[DEEP_IMPORT_SETTINGS_KEY] = clean_deep_import_settings(
                data.deep_import
            )
        else:
            settings.pop(DEEP_IMPORT_SETTINGS_KEY, None)
        update_data = ProjectUpdate(settings=settings)
        project = await self._repo.update(db, project, update_data)
        if project is None:
            raise NotFoundError(f"Project {project_id} not found")
        profile = sanitize_llm_profile(get_llm_profile(project.settings))
        profile[DEEP_IMPORT_SETTINGS_KEY] = deep_import_settings_for_response(
            project.settings
        )
        return ProjectLLMSettingsResponse.model_validate(profile)

    async def reset_llm_settings_field(
        self,
        db: AsyncSession,
        project_id: str,
        field_name: str,
    ) -> LLMFieldResetResponse:
        from modules.settings.constants import LLM_INHERITABLE_FIELDS

        if field_name not in LLM_INHERITABLE_FIELDS:
            raise ValueError(f"unknown llm field: {field_name}")
        project = await self._get_existing_project(db, project_id)
        settings = dict(project.settings or {})
        # D6: deep_import 是 settings 顶层 sibling，不在 settings["llm"] 内
        if field_name == "deep_import":
            settings.pop(DEEP_IMPORT_SETTINGS_KEY, None)
        else:
            llm = dict(settings.get(LLM_SETTINGS_KEY, {}))
            if field_name in llm:
                del llm[field_name]
            if llm:
                settings[LLM_SETTINGS_KEY] = llm
            else:
                settings.pop(LLM_SETTINGS_KEY, None)
        update_data = ProjectUpdate(settings=settings)
        await self._repo.update(db, project, update_data)
        return LLMFieldResetResponse(field=field_name, reset=True)

    async def delete_project(self, db: AsyncSession, project_id: str) -> None:
        """软删除：标记项目为已删除（移至回收站）"""
        pid = _parse_uuid(project_id, "project_id")
        deleted = await self._repo.soft_delete(db, pid)
        if not deleted:
            raise NotFoundError(f"Project {project_id} not found or already deleted")

    async def restore_project(self, db: AsyncSession, project_id: str) -> ProjectResponse:
        """从回收站恢复项目"""
        pid = _parse_uuid(project_id, "project_id")
        restored = await self._repo.restore(db, pid)
        if not restored:
            raise NotFoundError(f"Project {project_id} not found in recycle bin")
        project = await self._repo.get(db, pid)
        if project is None:
            raise NotFoundError(f"Project {project_id} not found after restore")
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
            raise ValidationError("permanent delete requires confirmed=true")
        pid = _parse_uuid(project_id, "project_id")
        deleted = await self._repo.permanent_delete(db, pid)
        if not deleted:
            raise NotFoundError(f"Project {project_id} not found in recycle bin")
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
        pid = _parse_uuid(novel_id, "novel_id")
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
            settings=dict(project.settings or {}),
        )

    async def _get_existing_project(self, db: AsyncSession, project_id: str):
        pid = _parse_uuid(project_id, "project_id")
        project = await self._repo.get(db, pid)
        if project is None:
            raise NotFoundError(f"Project {project_id} not found")
        return project

    async def _response_with_stats(
        self,
        db: AsyncSession,
        project: object,
    ) -> ProjectResponse:
        response = ProjectResponse.model_validate(project)
        stats = await self._writing_stats_provider(db, response.id)
        return self._apply_stats(response, stats)

    def _response_with_known_stats(
        self,
        project: object,
        stats: WritingProjectStatsContract | None,
    ) -> ProjectResponse:
        response = ProjectResponse.model_validate(project)
        return self._apply_stats(
            response,
            stats or WritingProjectStatsContract(novel_id=response.id),
        )

    def _apply_stats(
        self,
        response: ProjectResponse,
        stats: WritingProjectStatsContract,
    ) -> ProjectResponse:
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


async def _empty_project_writing_stats_batch(
    _db: AsyncSession,
    novel_ids: list[str],
) -> dict[str, WritingProjectStatsContract]:
    return {
        novel_id: WritingProjectStatsContract(novel_id=novel_id)
        for novel_id in novel_ids
    }
