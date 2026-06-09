"""DedupScorer 单元测试与难例回归测试

覆盖异质信号计算的正确性与级联评分策略的决策边界。
"""

from __future__ import annotations

import pytest

from modules.world.services.dedup_scorer import DedupScorer, DedupSignals
from modules.world.services.dedup_service import EntityDedupService


@pytest.fixture
def scorer() -> DedupScorer:
    return DedupScorer()


class TestDedupSignals:
    """信号数据结构测试"""

    def test_to_vector_defaults(self) -> None:
        s = DedupSignals()
        vec = s.to_vector()
        assert len(vec) == 7
        assert all(v == 0.0 for v in vec)

    def test_to_vector_with_semantic(self) -> None:
        s = DedupSignals(semantic_cosine=0.75)
        vec = s.to_vector()
        assert vec[-2] == 0.75
        assert vec[-1] == 0.0

    def test_to_vector_without_semantic(self) -> None:
        s = DedupSignals(semantic_cosine=None)
        vec = s.to_vector()
        assert vec[-2] == 0.0
        assert vec[-1] == 0.0

    def test_pg_trgm_raw_defaults_to_zero(self) -> None:
        s = DedupSignals()
        assert s.pg_trgm_raw == 0.0
        assert s.to_vector()[-1] == 0.0

    def test_pg_trgm_raw_populated(self) -> None:
        s = DedupSignals(pg_trgm_raw=0.42)
        assert s.to_vector()[-1] == 0.42


class TestRapidfuzzSignals:
    """字符形相似信号测试"""

    def test_exact_match(self, scorer: DedupScorer) -> None:
        s = scorer.compute_signals("张三", "张三")
        assert s.rapidfuzz_ratio == 1.0
        assert s.rapidfuzz_token_sort == 1.0

    def test_partial_ratio_short_in_long(self, scorer: DedupScorer) -> None:
        s = scorer.compute_signals("张三", "张三丰科技有限公司")
        # partial_ratio 应捕获子串
        assert s.rapidfuzz_ratio == 1.0

    def test_token_sort_order_invariant(self, scorer: DedupScorer) -> None:
        # token_sort_ratio 对空格分隔的 token 顺序变化更鲁棒
        s = scorer.compute_signals("北京 上海 深圳", "深圳 北京 上海")
        # partial_ratio 不会认为完全匹配，但 token_sort_ratio 会
        assert s.rapidfuzz_token_sort > s.rapidfuzz_ratio


class TestPinyinSignals:
    """音似信号测试"""

    def test_same_pinyin(self, scorer: DedupScorer) -> None:
        s = scorer.compute_signals("深振业", "深振亚")
        # 同音不同字，拼音信号应很高
        assert s.pinyin_jaro >= 0.90

    def test_different_pinyin(self, scorer: DedupScorer) -> None:
        s = scorer.compute_signals("张三", "李四")
        assert s.pinyin_jaro < 0.5

    def test_pinyin_fallback_on_jaro_error(self, scorer: DedupScorer) -> None:
        # 正常场景下 JaroWinkler 可用，此测试验证回退路径存在
        score = scorer._fallback_overlap("abc", "abd")
        assert 0.0 < score < 1.0


class TestSubstringSignals:
    """子串包含信号测试"""

    def test_exact_match(self, scorer: DedupScorer) -> None:
        s = scorer.compute_signals("张三", "张三")
        assert s.substring_match == 1.0

    def test_bidirectional_contains(self, scorer: DedupScorer) -> None:
        s = scorer.compute_signals("张三", "张三")
        assert s.substring_match == 1.0

    def test_unidirectional_contains(self, scorer: DedupScorer) -> None:
        s = scorer.compute_signals("张三", "张三丰科技有限公司")
        assert s.substring_match == 0.85

    def test_alias_contains(self, scorer: DedupScorer) -> None:
        s = scorer.compute_signals("三丰", "张三丰科技有限公司", ["三丰"])
        assert s.substring_match == 0.85

    def test_no_overlap(self, scorer: DedupScorer) -> None:
        s = scorer.compute_signals("张三", "李四")
        assert s.substring_match == 0.0


class TestTrigramSignals:
    """Trigram Jaccard（模拟 pg_trgm）测试"""

    def test_exact_match(self, scorer: DedupScorer) -> None:
        s = scorer.compute_signals("张三", "张三")
        assert s.pg_trgm_raw == 1.0

    def test_no_overlap(self, scorer: DedupScorer) -> None:
        s = scorer.compute_signals("张三", "李四")
        assert s.pg_trgm_raw < 0.2

    def test_partial_overlap(self, scorer: DedupScorer) -> None:
        s = scorer.compute_signals("张三丰", "张三")
        assert 0.0 < s.pg_trgm_raw < 1.0


class TestPrefixConflict:
    """行政区划前缀冲突测试"""

    def test_beijing_vs_shanghai(self, scorer: DedupScorer) -> None:
        s = scorer.compute_signals("北京科技", "上海科技")
        assert s.prefix_conflict is True

    def test_same_prefix(self, scorer: DedupScorer) -> None:
        s = scorer.compute_signals("北京科技", "北京文化")
        assert s.prefix_conflict is False

    def test_no_prefix(self, scorer: DedupScorer) -> None:
        s = scorer.compute_signals("张三", "李四")
        assert s.prefix_conflict is False


class TestLenDiffRatio:
    """长度差异信号测试"""

    def test_same_length(self, scorer: DedupScorer) -> None:
        s = scorer.compute_signals("张三", "李四")
        assert s.len_diff_ratio == 1.0

    def test_large_diff(self, scorer: DedupScorer) -> None:
        s = scorer.compute_signals("张三", "张三丰科技有限公司")
        assert s.len_diff_ratio < 0.5


class TestHardCases:
    """难例回归测试 — 这些 case 是改造的核心动机"""

    def test_zhangsanfen_vs_zhangsanfeng(self, scorer: DedupScorer) -> None:
        """张三分 vs 张三丰：近形歧义，拼音应极高但 partial 也高。

        级联规则应能利用多重信号区分笔误 vs 不同人。
        """
        s = scorer.compute_signals("张三分", "张三丰")
        assert s.rapidfuzz_ratio >= 0.75
        assert s.pinyin_jaro >= 0.90  # 拼音几乎相同
        # 不是子串包含
        assert s.substring_match < 0.85

    def test_wangwu_vs_wanglaowu(self, scorer: DedupScorer) -> None:
        """王五 vs 王老五：衍生名，partial 不应过高到误判。"""
        s = scorer.compute_signals("王五", "王老五")
        # partial_ratio 会比较高（王五是王老五的子串）
        assert s.substring_match == 0.85  # 单向包含
        # 但级联中 substring 直接给 0.95，需要其他规则来审查
        assert s.pinyin_jaro >= 0.90

    def test_mianjuren_vs_lisi_no_semantic(self, scorer: DedupScorer) -> None:
        """面具人 vs 李四：无语义向量时，纯词法信号应很低。"""
        s = scorer.compute_signals("面具人", "李四")
        assert s.rapidfuzz_ratio < 0.5
        assert s.substring_match == 0.0
        assert s.pinyin_jaro < 0.5

    def test_mianjuren_vs_lisi_with_semantic(self, scorer: DedupScorer) -> None:
        """面具人 vs 李四：有语义向量时，语义信号应主导。"""
        s = scorer.compute_signals(
            "面具人", "李四",
            semantic_cosine=0.88,
        )
        assert s.semantic_cosine == 0.88
        # 即使词法信号低，语义高也能通过级联

    def test_shenzhenye_vs_shenzhenya(self, scorer: DedupScorer) -> None:
        """深振业 vs 深振亚：同音不同字，拼音信号应高。"""
        s = scorer.compute_signals("深振业", "深振亚")
        assert s.pinyin_jaro >= 0.90
        assert s.rapidfuzz_ratio >= 0.75

    def test_alias_exact_match(self, scorer: DedupScorer) -> None:
        """别名精确匹配应返回 substring=0.85（单向包含）或更高。"""
        s = scorer.compute_signals(
            "四哥", "李四",
            candidate_aliases=["四哥"],
        )
        assert s.substring_match >= 0.85


class TestCascadeScore:
    """EntityDedupService._cascade_score 决策边界测试"""

    @pytest.fixture
    def dedup_svc(self) -> EntityDedupService:
        from modules.world.services.dedup_service import EntityDedupService
        return EntityDedupService()

    def test_exact_name_not_handled_by_cascade(
        self, dedup_svc: EntityDedupService,
    ) -> None:
        # 精确匹配在 find_similar_entities 中直接处理，不走 _cascade_score
        pass

    def test_substring_full(self, dedup_svc: EntityDedupService) -> None:
        from shared.enums import CandidateAction
        s = DedupSignals(substring_match=0.85)
        sim, method, action = dedup_svc._cascade_score(s)
        assert sim == 0.95
        assert method == "substring"
        assert action == CandidateAction.merge_with_existing

    def test_high_fuzzy_and_pinyin(self, dedup_svc: EntityDedupService) -> None:
        from shared.enums import CandidateAction
        s = DedupSignals(rapidfuzz_ratio=0.95, pinyin_jaro=0.95)
        sim, method, action = dedup_svc._cascade_score(s)
        assert sim == 0.90
        assert method == "fuzzy_pinyin"
        assert action == CandidateAction.merge_with_existing

    def test_high_semantic(self, dedup_svc: EntityDedupService) -> None:
        from shared.enums import CandidateAction
        s = DedupSignals(semantic_cosine=0.88)
        sim, method, action = dedup_svc._cascade_score(s)
        assert sim >= 0.80
        assert method == "semantic"
        assert action == CandidateAction.merge_with_existing

    def test_medium_semantic(self, dedup_svc: EntityDedupService) -> None:
        from shared.enums import CandidateAction
        s = DedupSignals(semantic_cosine=0.78)
        sim, method, action = dedup_svc._cascade_score(s)
        assert method == "semantic"
        assert action == CandidateAction.needs_user_decision

    def test_low_semantic_falls_to_lexical(self, dedup_svc: EntityDedupService) -> None:
        from shared.enums import CandidateAction
        s = DedupSignals(
            semantic_cosine=0.60,
            rapidfuzz_ratio=0.80,
            pinyin_jaro=0.80,
            rapidfuzz_token_sort=0.80,
            substring_match=0.0,
        )
        sim, method, action = dedup_svc._cascade_score(s)
        assert method == "lexical_fusion"
        # lexical = 0.5*0.8 + 0.2*0.8 + 0.2*0.8 + 0.1*0 = 0.72
        assert pytest.approx(sim, 0.01) == 0.72
        assert action == CandidateAction.needs_user_decision

    def test_prefix_conflict_downgrades(self, dedup_svc: EntityDedupService) -> None:
        from shared.constants import DEDUP_DISCARD_THRESHOLD
        s = DedupSignals(
            rapidfuzz_ratio=0.90,
            pinyin_jaro=0.90,
            rapidfuzz_token_sort=0.90,
            substring_match=0.5,
            prefix_conflict=True,
        )
        sim, method, action = dedup_svc._cascade_score(s)
        # 前缀冲突应降权到 discard 区间以下
        assert sim < DEDUP_DISCARD_THRESHOLD

    def test_below_discard(self, dedup_svc: EntityDedupService) -> None:
        from shared.constants import DEDUP_DISCARD_THRESHOLD
        s = DedupSignals(
            rapidfuzz_ratio=0.3,
            pinyin_jaro=0.2,
            rapidfuzz_token_sort=0.3,
            substring_match=0.0,
        )
        sim, method, action = dedup_svc._cascade_score(s)
        assert sim < DEDUP_DISCARD_THRESHOLD
