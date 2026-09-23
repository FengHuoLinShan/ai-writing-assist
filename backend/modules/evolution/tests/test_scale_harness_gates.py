"""E09 规模验证 harness 验收工具自身的测试（PR160-162 审查 F4/F5）。

验收工具不能只展示成功报告：退出判定必须真的拒绝异常报告（负向/
变异测试），real 模式缺计量、前序注入覆盖不足都必须失败；--limit
裁剪下跳场/过期检查的请求字段（scene_id、正文、章节号）必须指向
同一章，否则来源指纹在屏障之前拒绝，验证的就是错误的分支。
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from tools.evolution_scale_harness import (
    HarnessError,
    HarnessReport,
    _assert_exit_criteria,
    _step_request,
)


def _passing_report(sampler: str = "deterministic") -> HarnessReport:
    return HarnessReport(
        sampler=sampler,
        chapters=10,
        scenes_run=5,
        budget_total=5,
        budget_remaining_after_chain=0,
        budget_remaining_after_rerun=0,
        memory_events_written=0,
        prior_state_injected_scenes=[1, 2, 3, 4],
        barrier_skip_rejected=True,
        rerun_same_attempt=True,
        stale_source_rejected=True,
        stale_source_rejected_code="source_changed",
        quote_verbatim=True,
        mention_grounded=True,
        usage_recorded=True if sampler == "real" else None,
        wall_seconds=1.0,
    )


class TestExitCriteriaRejectsBrokenReports:
    """逐项把本应通过的 report 改坏，退出判定必须抛错（F4）。"""

    def test_passing_report_passes_for_both_samplers(self) -> None:
        _assert_exit_criteria(_passing_report())
        _assert_exit_criteria(_passing_report("real"))

    @pytest.mark.parametrize(
        "mutate, fragment",
        [
            (
                lambda r: setattr(r, "scenes_run", 0),
                "未推进任何 Scene",
            ),
            (
                lambda r: setattr(r, "budget_remaining_after_chain", 1),
                "链后预算剩余应为 0",
            ),
            (
                lambda r: setattr(r, "budget_remaining_after_rerun", 2),
                "幂等重跑后预算剩余应为 0",
            ),
            (
                lambda r: setattr(r, "memory_events_written", 1),
                "影子运行写入了正式 MemoryEvent",
            ),
            (
                lambda r: setattr(r, "prior_state_injected_scenes", [1]),
                "前序状态注入覆盖不符",
            ),
            (
                lambda r: setattr(r, "prior_state_injected_scenes", []),
                "前序状态注入覆盖不符",
            ),
            (
                lambda r: setattr(r, "barrier_skip_rejected", False),
                "跳场未被屏障拒绝",
            ),
            (
                lambda r: setattr(r, "rerun_same_attempt", False),
                "重跑未幂等返回原回执",
            ),
            (
                lambda r: setattr(r, "stale_source_rejected", False),
                "过期来源未被提交边界以精确",
            ),
            (
                # A09（2026-09-22 审查）：非 source_changed 的冲突 code 不得
                # 计为"过期来源被正确拦截"——parent_advanced 混过是假阳性。
                lambda r: setattr(r, "stale_source_rejected_code", "parent_advanced"),
                "过期来源拒绝未断言精确 code",
            ),
            (
                lambda r: setattr(r, "stale_source_rejected_code", None),
                "过期来源拒绝未断言精确 code",
            ),
            (
                lambda r: setattr(r, "quote_verbatim", False),
                "存在非逐字引用",
            ),
            (
                lambda r: setattr(r, "mention_grounded", False),
                "存在无据提及",
            ),
            (
                lambda r: setattr(r, "usage_recorded", False),
                "usage 计量未进入回执",
            ),
            (
                lambda r: setattr(r, "usage_recorded", None),
                "usage 计量未进入回执",
            ),
        ],
    )
    def test_mutated_report_fails_with_reason(
        self, mutate: Callable[[HarnessReport], None], fragment: str
    ) -> None:
        report = _passing_report("real")
        mutate(report)
        with pytest.raises(HarnessError) as excinfo:
            _assert_exit_criteria(report)
        assert fragment in str(excinfo.value)

    def test_deterministic_sampler_does_not_require_usage(self) -> None:
        report = _passing_report("deterministic")
        report.usage_recorded = None
        _assert_exit_criteria(report)  # 确定性采样无付费计量，不适用

    def test_single_scene_corpus_expects_no_prior_injection(self) -> None:
        # 单 Scene 语料：前序注入"不适用"，期望集为空集而非非空列表。
        report = _passing_report()
        report.scenes_run = 1
        report.prior_state_injected_scenes = []
        _assert_exit_criteria(report)


class _Corpus:
    def __init__(self, count: int = 10) -> None:
        self.texts = [f"第{index + 1}章正文。" for index in range(count)]
        self.scene_ids = [f"s{index}" for index in range(count)]


class TestVerificationSourceCoherenceUnderLimit:
    """--limit 裁剪下，跳场/过期检查的请求字段必须指向同一章（F5）。"""

    @pytest.mark.parametrize("limit", [2, 5, 9, 10])
    def test_skip_request_fields_stay_coherent(self, limit: int) -> None:
        corpus = _Corpus(10)
        budget_total = min(len(corpus.texts), limit)
        skip_source = (
            budget_total if budget_total < len(corpus.texts) else len(corpus.texts) - 1
        )
        request = _step_request(
            "n1",
            corpus.scene_ids,
            corpus.texts,
            skip_source,
            provider="p",
            budget_total=budget_total,
            scene_index=budget_total + 1,
            chapter_index=skip_source + 1,
        )
        # 同一章约束：正文、scene_id、章节号互相一致，来源指纹核验才能
        # 通过并走到屏障判定（修复前 --limit 5 用第六章正文配第十章号）。
        assert request["scene_text"] == corpus.texts[request["chapter_index"] - 1]
        assert request["scene_id"] == corpus.scene_ids[request["chapter_index"] - 1]
        assert request["scene_index"] == budget_total + 1

    @pytest.mark.parametrize("limit", [2, 5, 10])
    def test_stale_request_targets_the_revised_chapter(self, limit: int) -> None:
        corpus = _Corpus(10)
        budget_total = min(len(corpus.texts), limit)
        revised_chapter = budget_total  # harness 修订链尾章节（非语料末章）
        request = _step_request(
            "n1",
            corpus.scene_ids,
            corpus.texts,
            budget_total - 1,
            provider="p",
            budget_total=budget_total,
            scene_index=budget_total,
        )
        # 过期请求携带旧文本并指向被修订的同一章，指纹比对才会失败。
        assert request["chapter_index"] == revised_chapter
        assert request["scene_text"] == corpus.texts[revised_chapter - 1]
        assert request["scene_id"] == corpus.scene_ids[revised_chapter - 1]
        assert request["scene_index"] == budget_total
