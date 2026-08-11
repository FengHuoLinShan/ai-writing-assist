"""Small encrypted-envelope helpers for project-scoped LLM secrets."""

from __future__ import annotations

import hmac
import os
from copy import deepcopy
from typing import Any

_SECRET_ENV_KEY = "LLM_SETTINGS_ENCRYPTION_KEY"
_SECRET_ENVELOPE_VERSION = "fernet-v1"


def fingerprint_secret(value: str, *, purpose: str) -> str:
    """Return a stable deployment-keyed fingerprint for secret equality checks."""
    secret = (value or "").strip()
    domain = (purpose or "").strip()
    if not secret or not domain:
        raise ValueError("Secret fingerprint value and purpose must be non-empty")
    key = os.environ.get(_SECRET_ENV_KEY, "").strip()
    if not key:
        raise RuntimeError(f"{_SECRET_ENV_KEY} must be configured to fingerprint secrets")
    payload = domain.encode("utf-8") + b"\x00" + secret.encode("utf-8")
    return hmac.digest(key.encode("ascii"), payload, "sha256").hex()


def is_encrypted_secret(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("encrypted") is True
        and value.get("version") == _SECRET_ENVELOPE_VERSION
        and isinstance(value.get("value"), str)
    )


def secret_configured(value: Any) -> bool:
    if is_encrypted_secret(value):
        return bool(value.get("value"))
    return bool(value)


def encrypt_secret(value: str) -> dict[str, object]:
    """Encrypt a non-empty secret into a stable JSON envelope."""
    secret = (value or "").strip()
    if not secret:
        raise ValueError("Cannot encrypt an empty secret")
    fernet = _get_fernet()
    return {
        "encrypted": True,
        "version": _SECRET_ENVELOPE_VERSION,
        "value": fernet.encrypt(secret.encode("utf-8")).decode("ascii"),
    }


def ensure_encrypted_secret(value: Any) -> Any:
    """Return encrypted envelope for plaintext secrets, preserving envelopes."""
    if value is None or value == "":
        return value
    if is_encrypted_secret(value):
        return deepcopy(value)
    if isinstance(value, str):
        return encrypt_secret(value)
    return value


def decrypt_secret(value: Any) -> str:
    """Return plaintext for encrypted envelopes; legacy strings pass through."""
    if not is_encrypted_secret(value):
        return str(value or "")
    fernet = _get_fernet()
    try:
        return fernet.decrypt(str(value["value"]).encode("ascii")).decode("utf-8")
    except Exception as exc:
        raise ValueError("Unable to decrypt LLM secret") from exc


def _get_fernet():
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:  # pragma: no cover - exercised when dependency missing
        raise RuntimeError("cryptography is required for LLM secret encryption") from exc

    key = os.environ.get(_SECRET_ENV_KEY, "").strip()
    if not key:
        raise RuntimeError(f"{_SECRET_ENV_KEY} must be configured to store LLM API keys")
    try:
        return Fernet(key.encode("ascii"))
    except Exception as exc:
        raise RuntimeError(f"{_SECRET_ENV_KEY} is not a valid Fernet key") from exc
