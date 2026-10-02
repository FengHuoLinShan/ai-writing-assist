"""仓库治理门的负样本测试（B11 体积门 / P8 行数门 / B2 import 门）。

先例：tests/e2e/test_20_security.py 集中安全红线。本文件集中仓库治理门，
不依赖数据库，随 test-fast-coverage 进 CI。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_binary_growth  # noqa: E402
import check_file_sizes  # noqa: E402


# ============================================================
# B11 二进制增量体积门
# ============================================================


def test_binary_gate_blocks_oversized_single_file() -> None:
    change = check_binary_growth.BinaryChange(
        path="docs/plans/huge.png",
        status="A",
        delta_bytes=2 * 1024 * 1024,
        size_bytes=2 * 1024 * 1024,
    )

    problems = check_binary_growth.check([change])

    assert any("docs/plans/huge.png" in problem for problem in problems)


def test_binary_gate_blocks_pr_total_delta_over_limit() -> None:
    # 每个文件都在单文件限额内，但总增量超 5MB。
    per_file = 1_200_000
    changes = [
        check_binary_growth.BinaryChange(
            path=f"e2e/shot-{index}.png",
            status="A",
            delta_bytes=per_file,
            size_bytes=per_file,
        )
        for index in range(5)
    ]

    problems = check_binary_growth.check(changes)

    assert any("总增量" in problem for problem in problems)


def test_binary_gate_allows_small_binaries_and_modified_shrink() -> None:
    changes = [
        # 小二进制
        check_binary_growth.BinaryChange(
            path="docs/small.png", status="A", delta_bytes=1000, size_bytes=1000
        ),
        # 修改后反而变小（delta 0）
        check_binary_growth.BinaryChange(
            path="docs/plans/old.png",
            status="M",
            delta_bytes=0,
            size_bytes=900_000,
        ),
    ]

    assert check_binary_growth.check(changes) == []


def test_binary_gate_exempt_paths_block_only_registered_patterns() -> None:
    change = check_binary_growth.BinaryChange(
        path="backend/.test-logs/kept.png",
        status="M",
        delta_bytes=3_000_000,
        size_bytes=3_000_000,
    )

    # 未登记豁免时被拦
    assert check_binary_growth.check([change])
    # 登记豁免（带理由）后由 collect 阶段排除，check 不再见到它
    check_binary_growth.EXEMPT_PATHS["backend/.test-logs/**"] = "运行证据保留"
    try:
        assert check_binary_growth.is_exempt(change.path) == "运行证据保留"
    finally:
        check_binary_growth.EXEMPT_PATHS.pop("backend/.test-logs/**", None)


def test_binary_probe_detects_nul_bytes(tmp_path, monkeypatch) -> None:
    binary = tmp_path / "blob.bin"
    binary.write_bytes(b"PNG\x00rest")
    text = tmp_path / "note.md"
    text.write_text("普通中文文本", encoding="utf-8")

    monkeypatch.setattr(check_binary_growth, "REPO_ROOT", tmp_path.parent)
    # is_binary_file 按 REPO_ROOT / path 解析
    (tmp_path.parent / "blob.bin").write_bytes(b"PNG\x00rest")
    (tmp_path.parent / "note.md").write_text("普通中文文本", encoding="utf-8")

    assert check_binary_growth.is_binary_file("blob.bin") is True
    assert check_binary_growth.is_binary_file("note.md") is False


# ============================================================
# P8 生产文件行数门
# ============================================================


def test_file_size_gate_fails_new_file_over_5000_lines(tmp_path, monkeypatch) -> None:
    target = tmp_path / "big_service.py"
    target.write_text("x = 1\n" * 5001, encoding="utf-8")
    monkeypatch.setattr(check_file_sizes, "REPO_ROOT", tmp_path)
    check_file_sizes.SIZE_BASELINE.clear()

    failures, warnings = check_file_sizes.check_files(["big_service.py"])

    assert any("5001" in failure for failure in failures)
    assert not warnings


def test_file_size_gate_allows_baseline_file_and_warns_on_growth_within(
    tmp_path, monkeypatch
) -> None:
    target = tmp_path / "legacy.py"
    target.write_text("y = 2\n" * 5100, encoding="utf-8")
    monkeypatch.setattr(check_file_sizes, "REPO_ROOT", tmp_path)
    check_file_sizes.SIZE_BASELINE["legacy.py"] = 5200
    try:
        failures, warnings = check_file_sizes.check_files(["legacy.py"])
        assert failures == []
        assert any("入库基线" in warning for warning in warnings)

        # 涨破基线即失败
        target.write_text("y = 2\n" * 5201, encoding="utf-8")
        failures, _ = check_file_sizes.check_files(["legacy.py"])
        assert any("legacy.py" in failure for failure in failures)
    finally:
        check_file_sizes.SIZE_BASELINE.pop("legacy.py", None)


def test_file_size_gate_warns_between_3000_and_5000(tmp_path, monkeypatch) -> None:
    target = tmp_path / "mid.py"
    target.write_text("z = 3\n" * 3100, encoding="utf-8")
    monkeypatch.setattr(check_file_sizes, "REPO_ROOT", tmp_path)

    failures, warnings = check_file_sizes.check_files(["mid.py"])

    assert failures == []
    assert any("mid.py" in warning for warning in warnings)


def test_production_scope_excludes_tests_and_evals() -> None:
    assert check_file_sizes._is_production(
        "backend/modules/writing/services.py"
    )
    assert check_file_sizes._is_production("frontend-console/api.js")
    assert not check_file_sizes._is_production(
        "backend/modules/interaction/tests/test_services.py"
    )
    assert not check_file_sizes._is_production("backend/evals/rp_long_memory.py")
    assert not check_file_sizes._is_production("frontend-console/e2e/x.png")


# ============================================================
# B6 发布证据账本校验器
# ============================================================


def test_release_evidence_gate_rejects_incomplete_payload(tmp_path) -> None:
    import check_release_evidence as gate

    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps({"schema_version": "release-evidence-v1", "capability": "x"}),
        encoding="utf-8",
    )

    failures, _ = gate.check(evidence_dir=tmp_path, base="origin/main")

    assert any("缺少必填字段" in failure for failure in failures)


def test_release_evidence_gate_requires_claims_boundary(tmp_path) -> None:
    import check_release_evidence as gate

    payload = {
        "schema_version": "release-evidence-v1",
        "capability": "x",
        "dataset": {"name": "d", "files": []},
        "metrics": [],
        "generated_at": "2026-10-02T00:00:00+00:00",
        "generator_version": "g",
        "commit": "0d555c463",
        "claims_boundary": {"proves": []},  # 缺 does_not_prove
    }
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(payload), encoding="utf-8")

    failures, _ = gate.check(evidence_dir=tmp_path, base="origin/main")

    assert any("claims_boundary" in failure for failure in failures)


def test_release_evidence_gate_detects_sha_drift(tmp_path) -> None:
    import check_release_evidence as gate

    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text("{}\n", encoding="utf-8")
    payload = {
        "schema_version": "release-evidence-v1",
        "capability": "x",
        "dataset": {
            "name": "d",
            "files": [
                {
                    "path": str(dataset),
                    "sha256": "0" * 64,
                }
            ],
        },
        "metrics": [],
        "generated_at": "2026-10-02T00:00:00+00:00",
        "generator_version": "g",
        "commit": "0d555c463",
        "claims_boundary": {"proves": ["p"], "does_not_prove": ["n"]},
    }
    (tmp_path / "ev.json").write_text(json.dumps(payload), encoding="utf-8")

    failures, _ = gate.check(evidence_dir=tmp_path, base="origin/main")

    assert any("sha256 不一致" in failure for failure in failures)


def test_release_evidence_gate_flags_stale_evidence(tmp_path) -> None:
    import check_release_evidence as gate

    payload = {
        "schema_version": "release-evidence-v1",
        "capability": "x",
        "dataset": {"name": "d", "files": []},
        "metrics": [],
        "generated_at": "2024-01-01T00:00:00+00:00",
        "generator_version": "g",
        "commit": "0d555c463",
        "claims_boundary": {"proves": ["p"], "does_not_prove": ["n"]},
    }
    (tmp_path / "old.json").write_text(json.dumps(payload), encoding="utf-8")

    failures, warnings = gate.check(
        evidence_dir=tmp_path, base="origin/main", max_age_days=30
    )
    assert any("未更新" in failure for failure in failures)

    failures2, warnings2 = gate.check(
        evidence_dir=tmp_path, base="origin/main", max_age_days=30, stale_fails=False
    )
    assert failures2 == []
    assert any("未更新" in warning for warning in warnings2)


# ============================================================
# B2 跨模块 import 守护门
# ============================================================


def test_module_import_gate_blocks_reverse_dependency_sample(tmp_path) -> None:
    import check_module_imports as gate

    modules = {"alpha": ("modules/alpha",), "beta": ("modules/beta",)}
    offender = tmp_path / "modules" / "beta" / "offender.py"
    offender.parent.mkdir(parents=True)
    offender.write_text(
        "from modules.alpha.internal_helper import thing\n",
        encoding="utf-8",
    )

    violations = gate.iter_violations_for_paths(
        modules, [offender], repo_root=tmp_path, exempt={}
    )

    assert any(
        "modules.alpha.internal_helper" in item["target"] for item in violations
    )


def test_module_import_gate_allows_legal_forms(tmp_path) -> None:
    import check_module_imports as gate

    modules = {"alpha": ("modules/alpha",), "beta": ("modules/beta",)}
    legal = tmp_path / "modules" / "beta" / "legal.py"
    (tmp_path / "modules" / "beta").mkdir(parents=True, exist_ok=True)
    legal.write_text(
        "\n".join(
            [
                "from modules.alpha.contracts import A",
                "from modules.alpha.facade import B",
                "from modules.alpha import C",
                "from modules.alpha.sub.facade import D",
                "from modules.alpha.map_atlas_facade import E",
                "from modules.alpha.models import F",
                "from modules.alpha.session_models import G",
                "from core.errors import H",
                "from infrastructure.llm.client import I",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    violations = gate.iter_violations_for_paths(
        modules, [legal], repo_root=tmp_path, exempt={}
    )

    assert violations == []


def test_module_import_gate_exemption_patterns_apply(tmp_path) -> None:
    import check_module_imports as gate

    modules = {"alpha": ("modules/alpha",), "beta": ("modules/beta",)}
    offender = tmp_path / "modules" / "beta" / "legacy.py"
    offender.parent.mkdir(parents=True)
    offender.write_text("from modules.alpha.schemas import X\n", encoding="utf-8")

    blocked = gate.iter_violations_for_paths(
        modules, [offender], repo_root=tmp_path, exempt={}
    )
    assert blocked

    exempted = gate.iter_violations_for_paths(
        modules,
        [offender],
        repo_root=tmp_path,
        exempt={"modules/beta/legacy.py:modules.alpha.schemas": "历史豁免"},
    )
    assert exempted == []
