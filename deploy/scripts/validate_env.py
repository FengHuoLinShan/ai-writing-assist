#!/usr/bin/env python3
"""Fail-closed validation for the production dotenv file."""

from __future__ import annotations

import argparse
import base64
import binascii
import re
from pathlib import Path
from urllib.parse import urlsplit

PLACEHOLDER_PREFIX = "CHANGE_ME"
DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+"
    r"[a-zA-Z]{2,63}$"
)
URL_SAFE_SECRET_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        if "=" not in line:
            raise ValueError(f"{path}:{line_number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ValueError(f"{path}:{line_number}: invalid environment key")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def is_missing(value: str | None) -> bool:
    return not value or PLACEHOLDER_PREFIX in value.upper()


def validate(values: dict[str, str]) -> list[str]:
    errors: list[str] = []

    def require(name: str) -> str:
        value = values.get(name, "")
        if is_missing(value):
            errors.append(f"{name} is required and must not contain a placeholder")
        return value

    def positive_int(name: str) -> int | None:
        value = require(name)
        if is_missing(value):
            return None
        try:
            parsed = int(value)
        except ValueError:
            errors.append(f"{name} must be an integer")
            return None
        if parsed <= 0:
            errors.append(f"{name} must be positive")
        return parsed

    def non_negative_int(name: str) -> int | None:
        value = require(name)
        if is_missing(value):
            return None
        try:
            parsed = int(value)
        except ValueError:
            errors.append(f"{name} must be an integer")
            return None
        if parsed < 0:
            errors.append(f"{name} must be non-negative")
        return parsed

    domain = require("DEPLOY_DOMAIN").lower()
    if not is_missing(domain) and not DOMAIN_RE.fullmatch(domain):
        errors.append("DEPLOY_DOMAIN must be a DNS hostname, not an IP address or URL")

    base_url = require("PUBLIC_BASE_URL")
    if not is_missing(base_url):
        parsed_base = urlsplit(base_url)
        if (
            parsed_base.scheme != "https"
            or parsed_base.hostname != domain
            or parsed_base.path not in {"", "/"}
            or parsed_base.query
            or parsed_base.fragment
        ):
            errors.append(
                "PUBLIC_BASE_URL must be the HTTPS origin for DEPLOY_DOMAIN"
            )

    allowed_origins = require("ALLOWED_ORIGINS")
    origins = {origin.strip() for origin in allowed_origins.split(",") if origin.strip()}
    if "*" in origins:
        errors.append("ALLOWED_ORIGINS must not contain a wildcard in production")
    if base_url.rstrip("/") not in {origin.rstrip("/") for origin in origins}:
        errors.append("ALLOWED_ORIGINS must contain PUBLIC_BASE_URL")

    require("POSTGRES_DB")
    require("POSTGRES_USER")
    if require("DATABASE_MODE") != "fresh":
        errors.append("DATABASE_MODE must be fresh for this first deployment")
    database_password = require("POSTGRES_PASSWORD")
    if not is_missing(database_password) and (
        len(database_password) < 24
        or not URL_SAFE_SECRET_RE.fullmatch(database_password)
    ):
        errors.append(
            "POSTGRES_PASSWORD must be at least 24 URL-safe characters "
            "(letters, digits, underscore, hyphen)"
        )

    auth_mode = require("AUTH_MODE")
    if not is_missing(auth_mode) and auth_mode not in {"closed_test", "public"}:
        errors.append("AUTH_MODE must be closed_test or public")
    if auth_mode == "closed_test":
        token = require("APP_ACCESS_TOKEN")
        if not is_missing(token) and len(token) < 32:
            errors.append("APP_ACCESS_TOKEN must contain at least 32 characters")
    elif auth_mode == "public":
        secret = require("AUTH_SECRET_KEY")
        if not is_missing(secret) and len(secret) < 32:
            errors.append("AUTH_SECRET_KEY must contain at least 32 characters")
        for name in (
            "BOOTSTRAP_OWNER_EMAIL",
            "SMTP_HOST",
            "SMTP_USERNAME",
            "SMTP_PASSWORD",
            "SMTP_FROM",
            "SUPPORT_EMAIL",
            "TERMS_VERSION",
            "PRIVACY_VERSION",
        ):
            require(name)
        if values.get("SMTP_TLS_MODE", "starttls") not in {"starttls", "ssl"}:
            errors.append("SMTP_TLS_MODE must be starttls or ssl")
        smtp_port = positive_int("SMTP_PORT")
        if smtp_port is not None and smtp_port > 65535:
            errors.append("SMTP_PORT must be at most 65535")

    if values.get("AUTHING_WECHAT_ENABLED", "false").lower() in {"1", "true", "yes"}:
        for name in (
            "AUTHING_ISSUER",
            "AUTHING_CLIENT_ID",
            "AUTHING_CLIENT_SECRET",
            "AUTHING_REDIRECT_URI",
        ):
            require(name)

    for name in (
        "HTTP_RATE_LIMIT_PER_MINUTE",
        "HTTP_RATE_LIMIT_BURST",
        "HTTP_RATE_LIMIT_MAX_CLIENTS",
        "LLM_MAX_CONCURRENT_REQUESTS",
        "TASK_WORKER_MAX_CONCURRENT_TASKS",
        "BACKUP_RETENTION_DAYS",
        "EMBEDDING_MAX_CONCURRENT_REQUESTS",
    ):
        positive_int(name)
    non_negative_int("LLM_RATE_LIMIT_PER_MINUTE")

    encryption_key = require("LLM_SETTINGS_ENCRYPTION_KEY")
    if not is_missing(encryption_key):
        try:
            decoded = base64.urlsafe_b64decode(encryption_key.encode("ascii"))
        except (UnicodeEncodeError, binascii.Error, ValueError):
            decoded = b""
        if len(decoded) != 32:
            errors.append("LLM_SETTINGS_ENCRYPTION_KEY must be a valid Fernet key")

    embedding_deployment = require("EMBEDDING_DEPLOYMENT")
    if embedding_deployment != "local_tei":
        errors.append("EMBEDDING_DEPLOYMENT must be local_tei")
    embedding_provider = require("EMBEDDING_PROVIDER")
    if not is_missing(embedding_provider) and embedding_provider != "openai":
        errors.append("EMBEDDING_PROVIDER must be openai for local TEI")
    embedding_model = require("EMBEDDING_MODEL")
    embedding_model_id = require("EMBEDDING_MODEL_ID")
    embedding_image = require("EMBEDDING_IMAGE")
    if not is_missing(embedding_image) and "@sha256:" not in embedding_image:
        errors.append("EMBEDDING_IMAGE must be pinned by sha256 digest")
    embedding_base_url = require("EMBEDDING_BASE_URL")
    if not is_missing(embedding_base_url):
        parsed_embedding_url = urlsplit(embedding_base_url)
        if (
            parsed_embedding_url.scheme != "http"
            or parsed_embedding_url.hostname != "embedding"
            or parsed_embedding_url.port not in {None, 80}
            or parsed_embedding_url.path.rstrip("/") != "/v1"
        ):
            errors.append(
                "EMBEDDING_BASE_URL must be the internal TEI URL "
                "http://embedding:80/v1"
            )
    require("EMBEDDING_API_KEY")
    if embedding_model != "bge-base-zh-v1.5":
        errors.append("EMBEDDING_MODEL must match the deployed served model name")
    if embedding_model_id != "BAAI/bge-base-zh-v1.5":
        errors.append("EMBEDDING_MODEL_ID must be BAAI/bge-base-zh-v1.5")
    if values.get("EMBEDDING_DIM") != "768":
        errors.append("EMBEDDING_DIM must remain 768 for the current pgvector schema")

    loopback_ports: list[int] = []
    for name in (
        "API_LOOPBACK_PORT",
        "FRONTEND_LOOPBACK_PORT",
        "OPENRESTY_TUNNEL_PORT",
    ):
        port = positive_int(name)
        if port is not None:
            if port > 65535:
                errors.append(f"{name} must be at most 65535")
            loopback_ports.append(port)
    if len(loopback_ports) == 3 and len(set(loopback_ports)) != 3:
        errors.append(
            "API_LOOPBACK_PORT, FRONTEND_LOOPBACK_PORT, and "
            "OPENRESTY_TUNNEL_PORT must differ"
        )

    if require("OFFSITE_BACKUP_PROVIDER") != "backblaze_b2":
        errors.append("OFFSITE_BACKUP_PROVIDER must be backblaze_b2")
    restic_repository = require("RESTIC_REPOSITORY")
    if not is_missing(restic_repository) and not restic_repository.startswith("b2:"):
        errors.append("RESTIC_REPOSITORY must use the b2: backend")
    for name in ("B2_ACCOUNT_ID", "B2_ACCOUNT_KEY", "RESTIC_PASSWORD"):
        require(name)

    for name in (
        "HEALTHCHECKS_BACKUP_PING_URL",
        "HEALTHCHECKS_MAINTENANCE_PING_URL",
    ):
        ping_url = require(name)
        if not is_missing(ping_url):
            parsed_ping = urlsplit(ping_url)
            if parsed_ping.scheme != "https" or parsed_ping.hostname != "hc-ping.com":
                errors.append(f"{name} must be an HTTPS hc-ping.com URL")

    if values.get("LLM_TRUST_ENV", "false").lower() not in {"0", "false", "no", "off"}:
        errors.append("LLM_TRUST_ENV must remain false in production")

    require("OPENRESTY_CONTAINER")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--env",
        type=Path,
        default=Path(__file__).resolve().parents[1] / ".env.production",
    )
    parser.add_argument("--get", metavar="KEY")
    args = parser.parse_args()

    if not args.env.is_file():
        print(f"Production env file does not exist: {args.env}")
        return 1
    try:
        values = parse_env(args.env)
    except (OSError, ValueError) as exc:
        print(f"Invalid production env file: {exc}")
        return 1

    if args.get:
        value = values.get(args.get)
        if value is None:
            print(f"Missing environment key: {args.get}")
            return 1
        print(value)
        return 0

    errors = validate(values)
    if errors:
        print("Production environment is not ready:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Production environment validation passed (secret values not displayed).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
