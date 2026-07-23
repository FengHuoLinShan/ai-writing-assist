"""Account, identity, browser session, consent, and security-event ORM models."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.base import Base, TimestampMixin, UUIDMixin, UUIDType


class Account(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'pending_deletion', 'banned')",
            name="ck_accounts_status",
        ),
    )

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active", index=True
    )
    support_code: Mapped[str] = mapped_column(
        String(32), nullable=False, unique=True, index=True
    )
    deletion_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    purge_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    banned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    legacy_claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AccountIdentity(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "account_identities"
    __table_args__ = (
        UniqueConstraint(
            "provider", "issuer", "subject", name="uq_account_identity_subject"
        ),
    )

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    issuer: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    subject: Mapped[str] = mapped_column(String(512), nullable=False)


class WebSession(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "web_sessions"
    __table_args__ = (
        Index("ix_web_sessions_account_active", "account_id", "revoked_at"),
    )

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_digest: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    csrf_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    identity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    idle_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    absolute_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reauthenticated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class EmailLoginChallenge(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "email_login_challenges"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('login', 'reauth')",
            name="ck_email_login_challenge_purpose",
        ),
        Index(
            "ix_email_challenge_rate_window",
            "email_digest",
            "created_at",
        ),
    )

    email_digest: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    code_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    peer_digest: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    invalidated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AccountSecurityEvent(Base, UUIDMixin):
    __tablename__ = "account_security_events"

    account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    peer_digest: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class AccountConsent(Base, UUIDMixin):
    __tablename__ = "account_consents"
    __table_args__ = (
        UniqueConstraint(
            "account_id", "policy_type", "version", name="uq_account_consent_version"
        ),
    )

    account_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    policy_type: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
