"""Stable cross-module account contracts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

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
