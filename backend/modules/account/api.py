"""Public account and email-auth HTTP adapters."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from core.config import get_settings
from core.dependencies import DbSession
from core.errors import NotFoundError, ValidationError
from modules.account.constants import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from modules.account.context import current_principal
from modules.account.schemas import (
    AccountMeResponse,
    AuthConfigResponse,
    DeletionStateResponse,
    EmailCodeRequest,
    EmailCodeResponse,
    EmailVerifyRequest,
)
from modules.account.services import EmailVerificationRejected, LoginResult, service

router = APIRouter(prefix="/api/auth", tags=["auth"])
account_router = APIRouter(prefix="/api/account", tags=["account"])


def _peer(request: Request) -> str:
    client = request.client
    return client.host if client is not None else "unknown"


def _require_principal():
    principal = current_principal()
    if principal is None:
        raise NotFoundError("Account not found")
    return principal


def _set_login_cookies(response: Response, result: LoginResult) -> None:
    settings = get_settings()
    secure = settings.public_base_url.startswith("https://")
    response.set_cookie(
        SESSION_COOKIE_NAME,
        result.session_token,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
        max_age=settings.session_absolute_seconds,
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        result.csrf_token,
        httponly=False,
        secure=secure,
        samesite="lax",
        path="/",
        max_age=settings.session_absolute_seconds,
    )


def _clear_login_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")


def _verification_rejected_response(
    result: EmailVerificationRejected,
) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "error": "validation_error",
            "detail": result.message,
            "message": result.message,
            "status_code": 400,
        },
    )


@router.get("/config", response_model=AuthConfigResponse)
async def auth_config() -> AuthConfigResponse:
    settings = get_settings()
    return AuthConfigResponse(
        auth_mode=settings.auth_mode,
        email_enabled=settings.auth_mode == "public",
        wechat_enabled=(
            settings.auth_mode == "public" and settings.authing_wechat_enabled
        ),
        terms_version=settings.terms_version,
        privacy_version=settings.privacy_version,
        support_email=settings.support_email,
    )


@router.post("/email/request-code", response_model=EmailCodeResponse)
async def request_email_code(
    db: DbSession,
    request: Request,
    data: EmailCodeRequest,
) -> EmailCodeResponse:
    if get_settings().auth_mode != "public":
        raise NotFoundError("Email login is not enabled")
    return await service.request_email_code(
        db,
        email=data.email,
        purpose="login",
        peer=_peer(request),
    )


@router.post("/email/verify", response_model=AccountMeResponse)
async def verify_email(
    db: DbSession,
    response: Response,
    data: EmailVerifyRequest,
) -> AccountMeResponse | Response:
    if get_settings().auth_mode != "public":
        raise NotFoundError("Email login is not enabled")
    result = await service.verify_email(
        db,
        email=data.email,
        code=data.code,
        challenge_id=data.challenge_id,
        purpose="login",
        accept_terms=data.accept_terms,
        accept_privacy=data.accept_privacy,
    )
    if isinstance(result, EmailVerificationRejected):
        return _verification_rejected_response(result)
    if not isinstance(result, LoginResult):
        raise RuntimeError("Login verification did not create a browser session")
    _set_login_cookies(response, result)
    return result.me


@router.get("/me", response_model=AccountMeResponse)
async def auth_me(db: DbSession) -> AccountMeResponse:
    principal = _require_principal()
    from modules.account.models import Account

    account = await db.get(Account, principal.account_id)
    if account is None:
        raise NotFoundError("Account not found")
    return AccountMeResponse(
        id=str(account.id),
        status=account.status,
        identity_type=principal.identity_type,
        support_code=account.support_code,
        deletion_requested_at=account.deletion_requested_at,
        purge_after=account.purge_after,
    )


@router.post("/logout", status_code=204)
async def logout(db: DbSession, response: Response) -> Response:
    principal = _require_principal()
    if principal.session_id is not None:
        await service.logout(db, principal.session_id)
    _clear_login_cookies(response)
    response.status_code = 204
    return response


@router.post("/reauth/email/request-code", response_model=EmailCodeResponse)
async def request_reauth_email_code(
    db: DbSession,
    request: Request,
    data: EmailCodeRequest,
) -> EmailCodeResponse:
    principal = _require_principal()
    if principal.identity_type != "email":
        raise ValidationError("必须使用原登录方式重新认证")
    return await service.request_email_code(
        db,
        email=data.email,
        purpose="reauth",
        peer=_peer(request),
        current_account_id=principal.account_id,
    )


@router.post("/reauth/email/verify", response_model=AccountMeResponse)
async def verify_reauth_email(
    db: DbSession,
    data: EmailVerifyRequest,
) -> AccountMeResponse | Response:
    principal = _require_principal()
    if principal.identity_type != "email":
        raise ValidationError("必须使用原登录方式重新认证")
    result = await service.verify_email(
        db,
        email=data.email,
        code=data.code,
        challenge_id=data.challenge_id,
        purpose="reauth",
        accept_terms=False,
        accept_privacy=False,
        current_account_id=principal.account_id,
    )
    if isinstance(result, EmailVerificationRejected):
        return _verification_rejected_response(result)
    if isinstance(result, LoginResult):
        raise RuntimeError("Reauthentication unexpectedly created a session")
    return result


@account_router.get("/deletion", response_model=DeletionStateResponse)
async def deletion_state(db: DbSession) -> DeletionStateResponse:
    principal = _require_principal()
    from modules.account.models import Account

    account = await db.get(Account, principal.account_id)
    if account is None:
        raise NotFoundError("Account not found")
    return DeletionStateResponse(
        status=account.status,
        deletion_requested_at=account.deletion_requested_at,
        purge_after=account.purge_after,
    )


@account_router.post("/deletion", response_model=DeletionStateResponse)
async def request_deletion(db: DbSession) -> DeletionStateResponse:
    account = await service.request_deletion(db, _require_principal())
    return DeletionStateResponse(
        status=account.status,
        deletion_requested_at=account.deletion_requested_at,
        purge_after=account.purge_after,
    )


@account_router.delete("/deletion", response_model=DeletionStateResponse)
async def cancel_deletion(db: DbSession) -> DeletionStateResponse:
    principal = _require_principal()
    settings = get_settings()
    now = datetime.now(UTC).timestamp()
    if (
        principal.reauthenticated_at_epoch is None
        or principal.reauthenticated_at_epoch < now - settings.reauth_seconds
    ):
        raise ValidationError("此操作需要在 10 分钟内重新认证")
    account = await service.restore_account(db, principal)
    return DeletionStateResponse(status=account.status)


from modules.account.settings_api import (  # noqa: E402
    handler_router as settings_handler_router,
)

account_router.include_router(settings_handler_router, prefix="/settings")
