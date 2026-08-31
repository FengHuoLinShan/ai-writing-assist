"""
RAG 评分单元测试
"""

from __future__ import annotations

import pytest

from modules.evidence.indexing.scoring import (
    Scorer,
    compute_dynamic_weights,
    compute_keyword_score,
    compute_keyword_score_with_proximity,
    compute_relation_score,
    compute_temporal_decay,
    cosine_similarity,
    keyword_query_terms,
    smart_tokenize_chinese,
)


class TestCosineSimilarity:
    def test_identical_vectors(self) -> None:
        v = [1.0, 2.0, 3.0]
        assert abs(cosine_similarity(v, v) - 1.0) < 1e-6

    def test_orthogonal_vectors(self) -> None:
        assert abs(cosine_similarity([1.0, 0.0], [0.0, 1.0])) < 1e-6

    def test_zero_vector(self) -> None:
        assert cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0

    def test_different_dimensions(self) -> None:
        assert cosine_similarity([1.0], [1.0, 2.0]) == 0.0


class TestSmartTokenizeChinese:
    def test_space_separated(self) -> None:
        assert smart_tokenize_chinese("克莱恩 渴望 目标") == ["克莱恩", "渴望", "目标"]

    def test_single_char_filtered(self) -> None:
        assert smart_tokenize_chinese("一 的 人") == []

    def test_empty_query(self) -> None:
        assert smart_tokenize_chinese("") == []

    def test_mixed_chinese_english(self) -> None:
        terms = smart_tokenize_chinese("Klein 渴望")
        assert "klein" in terms
        assert "渴望" in terms

    def test_nfkc_punctuation_variants_are_equivalent(self) -> None:
        assert smart_tokenize_chinese("克莱恩，灰雾？") == smart_tokenize_chinese(
            "克莱恩,灰雾?"
        )


class TestKeywordScore:
    def test_long_chinese_question_uses_bounded_long_ngrams(self) -> None:
        query = "克莱恩在决裂之前为什么改变了继承立场"
        terms = keyword_query_terms(query)
        assert terms[0] == query
        assert len(terms) <= 97
        assert all(len(term) >= 2 for term in terms[1:])
        assert any("继承立场" in term for term in terms)

    def test_keyword_terms_ignore_punctuation_width(self) -> None:
        assert keyword_query_terms("克莱恩，灰雾？") == keyword_query_terms(
            "克莱恩,灰雾?"
        )

    def test_short_chinese_compound_keeps_bounded_ngrams(self) -> None:
        terms = keyword_query_terms("森林令牌")
        assert "森林" in terms
        assert "令牌" in terms
        assert "森林令牌" in terms

    def test_match(self) -> None:
        assert compute_keyword_score("艾伦在森林中行走", ["森林"]) == 1.0

    def test_no_match(self) -> None:
        assert compute_keyword_score("艾伦在城堡中", ["森林"]) == 0.0

    def test_empty_terms(self) -> None:
        assert compute_keyword_score("森林", []) == 0.0


class TestKeywordProximityScore:
    def test_close_terms_bonus(self) -> None:
        score = compute_keyword_score_with_proximity(
            "克莱恩渴望力量",
            ["克莱恩", "渴望"],
        )
        assert score > 0.5

    def test_far_terms_lower(self) -> None:
        score_far = compute_keyword_score_with_proximity(
            "克莱恩在很远很远的地方感受到了渴望",
            ["克莱恩", "渴望"],
        )
        score_close = compute_keyword_score_with_proximity(
            "克莱恩渴望力量",
            ["克莱恩", "渴望"],
        )
        assert score_close >= score_far

    def test_single_term(self) -> None:
        assert compute_keyword_score_with_proximity("克莱恩在森林中", ["克莱恩"]) == 1.0


class TestRelationScore:
    def test_no_filters(self) -> None:
        chunk = type(
            "Chunk",
            (),
            {"entity_ids": ["e1"], "character_ids": ["c1"], "thread_ids": []},
        )()
        assert compute_relation_score(chunk) == 0.0

    def test_character_match(self) -> None:
        chunk = type(
            "Chunk",
            (),
            {"entity_ids": [], "character_ids": ["c1"], "thread_ids": []},
        )()
        assert compute_relation_score(chunk, character_ids=["c1"]) == 1.0

    def test_case_insensitive(self) -> None:
        chunk = type(
            "Chunk",
            (),
            {"entity_ids": ["E1"], "character_ids": [], "thread_ids": []},
        )()
        assert compute_relation_score(chunk, entity_ids=["e1"]) == 1.0


class TestTemporalDecay:
    def test_extraction_no_decay(self) -> None:
        assert compute_temporal_decay(1, 100, "extraction") == 1.0

    def test_search_decay_increases_with_distance(self) -> None:
        close = compute_temporal_decay(5, 1, "search")
        far = compute_temporal_decay(20, 1, "search")
        assert far < close
        assert far == 0.5


class TestDynamicWeights:
    def test_short_query_boosts_keyword(self) -> None:
        weights = compute_dynamic_weights("克莱恩")
        # keyword weight should be highest
        assert weights[1] > weights[0]
        assert abs(sum(weights) - 1.0) < 1e-6

    def test_long_query_boosts_vector(self) -> None:
        long_query = "这是一个非常长的查询文本，用于测试动态权重分配"
        weights = compute_dynamic_weights(long_query)
        assert weights[0] > weights[1]
        assert abs(sum(weights) - 1.0) < 1e-6


class TestScorer:
    def test_vector_score_returns_zero_for_none(self) -> None:
        scorer = Scorer()
        assert scorer.vector_score(None, [0.1, 0.2]) == 0.0

    def test_importance_score(self) -> None:
        chunk = type("Chunk", (), {"importance": 0.8})()
        assert Scorer().importance_score(chunk) == pytest.approx(0.8)
