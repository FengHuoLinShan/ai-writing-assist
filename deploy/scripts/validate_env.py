#!/usr/bin/env python3
"""Fail-closed validation for the production dotenv file."""

from __future__ import annotations

import argparse
import base64
import binascii
import os
import re
import stat
from pathlib import Path
from urllib.parse import urlsplit

PLACEHOLDER_PREFIX = "CHANGE_ME"
DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+"
    r"[a-zA-Z]{2,63}$"
)
URL_SAFE_SECRET_RE = re.compile(r"^[A-Za-z0-9_-]+$")
IMAGE_PATH_COMPONENT_RE = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
IMAGE_TAG_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")
SHA256_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
REGISTRY_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
HEALTHCHECKS_CHECK_PATH_RE = re.compile(r"^/[A-Za-z0-9_-]+$")
S3_BUCKET_RE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)(?:\."
    r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?))*$"
)
ONE_TIME_MIGRATION_FIELDS = (
    "MAP_ATLAS_DESTRUCTIVE_MIGRATION_CONFIRMATION",
    "MAP_ATLAS_DESTRUCTIVE_MIGRATION_BACKUP_NAME",
    "MAP_ATLAS_DESTRUCTIVE_MIGRATION_BACKUP_SHA256",
)


def validate_env_file_metadata(
    path: Path,
    *,
    expected_uid: int | None = None,
) -> list[str]:
    """Return fail-closed errors for the production dotenv file itself."""
    try:
        file_stat = path.lstat()
    except FileNotFoundError:
        return [f"Production env file does not exist: {path}"]
    except OSError:
        return [f"Unable to inspect production env file metadata: {path}"]

    if stat.S_ISLNK(file_stat.st_mode):
        return [f"Production env file must not be a symlink: {path}"]
    if not stat.S_ISREG(file_stat.st_mode):
        return [f"Production env file must be a regular file: {path}"]

    owner_uid = os.geteuid() if expected_uid is None else expected_uid
    if file_stat.st_uid != owner_uid:
        return [f"Production env file must be owned by the current user: {path}"]
    if stat.S_IMODE(file_stat.st_mode) != 0o600:
        return [f"Production env file permissions must be exactly 0600: {path}"]

    return []


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


def is_pinned_image_reference(value: str) -> bool:
    """Validate the conservative Docker/OCI named-reference subset used here."""
    if not value or any(character.isspace() for character in value):
        return False

    image_name_and_tag, separator, digest = value.partition("@")
    if separator != "@" or "@" in digest or not SHA256_DIGEST_RE.fullmatch(digest):
        return False

    path_components = image_name_and_tag.split("/")
    if not path_components or any(not component for component in path_components):
        return False

    final_component = path_components[-1]
    if final_component.count(":") != 1:
        return False
    image_name, tag = final_component.split(":", maxsplit=1)
    if not IMAGE_PATH_COMPONENT_RE.fullmatch(image_name):
        return False
    if not IMAGE_TAG_RE.fullmatch(tag):
        return False

    first_component = path_components[0]
    has_registry = len(path_components) > 1 and (
        first_component == "localhost"
        or first_component.startswith("localhost:")
        or "." in first_component
        or ":" in first_component
    )
    repository_components = (
        path_components[1:-1] if has_registry else path_components[:-1]
    )
    if any(
        not IMAGE_PATH_COMPONENT_RE.fullmatch(component)
        for component in repository_components
    ):
        return False
    if not has_registry:
        return True

    registry_host, registry_separator, registry_port = first_component.partition(":")
    if registry_separator:
        if not registry_port or any(
            character < "0" or character > "9" for character in registry_port
        ):
            return False
        port = int(registry_port)
        if not 1 <= port <= 65535:
            return False
    if registry_host == "localhost":
        return True
    return bool(
        registry_host
        and all(REGISTRY_LABEL_RE.fullmatch(label) for label in registry_host.split("."))
        and "." in registry_host
    )


def normalize_healthchecks_check_base_url(value: str) -> str | None:
    """Return the canonical allowed Healthchecks check endpoint, if valid."""
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None

    normalized_path = parsed.path.rstrip("/")
    if (
        parsed.scheme != "https"
        or parsed.hostname != "hc-ping.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or port not in {None, 443}
        or not HEALTHCHECKS_CHECK_PATH_RE.fullmatch(normalized_path)
    ):
        return None
    return f"https://hc-ping.com{normalized_path}"


def is_valid_map_atlas_s3_endpoint_url(value: str) -> bool:
    """Validate the narrow endpoint set accepted by production deploy validation."""
    cleaned = value.strip()
    if not cleaned:
        return True
    try:
        parsed = urlsplit(cleaned)
        _ = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or any(ord(character) <= 0x20 for character in cleaned)
        or parsed.username is not None
        or parsed.password is not None
        or "?" in cleaned
        or "#" in cleaned
    ):
        return False
    return parsed.scheme == "https" or parsed.hostname.lower() in {
        "localhost",
        "127.0.0.1",
        "::1",
        "minio",
    }


def is_valid_s3_bucket_name(value: str) -> bool:
    """Validate the portable S3 bucket-name subset used by MinIO initialization."""
    if not 3 <= len(value) <= 63 or not S3_BUCKET_RE.fullmatch(value):
        return False
    if ".." in value:
        return False
    return not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", value)


def validate(values: dict[str, str]) -> list[str]:
    errors: list[str] = []

    for name in ONE_TIME_MIGRATION_FIELDS:
        if name in values:
            errors.append(f"{name} is one-time release state and must not be persisted")

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
    postgres_image = require("POSTGRES_IMAGE")
    if not is_missing(postgres_image) and not is_pinned_image_reference(postgres_image):
        errors.append(
            "POSTGRES_IMAGE must use a supported lowercase repository, explicit tag, "
            "and lowercase sha256 digest"
        )
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

    map_atlas_bucket = require("MAP_ATLAS_S3_BUCKET")
    world_object_bucket = require("WORLD_OBJECT_S3_BUCKET")
    for name, bucket in (
        ("MAP_ATLAS_S3_BUCKET", map_atlas_bucket),
        ("WORLD_OBJECT_S3_BUCKET", world_object_bucket),
    ):
        if not is_missing(bucket) and not is_valid_s3_bucket_name(bucket):
            errors.append(
                f"{name} must be a 3-63 character lowercase DNS-style bucket name"
            )
    if (
        not is_missing(map_atlas_bucket)
        and not is_missing(world_object_bucket)
        and map_atlas_bucket == world_object_bucket
    ):
        errors.append("WORLD_OBJECT_S3_BUCKET must differ from MAP_ATLAS_S3_BUCKET")

    for name in ("MINIO_IMAGE", "MINIO_MC_IMAGE"):
        image = require(name)
        if not is_missing(image) and not is_pinned_image_reference(image):
            errors.append(
                f"{name} must use a supported lowercase repository, explicit tag, "
                "and lowercase sha256 digest"
            )

    minio_root_user = require("MINIO_ROOT_USER")
    minio_root_password = require("MINIO_ROOT_PASSWORD")

    map_atlas_endpoint_url = require("MAP_ATLAS_S3_ENDPOINT_URL")
    if not is_valid_map_atlas_s3_endpoint_url(map_atlas_endpoint_url):
        errors.append(
            "MAP_ATLAS_S3_ENDPOINT_URL must be HTTPS without userinfo, query, or "
            "fragment; HTTP is only allowed for localhost, 127.0.0.1, [::1], or minio"
        )
    elif map_atlas_endpoint_url != "http://minio:9000":
        errors.append(
            "MAP_ATLAS_S3_ENDPOINT_URL must be http://minio:9000 for the private "
            "production MinIO service"
        )
    map_atlas_access_key = values.get("MAP_ATLAS_S3_ACCESS_KEY_ID", "")
    map_atlas_secret_key = values.get("MAP_ATLAS_S3_SECRET_ACCESS_KEY", "")
    if bool(map_atlas_access_key) != bool(map_atlas_secret_key):
        errors.append(
            "MAP_ATLAS_S3_ACCESS_KEY_ID and MAP_ATLAS_S3_SECRET_ACCESS_KEY "
            "must be configured together"
        )
    for name, value in (
        ("MAP_ATLAS_S3_ACCESS_KEY_ID", map_atlas_access_key),
        ("MAP_ATLAS_S3_SECRET_ACCESS_KEY", map_atlas_secret_key),
    ):
        if value and is_missing(value):
            errors.append(f"{name} must not contain a placeholder")
    if not map_atlas_access_key or not map_atlas_secret_key:
        errors.append(
            "MAP_ATLAS_S3_ACCESS_KEY_ID and MAP_ATLAS_S3_SECRET_ACCESS_KEY "
            "are required for MinIO"
        )
    if (
        not is_missing(minio_root_user)
        and not is_missing(map_atlas_access_key)
        and minio_root_user == map_atlas_access_key
    ):
        errors.append("MINIO_ROOT_USER must differ from MAP_ATLAS_S3_ACCESS_KEY_ID")
    if (
        not is_missing(minio_root_password)
        and not is_missing(map_atlas_secret_key)
        and minio_root_password == map_atlas_secret_key
    ):
        errors.append(
            "MINIO_ROOT_PASSWORD must differ from MAP_ATLAS_S3_SECRET_ACCESS_KEY"
        )
    if values.get("MAP_ATLAS_S3_FORCE_PATH_STYLE", "").lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        errors.append("MAP_ATLAS_S3_FORCE_PATH_STYLE must be true for MinIO")

    embedding_deployment = require("EMBEDDING_DEPLOYMENT")
    if embedding_deployment != "local_tei":
        errors.append("EMBEDDING_DEPLOYMENT must be local_tei")
    embedding_provider = require("EMBEDDING_PROVIDER")
    if not is_missing(embedding_provider) and embedding_provider != "openai":
        errors.append("EMBEDDING_PROVIDER must be openai for local TEI")
    embedding_model = require("EMBEDDING_MODEL")
    embedding_model_id = require("EMBEDDING_MODEL_ID")
    embedding_image = require("EMBEDDING_IMAGE")
    if not is_missing(embedding_image) and not is_pinned_image_reference(embedding_image):
        errors.append(
            "EMBEDDING_IMAGE must use a supported lowercase repository, explicit tag, "
            "and lowercase sha256 digest"
        )
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

    healthcheck_urls: list[str] = []
    for name in (
        "HEALTHCHECKS_BACKUP_PING_URL",
        "HEALTHCHECKS_MAINTENANCE_PING_URL",
        "HEALTHCHECKS_RUNTIME_PING_URL",
    ):
        ping_url = require(name)
        if not is_missing(ping_url):
            normalized_ping_url = normalize_healthchecks_check_base_url(ping_url)
            if normalized_ping_url is None:
                errors.append(
                    f"{name} must be an HTTPS hc-ping.com check base URL"
                )
            else:
                healthcheck_urls.append(normalized_ping_url)
    if len(healthcheck_urls) != len(set(healthcheck_urls)):
        errors.append("HEALTHCHECKS ping URLs must be distinct")

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

    metadata_errors = validate_env_file_metadata(args.env)
    if metadata_errors:
        print("Invalid production env file:")
        for error in metadata_errors:
            print(f"- {error}")
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
