from __future__ import annotations

import uuid

from core.config import get_settings
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID, AccountPrincipal
from modules.account.facade import current_owner_id_or_system_none


def test_closed_test_without_principal_is_scoped_to_bootstrap_owner(
    monkeypatch,
) -> None:
    monkeypatch.setenv("AUTH_MODE", "closed_test")
    get_settings.cache_clear()
    try:
        assert current_owner_id_or_system_none() == BOOTSTRAP_ACCOUNT_ID
    finally:
        get_settings.cache_clear()


def test_public_worker_without_principal_uses_explicit_system_seam(
    monkeypatch,
) -> None:
    monkeypatch.setenv("AUTH_MODE", "public")
    get_settings.cache_clear()
    try:
        assert current_owner_id_or_system_none() is None
    finally:
        get_settings.cache_clear()


def test_bound_principal_always_wins_over_runtime_mode(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "public")
    get_settings.cache_clear()
    account_id = uuid.uuid4()
    token = bind_principal(
        AccountPrincipal(
            account_id=account_id,
            status="active",
            identity_type="email",
            support_code="U-TESTOWNER",
        )
    )
    try:
        assert current_owner_id_or_system_none() == account_id
    finally:
        reset_principal(token)
        get_settings.cache_clear()
