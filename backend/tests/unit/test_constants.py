"""
shared/constants.py 单元测试

验证全局常量的类型和取值范围正确。
"""

from shared.constants import (
    API_PREFIX,
    APP_NAME,
    APP_VERSION,
    CONTEXT_BUDGET_DEFAULTS,
    DEDUP_AUTO_MERGE_THRESHOLD,
    DEDUP_CONFLICT_FIELDS,
    DEDUP_DISCARD_THRESHOLD,
    DEDUP_REVIEW_THRESHOLD,
    DEFAULT_EMBEDDING_DIM,
    DEFAULT_LLM_MAX_TOKENS,
    DEFAULT_LLM_TIMEOUT,
    DEFAULT_MAX_OVERFLOW,
    DEFAULT_PAGE_SIZE,
    DEFAULT_POOL_SIZE,
    ENTITY_EXTRACTION_MIN_IMPORTANCE_NORMAL,
    ENTITY_EXTRACTION_MIN_IMPORTANCE_STRICT,
    LLM_RETRY_BASE_DELAY,
    LLM_RETRY_MAX_ATTEMPTS,
    MAX_PAGE_SIZE,
    RAG_IMPORTANCE_WEIGHT,
    RAG_KEYWORD_WEIGHT,
    RAG_RELATION_WEIGHT,
    RAG_VECTOR_WEIGHT,
    SIMILARITY_HIGH_CONFIDENCE,
    SIMILARITY_LOW_CONFIDENCE,
    SIMILARITY_MEDIUM_CONFIDENCE,
    TASK_HEARTBEAT_INTERVAL,
    TASK_MAX_HEARTBEAT_GAP,
    VECTOR_INDEX_EF_CONSTRUCTION,
    VECTOR_INDEX_LISTS,
    VECTOR_INDEX_M,
)


class TestPagination:
    def test_default_page_size(self):
        assert DEFAULT_PAGE_SIZE == 20
        assert isinstance(DEFAULT_PAGE_SIZE, int)

    def test_max_page_size(self):
        assert MAX_PAGE_SIZE == 50
        assert MAX_PAGE_SIZE > DEFAULT_PAGE_SIZE


class TestEmbedding:
    def test_default_dim(self):
        assert DEFAULT_EMBEDDING_DIM == 768
        assert isinstance(DEFAULT_EMBEDDING_DIM, int)


class TestSimilarity:
    def test_thresholds_ordering(self):
        assert SIMILARITY_HIGH_CONFIDENCE > SIMILARITY_MEDIUM_CONFIDENCE
        assert SIMILARITY_MEDIUM_CONFIDENCE > SIMILARITY_LOW_CONFIDENCE
        assert all(
            0 < t < 1
            for t in (
                SIMILARITY_HIGH_CONFIDENCE,
                SIMILARITY_MEDIUM_CONFIDENCE,
                SIMILARITY_LOW_CONFIDENCE,
            )
        )

    def test_high_confidence_value(self):
        assert SIMILARITY_HIGH_CONFIDENCE == 0.88


class TestRagWeights:
    def test_weights_sum_to_one(self):
        total = (
            RAG_VECTOR_WEIGHT
            + RAG_KEYWORD_WEIGHT
            + RAG_RELATION_WEIGHT
            + RAG_IMPORTANCE_WEIGHT
        )
        assert abs(total - 1.0) < 0.001

    def test_vector_weight_highest(self):
        assert RAG_VECTOR_WEIGHT > RAG_KEYWORD_WEIGHT
        assert RAG_VECTOR_WEIGHT > RAG_RELATION_WEIGHT
        assert RAG_VECTOR_WEIGHT > RAG_IMPORTANCE_WEIGHT


class TestContextBudget:
    def test_all_keys_present(self):
        expected = {
            "core_entities",
            "normal_entities",
            "characters",
            "memories",
            "foreshadowings",
            "timeline_events",
            "geo_relationships",
            "relation_edges",
            "rag_chunks",
        }
        assert set(CONTEXT_BUDGET_DEFAULTS.keys()) == expected

    def test_all_values_positive(self):
        assert all(v > 0 for v in CONTEXT_BUDGET_DEFAULTS.values())


class TestDedup:
    def test_thresholds_ordering(self):
        assert DEDUP_AUTO_MERGE_THRESHOLD > DEDUP_REVIEW_THRESHOLD
        assert DEDUP_REVIEW_THRESHOLD > DEDUP_DISCARD_THRESHOLD

    def test_discard_threshold_positive(self):
        assert DEDUP_DISCARD_THRESHOLD > 0
        assert DEDUP_AUTO_MERGE_THRESHOLD < 1.0

    def test_conflict_fields_not_empty(self):
        assert len(DEDUP_CONFLICT_FIELDS) > 0
        assert "weapon" in DEDUP_CONFLICT_FIELDS


class TestLLM:
    def test_max_retries_positive(self):
        assert LLM_RETRY_MAX_ATTEMPTS > 0

    def test_base_delay_positive(self):
        assert LLM_RETRY_BASE_DELAY > 0

    def test_default_tokens(self):
        assert DEFAULT_LLM_MAX_TOKENS == 12_000

    def test_default_timeout(self):
        assert DEFAULT_LLM_TIMEOUT == 60


class TestTasks:
    def test_max_heartbeat_gap_reasonable(self):
        assert TASK_MAX_HEARTBEAT_GAP > TASK_HEARTBEAT_INTERVAL


class TestExtraction:
    def test_strict_higher_than_normal(self):
        assert (
            ENTITY_EXTRACTION_MIN_IMPORTANCE_STRICT
            > ENTITY_EXTRACTION_MIN_IMPORTANCE_NORMAL
        )

    def test_values_in_range(self):
        assert 0 < ENTITY_EXTRACTION_MIN_IMPORTANCE_STRICT < 1
        assert 0 < ENTITY_EXTRACTION_MIN_IMPORTANCE_NORMAL < 1


class TestVectorIndex:
    def test_values_positive(self):
        assert VECTOR_INDEX_LISTS > 0
        assert VECTOR_INDEX_EF_CONSTRUCTION > 0
        assert VECTOR_INDEX_M > 0


class TestApp:
    def test_app_name(self):
        assert APP_NAME == "ai-novel-structural-engine"

    def test_app_version(self):
        assert APP_VERSION == "2.0.0"

    def test_api_prefix(self):
        assert API_PREFIX == "/api"


class TestDatabaseDefaults:
    def test_pool_size(self):
        assert DEFAULT_POOL_SIZE == 10

    def test_max_overflow(self):
        assert DEFAULT_MAX_OVERFLOW == 20
