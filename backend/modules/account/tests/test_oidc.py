from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from core.config import get_settings
from core.errors import ValidationError
from modules.account import oidc


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
