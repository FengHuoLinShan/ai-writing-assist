"""Nightly PostgreSQL B7: all four real engineering paths at all three scales."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from modules.account.models import Account
from modules.project.models import Project
from tests.e2e.config import require_e2e_database_url
from tools.scale_gate_harness import release_evidence, run_gate, sample_chapter_indices

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


@pytest.mark.parametrize("tier", ["low", "mid", "high"])
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
