"""Account registration, OTP, session, reauthentication, and deletion services."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import Settings, get_settings
from core.errors import ConflictError, NotFoundError, ValidationError
from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID, AccountPrincipal
from modules.account.email_sender import send_login_code
from modules.account.models import (
    Account,
    AccountConsent,
    AccountIdentity,
    AccountSecurityEvent,
    EmailLoginChallenge,
    WebSession,
)
from modules.account.schemas import AccountMeResponse, EmailCodeResponse


@dataclass(frozen=True)
class LoginResult:
    principal: AccountPrincipal
    session_token: str
    csrf_token: str
    me: AccountMeResponse


@dataclass(frozen=True)
class EmailVerificationRejected:
    message: str = "验证码无效或已过期"


def normalize_email(value: str) -> str:
    try:
        result = validate_email(value, check_deliverability=False)
    except EmailNotValidError as exc:
        raise ValidationError("邮箱地址格式无效") from exc
    return result.normalized.lower()


def _keyed_digest(settings: Settings, namespace: str, value: str) -> str:
    key = settings.auth_secret_key.encode("utf-8")
    return hmac.new(
        key,
        f"{namespace}:{value}".encode(),
        hashlib.sha256,
    ).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    """Normalize SQLite's naive DateTime round-trip to the production UTC shape."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _support_code() -> str:
    return f"U-{secrets.token_hex(5).upper()}"


def _me(account: Account, identity_type: str) -> AccountMeResponse:
    return AccountMeResponse(
        id=str(account.id),
        status=account.status,
        identity_type=identity_type,
        support_code=account.support_code,
        deletion_requested_at=account.deletion_requested_at,
        purge_after=account.purge_after,
    )


class AccountService:
    async def login_oidc(
        self,
        db: AsyncSession,
        *,
        issuer: str,
        subject: str,
        purpose: str,
        accept_terms: bool,
        accept_privacy: bool,
        current_account_id: uuid.UUID | None,
        settings: Settings | None = None,
    ) -> LoginResult | AccountMeResponse:
        """Complete a verified Authing OIDC identity without persisting tokens."""
        resolved = settings or get_settings()
        identity = (
            await db.execute(
                select(AccountIdentity).where(
                    AccountIdentity.provider == "authing_wechat",
                    AccountIdentity.issuer == issuer,
                    AccountIdentity.subject == subject,
                )
            )
        ).scalar_one_or_none()
        now = _utcnow()
        if purpose == "reauth":
            if (
                identity is None
                or current_account_id is None
                or identity.account_id != current_account_id
            ):
                raise NotFoundError("Account not found")
            await db.execute(
                update(WebSession)
                .where(
                    WebSession.account_id == current_account_id,
                    WebSession.revoked_at.is_(None),
                )
                .values(reauthenticated_at=now)
            )
            account = await db.get(Account, current_account_id)
            if account is None:
                raise NotFoundError("Account not found")
            await self._record_event(db, account.id, "reauth_succeeded", "")
            return _me(account, "authing_wechat")
        if identity is None:
            if not accept_terms or not accept_privacy:
                raise ValidationError("注册前必须同意用户协议和隐私政策")
            nested = await db.begin_nested()
            try:
                account = Account(status="active", support_code=_support_code())
                db.add(account)
                await db.flush()
                identity = AccountIdentity(
                    account_id=account.id,
                    provider="authing_wechat",
                    issuer=issuer,
                    subject=subject,
                )
                db.add(identity)
                db.add_all(
                    [
                        AccountConsent(
                            account_id=account.id,
                            policy_type="terms",
                            version=resolved.terms_version,
                            accepted_at=now,
                        ),
                        AccountConsent(
                            account_id=account.id,
                            policy_type="privacy",
                            version=resolved.privacy_version,
                            accepted_at=now,
                        ),
                    ]
                )
                await db.flush()
                await nested.commit()
            except IntegrityError:
                await nested.rollback()
                identity = (
                    await db.execute(
                        select(AccountIdentity).where(
                            AccountIdentity.provider == "authing_wechat",
                            AccountIdentity.issuer == issuer,
                            AccountIdentity.subject == subject,
                        )
                    )
                ).scalar_one_or_none()
                if identity is None:
                    raise
        account = await db.get(Account, identity.account_id)
        if account is None or account.status == "banned":
            raise NotFoundError("Account not found")
        result = await self.create_session(
            db,
            account=account,
            identity_type="authing_wechat",
            settings=resolved,
        )
        await self._record_event(db, account.id, "login_succeeded", "")
        return result

    async def request_email_code(
        self,
        db: AsyncSession,
        *,
        email: str,
        purpose: str,
        peer: str,
        current_account_id: uuid.UUID | None = None,
        settings: Settings | None = None,
        sender=send_login_code,
    ) -> EmailCodeResponse:
        resolved = settings or get_settings()
        normalized = normalize_email(email)
        email_digest = _keyed_digest(resolved, "email", normalized)
        peer_digest = _keyed_digest(resolved, "peer", peer)
        now = _utcnow()
        bind = db.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            lock_key = int(email_digest[:16], 16)
            if lock_key >= 2**63:
                lock_key -= 2**64
            await db.execute(
                text("SELECT pg_advisory_xact_lock(:lock_key)"),
                {"lock_key": lock_key},
            )

        latest = (
            await db.execute(
                select(EmailLoginChallenge)
                .where(EmailLoginChallenge.email_digest == email_digest)
                .order_by(EmailLoginChallenge.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if latest is not None and _as_utc(latest.created_at) > now - timedelta(
            seconds=60
        ):
            raise ConflictError("请在 60 秒后重新发送")
        hourly_count = (
            await db.execute(
                select(func.count(EmailLoginChallenge.id)).where(
                    EmailLoginChallenge.email_digest == email_digest,
                    EmailLoginChallenge.created_at >= now - timedelta(hours=1),
                )
            )
        ).scalar_one()
        if hourly_count >= 5:
            raise ConflictError("验证码发送过于频繁，请稍后再试")

        if purpose == "reauth":
            if current_account_id is None:
                raise NotFoundError("Account not found")
            identity = (
                await db.execute(
                    select(AccountIdentity).where(
                        AccountIdentity.account_id == current_account_id,
                        AccountIdentity.provider == "email",
                        AccountIdentity.subject == normalized,
                    )
                )
            ).scalar_one_or_none()
            if identity is None:
                raise NotFoundError("Account not found")

        await db.execute(
            update(EmailLoginChallenge)
            .where(
                EmailLoginChallenge.email_digest == email_digest,
                EmailLoginChallenge.purpose == purpose,
                EmailLoginChallenge.used_at.is_(None),
                EmailLoginChallenge.invalidated_at.is_(None),
            )
            .values(invalidated_at=now)
        )
        code = f"{secrets.randbelow(1_000_000):06d}"
        challenge = EmailLoginChallenge(
            email_digest=email_digest,
            code_digest=_keyed_digest(resolved, "otp", f"{email_digest}:{code}"),
            purpose=purpose,
            account_id=current_account_id,
            peer_digest=peer_digest,
            expires_at=now + timedelta(minutes=5),
        )
        db.add(challenge)
        await db.flush()
        try:
            await sender(normalized, code, settings=resolved)
        except Exception:
            challenge.invalidated_at = now
            await db.flush()
            raise ValidationError("验证码暂时无法发送，请稍后重试") from None
        return EmailCodeResponse(challenge_id=str(challenge.id))

    async def verify_email(
        self,
        db: AsyncSession,
        *,
        email: str,
        code: str,
        challenge_id: str,
        purpose: str,
        accept_terms: bool,
        accept_privacy: bool,
        current_account_id: uuid.UUID | None = None,
        settings: Settings | None = None,
    ) -> LoginResult | AccountMeResponse | EmailVerificationRejected:
        resolved = settings or get_settings()
        normalized = normalize_email(email)
        email_digest = _keyed_digest(resolved, "email", normalized)
        try:
            cid = uuid.UUID(challenge_id)
        except ValueError as exc:
            raise ValidationError("验证码无效或已过期") from exc
        challenge = (
            await db.execute(
                select(EmailLoginChallenge)
                .where(EmailLoginChallenge.id == cid)
                .with_for_update()
            )
        ).scalar_one_or_none()
        now = _utcnow()
        if (
            challenge is None
            or challenge.purpose != purpose
            or challenge.email_digest != email_digest
            or challenge.used_at is not None
            or challenge.invalidated_at is not None
            or _as_utc(challenge.expires_at) <= now
            or challenge.attempts >= 5
        ):
            raise ValidationError("验证码无效或已过期")
        expected = _keyed_digest(resolved, "otp", f"{email_digest}:{code}")
        if not hmac.compare_digest(challenge.code_digest, expected):
            challenge.attempts += 1
            if challenge.attempts >= 5:
                challenge.invalidated_at = now
            await self._record_event(
                db,
                challenge.account_id,
                "email_code_rejected",
                challenge.peer_digest,
            )
            await db.flush()
            return EmailVerificationRejected()

        identity = (
            await db.execute(
                select(AccountIdentity).where(
                    AccountIdentity.provider == "email",
                    AccountIdentity.issuer == "",
                    AccountIdentity.subject == normalized,
                )
            )
        ).scalar_one_or_none()
        if purpose == "reauth":
            if (
                identity is None
                or current_account_id is None
                or identity.account_id != current_account_id
                or challenge.account_id != current_account_id
            ):
                raise NotFoundError("Account not found")
            challenge.used_at = now
            await db.execute(
                update(WebSession)
                .where(
                    WebSession.account_id == current_account_id,
                    WebSession.revoked_at.is_(None),
                )
                .values(reauthenticated_at=now)
            )
            await self._record_event(
                db, current_account_id, "reauth_succeeded", challenge.peer_digest
            )
            account = await db.get(Account, current_account_id)
            if account is None:
                raise NotFoundError("Account not found")
            return _me(account, "email")

        if identity is None:
            if not accept_terms or not accept_privacy:
                raise ValidationError("注册前必须同意用户协议和隐私政策")
            identity = await self._create_email_account_concurrently_safe(
                db,
                normalized,
                now,
                resolved,
            )
        account = await db.get(Account, identity.account_id)
        if account is None or account.status == "banned":
            raise NotFoundError("Account not found")
        challenge.used_at = now
        result = await self.create_session(
            db,
            account=account,
            identity_type="email",
            settings=resolved,
        )
        await self._record_event(db, account.id, "login_succeeded", challenge.peer_digest)
        return result

    async def _create_email_account_concurrently_safe(
        self,
        db: AsyncSession,
        normalized: str,
        now: datetime,
        settings: Settings,
    ) -> AccountIdentity:
        nested = await db.begin_nested()
        try:
            account = Account(status="active", support_code=_support_code())
            db.add(account)
            await db.flush()
            identity = AccountIdentity(
                account_id=account.id,
                provider="email",
                issuer="",
                subject=normalized,
            )
            db.add(identity)
            db.add_all(
                [
                    AccountConsent(
                        account_id=account.id,
                        policy_type="terms",
                        version=settings.terms_version,
                        accepted_at=now,
                    ),
                    AccountConsent(
                        account_id=account.id,
                        policy_type="privacy",
                        version=settings.privacy_version,
                        accepted_at=now,
                    ),
                ]
            )
            await db.flush()
            await nested.commit()
            return identity
        except IntegrityError:
            await nested.rollback()
            existing = (
                await db.execute(
                    select(AccountIdentity).where(
                        AccountIdentity.provider == "email",
                        AccountIdentity.issuer == "",
                        AccountIdentity.subject == normalized,
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                raise
            return existing

    async def create_session(
        self,
        db: AsyncSession,
        *,
        account: Account,
        identity_type: str,
        settings: Settings | None = None,
    ) -> LoginResult:
        resolved = settings or get_settings()
        now = _utcnow()
        locked_account = await db.get(Account, account.id, with_for_update=True)
        if locked_account is None or locked_account.status == "banned":
            raise NotFoundError("Account not found")
        account = locked_account
        await db.execute(
            update(WebSession)
            .where(
                WebSession.account_id == account.id,
                WebSession.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        raw_token = secrets.token_urlsafe(32)
        raw_csrf = secrets.token_urlsafe(32)
        session = WebSession(
            account_id=account.id,
            token_digest=_keyed_digest(resolved, "session", raw_token),
            csrf_digest=_keyed_digest(resolved, "csrf", raw_csrf),
            identity_type=identity_type,
            last_seen_at=now,
            idle_expires_at=now + timedelta(seconds=resolved.session_idle_seconds),
            absolute_expires_at=now
            + timedelta(seconds=resolved.session_absolute_seconds),
        )
        db.add(session)
        await db.flush()
        principal = AccountPrincipal(
            account_id=account.id,
            status=account.status,
            identity_type=identity_type,
            support_code=account.support_code,
            session_id=session.id,
            csrf_digest=session.csrf_digest,
        )
        return LoginResult(
            principal=principal,
            session_token=raw_token,
            csrf_token=raw_csrf,
            me=_me(account, identity_type),
        )

    async def authenticate_session(
        self,
        db: AsyncSession,
        raw_token: str,
        *,
        settings: Settings | None = None,
    ) -> AccountPrincipal | None:
        resolved = settings or get_settings()
        digest = _keyed_digest(resolved, "session", raw_token)
        now = _utcnow()
        row = (
            await db.execute(
                select(WebSession, Account)
                .join(Account, Account.id == WebSession.account_id)
                .where(
                    WebSession.token_digest == digest,
                    WebSession.revoked_at.is_(None),
                    WebSession.idle_expires_at > now,
                    WebSession.absolute_expires_at > now,
                )
            )
        ).one_or_none()
        if row is None:
            return None
        session, account = row
        if account.status == "banned":
            session.revoked_at = now
            await db.flush()
            return None
        session.last_seen_at = now
        session.idle_expires_at = min(
            now + timedelta(seconds=resolved.session_idle_seconds),
            _as_utc(session.absolute_expires_at),
        )
        await db.flush()
        return AccountPrincipal(
            account_id=account.id,
            status=account.status,
            identity_type=session.identity_type,
            support_code=account.support_code,
            session_id=session.id,
            csrf_digest=session.csrf_digest,
            reauthenticated_at_epoch=(
                _as_utc(session.reauthenticated_at).timestamp()
                if session.reauthenticated_at
                else None
            ),
        )

    async def logout(self, db: AsyncSession, session_id: uuid.UUID) -> None:
        await db.execute(
            update(WebSession)
            .where(WebSession.id == session_id)
            .values(revoked_at=_utcnow())
        )

    async def request_deletion(
        self,
        db: AsyncSession,
        principal: AccountPrincipal,
        *,
        settings: Settings | None = None,
    ) -> Account:
        resolved = settings or get_settings()
        now = _utcnow()
        if (
            principal.reauthenticated_at_epoch is None
            or principal.reauthenticated_at_epoch
            < now.timestamp() - resolved.reauth_seconds
        ):
            raise ValidationError("此操作需要在 10 分钟内重新认证")
        account = await db.get(Account, principal.account_id, with_for_update=True)
        if account is None or account.status == "banned":
            raise NotFoundError("Account not found")
        if account.status == "active":
            account.status = "pending_deletion"
            account.deletion_requested_at = now
            account.purge_after = now + timedelta(days=30)
            await self._cancel_account_tasks(db, account.id, "account_pending_deletion")
            await self._record_event(db, account.id, "deletion_requested", "")
        await db.flush()
        return account

    async def restore_account(
        self,
        db: AsyncSession,
        principal: AccountPrincipal,
    ) -> Account:
        account = await db.get(Account, principal.account_id, with_for_update=True)
        if account is None or account.status != "pending_deletion":
            raise NotFoundError("Account not found")
        account.status = "active"
        account.deletion_requested_at = None
        account.purge_after = None
        await self._record_event(db, account.id, "deletion_cancelled", "")
        await db.flush()
        return account

    async def claim_legacy(
        self,
        db: AsyncSession,
        email: str,
        *,
        settings: Settings | None = None,
    ) -> Account:
        resolved = settings or get_settings()
        normalized = normalize_email(email)
        account = await db.get(Account, BOOTSTRAP_ACCOUNT_ID, with_for_update=True)
        if account is None:
            raise NotFoundError("Bootstrap account not found")
        if account.legacy_claimed_at is not None:
            raise ConflictError("Legacy account has already been claimed")
        existing = (
            await db.execute(
                select(AccountIdentity).where(
                    AccountIdentity.provider == "email",
                    AccountIdentity.issuer == "",
                    AccountIdentity.subject == normalized,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise ConflictError("Email identity already exists")
        now = _utcnow()
        db.add(
            AccountIdentity(
                account_id=account.id,
                provider="email",
                issuer="",
                subject=normalized,
            )
        )
        db.add_all(
            [
                AccountConsent(
                    account_id=account.id,
                    policy_type="terms",
                    version=resolved.terms_version,
                    accepted_at=now,
                ),
                AccountConsent(
                    account_id=account.id,
                    policy_type="privacy",
                    version=resolved.privacy_version,
                    accepted_at=now,
                ),
            ]
        )
        account.legacy_claimed_at = now
        await db.flush()
        return account

    async def set_banned(
        self,
        db: AsyncSession,
        account_id: uuid.UUID,
        *,
        banned: bool,
    ) -> Account:
        account = await db.get(Account, account_id, with_for_update=True)
        if account is None:
            raise NotFoundError("Account not found")
        now = _utcnow()
        if banned:
            account.status = "banned"
            account.banned_at = now
            await db.execute(
                update(WebSession)
                .where(WebSession.account_id == account.id)
                .values(revoked_at=now)
            )
            await self._cancel_account_tasks(db, account.id, "account_banned")
            await self._record_event(db, account.id, "account_banned", "")
        else:
            account.status = "active"
            account.banned_at = None
            account.deletion_requested_at = None
            account.purge_after = None
            await self._record_event(db, account.id, "account_unbanned", "")
        await db.flush()
        return account

    async def purge_due(
        self,
        db: AsyncSession,
        *,
        execute: bool,
    ) -> list[uuid.UUID]:
        now = _utcnow()
        accounts = list(
            (
                await db.execute(
                    select(Account)
                    .where(
                        Account.status == "pending_deletion",
                        Account.purge_after <= now,
                    )
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        ids = [account.id for account in accounts]
        if not execute:
            return ids
        await db.execute(
            delete(AccountSecurityEvent).where(
                AccountSecurityEvent.created_at < now - timedelta(days=30)
            )
        )
        await db.execute(
            delete(EmailLoginChallenge).where(
                EmailLoginChallenge.created_at < now - timedelta(days=1)
            )
        )
        await db.execute(delete(WebSession).where(WebSession.absolute_expires_at < now))
        from modules.project.facade import purge_projects_for_owner

        for account in accounts:
            await self._cancel_account_tasks(db, account.id, "account_purge_due")
            await purge_projects_for_owner(db, account.id)
            await db.execute(delete(Account).where(Account.id == account.id))
        await db.flush()
        return ids

    async def _cancel_account_tasks(
        self,
        db: AsyncSession,
        account_id: uuid.UUID,
        reason: str,
    ) -> None:
        from infrastructure.tasks.facade import cancel_unfinished_tasks_for_novel
        from modules.project.facade import list_project_ids_for_owner

        for novel_id in await list_project_ids_for_owner(db, account_id):
            await cancel_unfinished_tasks_for_novel(
                db,
                novel_id=str(novel_id),
                transition_reason=reason,
            )

    async def _record_event(
        self,
        db: AsyncSession,
        account_id: uuid.UUID | None,
        event_type: str,
        peer_digest: str,
    ) -> None:
        db.add(
            AccountSecurityEvent(
                account_id=account_id,
                event_type=event_type,
                event_data={},
                peer_digest=peer_digest,
                created_at=_utcnow(),
            )
        )


service = AccountService()
