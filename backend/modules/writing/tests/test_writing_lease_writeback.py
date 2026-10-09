"""旧 worker 租约回写拒绝用例（BR-0b 交接 P0-4「旧 worker 恢复」）。

语义审查与定向返修的晚到回写携带旧租约：任务已被新租约完成后，旧回写不得
覆盖审查/返修结果。
"""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from typing import Any
from unittest import mock

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker

from infrastructure.llm.limits import reset_llm_limiter_for_tests
from infrastructure.llm.schemas import LLMCallResponse
from infrastructure.tasks.enqueuer import enqueue_task
from infrastructure.tasks.lifecycle import TaskLifecycleService
from infrastructure.tasks.models import AsyncTask
from infrastructure.tasks.worker import TaskWorker
from modules.project.models import Project
from modules.writing.models import WritingDraft


class _LeaseCapturingProvider:
    """provider 替身：首次调用时捕获任务行的运行中租约。"""

    name = "fake"

    def __init__(
        self,
        sessions,
        task_id: uuid.UUID,
        lease_holder: dict,
        draft_id: str,
    ) -> None:
        self._sessions = sessions
        self._task_id = task_id
        self._lease_holder = lease_holder
        self._draft_id = draft_id
        self.calls = 0

    async def generate(self, request) -> LLMCallResponse:
        del request
        self.calls += 1
        async with self._sessions() as db:
            row = await db.get(AsyncTask, self._task_id)
            assert row is not None and row.status == "running"
            self._lease_holder["lease_id"] = str(row.lease_id)
            self._lease_holder["attempt"] = int(row.attempt or 0)
        return LLMCallResponse(
            content=json.dumps(
                {
                    "findings": [],
                    "not_checked": [],
                    "coverage": [
                        {
                            "draft_id": self._draft_id,
                            "scene_contract": "checked",
                            "timeline_location": "checked",
                            "identity_relation": "checked",
                            "ability_world_rule": "checked",
                            "knowledge_boundary": "checked",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            finish_reason="stop",
            model="deepseek-flash",
            provider="fake",
        )


class _NullLimiter:
    def run(self, call, *, limiter_scope=None):
        return call()

    @asynccontextmanager
    async def scope(self, *, limiter_scope=None):
        yield


def _chain_client(monkeypatch: pytest.MonkeyPatch, provider: _LeaseCapturingProvider):
    from infrastructure.llm.client import LLMClient

    reset_llm_limiter_for_tests()
    client = LLMClient.from_project_settings(
        {"llm": {"provider_id": "deepseek", "model": "deepseek-flash"}}
    )
    client._provider = provider  # type: ignore[attr-defined]
    monkeypatch.setattr(
        "infrastructure.llm.client.get_llm_limiter", lambda: _NullLimiter()
    )
    return client


class _TaskManager:
    def __init__(self, engine: Any, sessions: Any) -> None:
        self.engine = engine
        self.session_factory = sessions


def _review_target(draft_id: str, content_hash: str) -> dict[str, Any]:
    return {
        "draft_id": draft_id,
        "chapter_index": 3,
        "title": "第三章",
        "content": "冻结正文",
        "content_hash": content_hash,
        "status": "candidate",
        "role": "target",
        "source_task_id": "generation-task",
        "scene_id": None,
        "scene_execution_bundle": None,
        "scene_execution_bundle_hash": None,
        "upstream_manifest": [],
        "review_context": {
            "status": "checked",
            "review_mode": "narrative_only",
            "context_fingerprint": "context-fingerprint",
            "confirmed_context": "已确认资料",
            "generation_profile": "default",
            "viewpoint_character_id": None,
            "pov_view": None,
            "deterministic_pov_validation": {
                "status": "passed",
                "findings": [],
                "warnings": [],
            },
            "knowledge_boundary_checked": True,
        },
    }


async def _old_lease_finalize_rejected(sessions, task_id, old_lease_id, poison) -> None:
    """旧租约的晚到 finalize 必须被拒绝且不覆盖已落库结果。"""
    async with sessions.begin() as stale_db:
        accepted = await TaskLifecycleService().finalize(
            stale_db,
            task_id=task_id,
            lease_id=old_lease_id,
            status="done",
            result_data=poison,
        )
    assert accepted is False
    async with sessions() as db:
        stored = await db.get(AsyncTask, task_id)
        assert stored is not None
        result = stored.result or {}
        assert result.get("verdict") == "pass"
        for value in result.values():
            assert value != "poisoned-by-stale-worker"


@pytest.mark.asyncio
async def test_semantic_review_rejects_stale_lease_writeback(test_engine, monkeypatch):
    """语义审查完成后，携带运行期旧租约的回写被栅栏拒绝。"""
    import modules.project.facade as project_facade
    import modules.writing.tasks  # noqa: F401  生产 handler 注册

    sessions = async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)
    novel_uuid = uuid.uuid4()
    novel_id = str(novel_uuid)
    content_hash = "a" * 64
    lease_holder: dict[str, Any] = {}

    async with sessions.begin() as db:
        db.add(
            Project(
                id=novel_uuid,
                title="stale lease review",
                language="zh",
                default_reveal_policy="author_safe",
                settings={},
            )
        )
        draft = WritingDraft(
            novel_id=novel_uuid,
            chapter_index=3,
            title="第三章",
            content="冻结正文",
            content_hash=content_hash,
            status="candidate",
            provenance_json={},
        )
        db.add(draft)
        await db.flush()
        draft_id = uuid.UUID(str(draft.id))
        task_id = uuid.UUID(
            enqueue_task(
                db,
                "writing_semantic_review",
                meta={
                    "novel_id": novel_id,
                    "draft_ids": [str(draft_id)],
                    "scope": "selection",
                    "llm_execution_snapshot": {
                        "profile": {"model": "deepseek-flash"},
                        "llm": {"model": "deepseek-flash"},
                    },
                },
                novel_id=novel_id,
            )
        )

    provider = _LeaseCapturingProvider(sessions, task_id, lease_holder, str(draft_id))

    @asynccontextmanager
    async def fake_snapshot_client(db, novel_id_arg, snapshot, **_kwargs):
        del db, novel_id_arg, snapshot
        client = _chain_client(monkeypatch, provider)
        yield client

    monkeypatch.setattr(project_facade, "require_active_project", _async_noop)
    monkeypatch.setattr(
        project_facade,
        "open_project_snapshot_llm_client",
        fake_snapshot_client,
    )
    import modules.writing.semantic_review as semantic_review_module

    target = _review_target(str(draft_id), content_hash)
    monkeypatch.setattr(
        semantic_review_module.WritingSemanticWorkflowService,
        "_freeze_review_set",
        mock.AsyncMock(side_effect=[([target], []), ([target], [])]),
    )

    try:
        returned = await TaskWorker(
            db_manager=_TaskManager(test_engine, sessions),
            heartbeat_interval=60.0,
        ).run_once(task_id=task_id, novel_id=novel_id)
        assert returned is not None and returned.status == "done"
        assert lease_holder.get("lease_id")

        await _old_lease_finalize_rejected(
            sessions,
            task_id,
            lease_holder["lease_id"],
            {"verdict": "poisoned-by-stale-worker"},
        )
    finally:
        async with sessions.begin() as cleanup:
            await cleanup.execute(delete(WritingDraft).where(WritingDraft.id == draft_id))
            await cleanup.execute(
                delete(AsyncTask).where(AsyncTask.novel_id == novel_uuid)
            )
            await cleanup.execute(delete(Project).where(Project.id == novel_uuid))


@pytest.mark.asyncio
async def test_targeted_revision_rejects_stale_lease_writeback(test_engine):
    """定向返修任务被新租约重领后，旧租约回写被栅栏拒绝。"""
    sessions = async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)
    novel_uuid = uuid.uuid4()
    novel_id = str(novel_uuid)
    task_id = uuid.uuid4()

    async with sessions.begin() as db:
        db.add(
            Project(
                id=novel_uuid,
                title="stale lease revision",
                language="zh",
                default_reveal_policy="author_safe",
                settings={},
            )
        )
        db.add(
            AsyncTask(
                id=task_id,
                task_type="writing_targeted_revision",
                status="pending",
                recovery_policy="auto_requeue",
                max_attempts=2,
                meta={"novel_id": novel_id},
                novel_id=novel_uuid,
            )
        )

    try:
        lifecycle = TaskLifecycleService()
        old_lease = str(uuid.uuid4())
        async with sessions.begin() as db:
            task = await db.get(AsyncTask, task_id)
            assert task is not None
            task.mark_running(lease_id=old_lease)
            await db.flush()

        # 旧 worker 失联：任务按崩溃路径重排，新 worker 以新租约重领并完成
        async with sessions.begin() as db:
            task = await db.get(AsyncTask, task_id)
            assert task is not None
            task.status = "pending"
            task.lease_id = None
            task.transition_reason = "stale_recovery"
            await db.flush()
        async with sessions.begin() as db:
            task = await db.get(AsyncTask, task_id)
            assert task is not None
            task.mark_running(lease_id=str(uuid.uuid4()))
            await db.flush()
        async with sessions.begin() as db:
            accepted = await lifecycle.finalize(
                db,
                task_id=task_id,
                lease_id=str(task.lease_id),
                status="done",
                result_data={"verdict": "pass", "draft_id": "revision-candidate"},
            )
        assert accepted is True

        # 旧 worker 晚到回写：携带旧租约的 poison 结果被拒绝
        await _old_lease_finalize_rejected(
            sessions,
            task_id,
            old_lease,
            {"verdict": "poisoned-by-stale-worker"},
        )
    finally:
        async with sessions.begin() as cleanup:
            await cleanup.execute(delete(AsyncTask).where(AsyncTask.id == task_id))
            await cleanup.execute(delete(Project).where(Project.id == novel_uuid))


async def _async_noop(_db, *_args, **_kwargs) -> None:
    return None
