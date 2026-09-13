from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from core.config import Settings
from core.errors import NotFoundError, ValidationError
from modules.account.api import _set_login_cookies
from modules.account.constants import ANONYMOUS_RP_SESSION_SECONDS, SESSION_COOKIE_NAME
from modules.account.models import Account, AccountConsent, AccountIdentity, WebSession
from modules.account.services import service

pytestmark = pytest.mark.asyncio


def _settings() -> Settings:
    return Settings(
        auth_mode="public",
        auth_secret_key="test-secret-key-with-at-least-32-bytes",
        public_demo_enabled=True,
        public_demo_rp_enabled=True,
        public_demo_rp_source_revision_id=str(uuid.uuid4()),
    )


async def test_anonymous_rp_session_is_temporary_consented_and_keyless(
    db_session,
) -> None:
    settings = _settings()
    result = await service.create_anonymous_rp_session(
        db_session,
        accept_terms=True,
        accept_privacy=True,
        settings=settings,
    )

    account = await db_session.get(Account, result.login.principal.account_id)
    session = await db_session.get(WebSession, result.login.principal.session_id)
    identity = (
        await db_session.execute(
            select(AccountIdentity).where(
                AccountIdentity.account_id == result.login.principal.account_id
            )
        )
    ).scalar_one()
    consents = list(
        (
            await db_session.execute(
                select(AccountConsent).where(
                    AccountConsent.account_id == result.login.principal.account_id
                )
            )
        ).scalars()
    )

    assert account is not None and account.temporary_expires_at is not None
    assert session is not None
    assert result.login.principal.identity_type == "anonymous_rp"
    assert identity.provider == "anonymous_rp"
    assert {item.policy_type for item in consents} == {"terms", "privacy"}
    assert session.token_digest != result.login.session_token
    assert session.csrf_digest != result.login.csrf_token
    assert (
        result.expires_at - datetime.now(UTC)
    ).total_seconds() <= ANONYMOUS_RP_SESSION_SECONDS

    from fastapi import Response

    response = Response()
    _set_login_cookies(
        response,
        result.login,
        max_age=ANONYMOUS_RP_SESSION_SECONDS,
    )
    cookies = "\n".join(response.headers.getlist("set-cookie"))
    assert f"{SESSION_COOKIE_NAME}=" in cookies
    assert "HttpOnly" in cookies
    assert result.login.session_token in cookies
    assert "temporary-deepseek-key" not in cookies


async def test_anonymous_rp_rejects_missing_consent_before_creating_account(
    db_session,
) -> None:
    before = (await db_session.execute(select(Account))).scalars().all()
    with pytest.raises(ValidationError, match="用户协议"):
        await service.create_anonymous_rp_session(
            db_session,
            accept_terms=False,
            accept_privacy=True,
            settings=_settings(),
        )
    after = (await db_session.execute(select(Account))).scalars().all()
    assert [item.id for item in after] == [item.id for item in before]


async def test_anonymous_rp_requires_enabled_valid_demo_configuration(db_session) -> None:
    with pytest.raises(NotFoundError):
        await service.create_anonymous_rp_session(
            db_session,
            accept_terms=True,
            accept_privacy=True,
            settings=Settings(
                auth_mode="public",
                auth_secret_key="test-secret-key-with-at-least-32-bytes",
            ),
        )


async def test_expired_anonymous_rp_accounts_are_purged_without_touching_others(
    db_session,
) -> None:
    result = await service.create_anonymous_rp_session(
        db_session,
        accept_terms=True,
        accept_privacy=True,
        settings=_settings(),
    )
    anonymous = await db_session.get(Account, result.login.principal.account_id)
    assert anonymous is not None
    anonymous.temporary_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    retained = Account(status="active", support_code="U-RETAINED")
    db_session.add(retained)
    await db_session.flush()

    due = await service.purge_expired_anonymous_rp(db_session, execute=False)
    assert due == [anonymous.id]
    deleted = await service.purge_expired_anonymous_rp(db_session, execute=True)

    assert deleted == [anonymous.id]
    assert await db_session.get(Account, anonymous.id) is None
    assert await db_session.get(Account, retained.id) is not None
