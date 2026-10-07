"""独立来源与旅程选择脚本冻结；矩阵默认不允许复用已见holdout。"""

from evals.rp_matrix import check_source_isolation, frozen_spec
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
