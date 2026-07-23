from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import core.database as database
from app.main import app
from core.base import Base
from core.config import get_settings
from modules.account.models import (
    Account,
    AccountConsent,
    AccountIdentity,
    AccountSecurityEvent,
    EmailLoginChallenge,
    WebSession,
)
from modules.account.services import _keyed_digest, normalize_email

ACCOUNT_TABLES = [
    Account.__table__,
    AccountIdentity.__table__,
    WebSession.__table__,
    EmailLoginChallenge.__table__,
    AccountSecurityEvent.__table__,
    AccountConsent.__table__,
]


@pytest.mark.asyncio
async def test_wrong_email_codes_persist_attempts_and_fifth_invalidation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_MODE", "public")
    monkeypatch.setenv("AUTH_SECRET_KEY", "x" * 32)
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://test")
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://test")
    get_settings.cache_clear()
    settings = get_settings()
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(
                sync_connection,
                tables=ACCOUNT_TABLES,
            )
        )
    monkeypatch.setattr(
        database,
        "get_manager",
        lambda: SimpleNamespace(session_factory=factory),
    )

    email = normalize_email("rollback-check@example.com")
    email_digest = _keyed_digest(settings, "email", email)
    challenge = EmailLoginChallenge(
        email_digest=email_digest,
        code_digest=_keyed_digest(settings, "otp", f"{email_digest}:123456"),
        purpose="login",
        peer_digest="route-test",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    async with factory() as session:
        session.add(challenge)
        await session.commit()
        challenge_id = str(challenge.id)

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            for attempt in range(1, 6):
                response = await client.post(
                    "/api/auth/email/verify",
                    headers={
                        "Origin": "http://test",
                        "X-Requested-With": "XMLHttpRequest",
                    },
                    json={
                        "email": email,
                        "code": "999999",
                        "challenge_id": challenge_id,
                        "accept_terms": True,
                        "accept_privacy": True,
                    },
                )

                assert response.status_code == 400
                assert response.json() == {
                    "error": "validation_error",
                    "detail": "验证码无效或已过期",
                    "message": "验证码无效或已过期",
                    "status_code": 400,
                }
                async with factory() as session:
                    persisted = (
                        await session.execute(
                            select(EmailLoginChallenge).where(
                                EmailLoginChallenge.id == challenge.id
                            )
                        )
                    ).scalar_one()
                    assert persisted.attempts == attempt
                    assert (persisted.invalidated_at is not None) is (attempt == 5)
    finally:
        get_settings.cache_clear()
        await engine.dispose()
