from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    BACKEND_ROOT / "alembic" / "versions" / "20260703_squashed_current_schema.py"
)

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _load_migration_module():
    spec = importlib.util.spec_from_file_location(
        "test_squashed_current_schema",
        MIGRATION_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MIGRATION = _load_migration_module()


def _normalized(sql: str) -> str:
    return " ".join(sql.split())


def _settings(**kwargs):
    from core.config import Settings

    return Settings(**kwargs)


def test_default_settings_create_hnsw_index_sql(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("VECTOR_INDEX_TYPE", raising=False)

    sql = MIGRATION._create_vector_index_sql(
        "ix_rag_chunks_embedding",
        "rag_chunks",
        "embedding",
        "vector_ip_ops",
    )

    normalized = _normalized(sql)
    assert "CREATE INDEX IF NOT EXISTS ix_rag_chunks_embedding_hnsw" in normalized
    assert "ON rag_chunks USING hnsw (embedding vector_ip_ops)" in normalized


def test_ivfflat_settings_create_distinct_index_sql():
    sql = MIGRATION._create_vector_index_sql(
        "ix_rag_chunks_embedding",
        "rag_chunks",
        "embedding",
        "vector_ip_ops",
        settings=_settings(vector_index_type="ivfflat"),
    )

    normalized = _normalized(sql)
    assert "CREATE INDEX IF NOT EXISTS ix_rag_chunks_embedding_ivfflat" in normalized
    assert "ON rag_chunks USING ivfflat (embedding vector_ip_ops)" in normalized


def test_env_backed_settings_create_ivfflat_index_sql(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("VECTOR_INDEX_TYPE", "ivfflat")

    sql = MIGRATION._create_vector_index_sql(
        "ix_core_entities_embedding",
        "core_entities",
        "embedding",
        "vector_cosine_ops",
        settings=_settings(),
    )

    normalized = _normalized(sql)
    assert "CREATE INDEX IF NOT EXISTS ix_core_entities_embedding_ivfflat" in normalized
    assert "ON core_entities USING ivfflat (embedding vector_cosine_ops)" in normalized


def test_vector_indexes_use_runtime_operator_opclasses():
    rag_sql = MIGRATION._create_vector_index_sql(
        "ix_rag_chunks_embedding",
        "rag_chunks",
        "embedding",
        "vector_ip_ops",
        settings=_settings(vector_index_type="hnsw"),
    )
    world_sql = MIGRATION._create_vector_index_sql(
        "ix_core_entities_embedding",
        "core_entities",
        "embedding",
        "vector_cosine_ops",
        settings=_settings(vector_index_type="hnsw"),
    )

    assert "vector_ip_ops" in rag_sql
    assert "vector_cosine_ops" in world_sql


def test_invalid_vector_index_type_is_rejected_without_echoing_value():
    dangerous_value = "hnsw; DROP TABLE rag_chunks;--"

    with pytest.raises(ValueError) as exc_info:
        MIGRATION._create_vector_index_sql(
            "ix_rag_chunks_embedding",
            "rag_chunks",
            "embedding",
            "vector_ip_ops",
            settings=_settings(vector_index_type=dangerous_value),
        )

    message = str(exc_info.value)
    assert "hnsw, ivfflat" in message
    assert dangerous_value not in message
