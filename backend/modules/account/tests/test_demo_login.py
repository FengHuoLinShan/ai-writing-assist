from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import replace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import Settings
from core.errors import ConflictError, NotFoundError, ValidationError
from modules.account.constants import DEMO_SHARED_IDENTITY_TYPE
from modules.account.models import (
    Account,
    AccountConsent,
    AccountSecurityEvent,
    WebSession,
)
from modules.account.services import service

pytestmark = pytest.mark.asyncio

SECRET = "demo-pass-123456"


class _MiddlewareSessionManager:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @asynccontextmanager
    async def session(self):
        yield self._session


def _settings(account_id: uuid.UUID) -> Settings:
    return Settings(
        auth_mode="public",
        auth_secret_key="test-secret-key-with-at-least-32-bytes",
        public_demo_login_enabled=True,
        public_demo_login_account_id=str(account_id),
        public_demo_login_secret=SECRET,
    )


async def _seed_account(db_session, *, status: str = "active") -> Account:
    account = Account(status=status, support_code=f"U-{uuid.uuid4().hex[:10].upper()}")
    db_session.add(account)
    await db_session.flush()
    return account


def _call(db_session, settings, secret=SECRET, *, accept=True, peer="203.0.113.9"):
    return service.create_demo_login_session(
        db_session,
        secret=secret,
        accept_terms=accept,
        accept_privacy=accept,
        peer=peer,
        settings=settings,
    )


async def test_demo_login_config_fails_closed(db_session) -> None:
    base = _settings(uuid.uuid4())
    for invalid in (
        replace(base, public_demo_login_enabled=False),
        replace(base, public_demo_login_account_id="not-a-uuid"),
        replace(base, public_demo_login_secret="short"),
        replace(base, public_demo_login_secret=""),
    ):
        with pytest.raises(NotFoundError):
            await _call(db_session, invalid)


async def test_demo_login_rejects_missing_consent_before_any_state(db_session) -> None:
    account = await _seed_account(db_session)
    with pytest.raises(ValidationError, match="用户协议"):
        await _call(db_session, _settings(account.id), accept=False)
    assert (await db_session.execute(select(WebSession))).scalars().all() == []
    assert (await db_session.execute(select(AccountSecurityEvent))).scalars().all() == []


async def test_demo_login_success_issues_full_session_with_consent_and_event(
    db_session,
) -> None:
    account = await _seed_account(db_session)
    result = await _call(db_session, _settings(account.id), peer="198.51.100.7")

    assert result.me.identity_type == DEMO_SHARED_IDENTITY_TYPE
    assert result.me.id == str(account.id)
    session = await db_session.get(WebSession, result.principal.session_id)
    assert session is not None
    assert session.identity_type == DEMO_SHARED_IDENTITY_TYPE
    assert session.token_digest != result.session_token
    assert session.csrf_digest != result.csrf_token
    consents = {
        (row.policy_type, row.version)
        for row in (
            await db_session.execute(
                select(AccountConsent).where(AccountConsent.account_id == account.id)
            )
        ).scalars()
    }
    settings = _settings(account.id)
    assert ("terms", settings.terms_version) in consents
    assert ("privacy", settings.privacy_version) in consents
    events = (
        (
            await db_session.execute(
                select(AccountSecurityEvent).where(
                    AccountSecurityEvent.account_id == account.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert [event.event_type for event in events] == ["demo_login_succeeded"]

    # Idempotent consent: a second login does not duplicate policy rows.
    await _call(db_session, settings)
    consent_rows = (
        (
            await db_session.execute(
                select(AccountConsent).where(AccountConsent.account_id == account.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(consent_rows) == 2


async def test_demo_login_revokes_previous_sessions(db_session) -> None:
    account = await _seed_account(db_session)
    first = await _call(db_session, _settings(account.id))
    second = await _call(db_session, _settings(account.id))
    old = await db_session.get(WebSession, first.principal.session_id)
    assert old is not None and old.revoked_at is not None
    current = await db_session.get(WebSession, second.principal.session_id)
    assert current is not None and current.revoked_at is None


async def test_demo_login_wrong_secret_rejected_then_throttled(db_session) -> None:
    account = await _seed_account(db_session)
    settings = _settings(account.id)
    for _ in range(5):
        with pytest.raises(ValidationError, match="演示口令无效"):
            await _call(db_session, settings, secret="wrong-secret")
    rejections = (
        (
            await db_session.execute(
                select(AccountSecurityEvent).where(
                    AccountSecurityEvent.event_type == "demo_login_rejected"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rejections) == 5
    with pytest.raises(ConflictError, match="过于频繁"):
        await _call(db_session, settings, secret=SECRET)
    # Another peer is not affected by this throttle window.
    other_peer = await service.create_demo_login_session(
        db_session,
        secret=SECRET,
        accept_terms=True,
        accept_privacy=True,
        peer="198.51.100.99",
        settings=settings,
    )
    assert other_peer.me.id == str(account.id)


async def test_demo_login_rejects_unusable_account(db_session) -> None:
    banned = await _seed_account(db_session, status="banned")
    with pytest.raises(NotFoundError):
        await _call(db_session, _settings(banned.id))
    events = (
        (
            await db_session.execute(
                select(AccountSecurityEvent).where(
                    AccountSecurityEvent.event_type == "demo_login_unavailable"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 1

    missing = uuid.uuid4()
    with pytest.raises(NotFoundError):
        await _call(db_session, _settings(missing))


@pytest.mark.asyncio
async def test_demo_login_route_end_to_end(
    db_session,
    async_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    from core.config import get_settings

    account_id = uuid.uuid4()
    monkeypatch.setenv("AUTH_MODE", "public")
    monkeypatch.setenv("AUTH_SECRET_KEY", "x" * 32)
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://test")
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://test")
    monkeypatch.setenv("PUBLIC_DEMO_LOGIN_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_DEMO_LOGIN_ACCOUNT_ID", str(account_id))
    monkeypatch.setenv("PUBLIC_DEMO_LOGIN_SECRET", SECRET)
    monkeypatch.setattr(
        "modules.account.middleware.get_manager",
        lambda: _MiddlewareSessionManager(db_session),
    )
    get_settings.cache_clear()
    db_session.add(Account(id=account_id, status="active", support_code="U-ROUTE01AA"))
    await db_session.flush()

    try:
        config = await async_client.get("/api/auth/config")
        assert config.status_code == 200
        assert config.json()["demo_login_enabled"] is True

        headers = {"Origin": "http://test"}
        rejected = await async_client.post(
            "/api/auth/demo-login",
            headers=headers,
            json={
                "secret": "wrong-secret",
                "accept_terms": True,
                "accept_privacy": True,
            },
        )
        assert rejected.status_code == 400

        accepted = await async_client.post(
            "/api/auth/demo-login",
            headers=headers,
            json={
                "secret": SECRET,
                "accept_terms": True,
                "accept_privacy": True,
            },
        )
        assert accepted.status_code == 200
        body = accepted.json()
        assert body["id"] == str(account_id)
        assert body["identity_type"] == "demo_shared"
        assert "aaw_session" in async_client.cookies

        me = await async_client.get("/api/auth/me")
        assert me.status_code == 200
        assert me.json()["identity_type"] == "demo_shared"
    finally:
        get_settings.cache_clear()
