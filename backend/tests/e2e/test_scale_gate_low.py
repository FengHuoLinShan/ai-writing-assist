"""长篇规模分档门（B7）：低档阈值回归，随每日 PG e2e 运行。

检索/审校分片/任务编排链路的规模覆盖由 tools/evolution_scale_harness
承接；本测试锁定编译链路在低档（10 万字）夹具上的确定性成本与
「输入成本不随章节位置无界增长」的边界。
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


@pytest_asyncio.fixture
async def scale_novel_id(db_session: AsyncSession, test_project_id: str) -> str:
    """在专用项目下预置低档夹具的全部章节草稿。"""
    from uuid import UUID

    from modules.writing.models import WritingDraft
    from tools.scale_fixtures import generate_corpus

    novel_uuid = UUID(test_project_id)
    chapters = generate_corpus("low")
    for index, chapter in enumerate(chapters, start=1):
        db_session.add(
            WritingDraft(
                novel_id=novel_uuid,
                chapter_index=index,
                title=chapter["title"],
                content=chapter["content"],
                content_hash="",
                version_number=1,
                status="published",
            )
        )
    await db_session.flush()
    return test_project_id


async def test_scale_gate_low_tier_compilation_thresholds(
    db_session: AsyncSession, scale_novel_id: str
) -> None:
    import json
    from pathlib import Path

    from tools.scale_gate_harness import (
        ScaleGateReport,
        check_thresholds,
        evaluate_growth,
        probe_compilation,
        sample_chapter_indices,
    )

    chapter_count = 22
    indices = sample_chapter_indices(chapter_count)
    probes = await probe_compilation(
        db_session, novel_id=scale_novel_id, indices=indices
    )

    assert len(probes) == len(indices)
    # 编译必须成功产出 sections（每章都有正文 objective 与基础结构）
    assert all(probe.section_count >= 1 for probe in probes)

    report = ScaleGateReport(tier="low", chapters=chapter_count, sampled=probes)
    evaluate_growth(report)
    # 核心边界：无 RAG 索引时编译输入由预算封顶，不随章节位置增长。
    assert report.growth_ratio == 1.0

    baselines = json.loads(
        (
            Path(__file__).resolve().parents[2] / "tools" / "scale_gate_baselines.json"
        ).read_text(encoding="utf-8")
    )
    check_thresholds(report, baselines=baselines)


async def test_scale_gate_sample_indices_are_stable() -> None:
    from tools.scale_gate_harness import sample_chapter_indices

    assert sample_chapter_indices(22) == [1, 6, 11, 16, 22]
    assert sample_chapter_indices(1) == [1]
    assert sample_chapter_indices(220) == [1, 55, 110, 165, 220]
