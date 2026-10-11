"""rp_cost_baseline 冻结样本族守护。

M0 测量的可复跑性依赖样本族常量与确定性语料生成；这里钉住族哈希与
生成器确定性，改动任一常量都必须显式换种子并在任务记录中说明。
"""

from __future__ import annotations

from evals.rp_cost_baseline import (
    FAMILY_SEED,
    _chapter_text,
    _query_for_round,
    build_family_spec,
    spec_hash,
)

FROZEN_SPEC_HASH = "2d40ed20bc8ae3df3fa83fcfb58aeccee4a5402c8ceed634339c1cbdd00a6698"


def test_family_spec_hash_is_frozen() -> None:
    assert spec_hash(build_family_spec()) == FROZEN_SPEC_HASH


def test_chapter_text_is_deterministic() -> None:
    first = _chapter_text(FAMILY_SEED % 36 + 1)
    second = _chapter_text(FAMILY_SEED % 36 + 1)
    assert first == second
    assert len(first) > 1500


def test_query_family_rounds_are_distinct() -> None:
    queries = [_query_for_round(index) for index in range(6)]
    assert len(set(queries)) == 6
    assert all(len(query) > 400 for query in queries)
