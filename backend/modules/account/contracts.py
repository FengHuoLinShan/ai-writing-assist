"""Stable cross-module account contracts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

BOOTSTRAP_ACCOUNT_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")


@dataclass(frozen=True)
class AccountPrincipal:
    account_id: uuid.UUID
    status: str
    identity_type: str
    support_code: str
    session_id: uuid.UUID | None = None
    csrf_digest: str | None = None
    reauthenticated_at_epoch: float | None = None
    access_scope: str = "account"
    demo_project_id: uuid.UUID | None = None


@dataclass(frozen=True)
class AccountLLMSettingsContract:
    """Secret-free account defaults used by project effective settings."""

    provider_id: str
    values: dict[str, Any]
    configured_provider_ids: tuple[str, ...]


@dataclass(frozen=True)
class AccountAuthorPreferencesContract:
    """Account preference values with their global/system provenance."""

    values: dict[str, Any]
    sources: dict[str, str]


# ============================================================
# 反向依赖 SPI（AO-4）— account（L0）需要项目 owner 事实时经组合根注册的
# DI port 反转，不 import modules.project。
# ============================================================


@dataclass(frozen=True)
class ProjectOwnerRef:
    """Secret-free owner reference of one project of either kind."""

    owner_id: str | None


class ProjectOwnerContextPort(Protocol):
    """Resolve one project's owner through the project-domain owner gates."""

    async def __call__(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> ProjectOwnerRef | None: ...
