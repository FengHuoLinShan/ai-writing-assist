"""Stable account facade used by project and settings modules."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from core.errors import NotFoundError
from modules.account.context import current_principal as _current_principal
from modules.account.contracts import (
    BOOTSTRAP_ACCOUNT_ID,
    AccountAuthorPreferencesContract,
    AccountLLMSettingsContract,
    AccountPrincipal,
)
from modules.account.models import Account
from modules.account.settings_schemas import (
    AccountImageRuntimeProfile,
    AccountLLMRuntimeProfile,
)
from modules.account.settings_service import SettingsService

_settings_service = SettingsService()


def current_account_id() -> uuid.UUID:
    principal = _current_principal()
    if principal is not None:
        return principal.account_id
    if get_settings().auth_mode in {"local", "closed_test"}:
        return BOOTSTRAP_ACCOUNT_ID
    raise NotFoundError("Account not found")


def current_account_principal() -> AccountPrincipal | None:
    """Return the request principal for owner-aware domain gates."""
    return _current_principal()


def current_owner_id_or_system_none() -> uuid.UUID | None:
    """Resolve browser ownership while preserving the public worker seam.

    Local and closed-test HTTP calls always represent the bootstrap account.
    Only public-mode code running without a bound request principal may use
    ``None`` as the explicit worker/system identity.
    """

    principal = _current_principal()
    if principal is not None:
        return principal.account_id
    if get_settings().auth_mode in {"local", "closed_test"}:
        return BOOTSTRAP_ACCOUNT_ID
    return None


async def require_account_active(
    db: AsyncSession,
    account_id: uuid.UUID | None,
    *,
    allow_local_bootstrap: bool = True,
) -> None:
    settings = get_settings()
    if (
        allow_local_bootstrap
        and account_id == BOOTSTRAP_ACCOUNT_ID
        and settings.auth_mode in {"local", "closed_test"}
    ):
        return
    account = (
        await db.execute(
            select(Account).where(Account.id == account_id).with_for_update(read=True)
        )
    ).scalar_one_or_none()
    if account is None or account.status != "active":
        raise NotFoundError("Account not found")


async def resolve_account_image_runtime_profile(
    db: AsyncSession,
    *,
    owner_id: uuid.UUID | None = None,
) -> AccountImageRuntimeProfile:
    return await _settings_service.resolve_account_image_runtime_profile(
        db,
        owner_id=owner_id,
    )


async def resolve_account_llm_runtime_profile(
    db: AsyncSession,
    *,
    owner_id: uuid.UUID | None = None,
    provider_id: str | None = None,
) -> AccountLLMRuntimeProfile:
    return await _settings_service.resolve_account_llm_runtime_profile(
        db,
        owner_id=owner_id,
        provider_id=provider_id,
    )


async def get_account_llm_settings_contract(
    db: AsyncSession,
    *,
    owner_id: uuid.UUID | None = None,
) -> AccountLLMSettingsContract:
    return await _settings_service.get_llm_settings_contract(db, owner_id=owner_id)


async def get_account_author_preferences_contract(
    db: AsyncSession,
    *,
    owner_id: uuid.UUID | None = None,
) -> AccountAuthorPreferencesContract:
    return await _settings_service.get_author_preferences_contract(
        db,
        owner_id=owner_id,
    )
