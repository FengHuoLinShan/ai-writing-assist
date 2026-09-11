"""
shared/constants.py 单元测试

验证全局常量的类型和取值范围正确。
"""

from shared.constants import (
    DEDUP_AUTO_MERGE_THRESHOLD,
    DEDUP_CONFLICT_FIELDS,
    DEDUP_DISCARD_THRESHOLD,
    DEDUP_REVIEW_THRESHOLD,
    DEFAULT_LLM_MAX_TOKENS,
    DEFAULT_PAGE_SIZE,
    LLM_RETRY_BASE_DELAY,
    LLM_RETRY_MAX_ATTEMPTS,
    MAX_PAGE_SIZE,
    RAG_IMPORTANCE_WEIGHT,
    RAG_KEYWORD_WEIGHT,
    RAG_RELATION_WEIGHT,
    RAG_VECTOR_WEIGHT,
    TASK_HEARTBEAT_INTERVAL,
    TASK_MAX_HEARTBEAT_GAP,
)


class TestPagination:
    def test_default_page_size(self):
        assert DEFAULT_PAGE_SIZE == 20
        assert isinstance(DEFAULT_PAGE_SIZE, int)

    def test_max_page_size(self):
        assert MAX_PAGE_SIZE == 50
        assert MAX_PAGE_SIZE > DEFAULT_PAGE_SIZE


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


class TestTasks:
    def test_max_heartbeat_gap_reasonable(self):
        assert TASK_MAX_HEARTBEAT_GAP > TASK_HEARTBEAT_INTERVAL
