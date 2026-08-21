"""Project-owned preference overrides and effective composition."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from modules.account.facade import (
    get_account_author_preferences_contract,
    get_account_llm_settings_contract,
)
from modules.project.contracts import ProjectSummary
from modules.project.settings_models import ProjectAuthorPreferences
from modules.project.settings_repository import ProjectAuthorPrefsRepository
from modules.project.settings_schemas import (
    EffectiveAuthorPrefsResponse,
    EffectiveLLMSettingsResponse,
    FieldResetResponse,
    FieldValueSource,
    ProjectAuthorPrefsResponse,
    ProjectsUsingDefaultsItem,
    ProjectsUsingDefaultsResponse,
)
from shared.deep_import_settings import DEEP_IMPORT_SETTINGS_KEY

_FIELDS = frozenset({"daily_goal", "editor_font", "default_focus_mode"})
LLM_INHERITABLE_FIELDS = frozenset(
    {
        "provider_id",
        "label",
        "base_url",
        "model",
        "timeout",
        "max_tokens",
        "temperature",
        "top_p",
        "extra",
        "creative_mode",
        "deep_import",
    }
)


class ProjectSettingsService:
    def __init__(self) -> None:
        self._repo = ProjectAuthorPrefsRepository()

    @staticmethod
    def _id(project_id: uuid.UUID | str) -> uuid.UUID:
        return project_id if isinstance(project_id, uuid.UUID) else uuid.UUID(project_id)

    async def get_project_author_prefs(
        self,
        db: AsyncSession,
        project_id: uuid.UUID | str,
    ) -> ProjectAuthorPrefsResponse:
        row = await self._repo.get(db, self._id(project_id))
        if row is None:
            return ProjectAuthorPrefsResponse()
        return ProjectAuthorPrefsResponse(
            daily_goal=row.daily_goal,
            editor_font=row.editor_font,
            default_focus_mode=row.default_focus_mode,
        )

    async def upsert_project_author_prefs(
        self,
        db: AsyncSession,
        project_id: uuid.UUID | str,
        payload: dict,
    ) -> ProjectAuthorPrefsResponse:
        data = {key: value for key, value in payload.items() if key in _FIELDS}
        data["project_id"] = self._id(project_id)
        row = await self._repo.upsert(db, data)
        return ProjectAuthorPrefsResponse(
            daily_goal=row.daily_goal,
            editor_font=row.editor_font,
            default_focus_mode=row.default_focus_mode,
        )

    async def reset_project_author_prefs_field(
        self,
        db: AsyncSession,
        project_id: uuid.UUID | str,
        field_name: str,
    ) -> FieldResetResponse:
        if field_name not in _FIELDS:
            raise ValueError(f"unknown author prefs field: {field_name}")
        await self._repo.reset_field(db, self._id(project_id), field_name)
        return FieldResetResponse(field=field_name)

    async def get_effective_author_prefs(
        self,
        db: AsyncSession,
        project_id: uuid.UUID | str,
        *,
        owner_id: uuid.UUID | None = None,
    ) -> EffectiveAuthorPrefsResponse:
        project = await self._repo.get(db, self._id(project_id))
        account = await get_account_author_preferences_contract(
            db,
            owner_id=owner_id,
        )

        def field(name: str) -> FieldValueSource:
            project_value = getattr(project, name, None) if project is not None else None
            if project_value is not None:
                return FieldValueSource(value=project_value, source="project")
            return FieldValueSource(
                value=account.values[name],
                source=account.sources[name],
            )

        return EffectiveAuthorPrefsResponse(
            daily_goal=field("daily_goal"),
            editor_font=field("editor_font"),
            default_focus_mode=field("default_focus_mode"),
        )

    async def get_effective_llm_settings(
        self,
        db: AsyncSession,
        project_settings: dict | None,
        *,
        owner_id: uuid.UUID | None = None,
    ) -> EffectiveLLMSettingsResponse:
        account = await get_account_llm_settings_contract(db, owner_id=owner_id)
        configured = list(account.configured_provider_ids)

        def global_value(name: str) -> FieldValueSource:
            return FieldValueSource(value=account.values.get(name), source="global")

        deep_import = (project_settings or {}).get(DEEP_IMPORT_SETTINGS_KEY)
        return EffectiveLLMSettingsResponse(
            provider_id=FieldValueSource(value=account.provider_id, source="global"),
            label=global_value("label"),
            base_url=global_value("base_url"),
            model=global_value("model"),
            timeout=global_value("timeout"),
            max_tokens=global_value("max_tokens"),
            temperature=global_value("temperature"),
            top_p=global_value("top_p"),
            extra=global_value("extra"),
            creative_mode=FieldValueSource(value=None, source="unset"),
            api_key_configured=FieldValueSource(
                value=account.provider_id in configured,
                source=("global" if account.provider_id in configured else "unset"),
            ),
            api_key_configured_providers=FieldValueSource(
                value=configured,
                source="global",
            ),
            deep_import=FieldValueSource(
                value=deep_import,
                source="project" if deep_import else "system",
            ),
        )

    def fully_overridden_project_ids_subquery(self) -> Select[tuple[uuid.UUID]]:
        return select(ProjectAuthorPreferences.project_id).where(
            ProjectAuthorPreferences.daily_goal.is_not(None),
            ProjectAuthorPreferences.editor_font.is_not(None),
            ProjectAuthorPreferences.default_focus_mode.is_not(None),
        )

    @staticmethod
    def build_projects_using_defaults_response(
        projects: Sequence[ProjectSummary],
        total: int,
    ) -> ProjectsUsingDefaultsResponse:
        return ProjectsUsingDefaultsResponse(
            items=[
                ProjectsUsingDefaultsItem(
                    project_id=str(project.project_id),
                    title=project.title,
                    inherited_fields=[],
                )
                for project in projects
            ],
            total=total,
            truncated=total > 100,
        )
