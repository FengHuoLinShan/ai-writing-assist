"""Account-level LLM connection contract tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from infrastructure.llm.balance import ProviderBalance, ProviderBalanceError
from infrastructure.llm.profiles import list_account_provider_templates
from infrastructure.llm.secret_store import (
    decrypt_secret,
    encrypt_secret,
    fingerprint_secret,
)
from modules.account.settings_constants import (
    ACCOUNT_LLM_PROVIDER_TEMPLATES,
    LOCAL_OWNER_ID,
)
from modules.account.settings_models import AccountLLMCredential
from modules.account.settings_repositories import AccountLLMCredentialRepository
from modules.account.settings_service import SettingsService

XHR_HEADERS = {"X-Requested-With": "XMLHttpRequest"}


def test_account_runtime_templates_derive_from_public_catalog() -> None:
    catalog = {item["id"]: item for item in list_account_provider_templates()}

    assert set(ACCOUNT_LLM_PROVIDER_TEMPLATES) == set(catalog)
    for provider_id, runtime in ACCOUNT_LLM_PROVIDER_TEMPLATES.items():
        assert runtime["base_url"] == catalog[provider_id]["base_url"]
        assert runtime["model"] == catalog[provider_id]["default_model"]


@pytest.fixture(autouse=True)
def enable_kimi_contract_tests(monkeypatch):
    """Most tests exercise the gated adapter; one test below checks the default."""

    monkeypatch.setenv("ENABLE_ACCOUNT_KIMI_K3", "1")


@pytest.mark.asyncio
async def test_connect_validates_encrypts_and_activates_atomically(
    db_session,
    monkeypatch,
):
    validate = AsyncMock()
    monkeypatch.setattr(
        "modules.account.settings_service._validate_account_llm_connection",
        validate,
    )

    response = await SettingsService().connect_account_llm_provider(
        db_session,
        "deepseek",
        "unit-test-account-key",
    )

    validate.assert_awaited_once_with("deepseek", "unit-test-account-key")
    assert response.active_provider_id == "deepseek"
    assert response.providers[0].connected is True
    row = (
        await db_session.execute(
            select(AccountLLMCredential).where(
                AccountLLMCredential.owner_id == LOCAL_OWNER_ID,
                AccountLLMCredential.provider_id == "deepseek",
            )
        )
    ).scalar_one()
    assert row.encrypted_api_key["encrypted"] is True
    assert decrypt_secret(row.encrypted_api_key) == "unit-test-account-key"
    assert row.key_fingerprint == fingerprint_secret(
        "unit-test-account-key",
        purpose="account-llm-api-key",
    )
    assert "unit-test-account-key" not in str(response.model_dump())


@pytest.mark.asyncio
async def test_unchanged_verified_key_reactivates_without_validation(
    db_session,
    monkeypatch,
):
    validate = AsyncMock()
    monkeypatch.setattr(
        "modules.account.settings_service._validate_account_llm_connection",
        validate,
    )
    service = SettingsService()
    await service.connect_account_llm_provider(
        db_session,
        "deepseek",
        "unit-test-same-key",
    )
    await service.connect_account_llm_provider(
        db_session,
        "deepseek",
        "unit-test-same-key",
    )

    validate.assert_awaited_once()


@pytest.mark.asyncio
async def test_stale_unkeyed_fingerprint_revalidates_and_upgrades(
    db_session,
    monkeypatch,
):
    validate = AsyncMock()
    monkeypatch.setattr(
        "modules.account.settings_service._validate_account_llm_connection",
        validate,
    )
    service = SettingsService()
    secret = "unit-test-legacy-fingerprint-key"
    await service.connect_account_llm_provider(db_session, "deepseek", secret)
    row = (await db_session.execute(select(AccountLLMCredential))).scalar_one()
    row.key_fingerprint = "0" * 64
    await db_session.flush()

    await service.connect_account_llm_provider(db_session, "deepseek", secret)

    assert validate.await_count == 2
    assert row.key_fingerprint == fingerprint_secret(
        secret,
        purpose="account-llm-api-key",
    )


@pytest.mark.asyncio
async def test_failed_validation_does_not_store_or_activate(
    db_session,
    monkeypatch,
):
    validate = AsyncMock(side_effect=ValueError("API Key 无效"))
    monkeypatch.setattr(
        "modules.account.settings_service._validate_account_llm_connection",
        validate,
    )

    with pytest.raises(ValueError, match="API Key 无效"):
        await SettingsService().connect_account_llm_provider(
            db_session,
            "kimi",
            "unit-test-rejected-key",
        )

    rows = (await db_session.execute(select(AccountLLMCredential))).scalars().all()
    assert rows == []
    state = await SettingsService().get_account_llm_connections(db_session)
    assert state.active_provider_id == "deepseek"
    assert all(not provider.connected for provider in state.providers)


@pytest.mark.asyncio
async def test_clear_active_key_keeps_provider_selected_but_disconnected(
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(
        "modules.account.settings_service._validate_account_llm_connection",
        AsyncMock(),
    )
    service = SettingsService()
    await service.connect_account_llm_provider(
        db_session,
        "kimi",
        "unit-test-kimi-key",
    )

    state = await service.clear_account_llm_provider(db_session, "kimi")

    assert state.active_provider_id == "kimi"
    kimi = next(item for item in state.providers if item.provider_id == "kimi")
    assert kimi.active is True
    assert kimi.connected is False
    with pytest.raises(ValueError, match="尚未连接"):
        await service.resolve_account_llm_runtime_profile(db_session)


@pytest.mark.asyncio
async def test_provider_credentials_are_owner_isolated(db_session):
    repo = AccountLLMCredentialRepository()
    owner_a = uuid.uuid4()
    owner_b = uuid.uuid4()
    now = datetime.now(UTC)
    await repo.upsert(
        db_session,
        {
            "owner_id": owner_a,
            "provider_id": "deepseek",
            "encrypted_api_key": encrypt_secret("owner-a-key"),
            "key_fingerprint": "a" * 64,
            "verified_at": now,
        },
    )
    await repo.upsert(
        db_session,
        {
            "owner_id": owner_b,
            "provider_id": "deepseek",
            "encrypted_api_key": encrypt_secret("owner-b-key"),
            "key_fingerprint": "b" * 64,
            "verified_at": now,
        },
    )

    assert (
        decrypt_secret(
            (await repo.get(db_session, owner_a, "deepseek")).encrypted_api_key
        )
        == "owner-a-key"
    )
    assert (
        decrypt_secret(
            (await repo.get(db_session, owner_b, "deepseek")).encrypted_api_key
        )
        == "owner-b-key"
    )


@pytest.mark.asyncio
async def test_credential_first_insert_lock_is_provider_scoped():
    repo = AccountLLMCredentialRepository()
    db = AsyncMock()
    bind = MagicMock()
    bind.dialect.name = "postgresql"
    db.get_bind = MagicMock(return_value=bind)
    owner_id = uuid.uuid4()

    await repo.lock_owner_provider(db, owner_id, "deepseek")

    statement, params = db.execute.await_args.args
    assert "pg_advisory_xact_lock" in str(statement)
    assert params == {
        "key": f"account_llm_credential:{owner_id}:deepseek",
    }


@pytest.mark.asyncio
async def test_balance_failure_is_auxiliary_and_does_not_disconnect(
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(
        "modules.account.settings_service._validate_account_llm_connection",
        AsyncMock(),
    )
    query = AsyncMock(side_effect=ProviderBalanceError("temporarily_unavailable"))
    monkeypatch.setattr("modules.account.settings_service.query_provider_balance", query)
    service = SettingsService()
    await service.connect_account_llm_provider(
        db_session,
        "deepseek",
        "unit-test-balance-key",
    )

    balances = await service.get_account_llm_balances(db_session)

    assert balances.items[0].status == "unavailable"
    assert balances.items[0].amount is None
    assert balances.items[0].currency is None
    assert (await service.get_account_llm_connections(db_session)).providers[
        0
    ].connected is True


@pytest.mark.asyncio
async def test_balance_success_preserves_original_amount_and_currency(
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(
        "modules.account.settings_service._validate_account_llm_connection",
        AsyncMock(),
    )
    query = AsyncMock(
        return_value=ProviderBalance(
            amount=Decimal("12.50"),
            currency="CNY",
        )
    )
    monkeypatch.setattr("modules.account.settings_service.query_provider_balance", query)
    service = SettingsService()
    await service.connect_account_llm_provider(
        db_session,
        "deepseek",
        "unit-test-balance-key",
    )

    balances = await service.get_account_llm_balances(db_session)

    assert balances.items[0].status == "available"
    assert balances.items[0].amount == "12.50"
    assert balances.items[0].currency == "CNY"


@pytest.mark.asyncio
async def test_connection_api_never_returns_key(
    async_client: AsyncClient,
    monkeypatch,
):
    monkeypatch.setattr(
        "modules.account.settings_service._validate_account_llm_connection",
        AsyncMock(),
    )

    response = await async_client.put(
        "/api/account/settings/llm-connections/deepseek",
        headers=XHR_HEADERS,
        json={"api_key": "unit-test-api-secret"},
    )

    assert response.status_code == 200
    assert "unit-test-api-secret" not in response.text
    assert response.json()["active_provider_id"] == "deepseek"


@pytest.mark.asyncio
async def test_unconnected_provider_cannot_be_activated(
    async_client: AsyncClient,
):
    response = await async_client.post(
        "/api/account/settings/llm-connections/kimi/activate",
        headers=XHR_HEADERS,
    )

    assert response.status_code == 400
    assert "API Key" in response.json()["detail"]


@pytest.mark.asyncio
async def test_unsupported_provider_is_rejected(
    async_client: AsyncClient,
    monkeypatch,
):
    validate = AsyncMock()
    monkeypatch.setattr(
        "modules.account.settings_service._validate_account_llm_connection",
        validate,
    )

    response = await async_client.put(
        "/api/account/settings/llm-connections/openai-compatible",
        headers=XHR_HEADERS,
        json={"api_key": "unit-test-unsupported-key"},
    )

    assert response.status_code == 400
    assert "DeepSeek" in response.json()["detail"]
    validate.assert_not_awaited()


@pytest.mark.asyncio
async def test_kimi_is_hidden_and_rejected_until_real_compatibility_gate(
    async_client: AsyncClient,
    monkeypatch,
):
    monkeypatch.delenv("ENABLE_ACCOUNT_KIMI_K3", raising=False)

    listing = await async_client.get("/api/account/settings/llm-connections")
    connect = await async_client.put(
        "/api/account/settings/llm-connections/kimi",
        headers=XHR_HEADERS,
        json={"api_key": "unit-test-gated-key"},
    )

    assert [item["provider_id"] for item in listing.json()["providers"]] == ["deepseek"]
    assert connect.status_code == 400
    assert "兼容验证" in connect.json()["detail"]
