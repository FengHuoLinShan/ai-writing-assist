"""作品进度投影（BR-1b）：候选/已采用只读投影与任务概要并入。

投影只读门禁结果与 provenance，不写回领域事实；任务概要经 BR-1a 的
tasks 只读缝取回后由组合根 adapter 合并。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from modules.project.contracts import WorkspaceCreationProgressItem
from modules.writing.models import WritingDraft
from modules.writing.repositories import WritingDraftRepository
from modules.writing.schemas import WritingDraftCreate
from modules.writing.services import WritingDraftService


async def _create_draft(
    db_session,
    novel_id: str,
    *,
    status: str,
    provenance: dict,
    chapter: int = 1,
    title: str | None = "AI 建议",
) -> WritingDraft:
    return await WritingDraftRepository().create_with_status(
        db_session,
        WritingDraftCreate(
            novel_id=novel_id,
            chapter_index=chapter,
            title=title,
            content="正文",
            provenance_json=provenance,
        ),
        status=status,
    )


@pytest.mark.asyncio
async def test_candidate_progress_surfaces_review_gate_stop(
    db_session,
    test_project_id,
) -> None:
    await _create_draft(
        db_session,
        test_project_id,
        status="candidate",
        provenance={
            "source": "writing_generate",
            "review_required": True,
            "knowledge_review": {"status": "unverifiable"},
        },
    )
    items = await WritingDraftService().list_creation_progress(
        db_session, test_project_id
    )
    assert len(items) == 1
    item = items[0]
    assert item.kind == "candidate"
    assert item.review_status == "unverifiable"
    assert item.stop_reason == "资料复核未完成，暂不能采用"
    assert item.applicability == "blocked"
    assert set(item.actions) == {"open_candidate", "reconfirm"}
    assert item.title.startswith("第 1 章 ·")


@pytest.mark.asyncio
async def test_candidate_progress_ready_for_review(
    db_session,
    test_project_id,
) -> None:
    await _create_draft(
        db_session,
        test_project_id,
        status="candidate",
        provenance={
            "source": "writing_generate",
            "review_required": True,
            "knowledge_review": {"status": "passed"},
            "independent_review": {"verdict": "pass", "blocking_count": 0},
        },
    )
    items = await WritingDraftService().list_creation_progress(
        db_session, test_project_id
    )
    assert items[0].stop_reason == "可审阅，待作者采用"
    assert items[0].source_freshness == "fresh"
    assert items[0].actions == ("open_candidate",)


@pytest.mark.asyncio
async def test_candidate_progress_needs_revision_and_stale(
    db_session,
    test_project_id,
) -> None:
    await _create_draft(
        db_session,
        test_project_id,
        status="candidate",
        provenance={
            "source": "writing_generate",
            "review_required": True,
            "knowledge_review": {"status": "passed", "stale_after_edit": True},
            "independent_review": {"verdict": "needs_revision", "blocking_count": 2},
        },
    )
    items = await WritingDraftService().list_creation_progress(
        db_session, test_project_id
    )
    assert items[0].stop_reason == "独立审查发现 2 个必须先处理的问题"
    assert items[0].source_freshness == "stale"


@pytest.mark.asyncio
async def test_adopted_and_published_progress_distinct(
    db_session,
    test_project_id,
) -> None:
    await _create_draft(
        db_session,
        test_project_id,
        status="draft",
        provenance={
            "source": "writing_generate",
            "adopted_from_candidate_id": "00000000-0000-0000-0000-00000000c001",
            "knowledge_review": {"status": "passed"},
            "adopted_with_open_issues": {
                "check_version": 1,
                "review_output_hash": "review_output_abc",
                "open_finding_ids": ["finding_a", "finding_b"],
            },
        },
    )
    await _create_draft(
        db_session,
        test_project_id,
        status="published",
        chapter=2,
        provenance={
            "source": "writing_generate",
            "adopted_from_candidate_id": "00000000-0000-0000-0000-00000000c002",
            "knowledge_review": {"status": "passed"},
        },
    )
    items = await WritingDraftService().list_creation_progress(
        db_session, test_project_id
    )
    by_status = {item.adoption_status: item for item in items}
    assert set(by_status) == {"adopted", "published"}
    assert by_status["adopted"].coverage.endswith("带 2 条未处理建议采用")
    assert by_status["published"].stop_reason == "已发布"
    assert by_status["adopted"].draft_id and by_status["published"].draft_id


@pytest.mark.asyncio
async def test_adapter_merges_task_overview_without_raw_meta(
    db_session,
    test_project_id,
    monkeypatch,
) -> None:
    """任务概要只保留 writing 类型且不带 raw meta；done 任务不重复出条目。"""

    async def fake_overview(
        db, *, novel_id, task_type=None, active_limit=50, terminal_limit=10
    ):
        return [
            SimpleNamespace(
                task_id="t-running",
                task_type="writing_generate",
                status="running",
                stale=False,
                recovery_required=False,
                meta={"chapter_index": 3, "secret": "raw-meta"},
                heartbeat_at="2026-10-09T10:00:00+00:00",
                finished_at=None,
                created_at="2026-10-09T09:59:00+00:00",
            ),
            SimpleNamespace(
                task_id="t-done",
                task_type="writing_generate",
                status="done",
                stale=False,
                recovery_required=False,
                meta={"chapter_index": 1},
                heartbeat_at=None,
                finished_at="2026-10-09T09:00:00+00:00",
                created_at="2026-10-09T08:59:00+00:00",
            ),
            SimpleNamespace(
                task_id="t-world",
                task_type="world_generation_suggestion",
                status="running",
                stale=False,
                recovery_required=False,
                meta={},
                heartbeat_at=None,
                finished_at=None,
                created_at="2026-10-09T09:58:00+00:00",
            ),
        ]

    async def fake_writing_items(db, novel_id, *, limit=6):
        return [
            WorkspaceCreationProgressItem(
                key="candidate:c1",
                kind="candidate",
                title="第 1 章 · AI 正文建议",
                adoption_status="candidate",
                stop_reason="可审阅，待作者采用",
                updated_at=None,
            )
        ]

    monkeypatch.setattr(
        "infrastructure.tasks.facade.list_novel_task_overview", fake_overview
    )
    monkeypatch.setattr(
        "modules.writing.facade.list_creation_progress", fake_writing_items
    )
    from modules.writing.project_ports import WritingWorkspaceStatsAdapter

    items = await WritingWorkspaceStatsAdapter().get_creation_progress(
        db_session, test_project_id
    )
    assert [item.kind for item in items] == ["task", "candidate"]
    task = items[0]
    assert task.task_id == "t-running"
    assert task.title == "第 3 章 · 生成正文"
    assert task.stop_reason == "正在处理"
    assert task.actions == ("view_task",)
    assert all("secret" not in str(item) for item in items)
