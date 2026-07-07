"""Settings service: upsert, effective merge, field reset, aggregation."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.profiles import get_llm_profile
from modules.project.facade import get_project_by_id, list_active_projects
from modules.settings.constants import (
    AUTHOR_PREFS_DEFAULTS,
    AUTHOR_PREFS_FIELDS,
    LLM_DEFAULTS_SYSTEM,
    LLM_INHERITABLE_FIELDS,
    LOCAL_OWNER_ID,
    SOURCE_GLOBAL,
    SOURCE_PROJECT,
    SOURCE_SYSTEM,
    SOURCE_UNSET,
)
from modules.settings.models import ProjectAuthorPreferences
from modules.settings.repositories import (
    GlobalAuthorPrefsRepository,
    GlobalLLMDefaultsRepository,
    ProjectAuthorPrefsRepository,
)
from modules.settings.schemas import (
    EffectiveAuthorPrefsResponse,
    EffectiveLLMSettingsResponse,
    FieldResetResponse,
    FieldValueSource,
    GlobalAuthorPrefsResponse,
    GlobalLLMDefaultsResponse,
    ProjectAuthorPrefsResponse,
    ProjectsUsingDefaultsItem,
    ProjectsUsingDefaultsResponse,
)
from shared.deep_import_settings import DEEP_IMPORT_SETTINGS_KEY


def _current_owner_id() -> uuid.UUID:
    """Demo 阶段固定 local。未来注入 authorizer。"""
    return LOCAL_OWNER_ID


class SettingsService:
    def __init__(self) -> None:
        self._llm_repo = GlobalLLMDefaultsRepository()
        self._g_prefs_repo = GlobalAuthorPrefsRepository()
        self._p_prefs_repo = ProjectAuthorPrefsRepository()

    # ----- global LLM defaults -----
    async def get_global_llm_defaults(
        self, db: AsyncSession
    ) -> GlobalLLMDefaultsResponse | None:
        row = await self._llm_repo.get(db, _current_owner_id())
        if row is None:
            return None
        return GlobalLLMDefaultsResponse(
            provider_id=row.provider_id,
            label=row.label,
            base_url=row.base_url,
            model=row.model,
            timeout=row.timeout,
            max_tokens=row.max_tokens,
            temperature=row.temperature,
            top_p=row.top_p,
            extra=row.extra,
            creative_mode=row.creative_mode,
            deep_import=row.deep_import,  # 本期永远 None
        )

    async def upsert_global_llm_defaults(
        self, db: AsyncSession, payload: dict
    ) -> GlobalLLMDefaultsResponse:
        # D8 硬拒绝 api_key
        if "api_key" in payload or "api_key_configured" in payload:
            raise ValueError("global LLM defaults must not contain api_key")
        data = {k: v for k, v in payload.items() if k in LLM_INHERITABLE_FIELDS}
        data["owner_id"] = _current_owner_id()
        row = await self._llm_repo.upsert(db, data)
        return GlobalLLMDefaultsResponse(
            provider_id=row.provider_id,
            label=row.label,
            base_url=row.base_url,
            model=row.model,
            timeout=row.timeout,
            max_tokens=row.max_tokens,
            temperature=row.temperature,
            top_p=row.top_p,
            extra=row.extra,
            creative_mode=row.creative_mode,
            deep_import=row.deep_import,
        )

    # ----- global author prefs -----
    async def get_global_author_prefs(
        self, db: AsyncSession
    ) -> GlobalAuthorPrefsResponse | None:
        row = await self._g_prefs_repo.get(db, _current_owner_id())
        if row is None:
            return None
        return GlobalAuthorPrefsResponse(
            daily_goal=row.daily_goal,
            editor_font=row.editor_font,
            default_focus_mode=row.default_focus_mode,
        )

    async def get_or_system_author_prefs(
        self, db: AsyncSession
    ) -> GlobalAuthorPrefsResponse:
        resp = await self.get_global_author_prefs(db)
        if resp is None:
            return GlobalAuthorPrefsResponse(
                **{k: AUTHOR_PREFS_DEFAULTS[k] for k in AUTHOR_PREFS_DEFAULTS},
            )
        return resp

    async def upsert_global_author_prefs(
        self, db: AsyncSession, payload: dict
    ) -> GlobalAuthorPrefsResponse:
        data = {k: v for k, v in payload.items() if k in AUTHOR_PREFS_FIELDS}
        data["owner_id"] = _current_owner_id()
        row = await self._g_prefs_repo.upsert(db, data)
        return GlobalAuthorPrefsResponse(
            daily_goal=row.daily_goal,
            editor_font=row.editor_font,
            default_focus_mode=row.default_focus_mode,
        )

    # ----- project author prefs -----
    async def get_project_author_prefs(
        self, db: AsyncSession, project_id: uuid.UUID | str
    ) -> ProjectAuthorPrefsResponse:
        pid = project_id if isinstance(project_id, uuid.UUID) else uuid.UUID(project_id)
        row = await self._p_prefs_repo.get(db, pid)
        if row is None:
            # D13 不抛 404，返回全 NULL 空对象
            return ProjectAuthorPrefsResponse()
        return ProjectAuthorPrefsResponse(
            daily_goal=row.daily_goal,
            editor_font=row.editor_font,
            default_focus_mode=row.default_focus_mode,
        )

    async def upsert_project_author_prefs(
        self, db: AsyncSession, project_id: uuid.UUID | str, payload: dict
    ) -> ProjectAuthorPrefsResponse:
        pid = project_id if isinstance(project_id, uuid.UUID) else uuid.UUID(project_id)
        data = {k: v for k, v in payload.items() if k in AUTHOR_PREFS_FIELDS}
        data["project_id"] = pid
        row = await self._p_prefs_repo.upsert(db, data)
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
        if field_name not in AUTHOR_PREFS_FIELDS:
            raise ValueError(f"unknown author prefs field: {field_name}")
        pid = project_id if isinstance(project_id, uuid.UUID) else uuid.UUID(project_id)
        await self._p_prefs_repo.reset_field(db, pid, field_name)
        return FieldResetResponse(field=field_name, reset=True)

    # ----- effective views -----
    async def get_effective_author_prefs(
        self, db: AsyncSession, project_id: uuid.UUID | str
    ) -> EffectiveAuthorPrefsResponse:
        pid = project_id if isinstance(project_id, uuid.UUID) else uuid.UUID(project_id)
        proj_row = await self._p_prefs_repo.get(db, pid)
        glob_row = await self._g_prefs_repo.get(db, _current_owner_id())

        def pack(field_name: str) -> FieldValueSource:
            if proj_row is not None and getattr(proj_row, field_name) is not None:
                return FieldValueSource(
                    value=getattr(proj_row, field_name), source=SOURCE_PROJECT
                )
            if glob_row is not None and getattr(glob_row, field_name) is not None:
                return FieldValueSource(
                    value=getattr(glob_row, field_name), source=SOURCE_GLOBAL
                )
            return FieldValueSource(
                value=AUTHOR_PREFS_DEFAULTS[field_name], source=SOURCE_SYSTEM
            )

        return EffectiveAuthorPrefsResponse(
            daily_goal=pack("daily_goal"),
            editor_font=pack("editor_font"),
            default_focus_mode=pack("default_focus_mode"),
        )

    async def get_effective_llm_settings(
        self, db: AsyncSession, project_id: uuid.UUID | str
    ) -> EffectiveLLMSettingsResponse:
        pid = project_id if isinstance(project_id, uuid.UUID) else uuid.UUID(project_id)
        project = await get_project_by_id(db, pid)
        if project is None:
            raise LookupError(f"project {project_id} not found")
        proj_profile = get_llm_profile(project.settings) if project.settings else {}
        # deep_import 是 settings 顶层 sibling，不在 settings["llm"] 内（D6 atomic）
        proj_deep_import = (project.settings or {}).get(DEEP_IMPORT_SETTINGS_KEY)
        glob_row = await self._llm_repo.get(db, _current_owner_id())
        glob_profile = (
            {f: getattr(glob_row, f) for f in LLM_INHERITABLE_FIELDS} if glob_row else {}
        )

        def pack(
            field_name: str, *, default_val, allow_unset: bool = False
        ) -> FieldValueSource:
            proj_v = proj_profile.get(field_name)
            if proj_v is not None and proj_v != "":
                return FieldValueSource(value=proj_v, source=SOURCE_PROJECT)
            glob_v = glob_profile.get(field_name)
            if glob_v is not None:
                return FieldValueSource(value=glob_v, source=SOURCE_GLOBAL)
            sys_v = default_val
            if sys_v is None and allow_unset:
                return FieldValueSource(value=None, source=SOURCE_UNSET)
            return FieldValueSource(value=sys_v, source=SOURCE_SYSTEM)

        return EffectiveLLMSettingsResponse(
            provider_id=pack(
                "provider_id", default_val=LLM_DEFAULTS_SYSTEM["provider_id"]
            ),
            label=pack(
                "label", default_val=LLM_DEFAULTS_SYSTEM["label"], allow_unset=True
            ),
            base_url=pack("base_url", default_val=LLM_DEFAULTS_SYSTEM["base_url"]),
            model=pack("model", default_val=LLM_DEFAULTS_SYSTEM["model"]),
            timeout=pack("timeout", default_val=LLM_DEFAULTS_SYSTEM["timeout"]),
            max_tokens=pack("max_tokens", default_val=LLM_DEFAULTS_SYSTEM["max_tokens"]),
            temperature=pack(
                "temperature", default_val=LLM_DEFAULTS_SYSTEM["temperature"]
            ),
            top_p=pack(
                "top_p", default_val=LLM_DEFAULTS_SYSTEM["top_p"], allow_unset=True
            ),
            extra=pack("extra", default_val=LLM_DEFAULTS_SYSTEM["extra"]),
            creative_mode=pack(
                "creative_mode",
                default_val=LLM_DEFAULTS_SYSTEM["creative_mode"],
                allow_unset=True,
            ),
            api_key_configured=FieldValueSource(
                value=bool(proj_profile.get("api_key")),
                source=SOURCE_PROJECT if proj_profile.get("api_key") else SOURCE_UNSET,
            ),
            deep_import=FieldValueSource(
                value=proj_deep_import,
                source=SOURCE_PROJECT if proj_deep_import else SOURCE_SYSTEM,
            ),
        )

    # ----- aggregation -----
    async def list_projects_using_defaults(
        self,
        db: AsyncSession,
        limit: int = 50,
        offset: int = 0,
    ) -> ProjectsUsingDefaultsResponse:
        """D18: 仅统计作者偏好默认；任一字段为 NULL 或行不存在即视为继承默认。"""
        from sqlalchemy import select

        all_projects = await list_active_projects(db)
        prefs_rows = await db.execute(select(ProjectAuthorPreferences))
        prefs_by_pid = {row.project_id: row for row in prefs_rows.scalars().all()}

        inheriting: list[uuid.UUID] = []
        for proj in all_projects:
            row = prefs_by_pid.get(proj.id)
            if row is None:
                inheriting.append(proj.id)
                continue
            if (
                row.daily_goal is None
                or row.editor_font is None
                or row.default_focus_mode is None
            ):
                inheriting.append(proj.id)

        total = len(inheriting)
        truncated = total > 100
        page = inheriting[offset : offset + limit]
        title_by_id = {p.id: p.title for p in all_projects}
        items = [
            ProjectsUsingDefaultsItem(
                project_id=str(pid),
                title=title_by_id.get(pid, ""),
                inherited_fields=[],
            )
            for pid in page
        ]
        return ProjectsUsingDefaultsResponse(
            items=items, total=total, truncated=truncated
        )
