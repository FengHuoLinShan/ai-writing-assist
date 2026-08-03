"""Authing hosted WeChat OIDC authorization-code flow."""

from __future__ import annotations

import base64
import hashlib
import secrets
import uuid
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.oidc.core import CodeIDToken
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from joserfc import jwt
from joserfc.jwk import KeySet

from core.config import get_settings
from core.dependencies import DbSession
from core.errors import NotFoundError, ValidationError
from modules.account.api import _set_login_cookies
from modules.account.context import current_principal
from modules.account.services import LoginResult, service

router = APIRouter(prefix="/api/auth/wechat", tags=["auth"])
reauth_router = APIRouter(prefix="/api/auth/reauth/wechat", tags=["auth"])
_STATE_COOKIE = "aaw_oidc_state"
_ID_TOKEN_ALGORITHMS = ("RS256", "ES256")


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(
        get_settings().auth_secret_key,
        salt="authing-wechat-oidc-state-v1",
    )


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _https_host_port(value: Any, field: str) -> tuple[str, int]:
    if not isinstance(value, str) or not value:
        raise ValidationError(f"OIDC {field} 配置无效")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ValidationError(f"OIDC {field} 配置无效") from None
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValidationError(f"OIDC {field} 必须使用 HTTPS")
    return parsed.hostname.lower().rstrip("."), port or 443


def _validate_discovery_document(
    document: dict[str, Any],
    issuer: str,
) -> dict[str, Any]:
    if str(document.get("issuer", "")).rstrip("/") != issuer:
        raise ValidationError("OIDC issuer 配置不匹配")
    try:
        issuer_url = urlsplit(issuer)
        issuer_port = issuer_url.port
    except ValueError:
        raise ValidationError("OIDC issuer 配置不匹配") from None
    if not issuer_url.hostname:
        raise ValidationError("OIDC issuer 配置不匹配")
    issuer_authority = (
        issuer_url.hostname.lower().rstrip("."),
        issuer_port or (443 if issuer_url.scheme.lower() == "https" else 80),
    )
    for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if _https_host_port(document.get(field), field) != issuer_authority:
            raise ValidationError(f"OIDC {field} 必须与 issuer 使用相同主机和端口")
    return document


async def _discovery() -> dict[str, Any]:
    settings = get_settings()
    issuer = settings.authing_issuer.rstrip("/")
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        response = await client.get(f"{issuer}/.well-known/openid-configuration")
        response.raise_for_status()
        document = response.json()
    if not isinstance(document, dict):
        raise ValidationError("OIDC discovery 配置无效")
    return _validate_discovery_document(document, issuer)


def _decode_id_token(
    id_token: str,
    jwks: dict[str, Any],
    *,
    issuer: str,
    client_id: str,
    nonce: Any,
    access_token: str | None,
) -> CodeIDToken:
    """Verify a signed Authing ID token before applying OIDC claim semantics."""
    token = jwt.decode(
        id_token,
        KeySet.import_key_set(jwks),
        algorithms=_ID_TOKEN_ALGORITHMS,
    )
    claims = CodeIDToken(
        token.claims,
        token.header,
        options={
            "iss": {"essential": True, "value": issuer},
            "aud": {"essential": True, "value": client_id},
            "exp": {"essential": True},
            "sub": {"essential": True},
        },
        params={
            "client_id": client_id,
            "nonce": nonce,
            "access_token": access_token,
        },
    )
    claims.validate(leeway=60)
    return claims


async def _start_wechat(
    *,
    purpose: str,
    accept_terms: bool = False,
    accept_privacy: bool = False,
) -> RedirectResponse:
    settings = get_settings()
    if not settings.authing_wechat_enabled:
        raise NotFoundError("WeChat login is not enabled")
    principal = current_principal()
    if purpose == "reauth":
        if principal is None or principal.identity_type != "authing_wechat":
            raise ValidationError("必须使用原登录方式重新认证")
        account_id = str(principal.account_id)
    else:
        account_id = ""
    if purpose == "login" and (not accept_terms or not accept_privacy):
        raise ValidationError("注册前必须同意用户协议和隐私政策")
    document = await _discovery()
    verifier = secrets.token_urlsafe(48)
    nonce = secrets.token_urlsafe(24)
    state = secrets.token_urlsafe(32)
    state_cookie = _serializer().dumps(
        {
            "state": state,
            "nonce": nonce,
            "verifier": verifier,
            "purpose": purpose,
            "account_id": account_id,
            "accept_terms": accept_terms,
            "accept_privacy": accept_privacy,
        }
    )
    params = {
        "client_id": settings.authing_client_id,
        "response_type": "code",
        "scope": "openid profile",
        "redirect_uri": settings.authing_redirect_uri,
        "state": state,
        "nonce": nonce,
        "code_challenge": _pkce_challenge(verifier),
        "code_challenge_method": "S256",
    }
    if purpose == "reauth":
        params["prompt"] = "login"
    response = RedirectResponse(
        f"{document['authorization_endpoint']}?{urlencode(params)}",
        status_code=302,
    )
    response.set_cookie(
        _STATE_COOKIE,
        state_cookie,
        httponly=True,
        secure=settings.public_base_url.startswith("https://"),
        samesite="lax",
        path="/api/auth/wechat/callback",
        max_age=600,
    )
    return response


@router.get("/start")
async def start_wechat(
    accept_terms: bool = False,
    accept_privacy: bool = False,
) -> RedirectResponse:
    return await _start_wechat(
        purpose="login",
        accept_terms=accept_terms,
        accept_privacy=accept_privacy,
    )


@reauth_router.get("/start")
async def start_wechat_reauth() -> RedirectResponse:
    return await _start_wechat(purpose="reauth")


@router.get("/callback")
async def wechat_callback(
    db: DbSession,
    request: Request,
    code: str,
    state: str,
) -> RedirectResponse:
    settings = get_settings()
    if not settings.authing_wechat_enabled:
        raise NotFoundError("WeChat login is not enabled")
    cookie_state = request.cookies.get(_STATE_COOKIE, "")
    if not cookie_state:
        raise ValidationError("OIDC state 无效或已过期")
    try:
        payload = _serializer().loads(cookie_state, max_age=600)
    except (BadSignature, SignatureExpired) as exc:
        raise ValidationError("OIDC state 无效或已过期") from exc
    if not secrets.compare_digest(str(payload.get("state", "")), state):
        raise ValidationError("OIDC state 无效或已过期")
    document = await _discovery()
    client = AsyncOAuth2Client(
        client_id=settings.authing_client_id,
        client_secret=settings.authing_client_secret,
    )
    try:
        token = await client.fetch_token(
            document["token_endpoint"],
            code=code,
            redirect_uri=settings.authing_redirect_uri,
            code_verifier=payload["verifier"],
        )
    finally:
        await client.aclose()
    id_token = token.get("id_token")
    if not isinstance(id_token, str) or not id_token:
        raise ValidationError("OIDC 响应缺少 id_token")
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as http:
        jwks_response = await http.get(document["jwks_uri"])
        jwks_response.raise_for_status()
        jwks = jwks_response.json()
    claims = _decode_id_token(
        id_token,
        jwks,
        issuer=str(document["issuer"]),
        client_id=settings.authing_client_id,
        nonce=payload["nonce"],
        access_token=token.get("access_token"),
    )
    purpose = payload["purpose"]
    account_id = uuid.UUID(payload["account_id"]) if payload.get("account_id") else None
    result = await service.login_oidc(
        db,
        issuer=str(document["issuer"]),
        subject=str(claims["sub"]),
        purpose=purpose,
        accept_terms=bool(payload.get("accept_terms")),
        accept_privacy=bool(payload.get("accept_privacy")),
        current_account_id=account_id,
        settings=settings,
    )
    response = RedirectResponse("/?auth=reauthenticated" if purpose == "reauth" else "/")
    response.delete_cookie(_STATE_COOKIE, path="/api/auth/wechat/callback")
    if isinstance(result, LoginResult):
        _set_login_cookies(response, result)
    return response
