"""独立来源与旅程选择脚本冻结；矩阵默认不允许复用已见holdout。"""

from evals.rp_matrix import (
    check_source_isolation,
    frozen_spec,
    source_invalidation_draft_ids,
    source_invalidation_result,
)
from evals.rp_source_families import FAMILIES


def test_matrix_source_families_and_long_holdout_are_disjoint_and_frozen():
    check_source_isolation()
    spec = frozen_spec()
    import json

    assert spec == frozen_spec() == json.loads(json.dumps(spec))
    assert spec["turns"] == {"dev": 30, "holdout": 30}
    assert spec["scope"] == "full_context_pipeline_original_layout"
    assert spec["judge_points"]["holdout"][-1] == 30
    assert len([family for family in FAMILIES if family.stage == "dev"]) == 6
    assert len([family for family in FAMILIES if family.stage == "holdout"]) == 3
    assert len({family.input(1) for family in FAMILIES}) == 9
    import hashlib

    assert spec["judge_ground_truth_hashes"] == {
        family.key: hashlib.sha256(family.judge_ground_truth.encode()).hexdigest()
        for family in FAMILIES
    }


def test_judge_uses_source_facts_beyond_the_short_recap_without_future_facts():
    family = next(family for family in FAMILIES if family.key == "dev-port")
    facts = family.judge_ground_truth
    assert "第6章：" in facts and "第12章：" in facts
    assert "彭野在等候区查看天气" in facts
    assert family.secret_canary in facts
    assert "不代表角色全部知情" in facts
    assert all(family.chapter(number) in facts for number in range(1, 13))
    assert family.future_canary not in facts
    assert "第37章：" not in facts


def test_source_invalidation_requires_a_source_failure_before_any_paid_call():
    from types import SimpleNamespace

    attempt = SimpleNamespace(
        status="failed", error_kind="source_context_blocked", visible_text=""
    )
    assert source_invalidation_result(attempt, 0)["source_blocked"]
    assert not source_invalidation_result(attempt, 1)["source_blocked"]
    for kind in ("quota", "configuration", "generation_failed", "timeout"):
        attempt.error_kind = kind
        assert not source_invalidation_result(attempt, 0)["source_blocked"]


def test_source_invalidation_removes_all_support_without_touching_future_sources():
    from uuid import uuid4

    manifest = [
        {"draft_id": str(uuid4()), "chapter_index": number}
        for number in (1, 2, 12, 37)
    ]
    ids = source_invalidation_draft_ids(manifest, 12)
    assert [str(value) for value in ids] == [ref["draft_id"] for ref in manifest[:3]]
