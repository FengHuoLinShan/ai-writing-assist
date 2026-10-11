"""发布成功、派生索引失败的恢复用例（BR-0b 交接 P0-4「正文已存、派生未完成」）。

正文发布与索引派生分别投影：索引失败不回滚已发布正文，失败状态对作者可见，
并可用既有重建入口恢复到新鲜。
"""

from __future__ import annotations

import uuid
from unittest import mock

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.service_keys import RAG_INDEX_CHAPTER_FOR_TASK
from infrastructure.tasks.models import AsyncTask
from modules.evidence.indexing.index_state import RagIndexStateService
from modules.evidence.indexing.models import RagIndexState
from modules.project.models import Project
from modules.writing.models import WritingDraft


def _worker(sessions):
    import modules.evidence.indexing.tasks  # noqa: F401  (注册任务处理器)
    import modules.writing.tasks  # noqa: F401  (注册任务处理器)
    from infrastructure.tasks.worker import TaskWorker
    from run_worker import (
        _guard_active_task_project_finalize,
        _require_active_task_project,
    )

    class _Manager:
        def __init__(self) -> None:
            self.engine = sessions.kw["bind"]
            self.session_factory = sessions

    return TaskWorker(
        db_manager=_Manager(),
        heartbeat_interval=60.0,
        task_preflight=_require_active_task_project,
        task_commit_guard=_guard_active_task_project_finalize,
    )


async def _owner_index_task(sessions, novel_id: str) -> uuid.UUID:
    """定位章节索引状态登记的在途 owner 任务（mark_dirty 入队的恢复任务）。"""
    async with sessions() as db:
        owner_id = (
            await db.execute(
                select(RagIndexState.active_task_id).where(
                    RagIndexState.novel_id == uuid.UUID(str(novel_id)),
                    RagIndexState.chapter_index == 1,
                    RagIndexState.content_mode == "canonical",
                )
            )
        ).scalar_one_or_none()
    assert owner_id is not None, "mark_dirty 应已登记章节索引 owner 任务"
    return uuid.UUID(str(owner_id))


@pytest.mark.asyncio
async def test_publish_success_index_failure_visible_and_pending_index_recovers(
    test_engine,
    monkeypatch,
):
    """发布落库后索引失败：正文不回滚，索引进 stale 可见，重建后恢复新鲜。"""
    from core.container import container_scope
    from infrastructure.tasks.facade import enqueue_task
    from modules.evidence.facade import mark_chapter_index_dirty
    from modules.writing.facade import create_published_draft_only

    sessions = async_sessionmaker(
        test_engine,
        expire_on_commit=False,
        autoflush=False,
    )
    novel_uuid = uuid.uuid4()
    novel_id = str(novel_uuid)

    async with sessions() as setup_db:
        setup_db.add(
            Project(
                id=novel_uuid,
                title="publish index recovery",
                language="zh",
                default_reveal_policy="author_safe",
                settings={},
            )
        )
        await setup_db.flush()
        await create_published_draft_only(
            setup_db,
            novel_id,
            1,
            "第一章",
            "周明瑞从梦中醒来，发现一切都变得陌生。" * 20,
        )
        await mark_chapter_index_dirty(
            setup_db,
            novel_id,
            1,
            content_mode="canonical",
        )
        publish_task_id = uuid.UUID(
            enqueue_task(
                setup_db,
                "publish_chapter",
                meta={"novel_id": novel_id, "chapter_index": 1},
                novel_id=novel_id,
            )
        )
        await setup_db.commit()

    try:

        async def _index_down(*_args, **_kwargs):
            raise RuntimeError("embedding service down")

        with container_scope({RAG_INDEX_CHAPTER_FOR_TASK: _index_down}):
            worker = _worker(sessions)
            returned = await worker.run_once(task_id=publish_task_id, novel_id=novel_id)
        assert returned is not None
        assert returned.status == "failed"
        assert "请稍后重试" in (returned.error_message or "")

        async with sessions() as check_db:
            # 正文发布不回滚；索引失败对作者可见（stale + 非 succeeded 状态）
            published = (
                await check_db.execute(
                    select(WritingDraft).where(
                        WritingDraft.novel_id == novel_uuid,
                        WritingDraft.chapter_index == 1,
                    )
                )
            ).scalars()
            assert any(d.status == "published" for d in published)
            state = (
                await check_db.execute(
                    select(RagIndexState).where(
                        RagIndexState.novel_id == novel_uuid,
                        RagIndexState.chapter_index == 1,
                        RagIndexState.content_mode == "canonical",
                    )
                )
            ).scalar_one_or_none()
            assert state is not None
            assert state.status != "succeeded"
            freshness = await RagIndexStateService().freshness(
                check_db,
                novel_id=novel_id,
                content_mode="canonical",
            )
            assert freshness["stale"] == 1

        # 既有重试入口：mark_dirty 已入队的 rag_index_chapter 在途 owner 任务
        # 完成索引，章节状态恢复新鲜（chunk 级 embedding 失败另有 retry-embeddings
        # 入口，不影响章节新鲜度投影）
        mock_client = mock.AsyncMock()
        mock_client.generate_embedding = mock.AsyncMock(
            side_effect=Exception("embedding down")
        )
        with mock.patch(
            "infrastructure.llm.client.LLMClient",
            autospec=True,
        ) as mock_client_cls:
            mock_client_cls.return_value = mock_client
            worker = _worker(sessions)
            reindex_task_id = await _owner_index_task(sessions, novel_id)
            reindexed = await worker.run_once(task_id=reindex_task_id, novel_id=novel_id)
        assert reindexed is not None
        assert reindexed.status == "done"
        result = reindexed.result or {}
        assert result["chunks_created"] > 0

        async with sessions() as verify_db:
            state = (
                await verify_db.execute(
                    select(RagIndexState).where(
                        RagIndexState.novel_id == novel_uuid,
                        RagIndexState.chapter_index == 1,
                        RagIndexState.content_mode == "canonical",
                    )
                )
            ).scalar_one_or_none()
            assert state is not None
            assert state.status == "succeeded"
            assert state.indexed_hash == state.requested_hash
            freshness = await RagIndexStateService().freshness(
                verify_db,
                novel_id=novel_id,
                content_mode="canonical",
            )
            assert freshness["stale"] == 0
            assert freshness["fresh"] == 1
    finally:
        async with sessions.begin() as cleanup_db:
            await cleanup_db.execute(
                delete(RagIndexState).where(RagIndexState.novel_id == novel_uuid)
            )
            from modules.evidence.indexing.models import RagChunk

            await cleanup_db.execute(
                delete(RagChunk).where(RagChunk.novel_id == novel_uuid)
            )
            await cleanup_db.execute(
                delete(WritingDraft).where(WritingDraft.novel_id == novel_uuid)
            )
            await cleanup_db.execute(
                delete(AsyncTask).where(AsyncTask.novel_id == novel_uuid)
            )
            await cleanup_db.execute(delete(Project).where(Project.id == novel_uuid))
