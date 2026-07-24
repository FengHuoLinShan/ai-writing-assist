from __future__ import annotations

import base64
import importlib.util
from pathlib import Path
from types import ModuleType


def _load_validator() -> ModuleType:
    module_path = Path(__file__).parents[1] / "scripts" / "validate_env.py"
    spec = importlib.util.spec_from_file_location("deploy_validate_env", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = _load_validator()


def _valid_values() -> dict[str, str]:
    return {
        "DEPLOY_DOMAIN": "novel.example.com",
        "PUBLIC_BASE_URL": "https://novel.example.com",
        "ALLOWED_ORIGINS": "https://novel.example.com",
        "POSTGRES_DB": "ai_writing_assist",
        "POSTGRES_USER": "ai_writing_assist",
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


def test_production_can_disable_global_llm_rpm() -> None:
    values = _valid_values()
    values["LLM_RATE_LIMIT_PER_MINUTE"] = "0"

    assert validator.validate(values) == []


def test_negative_global_llm_rpm_is_rejected() -> None:
    values = _valid_values()
    values["LLM_RATE_LIMIT_PER_MINUTE"] = "-1"

    errors = validator.validate(values)

    assert any("LLM_RATE_LIMIT_PER_MINUTE" in error for error in errors)


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
