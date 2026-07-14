"""
core/config.py 单元测试

测试 Settings dataclass 的行为。
注意：部分字段使用 = int(_env(...)) 在类定义时求值，monkeypatch 无法覆盖；
仅 field(default_factory=...) 字段可在实例化时响应环境变量变化。
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from core.config import (
    Settings,
    _env,
    get_settings,
    load_env_file,
    validate_app_access_token_config,
    validate_cors_origins,
    validate_http_rate_limit_config,
    validate_llm_rate_limit_config,
)


class TestSettingsEffectiveDefaults:
    """验证 Settings 与项目 .env 文件一致的默认值"""

    def test_effective_pool_size(self):
        assert Settings().pool_size == 10

    def test_effective_max_overflow(self):
        assert Settings().max_overflow == 20

    def test_effective_echo_sql(self):
        assert Settings().echo_sql is False

    def test_effective_llm_max_tokens(self):
        assert Settings().llm_max_tokens == 12_000

    def test_effective_llm_timeout(self):
        assert Settings().llm_timeout == 180

    def test_effective_embedding_dim(self):
        assert Settings().embedding_dim == 768

    def test_effective_inference_timeout(self):
        assert Settings().inference_worker_timeout == 30.0

    def test_effective_inference_max_batch(self):
        assert Settings().inference_worker_max_batch == 64

    def test_effective_inference_worker_queue_maxsize(self):
        assert Settings().inference_worker_queue_maxsize == 200

    def test_effective_reranker(self):
        assert Settings().reranker_enabled is False

    def test_effective_rag_prewarm_on_startup(self):
        assert Settings().rag_prewarm_on_startup is False

    def test_effective_import_max_chapters(self):
        assert Settings().import_max_chapters == 1000

    def test_effective_debug(self, monkeypatch):
        monkeypatch.delenv("DEBUG", raising=False)
        monkeypatch.delenv("APP_DEBUG", raising=False)
        assert Settings().debug is False

    def test_env_example_uses_the_debug_key_consumed_by_settings(self):
        example = (Path(__file__).resolve().parents[2] / ".env.example").read_text(
            encoding="utf-8"
        )
        keys = {
            line.split("=", 1)[0].strip()
            for line in example.splitlines()
            if line.strip() and not line.lstrip().startswith("#") and "=" in line
        }

        assert "DEBUG" in keys
        assert "APP_DEBUG" not in keys

    def test_fastapi_app_consumes_debug_setting(self):
        from app.main import app

        assert app.debug is get_settings().debug

    # --- field(default_factory=...) 字段：实例化时求值 ---

    def test_effective_database_url(self):
        assert "postgresql+asyncpg" in Settings().database_url

    def test_effective_llm_base_url(self):
        assert Settings().llm_base_url == "https://api.deepseek.com"

    def test_effective_llm_model(self):
        assert Settings().llm_model == "deepseek-v4-flash"

    def test_effective_embedding_model(self):
        assert Settings().embedding_model == "bge-base-zh-v1.5"

    def test_effective_embedding_provider(self):
        assert Settings().embedding_provider == "openai"

    def test_effective_allowed_origins(self):
        assert Settings().allowed_origins == ["*"]

    def test_effective_log_level(self, monkeypatch):
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        assert Settings().log_level == "INFO"

    def test_effective_bge_device(self):
        assert Settings().bge_onnx_device == "cpu"

    def test_effective_bge_quantization(self):
        assert Settings().bge_onnx_quantization == "int8"

    def test_effective_vector_index_type(self):
        assert Settings().vector_index_type == "hnsw"

    def test_effective_vector_distance(self):
        assert Settings().vector_distance == "vector_cosine_ops"

    # --- 静态字段 ---

    def test_app_metadata(self):
        s = Settings()
        assert s.app_name == "ai-novel-structural-engine"
        assert s.app_version == "2.0.0"


class TestSettingsExplicitConstruction:
    """通过显式传参创建 Settings，验证字段可定制性"""

    def test_explicit_database_url(self):
        s = Settings(database_url="sqlite:///test.db")
        assert s.database_url == "sqlite:///test.db"

    def test_explicit_pool_size(self):
        s = Settings(pool_size=5)
        assert s.pool_size == 5

    def test_explicit_llm_model(self):
        s = Settings(llm_model="custom-model")
        assert s.llm_model == "custom-model"

    def test_explicit_embedding_dim(self):
        s = Settings(embedding_dim=512)
        assert s.embedding_dim == 512

    def test_explicit_debug(self):
        s = Settings(debug=True)
        assert s.debug is True

    def test_explicit_llm_api_key(self):
        s = Settings(llm_api_key="sk-custom")
        assert s.llm_api_key == "sk-custom"

    def test_explicit_allowed_origins(self):
        s = Settings(allowed_origins=["https://x.com"])
        assert s.allowed_origins == ["https://x.com"]


class TestSettingsFromEnvFactoryFields:
    """field(default_factory=...) 字段能从 monkeypatch 环境变量读取"""

    def test_database_url_from_env(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://custom:5432/db")
        assert Settings().database_url == "postgresql://custom:5432/db"

    def test_llm_api_key_ignores_env(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "sk-test")
        assert Settings().llm_api_key == ""

    def test_llm_model_ignores_env(self, monkeypatch):
        monkeypatch.setenv("LLM_MODEL", "test-model")
        assert Settings().llm_model == "deepseek-v4-flash"

    def test_llm_base_url_ignores_env(self, monkeypatch):
        monkeypatch.setenv("LLM_BASE_URL", "https://test.local/v1")
        assert Settings().llm_base_url == "https://api.deepseek.com"

    def test_embedding_model_from_env(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_MODEL", "test-emb")
        assert Settings().embedding_model == "test-emb"

    def test_embedding_provider_from_env(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_PROVIDER", "test-provider")
        assert Settings().embedding_provider == "test-provider"

    @pytest.mark.parametrize("level", ["DEBUG", "WARNING", "ERROR"])
    def test_log_level_from_env(self, monkeypatch, level):
        monkeypatch.setenv("LOG_LEVEL", level)
        assert Settings().log_level == level

    @pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
    def test_debug_from_env(self, monkeypatch, value):
        monkeypatch.setenv("DEBUG", value)
        assert Settings().debug is True

    def test_legacy_app_debug_is_not_consumed(self, monkeypatch):
        monkeypatch.delenv("DEBUG", raising=False)
        monkeypatch.setenv("APP_DEBUG", "true")
        assert Settings().debug is False

    def test_bge_device_from_env(self, monkeypatch):
        monkeypatch.setenv("BGE_ONNX_DEVICE", "cuda")
        assert Settings().bge_onnx_device == "cuda"

    def test_allowed_origins_multiple(self, monkeypatch):
        monkeypatch.setenv("ALLOWED_ORIGINS", "http://a.com,http://b.com")
        assert Settings().allowed_origins == ["http://a.com", "http://b.com"]

    def test_allowed_origins_trims_whitespace(self, monkeypatch):
        monkeypatch.setenv("ALLOWED_ORIGINS", " http://a.com , http://b.com ")
        assert Settings().allowed_origins == ["http://a.com", "http://b.com"]

    def test_vector_index_type_from_env(self, monkeypatch):
        monkeypatch.setenv("VECTOR_INDEX_TYPE", "ivfflat")
        assert Settings().vector_index_type == "ivfflat"

    def test_rag_prewarm_on_startup_from_env(self, monkeypatch):
        monkeypatch.setenv("RAG_PREWARM_ON_STARTUP", "true")
        assert Settings().rag_prewarm_on_startup is True

    def test_inference_worker_queue_maxsize_from_env(self, monkeypatch):
        monkeypatch.setenv("INFERENCE_WORKER_QUEUE_MAXSIZE", "37")
        assert Settings().inference_worker_queue_maxsize == 37

    def test_import_max_chapters_from_env(self, monkeypatch):
        monkeypatch.setenv("IMPORT_MAX_CHAPTERS", "12")
        assert Settings().import_max_chapters == 12


class TestCorsOriginValidation:
    """CORS wildcard is local-only."""

    @pytest.mark.parametrize("app_env", ["development", "test", "local", " TEST "])
    @pytest.mark.parametrize("origins", [[], ["*"]])
    def test_local_env_allows_empty_or_wildcard_origins(self, app_env, origins):
        validate_cors_origins(app_env, origins)

    @pytest.mark.parametrize("app_env", ["development", "test", "production"])
    def test_mixed_wildcard_origins_are_rejected(self, app_env):
        with pytest.raises(RuntimeError) as exc_info:
            validate_cors_origins(app_env, ["https://x.com", "*"])

        assert "cannot be mixed" in str(exc_info.value)

    @pytest.mark.parametrize("app_env", ["production", "prod", "staging"])
    @pytest.mark.parametrize("origins", [[], ["*"]])
    def test_non_local_env_rejects_empty_or_wildcard_origins(
        self,
        app_env,
        origins,
    ):
        with pytest.raises(RuntimeError) as exc_info:
            validate_cors_origins(app_env, origins)

        assert "CORS wildcard origins" in str(exc_info.value)
        assert "https://x.com" not in str(exc_info.value)

    @pytest.mark.parametrize("app_env", ["production", "staging"])
    def test_non_local_env_allows_specific_origins(self, app_env):
        validate_cors_origins(app_env, ["https://example.com"])


class TestAppAccessTokenValidation:
    @pytest.mark.parametrize("app_env", ["development", "test", "local"])
    def test_local_env_allows_missing_token(self, app_env):
        validate_app_access_token_config(app_env, "")

    @pytest.mark.parametrize("app_env", ["production", "staging"])
    def test_non_local_env_requires_token(self, app_env):
        with pytest.raises(RuntimeError) as exc_info:
            validate_app_access_token_config(app_env, "")

        assert "APP_ACCESS_TOKEN" in str(exc_info.value)

    def test_non_local_env_accepts_token(self):
        validate_app_access_token_config("production", "secret")


class TestHttpRateLimitValidation:
    @pytest.mark.parametrize("app_env", ["development", "test", "local"])
    def test_local_env_allows_disabled_limiter(self, app_env):
        validate_http_rate_limit_config(app_env, 0, 60, 10_000)

    @pytest.mark.parametrize("app_env", ["production", "staging"])
    def test_non_local_env_requires_positive_rate(self, app_env):
        with pytest.raises(RuntimeError, match="HTTP_RATE_LIMIT_PER_MINUTE"):
            validate_http_rate_limit_config(app_env, 0, 60, 10_000)

    def test_non_local_env_accepts_valid_limiter(self):
        validate_http_rate_limit_config("production", 240, 60, 10_000)

    @pytest.mark.parametrize(
        ("rate", "burst", "max_clients", "field"),
        [
            (-1, 60, 10_000, "HTTP_RATE_LIMIT_PER_MINUTE"),
            (60, -1, 10_000, "HTTP_RATE_LIMIT_BURST"),
            (60, 0, 10_000, "HTTP_RATE_LIMIT_BURST"),
            (60, 60, 0, "HTTP_RATE_LIMIT_MAX_CLIENTS"),
        ],
    )
    def test_invalid_limiter_values_are_rejected(
        self,
        rate,
        burst,
        max_clients,
        field,
    ):
        with pytest.raises(RuntimeError, match=field):
            validate_http_rate_limit_config(
                "development",
                rate,
                burst,
                max_clients,
            )


class TestLlmRateLimitValidation:
    @pytest.mark.parametrize("app_env", ["development", "test", "local", " TEST "])
    def test_local_env_allows_disabled_limiter(self, app_env):
        validate_llm_rate_limit_config(app_env, 0)

    @pytest.mark.parametrize("app_env", ["production", "prod", "staging"])
    def test_non_local_env_requires_positive_rate(self, app_env):
        with pytest.raises(RuntimeError, match="LLM_RATE_LIMIT_PER_MINUTE"):
            validate_llm_rate_limit_config(app_env, 0)

    def test_non_local_env_accepts_positive_rate(self):
        validate_llm_rate_limit_config("production", 60)

    def test_negative_rate_is_rejected_in_local_env(self):
        with pytest.raises(RuntimeError, match="LLM_RATE_LIMIT_PER_MINUTE"):
            validate_llm_rate_limit_config("development", -1)

    def test_non_local_api_process_rejects_disabled_limiter(self):
        backend_root = Path(__file__).resolve().parents[2]
        env = os.environ.copy()
        env.update(
            {
                "APP_ENV": "production",
                "ALLOWED_ORIGINS": "https://example.com",
                "APP_ACCESS_TOKEN": "test-access-token",
                "HTTP_RATE_LIMIT_PER_MINUTE": "60",
                "HTTP_RATE_LIMIT_BURST": "10",
                "LLM_RATE_LIMIT_PER_MINUTE": "0",
            }
        )

        result = subprocess.run(
            [sys.executable, "-c", "import app.main"],
            cwd=backend_root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode != 0
        assert "LLM_RATE_LIMIT_PER_MINUTE must be positive" in result.stderr


class TestSettingsFrozen:
    """Settings 是不可变对象"""

    def test_cannot_set_attribute(self):
        s = Settings()
        with pytest.raises(Exception):
            s.database_url = "changed"  # type: ignore[misc]


class TestGetSettings:
    """get_settings() lru_cache 单例行为"""

    def teardown_method(self):
        get_settings.cache_clear()

    def test_returns_same_instance(self):
        assert get_settings() is get_settings()

    def test_different_instances_after_cache_clear(self):
        a = get_settings()
        get_settings.cache_clear()
        assert a is not get_settings()


class TestEnvHelper:
    """_env() 工具函数"""

    def test_returns_default_for_missing_key(self):
        assert _env("NONEXISTENT_KEY_12345", "default") == "default"

    def test_returns_empty_string_default(self):
        assert _env("NONEXISTENT_KEY_12345") == ""

    def test_reads_env_var(self, monkeypatch):
        monkeypatch.setenv("TEST_HELPER_KEY", "test-value")
        assert _env("TEST_HELPER_KEY") == "test-value"


class TestLoadEnvFile:
    """load_env_file() loads .env-style files without overriding env."""

    def test_loads_custom_env_file(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "\n".join(
                [
                    "# comment",
                    "",
                    "CUSTOM_ENV_FILE_KEY='from-file'",
                    'CUSTOM_SPACED_KEY = " spaced value "',
                    "IGNORED_LINE_WITHOUT_EQUALS",
                ]
            ),
            encoding="utf-8",
        )
        monkeypatch.delenv("CUSTOM_ENV_FILE_KEY", raising=False)
        monkeypatch.delenv("CUSTOM_SPACED_KEY", raising=False)

        load_env_file(env_file)

        assert os.environ["CUSTOM_ENV_FILE_KEY"] == "from-file"
        assert os.environ["CUSTOM_SPACED_KEY"] == " spaced value "

    def test_load_env_file_does_not_override_existing_env(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("CUSTOM_EXISTING_KEY=from-file\n", encoding="utf-8")
        monkeypatch.setenv("CUSTOM_EXISTING_KEY", "existing")

        load_env_file(env_file)

        assert os.environ["CUSTOM_EXISTING_KEY"] == "existing"
