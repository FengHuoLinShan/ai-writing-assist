"""
Project Service
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.llm.egress import validate_user_llm_base_url
from infrastructure.llm.profiles import (
    LLM_API_KEY_FIELD,
    LLM_API_KEYS_BY_PROVIDER_FIELD,
    LLM_SETTINGS_KEY,
    get_llm_profile,
    list_account_provider_templates,
    sanitize_llm_profile,
)
from infrastructure.tasks.facade import (
    cancel_unfinished_tasks_for_novel,
    delete_tasks_for_novel,
    delete_tasks_for_novels,
)
from modules.account.facade import (
    current_account_id,
    current_owner_id_or_system_none,
    require_account_active,
)
from modules.project.contracts import InteractionProjectContract
from modules.project.repositories import ProjectRepository
from modules.project.schemas import (
    LLMFieldResetResponse,
    LLMProviderTemplateListResponse,
    ProjectBulkPermanentDeleteResponse,
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
        task_canceller: Callable[..., Awaitable[int]] = (
            cancel_unfinished_tasks_for_novel
        ),
        task_deleter: Callable[..., Awaitable[int]] = delete_tasks_for_novel,
        tasks_deleter: Callable[..., Awaitable[int]] = delete_tasks_for_novels,
    ) -> None:
        self._uses_default_repo = repo is None
        self._repo = repo or ProjectRepository()
        self._writing_stats_provider = writing_stats_provider or (
            get_project_writing_stats if repo is None else _empty_project_writing_stats
        )
        self._writing_stats_batch_provider = writing_stats_batch_provider or (
            list_project_writing_stats
            if repo is None
            else _empty_project_writing_stats_batch
        )
        self._task_canceller = task_canceller
        self._task_deleter = task_deleter
        self._tasks_deleter = tasks_deleter

    def list_llm_provider_templates(self) -> LLMProviderTemplateListResponse:
        return LLMProviderTemplateListResponse(
            items=list_account_provider_templates()
        )

    async def create_project(
        self, db: AsyncSession, data: ProjectCreate
    ) -> ProjectResponse:
        if data.settings:
            update_shape = ProjectUpdate(settings=data.settings)
            encrypted = self._encrypt_project_settings_update(update_shape)
            data = data.model_copy(update={"settings": encrypted.settings})
        owner_id = current_account_id()
        await require_account_active(db, owner_id)
        project = (
            await self._repo.create(db, data, owner_id=owner_id)
            if self._uses_default_repo
            else await self._repo.create(db, data)
        )
        return await self._response_with_stats(db, project)

    async def create_interaction_project(
        self,
        db: AsyncSession,
        *,
        title: str,
    ) -> InteractionProjectContract:
        """Create one hidden project root for an RP journey.

        This is intentionally not exposed by the public project API.
        """
        owner_id = current_account_id()
        await require_account_active(db, owner_id)
        project = await self._repo.create(
            db,
            ProjectCreate(
                title=title,
                current_stage="interaction",
                settings={},
            ),
            owner_id=owner_id,
            project_kind="interaction",
        )
        return InteractionProjectContract(
            novel_id=str(project.id),
            owner_id=owner_id,
        )

    async def get_project(self, db: AsyncSession, project_id: str) -> ProjectResponse:
        pid = _parse_uuid(project_id, "project_id")
        owner_id = self._request_owner_id()
        project = (
            await self._repo.get(db, pid, owner_id)
            if owner_id is not None
            else await self._repo.get(db, pid)
        )
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
        owner_id = self._request_owner_id()
        if owner_id is None:
            items, total = await self._repo.list(db, skip=skip, limit=limit)
        else:
            items, total = await self._repo.list(
                db, skip=skip, limit=limit, owner_id=owner_id
            )
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
        data = self._encrypt_project_settings_update(data)
        owner_id = self._request_owner_id()
        project = (
            await self._repo.update(db, pid, data, owner_id=owner_id)
            if owner_id is not None
            else await self._repo.update(db, pid, data)
        )
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
        if data.api_key or data.clear_api_key or data.clear_all_api_keys:
            raise ValidationError("API Key 只能在账户设置中配置")

        next_profile: dict[str, object] = {
            key: value
            for key, value in existing_profile.items()
            if key not in {LLM_API_KEY_FIELD, LLM_API_KEYS_BY_PROVIDER_FIELD}
        }
        if data.provider_id is not None and data.provider_id != "":
            next_profile["provider_id"] = data.provider_id
        if data.label is not None:
            next_profile["label"] = data.label
        if data.base_url is not None and data.base_url != "":
            try:
                next_profile["base_url"] = validate_user_llm_base_url(data.base_url)
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc
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

    @staticmethod
    def _encrypt_project_settings_update(data: ProjectUpdate) -> ProjectUpdate:
        if data.settings is None:
            return data
        settings = dict(data.settings)
        llm = settings.get(LLM_SETTINGS_KEY)
        if not isinstance(llm, dict):
            return data
        next_llm = dict(llm)
        if (
            LLM_API_KEY_FIELD in next_llm
            or LLM_API_KEYS_BY_PROVIDER_FIELD in next_llm
        ):
            raise ValidationError("API Key 只能在账户设置中配置")
        if next_llm.get("base_url"):
            try:
                next_llm["base_url"] = validate_user_llm_base_url(
                    str(next_llm["base_url"])
                )
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc
        settings[LLM_SETTINGS_KEY] = next_llm
        return data.model_copy(update={"settings": settings})

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
        """软删除项目，并在同一事务取消其未完成任务。"""
        pid = _parse_uuid(project_id, "project_id")
        owner_id = self._request_owner_id()
        deleted = (
            await self._repo.soft_delete(db, pid, owner_id)
            if owner_id is not None
            else await self._repo.soft_delete(db, pid)
        )
        if not deleted:
            raise NotFoundError(f"Project {project_id} not found or already deleted")
        await self._task_canceller(
            db,
            novel_id=str(pid),
            transition_reason="project_soft_deleted",
        )

    async def restore_project(self, db: AsyncSession, project_id: str) -> ProjectResponse:
        """从回收站恢复项目"""
        pid = _parse_uuid(project_id, "project_id")
        owner_id = self._request_owner_id()
        restored = (
            await self._repo.restore(db, pid, owner_id)
            if owner_id is not None
            else await self._repo.restore(db, pid)
        )
        if not restored:
            raise NotFoundError(f"Project {project_id} not found in recycle bin")
        project = (
            await self._repo.get(db, pid, owner_id)
            if owner_id is not None
            else await self._repo.get(db, pid)
        )
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
        owner_id = self._request_owner_id()
        deleted = (
            await self._repo.permanent_delete(db, pid, owner_id)
            if owner_id is not None
            else await self._repo.permanent_delete(db, pid)
        )
        if not deleted:
            raise NotFoundError(f"Project {project_id} not found in recycle bin")
        await self._task_deleter(db, novel_id=str(pid))

    async def permanent_delete_projects(
        self,
        db: AsyncSession,
        project_ids: list[str],
        *,
        confirmed: bool = False,
    ) -> ProjectBulkPermanentDeleteResponse:
        """原子地批量永久删除回收站项目。"""
        if not confirmed:
            raise ValidationError("bulk permanent delete requires confirmed=true")

        parsed_ids = [_parse_uuid(project_id, "project_id") for project_id in project_ids]
        unique_ids = list(dict.fromkeys(parsed_ids))
        owner_id = self._request_owner_id()
        deleted_ids = (
            await self._repo.list_deleted_ids(db, unique_ids, owner_id)
            if owner_id is not None
            else await self._repo.list_deleted_ids(db, unique_ids)
        )
        missing_ids = [
            project_id for project_id in unique_ids if project_id not in deleted_ids
        ]
        if missing_ids:
            missing = ", ".join(str(project_id) for project_id in missing_ids)
            raise NotFoundError(f"Projects not found in recycle bin: {missing}")

        deleted_count = (
            await self._repo.permanent_delete_many(db, unique_ids, owner_id)
            if owner_id is not None
            else await self._repo.permanent_delete_many(db, unique_ids)
        )
        if deleted_count != len(unique_ids):
            raise ConflictError(
                "Recycle bin changed during bulk permanent delete; "
                "no projects were deleted"
            )
        await self._tasks_deleter(
            db,
            novel_ids=[str(project_id) for project_id in unique_ids],
        )
        return ProjectBulkPermanentDeleteResponse(
            deleted_ids=[str(project_id) for project_id in unique_ids],
            deleted_count=deleted_count,
        )

    async def list_deleted_projects(
        self,
        db: AsyncSession,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> ProjectListResponse:
        """列出回收站中的项目"""
        limit = min(limit, MAX_PAGE_SIZE)
        owner_id = self._request_owner_id()
        if owner_id is None:
            items, total = await self._repo.list_deleted(db, skip=skip, limit=limit)
        else:
            items, total = await self._repo.list_deleted(
                db, skip=skip, limit=limit, owner_id=owner_id
            )
        return ProjectListResponse(
            items=[await self._response_with_stats(db, p) for p in items],
            total=total,
        )

    async def get_project_context(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        project_kind: str | None = "author",
    ) -> ProjectContext | None:
        pid = _parse_uuid(novel_id, "novel_id")
        owner_id = self._request_owner_id()
        project = (
            await self._repo.get(
                db,
                pid,
                owner_id,
                project_kind=project_kind,
            )
            if owner_id is not None
            else await self._repo.get(db, pid, project_kind=project_kind)
        )
        if project is None:
            return None
        if self._uses_default_repo:
            await require_account_active(db, project.owner_id)
        raw_project_kind = getattr(project, "project_kind", "author")
        resolved_project_kind = (
            raw_project_kind if isinstance(raw_project_kind, str) else "author"
        )
        return ProjectContext(
            novel_id=str(project.id),
            owner_id=str(project.owner_id) if project.owner_id is not None else None,
            project_kind=resolved_project_kind,
            title=project.title,
            genre=project.genre,
            tone=project.tone,
            language=project.language,
            target_length=project.target_length,
            current_stage=project.current_stage,
            default_reveal_policy=project.default_reveal_policy,
            settings=dict(project.settings or {}),
        )

    async def require_active_project(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        project_kind: str | None = "author",
    ) -> None:
        """Hold a shared project row lock for the caller's transaction."""
        pid = _parse_uuid(novel_id, "novel_id")
        owner_id = self._request_owner_id()
        project = (
            await self._repo.get_active_for_share(
                db,
                pid,
                owner_id,
                project_kind=project_kind,
            )
            if owner_id is not None
            else await self._repo.get_active_for_share(
                db,
                pid,
                project_kind=project_kind,
            )
        )
        if project is None:
            raise NotFoundError(f"Project {novel_id} not found")
        if self._uses_default_repo:
            await require_account_active(db, project.owner_id)

    async def require_active_project_exclusive(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        project_kind: str | None = "author",
    ) -> None:
        """Hold a short exclusive project lock for source-sensitive finalizers."""
        pid = _parse_uuid(novel_id, "novel_id")
        owner_id = self._request_owner_id()
        project = (
            await self._repo.get_active_for_update(
                db,
                pid,
                owner_id,
                project_kind=project_kind,
            )
            if owner_id is not None
            else await self._repo.get_active_for_update(
                db,
                pid,
                project_kind=project_kind,
            )
        )
        if project is None:
            raise NotFoundError(f"Project {novel_id} not found")
        if self._uses_default_repo:
            await require_account_active(db, project.owner_id)

    async def archive_interaction_project(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> None:
        pid = _parse_uuid(novel_id, "novel_id")
        owner_id = self._request_owner_id()
        deleted = await self._repo.soft_delete(
            db,
            pid,
            owner_id,
            project_kind="interaction",
        )
        if not deleted:
            raise NotFoundError(f"Interaction journey {novel_id} not found")
        await self._task_canceller(
            db,
            novel_id=str(pid),
            transition_reason="interaction_archived",
        )

    async def restore_interaction_project(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> None:
        pid = _parse_uuid(novel_id, "novel_id")
        owner_id = self._request_owner_id()
        restored = await self._repo.restore(
            db,
            pid,
            owner_id,
            project_kind="interaction",
        )
        if not restored:
            raise NotFoundError(f"Archived interaction journey {novel_id} not found")

    async def permanently_delete_interaction_project(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> None:
        pid = _parse_uuid(novel_id, "novel_id")
        owner_id = self._request_owner_id()
        deleted = await self._repo.permanent_delete(
            db,
            pid,
            owner_id,
            project_kind="interaction",
        )
        if not deleted:
            raise NotFoundError(f"Archived interaction journey {novel_id} not found")
        await self._task_deleter(db, novel_id=str(pid))

    async def _get_existing_project(self, db: AsyncSession, project_id: str):
        pid = _parse_uuid(project_id, "project_id")
        owner_id = self._request_owner_id()
        project = (
            await self._repo.get(db, pid, owner_id)
            if owner_id is not None
            else await self._repo.get(db, pid)
        )
        if project is None:
            raise NotFoundError(f"Project {project_id} not found")
        return project

    @staticmethod
    def _request_owner_id() -> uuid.UUID | None:
        """Return the browser owner; public worker calls alone may return None."""
        return current_owner_id_or_system_none()

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
        novel_id: WritingProjectStatsContract(novel_id=novel_id) for novel_id in novel_ids
    }
