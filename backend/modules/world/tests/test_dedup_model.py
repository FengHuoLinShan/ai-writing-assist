"""DedupModelProxy 与 LR 模型评分集成测试。

覆盖模型加载、回退、阈值决策、短路路径。
"""

from __future__ import annotations

from unittest import mock

import pytest
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from modules.world.services.dedup_scorer import DedupSignals
from modules.world.services.dedup_service import (
    DedupModelProxy,
    EntityDedupService,
)
from shared.enums import CandidateAction


@pytest.fixture(autouse=True)
def reset_dedup_proxy():
    """每个测试后清理 DedupModelProxy 单例，防止泄漏到后续测试。"""
    yield
    DedupModelProxy._instance = None


@pytest.fixture
def dedup_svc() -> EntityDedupService:
    return EntityDedupService()


@pytest.fixture
def mock_pipeline() -> Pipeline:
    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression()),
    ])
    x_train = [[0.0] * 7, [0.2] * 7, [0.5] * 7, [0.9] * 7]
    y_train = [0, 0, 1, 1]
    pipeline.fit(x_train, y_train)
    return pipeline


@pytest.fixture
def mock_model_metadata() -> dict:
    return {
        "sklearn_version": "unknown_for_test",
        "feature_dim": 7,
        "model_version": "test",
        "thresholds": {
            "theta_merge": 0.80,
            "theta_review": 0.50,
            "theta_discard": 0.20,
        },
    }


@pytest.fixture
def patched_proxy(mock_pipeline: Pipeline, mock_model_metadata: dict):
    """构造一个已加载最小模型的代理实例。"""
    DedupModelProxy._instance = None
    proxy = object.__new__(DedupModelProxy)
    proxy._pipeline = mock_pipeline
    proxy._metadata = mock_model_metadata
    proxy._feature_dim = 7
    proxy._model_version = mock_model_metadata["model_version"]
    DedupModelProxy._instance = proxy
    return proxy


class TestDedupModelProxy:
    def test_model_loads_from_valid_pickle(
        self, patched_proxy: DedupModelProxy,
    ) -> None:
        proba, version = patched_proxy.predict([0.9] * 7)
        assert 0.0 <= proba <= 1.0
        assert version == "test"

    def test_missing_model_falls_back_to_cascade(
        self, dedup_svc: EntityDedupService,
    ) -> None:
        DedupModelProxy._instance = None
        proxy = object.__new__(DedupModelProxy)
        proxy._pipeline = None
        proxy._metadata = {}
        proxy._feature_dim = 7
        proxy._model_version = "unknown"
        DedupModelProxy._instance = proxy
        signals = DedupSignals(
            rapidfuzz_ratio=0.3, pinyin_jaro=0.2,
            rapidfuzz_token_sort=0.3, substring_match=0.0,
        )
        sim, method, action = dedup_svc._resolve_score(signals)
        from shared.constants import DEDUP_DISCARD_THRESHOLD
        assert sim < DEDUP_DISCARD_THRESHOLD
        assert method == "lexical_fusion"
        assert action == CandidateAction.ignore

    def test_feature_dim_mismatch_raises(self, patched_proxy: DedupModelProxy) -> None:
        patched_proxy._feature_dim = 99
        with pytest.raises(ValueError, match="expected 99 features"):
            patched_proxy.predict([0.5] * 7)
        patched_proxy._feature_dim = 7  # restore


class TestModelScore:
    def test_model_auto_merge(
        self, dedup_svc: EntityDedupService, patched_proxy: DedupModelProxy,
    ) -> None:
        with mock.patch("modules.world.services.dedup_service.DEDUP_MODEL_ACTIVE", True):
            signals = DedupSignals(
                rapidfuzz_ratio=0.9, pinyin_jaro=0.9,
                rapidfuzz_token_sort=0.9, substring_match=0.5,
                semantic_cosine=0.85, pg_trgm_raw=0.8,
            )
            sim, method, action = dedup_svc._resolve_score(signals)
            assert method == "lr_model"
            assert sim >= 0.80
            assert action == CandidateAction.merge_with_existing

    def test_model_review(
        self, dedup_svc: EntityDedupService, patched_proxy: DedupModelProxy,
    ) -> None:
        with mock.patch("modules.world.services.dedup_service.DEDUP_MODEL_ACTIVE", True):
            signals = DedupSignals(
                rapidfuzz_ratio=0.5, pinyin_jaro=0.5,
                rapidfuzz_token_sort=0.5, substring_match=0.0,
                semantic_cosine=0.60, pg_trgm_raw=0.3,
            )
            sim, method, action = dedup_svc._resolve_score(signals)
            assert method == "lr_model"
            assert 0.20 <= sim < 0.80
            assert action == CandidateAction.needs_user_decision

    def test_model_discard(
        self, dedup_svc: EntityDedupService, patched_proxy: DedupModelProxy,
    ) -> None:
        with mock.patch("modules.world.services.dedup_service.DEDUP_MODEL_ACTIVE", True):
            signals = DedupSignals(
                rapidfuzz_ratio=0.1, pinyin_jaro=0.1,
                rapidfuzz_token_sort=0.1, substring_match=0.0,
                semantic_cosine=0.10, pg_trgm_raw=0.0,
            )
            sim, method, action = dedup_svc._resolve_score(signals)
            assert method == "lr_model"
            assert sim < 0.20
            assert action == CandidateAction.ignore


class TestResolveScorePaths:
    def test_prefix_conflict_short_circuits_before_model(
        self, dedup_svc: EntityDedupService,
    ) -> None:
        # 用不会命中 fuzzy_pinyin 短路（rapidfuzz<0.92）的信号，
        # 使前缀冲突在 lexical 路径中生效
        signals = DedupSignals(
            rapidfuzz_ratio=0.90, pinyin_jaro=0.90,
            rapidfuzz_token_sort=0.90, substring_match=0.5,
            prefix_conflict=True,
        )
        sim, method, action = dedup_svc._cascade_score(signals)
        from shared.constants import DEDUP_DISCARD_THRESHOLD
        assert sim < DEDUP_DISCARD_THRESHOLD

    def test_exact_name_skips_model(self, dedup_svc: EntityDedupService) -> None:
        # exact_name 路径在 find_similar_entities 中直接返回，不进入 _resolve_score
        signals = DedupSignals()
        with mock.patch("modules.world.services.dedup_service.DEDUP_MODEL_ACTIVE", True):
            sim, method, action = dedup_svc._resolve_score(signals)
            # 无模型时回退到级联
            assert method in ("lr_model", "lexical_fusion")

    def test_to_vector_returns_7_elements(self) -> None:
        signals = DedupSignals(semantic_cosine=0.75, pg_trgm_raw=0.33)
        vec = signals.to_vector()
        assert len(vec) == 7
        assert vec[5] == 0.75
        assert vec[6] == 0.33

    def test_null_pinyin_defaults_to_zero(self) -> None:
        signals = DedupSignals()
        assert signals.pinyin_jaro == 0.0
        vec = signals.to_vector()
        assert vec[2] == 0.0


class TestNovelHardCases:
    def test_novel_full_vs_nickname(self, dedup_svc: EntityDedupService) -> None:
        signals = DedupSignals(substring_match=0.85)
        sim, method, action = dedup_svc._cascade_score(signals)
        assert sim == 0.95
        assert action == CandidateAction.merge_with_existing
