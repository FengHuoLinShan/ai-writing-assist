"""
core/config.py 单元测试

测试 Settings dataclass 的行为。
注意：部分字段使用 = int(_env(...)) 在类定义时求值，monkeypatch 无法覆盖；
仅 field(default_factory=...) 字段可在实例化时响应环境变量变化。
"""

import pytest

from core.config import Settings, _env, get_settings


class TestSettingsEffectiveDefaults:
    """验证 Settings 与项目 .env 文件一致的默认值"""

    def test_effective_pool_size(self):
        assert Settings().pool_size == 10

    def test_effective_max_overflow(self):
        assert Settings().max_overflow == 20

    def test_effective_echo_sql(self):
        assert Settings().echo_sql is False

    def test_effective_llm_max_tokens(self):
        assert Settings().llm_max_tokens == 4096

    def test_effective_llm_timeout(self):
        assert Settings().llm_timeout == 60

    def test_effective_embedding_dim(self):
        assert Settings().embedding_dim == 1024  # .env 覆盖默认 768

    def test_effective_inference_timeout(self):
        assert Settings().inference_worker_timeout == 30.0

    def test_effective_inference_max_batch(self):
        assert Settings().inference_worker_max_batch == 64

    def test_effective_reranker(self):
        assert Settings().reranker_enabled is False

    def test_effective_debug(self):
        assert Settings().debug is False

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

    def test_effective_log_level(self):
        assert Settings().log_level == "DEBUG"

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

    def test_llm_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "sk-test")
        assert Settings().llm_api_key == "sk-test"

    def test_llm_model_from_env(self, monkeypatch):
        monkeypatch.setenv("LLM_MODEL", "test-model")
        assert Settings().llm_model == "test-model"

    def test_llm_base_url_from_env(self, monkeypatch):
        monkeypatch.setenv("LLM_BASE_URL", "https://test.local/v1")
        assert Settings().llm_base_url == "https://test.local/v1"

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
