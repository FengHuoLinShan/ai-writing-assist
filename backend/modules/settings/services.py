"""Settings service: upsert, effective merge, field reset, aggregation."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from core.config import get_settings
from infrastructure.llm.balance import (
    ProviderBalanceError,
    query_provider_balance,
)
from infrastructure.llm.health import LLMHealthChecker
from infrastructure.llm.image_client import ImageGenerationError, OpenAIImageClient
from infrastructure.llm.secret_store import (
    decrypt_secret,
    encrypt_secret,
    fingerprint_secret,
)
from modules.project.contracts import ProjectSummary
from modules.settings.constants import (
    ACCOUNT_LLM_PROVIDER_TEMPLATES,
    AUTHOR_PREFS_DEFAULTS,
    AUTHOR_PREFS_FIELDS,
    LLM_INHERITABLE_FIELDS,
    SOURCE_GLOBAL,
    SOURCE_PROJECT,
    SOURCE_SYSTEM,
    SOURCE_UNSET,
    account_llm_provider_enabled,
    enabled_account_llm_provider_order,
)
from modules.settings.models import ProjectAuthorPreferences
from modules.settings.repositories import (
    AccountLLMCredentialRepository,
    GlobalAuthorPrefsRepository,
    GlobalLLMDefaultsRepository,
    ProjectAuthorPrefsRepository,
)
from modules.settings.schemas import (
    AccountImageConnectionResponse,
    AccountImageRuntimeProfile,
    AccountLLMBalanceItem,
    AccountLLMBalancesResponse,
    AccountLLMConnectionsResponse,
    AccountLLMProviderState,
    AccountLLMRuntimeProfile,
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

_IMAGE_PROVIDER_ID = "openai-image"


def _current_owner_id(owner_id: uuid.UUID | None = None) -> uuid.UUID:
    """Resolve a browser owner while preserving the local bootstrap identity."""
    if owner_id is not None:
        return owner_id
    from modules.account.facade import current_account_id

    return current_account_id()


async def _validate_account_llm_connection(
    provider_id: str,
    api_key: str,
) -> None:
    """Perform the required minimal real generation before accepting a key."""

    template = ACCOUNT_LLM_PROVIDER_TEMPLATES[provider_id]
    settings = get_settings()
    checker = LLMHealthChecker(
        api_key=api_key,
        base_url=str(template["base_url"]),
        model=str(template["model"]),
        trust_env=settings.llm_trust_env,
        proxy_url=settings.llm_proxy_url,
        timeout=30,
    )
    result = await checker.check()
    if result.ok:
        return
    if result.error_kind == "auth_error":
        message = "API Key 无效或没有使用该模型的权限"
    elif result.error_kind == "rate_limit":
        message = "模型请求过于频繁或当前额度不可用"
    else:
        message = "暂时无法验证模型连接，请稍后重试"
    raise ValueError(message)


class SettingsService:
    def __init__(self) -> None:
        self._llm_repo = GlobalLLMDefaultsRepository()
        self._credential_repo = AccountLLMCredentialRepository()
        self._g_prefs_repo = GlobalAuthorPrefsRepository()
        self._p_prefs_repo = ProjectAuthorPrefsRepository()

    # ----- account image connection -----
    async def get_account_image_connection(
        self,
        db: AsyncSession,
        owner_id: uuid.UUID | None = None,
    ) -> AccountImageConnectionResponse:
        resolved_owner = _current_owner_id(owner_id)
        row = await self._credential_repo.get(
            db,
            resolved_owner,
            _IMAGE_PROVIDER_ID,
        )
        return AccountImageConnectionResponse(
            connected=row is not None,
            verified_at=row.verified_at if row is not None else None,
        )

    async def connect_account_image_provider(
        self,
        db: AsyncSession,
        api_key: str,
    ) -> AccountImageConnectionResponse:
        owner_id = _current_owner_id()
        fingerprint = fingerprint_secret(
            api_key,
            purpose="account-image-api-key",
        )
        await self._credential_repo.lock_owner_provider(
            db,
            owner_id,
            _IMAGE_PROVIDER_ID,
        )
        existing = await self._credential_repo.get(
            db,
            owner_id,
            _IMAGE_PROVIDER_ID,
        )
        unchanged_verified = (
            existing is not None
            and existing.key_fingerprint == fingerprint
            and existing.verified_at is not None
        )
        if not unchanged_verified:
            client = OpenAIImageClient(api_key=api_key, timeout=30)
            try:
                await client.verify_connection()
            except ImageGenerationError as exc:
                raise ValueError(str(exc)) from exc
            finally:
                await client.close()
        now = datetime.now(UTC)
        await self._credential_repo.upsert(
            db,
            {
                "owner_id": owner_id,
                "provider_id": _IMAGE_PROVIDER_ID,
                "encrypted_api_key": (
                    existing.encrypted_api_key
                    if unchanged_verified and existing is not None
                    else encrypt_secret(api_key)
                ),
                "key_fingerprint": fingerprint,
                "verified_at": (
                    existing.verified_at
                    if unchanged_verified and existing is not None
                    else now
                ),
            },
        )
        return await self.get_account_image_connection(db, owner_id)

    async def clear_account_image_provider(
        self,
        db: AsyncSession,
    ) -> AccountImageConnectionResponse:
        owner_id = _current_owner_id()
        await self._credential_repo.lock_owner_provider(
            db,
            owner_id,
            _IMAGE_PROVIDER_ID,
        )
        await self._credential_repo.delete(db, owner_id, _IMAGE_PROVIDER_ID)
        return await self.get_account_image_connection(db, owner_id)

    async def resolve_account_image_runtime_profile(
        self,
        db: AsyncSession,
        *,
        owner_id: uuid.UUID | None = None,
    ) -> AccountImageRuntimeProfile:
        resolved_owner = _current_owner_id(owner_id)
        row = await self._credential_repo.get(
            db,
            resolved_owner,
            _IMAGE_PROVIDER_ID,
        )
        if row is None:
            raise ValueError(
                "账户图片服务尚未连接，请先在账户设置中填写 OpenAI API Key"
            )
        try:
            api_key = decrypt_secret(row.encrypted_api_key)
        except ValueError as exc:
            raise ValueError("账户图片连接无法读取，请重新填写 API Key") from exc
        if not api_key:
            raise ValueError(
                "账户图片服务尚未连接，请先在账户设置中填写 OpenAI API Key"
            )
        return AccountImageRuntimeProfile(api_key=api_key)

    # ----- account LLM connections -----
    @staticmethod
    def _require_account_provider(provider_id: str) -> dict:
        template = ACCOUNT_LLM_PROVIDER_TEMPLATES.get(provider_id)
        if template is None:
            raise ValueError("仅支持 DeepSeek 和 Kimi")
        if not account_llm_provider_enabled(provider_id):
            raise ValueError("Kimi K3 仍在兼容验证中，暂不可用")
        return template

    async def get_account_llm_connections(
        self,
        db: AsyncSession,
        owner_id: uuid.UUID | None = None,
    ) -> AccountLLMConnectionsResponse:
        resolved_owner = _current_owner_id(owner_id)
        defaults = await self._llm_repo.get(db, resolved_owner)
        enabled_order = enabled_account_llm_provider_order()
        active_provider = (
            defaults.provider_id
            if defaults is not None and account_llm_provider_enabled(defaults.provider_id)
            else enabled_order[0]
        )
        rows = await self._credential_repo.list_for_owner(db, resolved_owner)
        by_provider = {row.provider_id: row for row in rows}
        providers = []
        for provider_id in enabled_order:
            template = ACCOUNT_LLM_PROVIDER_TEMPLATES[provider_id]
            row = by_provider.get(provider_id)
            providers.append(
                AccountLLMProviderState(
                    provider_id=provider_id,
                    label=str(template["label"]),
                    model=str(template["model"]),
                    connected=row is not None,
                    active=provider_id == active_provider,
                    verified_at=row.verified_at if row is not None else None,
                )
            )
        return AccountLLMConnectionsResponse(
            active_provider_id=active_provider,
            providers=providers,
        )

    async def connect_account_llm_provider(
        self,
        db: AsyncSession,
        provider_id: str,
        api_key: str,
    ) -> AccountLLMConnectionsResponse:
        template = self._require_account_provider(provider_id)
        owner_id = _current_owner_id()
        fingerprint = fingerprint_secret(api_key, purpose="account-llm-api-key")
        await self._credential_repo.lock_owner_provider(
            db,
            owner_id,
            provider_id,
        )
        await self._llm_repo.lock_owner_head(db, owner_id)
        existing = await self._credential_repo.get(db, owner_id, provider_id)
        unchanged_verified = (
            existing is not None
            and existing.key_fingerprint == fingerprint
            and existing.verified_at is not None
        )
        if not unchanged_verified:
            await _validate_account_llm_connection(provider_id, api_key)
        now = datetime.now(UTC)
        if unchanged_verified:
            encrypted_api_key = existing.encrypted_api_key
            verified_at = existing.verified_at
        else:
            encrypted_api_key = encrypt_secret(api_key)
            verified_at = now
        await self._credential_repo.upsert(
            db,
            {
                "owner_id": owner_id,
                "provider_id": provider_id,
                "encrypted_api_key": encrypted_api_key,
                "key_fingerprint": fingerprint,
                "verified_at": verified_at,
            },
        )
        await self._llm_repo.upsert(
            db,
            {
                "owner_id": owner_id,
                **template,
                "creative_mode": None,
                "deep_import": None,
            },
        )
        return await self.get_account_llm_connections(db, owner_id)

    async def activate_account_llm_provider(
        self,
        db: AsyncSession,
        provider_id: str,
    ) -> AccountLLMConnectionsResponse:
        template = self._require_account_provider(provider_id)
        owner_id = _current_owner_id()
        await self._credential_repo.lock_owner_provider(
            db,
            owner_id,
            provider_id,
        )
        await self._llm_repo.lock_owner_head(db, owner_id)
        credential = await self._credential_repo.get(db, owner_id, provider_id)
        if credential is None:
            raise ValueError("请先填写并验证 API Key")
        await self._llm_repo.upsert(
            db,
            {
                "owner_id": owner_id,
                **template,
                "creative_mode": None,
                "deep_import": None,
            },
        )
        return await self.get_account_llm_connections(db, owner_id)

    async def clear_account_llm_provider(
        self,
        db: AsyncSession,
        provider_id: str,
    ) -> AccountLLMConnectionsResponse:
        self._require_account_provider(provider_id)
        owner_id = _current_owner_id()
        await self._credential_repo.lock_owner_provider(
            db,
            owner_id,
            provider_id,
        )
        await self._llm_repo.lock_owner_head(db, owner_id)
        await self._credential_repo.delete(db, owner_id, provider_id)
        return await self.get_account_llm_connections(db, owner_id)

    async def resolve_account_llm_runtime_profile(
        self,
        db: AsyncSession,
        *,
        owner_id: uuid.UUID | None = None,
        provider_id: str | None = None,
    ) -> AccountLLMRuntimeProfile:
        resolved_owner = _current_owner_id(owner_id)
        if provider_id is None:
            defaults = await self._llm_repo.get(db, resolved_owner)
            provider_id = (
                defaults.provider_id
                if defaults is not None
                and account_llm_provider_enabled(defaults.provider_id)
                else enabled_account_llm_provider_order()[0]
            )
        template = self._require_account_provider(provider_id)
        credential = await self._credential_repo.get(
            db,
            resolved_owner,
            provider_id,
        )
        if credential is None:
            raise ValueError("账户模型尚未连接，请先在账户设置中填写 API Key")
        try:
            api_key = decrypt_secret(credential.encrypted_api_key)
        except ValueError as exc:
            raise ValueError("账户模型连接无法读取，请重新填写 API Key") from exc
        if not api_key:
            raise ValueError("账户模型尚未连接，请先在账户设置中填写 API Key")
        return AccountLLMRuntimeProfile(api_key=api_key, **template)

    async def get_account_llm_balances(
        self,
        db: AsyncSession,
    ) -> AccountLLMBalancesResponse:
        owner_id = _current_owner_id()
        credentials = {
            row.provider_id: row
            for row in await self._credential_repo.list_for_owner(db, owner_id)
            if row.provider_id in ACCOUNT_LLM_PROVIDER_TEMPLATES
        }

        async def query(provider_id: str) -> AccountLLMBalanceItem:
            queried_at = datetime.now(UTC)
            row = credentials[provider_id]
            try:
                api_key = decrypt_secret(row.encrypted_api_key)
                balance = await query_provider_balance(provider_id, api_key)
            except (ProviderBalanceError, ValueError, RuntimeError):
                return AccountLLMBalanceItem(
                    provider_id=provider_id,
                    status="unavailable",
                    queried_at=queried_at,
                )
            return AccountLLMBalanceItem(
                provider_id=provider_id,
                status="available",
                amount=format(balance.amount, "f"),
                currency=balance.currency,
                queried_at=queried_at,
            )

        items = await asyncio.gather(
            *(
                query(provider_id)
                for provider_id in enabled_account_llm_provider_order()
                if provider_id in credentials
            )
        )
        return AccountLLMBalancesResponse(items=list(items))

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
        connection_fields = {"provider_id", "label", "base_url", "model"}
        if connection_fields & payload.keys():
            raise ValueError("模型连接只能在账户模型连接入口中切换")
        data = {k: v for k, v in payload.items() if k in LLM_INHERITABLE_FIELDS}
        owner_id = _current_owner_id()
        await self._llm_repo.lock_owner_head(db, owner_id)
        data["owner_id"] = owner_id
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

    async def get_effective_llm_settings_for_project_settings(
        self,
        db: AsyncSession,
        project_settings: dict | None,
        owner_id: uuid.UUID | None = None,
    ) -> EffectiveLLMSettingsResponse:
        resolved_owner = _current_owner_id(owner_id)
        proj_deep_import = (project_settings or {}).get(DEEP_IMPORT_SETTINGS_KEY)
        glob_row = await self._llm_repo.get(db, resolved_owner)
        provider_id = (
            glob_row.provider_id
            if glob_row is not None and account_llm_provider_enabled(glob_row.provider_id)
            else enabled_account_llm_provider_order()[0]
        )
        template = ACCOUNT_LLM_PROVIDER_TEMPLATES[provider_id]
        credentials = await self._credential_repo.list_for_owner(db, resolved_owner)
        configured_providers = sorted(
            row.provider_id
            for row in credentials
            if account_llm_provider_enabled(row.provider_id)
        )

        def account_value(field_name: str) -> FieldValueSource:
            return FieldValueSource(
                value=template.get(field_name),
                source=SOURCE_GLOBAL,
            )

        return EffectiveLLMSettingsResponse(
            provider_id=account_value("provider_id"),
            label=account_value("label"),
            base_url=account_value("base_url"),
            model=account_value("model"),
            timeout=account_value("timeout"),
            max_tokens=account_value("max_tokens"),
            temperature=account_value("temperature"),
            top_p=account_value("top_p"),
            extra=account_value("extra"),
            creative_mode=FieldValueSource(
                value=None,
                source=SOURCE_UNSET,
            ),
            api_key_configured=FieldValueSource(
                value=provider_id in configured_providers,
                source=SOURCE_GLOBAL
                if provider_id in configured_providers
                else SOURCE_UNSET,
            ),
            api_key_configured_providers=FieldValueSource(
                value=configured_providers,
                source=SOURCE_GLOBAL,
            ),
            deep_import=FieldValueSource(
                value=proj_deep_import,
                source=SOURCE_PROJECT if proj_deep_import else SOURCE_SYSTEM,
            ),
        )

    # ----- aggregation -----
    def fully_overridden_project_ids_subquery(self) -> Select[tuple[uuid.UUID]]:
        """D18: projects with every preference overridden, for DB-side exclusion."""
        return select(ProjectAuthorPreferences.project_id).where(
            ProjectAuthorPreferences.daily_goal.is_not(None),
            ProjectAuthorPreferences.editor_font.is_not(None),
            ProjectAuthorPreferences.default_focus_mode.is_not(None),
        )

    def build_projects_using_defaults_response(
        self,
        projects: Sequence[ProjectSummary],
        total: int,
    ) -> ProjectsUsingDefaultsResponse:
        truncated = total > 100
        items = [
            ProjectsUsingDefaultsItem(
                project_id=str(project.project_id),
                title=project.title,
                inherited_fields=[],
            )
            for project in projects
        ]
        return ProjectsUsingDefaultsResponse(
            items=items, total=total, truncated=truncated
        )
