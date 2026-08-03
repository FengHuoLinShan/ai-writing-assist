from __future__ import annotations

import base64
import hashlib
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from joserfc import jwt
from joserfc.errors import (
    BadSignatureError,
    ExpiredTokenError,
    InvalidClaimError,
    InvalidKeyIdError,
    MissingClaimError,
    UnsupportedAlgorithmError,
)
from joserfc.jwk import ECKey, OctKey, RSAKey

from core.config import get_settings
from core.errors import ValidationError
from modules.account import oidc

_ISSUER = "https://issuer.example"
_CLIENT_ID = "client-id"
_NONCE = "nonce"


def _id_token_claims(**overrides: Any) -> dict[str, Any]:
    now = int(time.time())
    claims = {
        "iss": _ISSUER,
        "aud": _CLIENT_ID,
        "exp": now + 300,
        "iat": now,
        "sub": "subject-id",
        "nonce": _NONCE,
    }
    claims.update(overrides)
    return claims


def _signed_id_token(
    key: Any,
    algorithm: str,
    *,
    claims: dict[str, Any] | None = None,
    kid: str | None = None,
) -> str:
    return jwt.encode(
        {"alg": algorithm, "kid": kid or key.kid},
        claims if claims is not None else _id_token_claims(),
        key,
        algorithms=[algorithm],
    )


def _decode_id_token(id_token: str, key: Any, *, access_token: str | None = None):
    return oidc._decode_id_token(
        id_token,
        {"keys": [key.as_dict()]},
        issuer=_ISSUER,
        client_id=_CLIENT_ID,
        nonce=_NONCE,
        access_token=access_token,
    )


def _at_hash(access_token: str) -> str:
    digest = hashlib.sha256(access_token.encode()).digest()
    return base64.urlsafe_b64encode(digest[: len(digest) // 2]).rstrip(b"=").decode()


@pytest.mark.asyncio
async def test_wechat_start_keeps_pkce_verifier_out_of_authorization_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTH_MODE", "public")
    monkeypatch.setenv("AUTH_SECRET_KEY", "x" * 32)
    monkeypatch.setenv("AUTHING_WECHAT_ENABLED", "true")
    monkeypatch.setenv("AUTHING_ISSUER", "https://issuer.example")
    monkeypatch.setenv("AUTHING_CLIENT_ID", "client-id")
    monkeypatch.setenv("AUTHING_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv(
        "AUTHING_REDIRECT_URI",
        "https://app.example/api/auth/wechat/callback",
    )
    get_settings.cache_clear()

    async def discovery():
        return {
            "issuer": "https://issuer.example",
            "authorization_endpoint": "https://issuer.example/authorize",
        }

    monkeypatch.setattr(oidc, "_discovery", discovery)
    try:
        response = await oidc.start_wechat(
            accept_terms=True,
            accept_privacy=True,
        )
        query = parse_qs(urlsplit(response.headers["location"]).query)
        state_cookie = response.headers["set-cookie"]
        signed = state_cookie.split("=", 1)[1].split(";", 1)[0]
        payload = oidc._serializer().loads(signed, max_age=600)
    finally:
        get_settings.cache_clear()

    assert query["state"] == [payload["state"]]
    assert query["code_challenge_method"] == ["S256"]
    assert payload["verifier"] not in response.headers["location"]


def test_discovery_accepts_https_endpoints_on_issuer_authority() -> None:
    document = {
        "issuer": "https://issuer.example:8443",
        "authorization_endpoint": "https://issuer.example:8443/authorize",
        "token_endpoint": "https://issuer.example:8443/token",
        "jwks_uri": "https://issuer.example:8443/jwks",
    }

    assert (
        oidc._validate_discovery_document(document, "https://issuer.example:8443")
        is document
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "authorization_endpoint",
            "http://issuer.example/authorize",
            "必须使用 HTTPS",
        ),
        (
            "token_endpoint",
            "https://tokens.example/token",
            "相同主机和端口",
        ),
        (
            "jwks_uri",
            "https://issuer.example:444/jwks",
            "相同主机和端口",
        ),
    ],
)
def test_discovery_rejects_unsafe_or_cross_authority_endpoints(
    field: str,
    value: str,
    message: str,
) -> None:
    document = {
        "issuer": "https://issuer.example",
        "authorization_endpoint": "https://issuer.example/authorize",
        "token_endpoint": "https://issuer.example/token",
        "jwks_uri": "https://issuer.example/jwks",
        field: value,
    }

    with pytest.raises(ValidationError, match=message):
        oidc._validate_discovery_document(document, "https://issuer.example")


@pytest.mark.parametrize("algorithm", ["RS256", "ES256"])
def test_decode_id_token_accepts_allowed_signed_algorithms(algorithm: str) -> None:
    key = (
        RSAKey.generate_key(auto_kid=True)
        if algorithm == "RS256"
        else ECKey.generate_key(auto_kid=True)
    )
    expected_claims = _id_token_claims()
    id_token = _signed_id_token(key, algorithm, claims=expected_claims)

    claims = _decode_id_token(id_token, key)

    assert dict(claims) == expected_claims


def test_decode_id_token_rejects_validly_signed_disallowed_algorithm() -> None:
    key = OctKey.generate_key(auto_kid=True)
    id_token = _signed_id_token(key, "HS256")

    with pytest.raises(UnsupportedAlgorithmError):
        _decode_id_token(id_token, key)


def test_decode_id_token_rejects_wrong_signature() -> None:
    trusted_key = RSAKey.generate_key(auto_kid=True)
    attacker_key = RSAKey.generate_key(auto_kid=True)
    id_token = _signed_id_token(attacker_key, "RS256", kid=trusted_key.kid)

    with pytest.raises(BadSignatureError):
        _decode_id_token(id_token, trusted_key)


def test_decode_id_token_rejects_unknown_key() -> None:
    trusted_key = RSAKey.generate_key(auto_kid=True)
    unknown_key = RSAKey.generate_key(auto_kid=True)
    id_token = _signed_id_token(unknown_key, "RS256")

    with pytest.raises(InvalidKeyIdError):
        _decode_id_token(id_token, trusted_key)


@pytest.mark.parametrize(
    ("overrides", "removed_claim", "error"),
    [
        pytest.param(
            {"iss": "https://other.example"}, None, InvalidClaimError, id="issuer"
        ),
        pytest.param({"aud": "other-client"}, None, InvalidClaimError, id="audience"),
        pytest.param({"nonce": "other-nonce"}, None, InvalidClaimError, id="nonce"),
        pytest.param({}, None, ExpiredTokenError, id="expiry"),
        pytest.param({}, "sub", MissingClaimError, id="missing-sub"),
        pytest.param({}, "iat", MissingClaimError, id="missing-iat"),
        pytest.param({}, "nonce", MissingClaimError, id="missing-nonce"),
    ],
)
def test_decode_id_token_rejects_invalid_required_claims(
    overrides: dict[str, Any],
    removed_claim: str | None,
    error: type[Exception],
) -> None:
    key = RSAKey.generate_key(auto_kid=True)
    claims = _id_token_claims()
    claims.update(overrides)
    if error is ExpiredTokenError:
        claims["exp"] = int(time.time()) - 120
    if removed_claim is not None:
        claims.pop(removed_claim)
    id_token = _signed_id_token(key, "RS256", claims=claims)

    with pytest.raises(error):
        _decode_id_token(id_token, key)


def test_decode_id_token_validates_matching_access_token_hash() -> None:
    key = RSAKey.generate_key(auto_kid=True)
    access_token = "access-token"
    claims = _id_token_claims(at_hash=_at_hash(access_token))
    id_token = _signed_id_token(key, "RS256", claims=claims)

    decoded = _decode_id_token(id_token, key, access_token=access_token)

    assert dict(decoded) == claims


def test_decode_id_token_rejects_mismatched_access_token_hash() -> None:
    key = RSAKey.generate_key(auto_kid=True)
    claims = _id_token_claims(at_hash=_at_hash("expected-access-token"))
    id_token = _signed_id_token(key, "RS256", claims=claims)

    with pytest.raises(InvalidClaimError, match="at_hash"):
        _decode_id_token(id_token, key, access_token="different-access-token")
