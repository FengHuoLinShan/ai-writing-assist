from __future__ import annotations

import base64
import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _load_validator() -> ModuleType:
    module_path = Path(__file__).parents[1] / "scripts" / "validate_env.py"
    spec = importlib.util.spec_from_file_location("deploy_validate_env", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = _load_validator()
EXAMPLE_ENV = Path(__file__).parents[1] / ".env.production.example"


def _valid_values() -> dict[str, str]:
    return {
        "DEPLOY_DOMAIN": "novel.example.com",
        "PUBLIC_BASE_URL": "https://novel.example.com",
        "ALLOWED_ORIGINS": "https://novel.example.com",
        "POSTGRES_DB": "ai_writing_assist",
        "POSTGRES_USER": "ai_writing_assist",
        "POSTGRES_IMAGE": (
            "docker.m.daocloud.io/pgvector/pgvector:0.8.6-pg17-bookworm"
            "@sha256:7ae6051efd0e60444282c27c7e141af07f322ce033300e727a49c3dd11075e38"
        ),
        "DATABASE_MODE": "fresh",
        "POSTGRES_PASSWORD": "a_secure_database_password_123",
        "AUTH_MODE": "closed_test",
        "APP_ACCESS_TOKEN": "a" * 32,
        "HTTP_RATE_LIMIT_PER_MINUTE": "120",
        "HTTP_RATE_LIMIT_BURST": "30",
        "HTTP_RATE_LIMIT_MAX_CLIENTS": "10000",
        "LLM_RATE_LIMIT_PER_MINUTE": "0",
        "LLM_MAX_CONCURRENT_REQUESTS": "4",
        "TASK_WORKER_MAX_CONCURRENT_TASKS": "1",
        "BACKUP_RETENTION_DAYS": "30",
        "LLM_SETTINGS_ENCRYPTION_KEY": base64.urlsafe_b64encode(b"k" * 32).decode(),
        "EMBEDDING_DEPLOYMENT": "local_tei",
        "EMBEDDING_IMAGE": (
            "ghcr.io/huggingface/text-embeddings-inference:cpu-1.9"
            "@sha256:c26a226262ad4ff3330fb30b76653c1bb65da2fcf413b92284545a010e0a8a48"
        ),
        "EMBEDDING_MODEL_ID": "BAAI/bge-base-zh-v1.5",
        "EMBEDDING_PROVIDER": "openai",
        "EMBEDDING_MODEL": "bge-base-zh-v1.5",
        "EMBEDDING_BASE_URL": "http://embedding:80/v1",
        "EMBEDDING_API_KEY": "local-tei-internal",
        "EMBEDDING_DIM": "768",
        "EMBEDDING_MAX_CONCURRENT_REQUESTS": "16",
        "API_LOOPBACK_PORT": "18000",
        "FRONTEND_LOOPBACK_PORT": "18080",
        "OPENRESTY_TUNNEL_PORT": "3259",
        "OPENRESTY_CONTAINER": "OpenResty",
        "LLM_TRUST_ENV": "false",
        "OFFSITE_BACKUP_PROVIDER": "backblaze_b2",
        "RESTIC_REPOSITORY": "b2:private-fixture-bucket:ai-writing-assist",
        "B2_ACCOUNT_ID": "fixture-key-id",
        "B2_ACCOUNT_KEY": "fixture-application-key",
        "RESTIC_PASSWORD": "fixture-restic-password",
        "HEALTHCHECKS_BACKUP_PING_URL": "https://hc-ping.com/backup-fixture",
        "HEALTHCHECKS_MAINTENANCE_PING_URL": (
            "https://hc-ping.com/maintenance-fixture"
        ),
        "HEALTHCHECKS_RUNTIME_PING_URL": "https://hc-ping.com/runtime-fixture",
    }


def test_closed_test_environment_is_valid() -> None:
    assert validator.validate(_valid_values()) == []


def test_example_placeholders_fail_closed() -> None:
    values = _valid_values()
    values["DEPLOY_DOMAIN"] = "CHANGE_ME_DOMAIN"
    values["B2_ACCOUNT_KEY"] = "CHANGE_ME_B2_APPLICATION_KEY"

    errors = validator.validate(values)

    assert any("DEPLOY_DOMAIN" in error for error in errors)
    assert any("B2_ACCOUNT_KEY" in error for error in errors)


def test_public_example_keeps_operator_bound_mail_settings_as_placeholders() -> None:
    values = validator.parse_env(EXAMPLE_ENV)
    operator_bound_fields = (
        "BOOTSTRAP_OWNER_EMAIL",
        "SMTP_HOST",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "SMTP_FROM",
        "SUPPORT_EMAIL",
    )

    for field in operator_bound_fields:
        assert field in values
        assert validator.is_missing(values[field])
        assert "CHANGE_ME" in values[field].upper()

    assert values["SMTP_PORT"] == "587"
    assert values["SMTP_TLS_MODE"] == "starttls"
    errors = validator.validate(values)
    assert errors
    assert any(
        any(field in error for field in operator_bound_fields) for error in errors
    )


def test_production_can_disable_global_llm_rpm() -> None:
    values = _valid_values()
    values["LLM_RATE_LIMIT_PER_MINUTE"] = "0"

    assert validator.validate(values) == []


def test_negative_global_llm_rpm_is_rejected() -> None:
    values = _valid_values()
    values["LLM_RATE_LIMIT_PER_MINUTE"] = "-1"

    errors = validator.validate(values)

    assert any("LLM_RATE_LIMIT_PER_MINUTE" in error for error in errors)


@pytest.mark.parametrize(
    "image",
    (
        "",
        "pgvector/pgvector",
        "pgvector/pgvector@sha256:" + "a" * 64,
        "pgvector/pgvector:0.8.6-pg17-bookworm",
        "pgvector/pgvector:0.8.6-pg17-bookworm@sha256:" + "a" * 63,
        "pgvector/pgvector:0.8.6-pg17-bookworm@sha256:" + "A" * 64,
        "pgvector/pgvector:0.8.6-pg17-bookworm@sha256:" + "g" * 64,
        "pgvector/pgvector:0.8.6-pg17-bookworm@sha256:" + "a" * 64 + "@junk",
        "pgvector/pgvector:0.8.6-pg17-bookworm@sha256:" + "a" * 64 + " ",
        "https://registry.example/repo:tag@sha256:" + "a" * 64,
        "/registry.example/repo:tag@sha256:" + "a" * 64,
        "registry.example//repo:tag@sha256:" + "a" * 64,
        "registry.example/repo/:tag@sha256:" + "a" * 64,
        "registry.example/repo:tag:again@sha256:" + "a" * 64,
        "registry.example/Repo:tag@sha256:" + "a" * 64,
        "registry.example/repo:tag@sha256:" + "a" * 64 + "?query=1",
        "registry.example/repo:tag@sha256:" + "a" * 64 + "#fragment",
        "registry.example:port/repo:tag@sha256:" + "a" * 64,
        "registry.example:１２３/repo:tag@sha256:" + "a" * 64,
        "registry.example:١٢٣/repo:tag@sha256:" + "a" * 64,
        "registry.example:65536/repo:tag@sha256:" + "a" * 64,
    )
)
def test_pinned_image_reference_rejects_malformed_oci_named_references(
    image: str,
) -> None:
    assert not validator.is_pinned_image_reference(image)


def test_container_images_require_a_tag_and_exact_lowercase_digest() -> None:
    malformed = (
        "",
        "pgvector/pgvector",
        "pgvector/pgvector@sha256:" + "a" * 64,
        "pgvector/pgvector:0.8.6-pg17-bookworm",
        "registry.example/repo:tag:again@sha256:" + "a" * 64,
        "https://registry.example/repo:tag@sha256:" + "a" * 64,
    )

    for image in malformed:
        values = _valid_values()
        values["POSTGRES_IMAGE"] = image
        values["EMBEDDING_IMAGE"] = image

        errors = validator.validate(values)

        assert any("POSTGRES_IMAGE" in error for error in errors), image
        assert any("EMBEDDING_IMAGE" in error for error in errors), image


def test_invalid_image_reference_errors_describe_the_full_supported_contract() -> None:
    values = _valid_values()
    values["POSTGRES_IMAGE"] = "https://registry.example/repo:tag@sha256:" + "a" * 64
    values["EMBEDDING_IMAGE"] = "registry.example/Repo:tag@sha256:" + "a" * 64

    assert validator.validate(values) == [
        "POSTGRES_IMAGE must use a supported lowercase repository, explicit tag, "
        "and lowercase sha256 digest",
        "EMBEDDING_IMAGE must use a supported lowercase repository, explicit tag, "
        "and lowercase sha256 digest",
    ]


@pytest.mark.parametrize(
    "image",
    (
        "pgvector/pgvector:0.8.6-pg17-bookworm@sha256:" + "a" * 64,
        "ghcr.io/huggingface/text-embeddings-inference:cpu-1.9@sha256:"
        + "b" * 64,
        "docker.m.daocloud.io/pgvector/pgvector:0.8.6-pg17-bookworm@sha256:"
        + "c" * 64,
        "registry.example:5443/team/postgres:17.4-bookworm@sha256:" + "d" * 64,
        "registry.example:05443/team/postgres:17.4-bookworm@sha256:" + "e" * 64,
        "localhost:5000/team/postgres:17.4-bookworm@sha256:" + "f" * 64,
    ),
)
def test_pinned_image_reference_allows_reviewed_oci_named_references(
    image: str,
) -> None:
    assert validator.is_pinned_image_reference(image)


def test_openresty_tunnel_port_must_not_overlap_application_ports() -> None:
    values = _valid_values()
    values["OPENRESTY_TUNNEL_PORT"] = values["API_LOOPBACK_PORT"]

    errors = validator.validate(values)

    assert any("OPENRESTY_TUNNEL_PORT must differ" in error for error in errors)


def test_public_mode_requires_smtp_and_auth_secret() -> None:
    values = _valid_values()
    values["AUTH_MODE"] = "public"
    values["APP_ACCESS_TOKEN"] = ""

    errors = validator.validate(values)

    assert any("AUTH_SECRET_KEY" in error for error in errors)
    assert any("SMTP_HOST" in error for error in errors)


def test_runtime_healthcheck_url_is_required_and_must_use_https_hc_ping() -> None:
    missing = _valid_values()
    missing.pop("HEALTHCHECKS_RUNTIME_PING_URL")

    missing_errors = validator.validate(missing)

    assert any(
        "HEALTHCHECKS_RUNTIME_PING_URL is required" in error
        for error in missing_errors
    )

    invalid = _valid_values()
    invalid["HEALTHCHECKS_RUNTIME_PING_URL"] = "http://hc-ping.com/runtime"

    invalid_errors = validator.validate(invalid)

    assert invalid_errors == [
        "HEALTHCHECKS_RUNTIME_PING_URL must be an HTTPS hc-ping.com check base URL"
    ]


@pytest.mark.parametrize(
    "ping_url",
    (
        "https://hc-ping.com/",
        "https://hc-ping.com/backup-fixture/start",
        "https://hc-ping.com/runtime-fixture?next=/start",
        "https://hc-ping.com/runtime-fixture#fragment",
        "https://user:password@hc-ping.com/runtime-fixture",
        "https://hc-ping.com:444/runtime-fixture",
        "https://hc-ping.com:not-a-port/runtime-fixture",
    ),
)
def test_healthchecks_ping_urls_require_a_safe_single_segment_check_base(
    ping_url: str,
) -> None:
    values = _valid_values()
    values["HEALTHCHECKS_RUNTIME_PING_URL"] = ping_url

    errors = validator.validate(values)

    assert errors == [
        "HEALTHCHECKS_RUNTIME_PING_URL must be an HTTPS hc-ping.com check base URL"
    ]


def test_healthchecks_ping_urls_must_be_distinct() -> None:
    values = _valid_values()
    values["HEALTHCHECKS_RUNTIME_PING_URL"] = values[
        "HEALTHCHECKS_BACKUP_PING_URL"
    ]

    errors = validator.validate(values)

    assert errors == ["HEALTHCHECKS ping URLs must be distinct"]


def test_healthchecks_ping_urls_reject_trailing_slash_aliases() -> None:
    values = _valid_values()
    values["HEALTHCHECKS_RUNTIME_PING_URL"] = (
        values["HEALTHCHECKS_BACKUP_PING_URL"] + "/"
    )

    errors = validator.validate(values)

    assert errors == ["HEALTHCHECKS ping URLs must be distinct"]


def test_healthchecks_ping_urls_reject_default_port_and_trailing_slash_aliases() -> None:
    values = _valid_values()
    values["HEALTHCHECKS_RUNTIME_PING_URL"] = (
        "https://hc-ping.com:443/backup-fixture/"
    )

    errors = validator.validate(values)

    assert errors == ["HEALTHCHECKS ping URLs must be distinct"]


def test_env_file_metadata_accepts_current_owner_with_exact_mode(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.production"
    env_file.write_text("EXAMPLE_KEY=fixture-value\n")
    env_file.chmod(0o600)

    assert validator.validate_env_file_metadata(env_file) == []


def test_env_file_metadata_rejects_a_missing_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.production"

    errors = validator.validate_env_file_metadata(env_file)

    assert errors == [f"Production env file does not exist: {env_file}"]


def test_env_file_metadata_rejects_modes_other_than_exact_0600(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.production"
    env_file.write_text("EXAMPLE_KEY=fixture-value\n")

    for mode in (0o644, 0o640, 0o400):
        env_file.chmod(mode)

        errors = validator.validate_env_file_metadata(env_file)

        assert errors == [
            f"Production env file permissions must be exactly 0600: {env_file}"
        ]


def test_env_file_metadata_rejects_safe_target_symlink(tmp_path: Path) -> None:
    target = tmp_path / "safe-target.env"
    target.write_text("EXAMPLE_KEY=fixture-value\n")
    target.chmod(0o600)
    env_file = tmp_path / ".env.production"
    env_file.symlink_to(target)

    errors = validator.validate_env_file_metadata(env_file)

    assert errors == [f"Production env file must not be a symlink: {env_file}"]


def test_env_file_metadata_rejects_non_regular_files(tmp_path: Path) -> None:
    errors = validator.validate_env_file_metadata(tmp_path)

    assert errors == [f"Production env file must be a regular file: {tmp_path}"]


def test_env_file_metadata_rejects_different_owner_without_chown(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.production"
    env_file.write_text("EXAMPLE_KEY=fixture-value\n")
    env_file.chmod(0o600)

    errors = validator.validate_env_file_metadata(
        env_file,
        expected_uid=os.geteuid() + 1,
    )

    assert errors == [
        f"Production env file must be owned by the current user: {env_file}"
    ]


def test_get_refuses_unsafe_file_without_printing_value(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.production"
    secret_value = "must-not-be-printed"
    env_file.write_text(f"EXAMPLE_KEY={secret_value}\n")
    env_file.chmod(0o644)

    result = subprocess.run(
        [
            sys.executable,
            str(Path(validator.__file__)),
            "--env",
            str(env_file),
            "--get",
            "EXAMPLE_KEY",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert secret_value not in result.stdout
    assert "permissions must be exactly 0600" in result.stdout


def test_get_preserves_output_for_safe_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.production"
    env_file.write_text("EXAMPLE_KEY=fixture-value\n")
    env_file.chmod(0o600)

    result = subprocess.run(
        [
            sys.executable,
            str(Path(validator.__file__)),
            "--env",
            str(env_file),
            "--get",
            "EXAMPLE_KEY",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout == "fixture-value\n"
