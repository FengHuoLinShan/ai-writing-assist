from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from core.config import Settings
from modules.account.models import Account, EmailLoginChallenge, WebSession
from modules.account.services import (
    AccountService,
    EmailVerificationRejected,
    LoginResult,
)


def _settings() -> Settings:
    return Settings(
        auth_mode="public",
        auth_secret_key="test-secret-key-with-at-least-32-bytes",
        smtp_host="smtp.example.test",
        smtp_username="sender",
        smtp_password="secret",
        smtp_from="sender@example.test",
        support_email="support@example.test",
    )


class CapturingSender:
    def __init__(self) -> None:
        self.recipient = ""
        self.code = ""

    async def __call__(self, recipient: str, code: str, *, settings: Settings) -> None:
        self.recipient = recipient
        self.code = code


@pytest.mark.asyncio
async def test_email_registration_stores_only_digests_and_creates_session(
    db_session,
) -> None:
    service = AccountService()
    sender = CapturingSender()

    issued = await service.request_email_code(
        db_session,
        email="User@Example.com",
        purpose="login",
        peer="127.0.0.1",
        settings=_settings(),
        sender=sender,
    )
    result = await service.verify_email(
        db_session,
        email="user@example.com",
        code=sender.code,
        challenge_id=issued.challenge_id or "",
        purpose="login",
        accept_terms=True,
        accept_privacy=True,
        settings=_settings(),
    )

    assert isinstance(result, LoginResult)
    assert result.me.identity_type == "email"
    challenge = (await db_session.execute(select(EmailLoginChallenge))).scalar_one()
    assert sender.code not in challenge.code_digest
    assert "user@example.com" not in challenge.email_digest
    assert challenge.used_at is not None


@pytest.mark.asyncio
async def test_email_code_is_invalidated_after_five_wrong_attempts(db_session) -> None:
    service = AccountService()
    sender = CapturingSender()
    issued = await service.request_email_code(
        db_session,
        email="attempts@example.com",
        purpose="login",
        peer="127.0.0.1",
        settings=_settings(),
        sender=sender,
    )

    for _ in range(5):
        result = await service.verify_email(
            db_session,
            email="attempts@example.com",
            code="999999" if sender.code != "999999" else "888888",
            challenge_id=issued.challenge_id or "",
            purpose="login",
            accept_terms=True,
            accept_privacy=True,
            settings=_settings(),
        )
        assert isinstance(result, EmailVerificationRejected)

    challenge = await db_session.get(
        EmailLoginChallenge,
        uuid.UUID(issued.challenge_id or ""),
    )
    assert challenge is not None
    assert challenge.attempts == 5
    assert challenge.invalidated_at is not None


@pytest.mark.asyncio
async def test_new_login_revokes_previous_browser_session(db_session) -> None:
    service = AccountService()
    account = Account(status="active", support_code="U-SESSION01")
    db_session.add(account)
    await db_session.flush()

    first = await service.create_session(
        db_session,
        account=account,
        identity_type="email",
        settings=_settings(),
    )
    second = await service.create_session(
        db_session,
        account=account,
        identity_type="email",
        settings=_settings(),
    )

    assert (
        await service.authenticate_session(
            db_session, first.session_token, settings=_settings()
        )
        is None
    )
    assert (
        await service.authenticate_session(
            db_session, second.session_token, settings=_settings()
        )
        is not None
    )
    sessions = list((await db_session.execute(select(WebSession))).scalars())
    assert sum(item.revoked_at is None for item in sessions) == 1
