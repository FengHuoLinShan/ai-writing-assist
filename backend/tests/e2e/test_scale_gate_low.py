"""Nightly PostgreSQL B7: all four real engineering paths at the low tier.

默认只跑 low 档阈值回归（方案 B7：nightly 只跑低档，防 hosted runner 超时）；
mid/high 全档定标在本地或手动执行，两种入口：
- pytest：``SCALE_GATE_ALL_TIERS=1``（仓库既有 env 开关惯例，见
  test_interaction_long_context_real_kimi.py）；
- CLI：``make scale-gate TIER=mid -- DATABASE_URL=...``。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from core.container import reset
from modules.account.models import Account
from modules.project.models import Project
from tests.e2e.config import require_e2e_database_url
from tools.scale_gate_harness import release_evidence, run_gate, sample_chapter_indices

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_evolution_harness_runs_from_cold_container(db_session):
    from tools.evolution_scale_harness import _assert_exit_criteria, run_harness

    connection = await db_session.connection()
    reset()  # Match the standalone CLI, which has not imported app.main.
    report = await run_harness(
        SimpleNamespace(create_schema=False, sampler="deterministic", limit=2, keep=True),
        connection=connection,
        chapters=[
            {"title": f"第{index}章", "content": "林舟取出星盘。柳青拿着钥匙。"}
            for index in range(1, 4)
        ],
    )

    _assert_exit_criteria(report)
    assert report.chapters == 3
    assert report.scenes_run == 2


def _tier_params() -> list[str]:
    if os.getenv("SCALE_GATE_ALL_TIERS") == "1":
        return ["low", "mid", "high"]
    return ["low"]


@pytest.mark.parametrize("tier", _tier_params())
async def test_scale_gate_four_paths_at_each_tier(db_session, tier):
    before_projects = await db_session.scalar(select(func.count()).select_from(Project))
    before_accounts = await db_session.scalar(select(func.count()).select_from(Account))
    report = await run_gate(
        SimpleNamespace(
            database_url=require_e2e_database_url(),
            create_schema=False,
            tier=tier,
            baseline_check=True,
        )
    )
    assert report.indexed_chunks > report.chapters
    assert report.retrieval_hits > 0
    assert report.reviewed_chapters == report.chapters
    assert report.orchestration["scenes_run"] == 6
    assert all(p.evidence_tokens > 100 for p in report.sampled)
    assert (
        await db_session.scalar(select(func.count()).select_from(Project))
        == before_projects
    )
    assert (
        await db_session.scalar(select(func.count()).select_from(Account))
        == before_accounts
    )
    # B6 consumes exactly the JSON exported by CLI/nightly; no format converter.
    import sys

    repo_root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(repo_root / "scripts"))
    import check_release_evidence as gate

    evidence = release_evidence(report)
    path = repo_root / "backend/.test-artifacts" / f"scale-{tier}.json"
    assert gate.validate_payload(evidence, path) == []
    assert gate.validate_files(evidence, path) == []
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")


async def test_scale_gate_sample_indices_are_stable():
    assert sample_chapter_indices(22) == [1, 6, 11, 16, 22]
    assert sample_chapter_indices(1) == [1]
    assert sample_chapter_indices(220) == [1, 55, 110, 165, 220]
