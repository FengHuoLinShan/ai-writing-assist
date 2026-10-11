"""旧 worker 租约回写拒绝用例（BR-0b 交接 P0-4「旧 worker 恢复」）。

语义审查与定向返修均执行真实 handler：模型等待期间换租约，旧 handler
返回后不得落审查记录、候选或任务完成结果。
"""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from typing import Any
from unittest import mock

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from infrastructure.llm.limits import reset_llm_limiter_for_tests
from infrastructure.llm.schemas import LLMCallResponse
from infrastructure.tasks.enqueuer import enqueue_task
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
        *,
        revision: bool = False,
    ) -> None:
        self._sessions = sessions
        self._task_id = task_id
        self._lease_holder = lease_holder
        self._draft_id = draft_id
        self.calls = 0
        self.revision = revision

    async def generate(self, request) -> LLMCallResponse:
        self.calls += 1
        async with self._sessions() as db:
            row = await db.get(AsyncTask, self._task_id)
            assert row is not None and row.status == "running"
            self._lease_holder["lease_id"] = str(row.lease_id)
            self._lease_holder["attempt"] = int(row.attempt or 0)
            row.lease_id = str(uuid.uuid4())
            await db.commit()
        if self.revision:
            inputs = json.loads(request.messages[-1].content)
            return LLMCallResponse(
                content=json.dumps(
                    {
                        "patches": [
                            {"patch_id": item["patch_id"], "replacement": "过时返修结果"}
                            for item in inputs["editable_ranges"]
                        ]
                    }
                ),
                finish_reason="stop",
                model="deepseek-flash",
                provider="fake",
            )
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


@pytest.mark.asyncio
async def test_semantic_review_rejects_stale_lease_writeback(test_engine, monkeypatch):
    """模型返回前丢失租约，旧审查 handler 不能写领域结果。"""
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
        assert returned is not None and returned.status != "done"
        assert lease_holder.get("lease_id")

        assert provider.calls == 1
        async with sessions() as db:
            unchanged = await db.get(WritingDraft, draft_id)
            assert unchanged.provenance_json == {}
            stored = await db.get(AsyncTask, task_id)
            assert stored.lease_id != lease_holder["lease_id"]
            assert not (stored.result or {}).get("verdict")

    finally:
        async with sessions.begin() as cleanup:
            await cleanup.execute(delete(WritingDraft).where(WritingDraft.id == draft_id))
            await cleanup.execute(
                delete(AsyncTask).where(AsyncTask.novel_id == novel_uuid)
            )
            await cleanup.execute(delete(Project).where(Project.id == novel_uuid))


@pytest.mark.asyncio
async def test_targeted_revision_rejects_stale_lease_writeback(test_engine, monkeypatch):
    import modules.project.facade as project_facade
    import modules.writing.semantic_review as semantic_module
    import modules.writing.tasks  # noqa: F401

    sessions = async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)
    novel_uuid, draft_id, review_id, task_id = (uuid.uuid4() for _ in range(4))
    nid = str(novel_uuid)
    provenance = {
        "source": "writing_generate",
        "context_confirmation_id": str(uuid.uuid4()),
        "review_required": True,
    }
    async with sessions.begin() as db:
        db.add(
            Project(
                id=novel_uuid,
                title="旧租约实际返修",
                language="zh",
                default_reveal_policy="author_safe",
                settings={},
            )
        )
        db.add(
            WritingDraft(
                id=draft_id,
                novel_id=novel_uuid,
                chapter_index=3,
                title="第三章",
                content="冻结正文",
                content_hash="a" * 64,
                status="candidate",
                provenance_json=provenance,
            )
        )
        db.add(
            AsyncTask(
                id=review_id,
                task_type="writing_semantic_review",
                novel_id=novel_uuid,
                meta={"novel_id": nid},
                status="done",
                result={
                    "findings": [
                        {
                            "finding_id": "f-1",
                            "location": {
                                "draft_id": str(draft_id),
                                "chapter_index": 3,
                                "excerpt": "冻结正文",
                            },
                            "preserve": [],
                        }
                    ],
                    "frozen_manifest": [
                        {
                            "draft_id": str(draft_id),
                            "content_hash": "a" * 64,
                            "context_fingerprint": "context-fingerprint",
                            "scene_execution_bundle_hash": None,
                        }
                    ],
                },
            )
        )
        db.add(
            AsyncTask(
                id=task_id,
                task_type="writing_targeted_revision",
                novel_id=novel_uuid,
                status="pending",
                meta={
                    "novel_id": nid,
                    "draft_id": str(draft_id),
                    "review_task_id": str(review_id),
                    "finding_ids": ["f-1"],
                    "llm_execution_snapshot": {
                        "profile": {"model": "deepseek-flash"},
                        "llm": {"model": "deepseek-flash"},
                    },
                },
            )
        )
    lease_holder = {}
    provider = _LeaseCapturingProvider(
        sessions, task_id, lease_holder, str(draft_id), revision=True
    )

    @asynccontextmanager
    async def fake_client(db, novel_id_arg, snapshot, **kwargs):
        yield _chain_client(monkeypatch, provider)

    async def context(self, db, **kwargs):
        return _review_target(str(draft_id), "a" * 64)["review_context"], []

    monkeypatch.setattr(project_facade, "open_project_snapshot_llm_client", fake_client)
    monkeypatch.setattr(project_facade, "require_active_project", _async_noop)
    monkeypatch.setattr(
        semantic_module.WritingSemanticWorkflowService,
        "_materialize_review_context",
        context,
    )
    monkeypatch.setattr(
        semantic_module, "_scene_bundle", mock.AsyncMock(return_value=None)
    )
    try:
        await TaskWorker(
            db_manager=_TaskManager(test_engine, sessions), heartbeat_interval=60.0
        ).run_once(task_id=task_id, novel_id=nid)
        assert provider.calls == 1
        async with sessions() as db:
            drafts = list(
                (
                    await db.execute(
                        select(WritingDraft).where(WritingDraft.novel_id == novel_uuid)
                    )
                ).scalars()
            )
            assert len(drafts) == 1
            assert drafts[0].content == "冻结正文"
            assert drafts[0].provenance_json == provenance
            stored = await db.get(AsyncTask, task_id)
            assert stored.status != "done"
            assert stored.lease_id != lease_holder["lease_id"]
    finally:
        async with sessions.begin() as db:
            await db.execute(
                delete(WritingDraft).where(WritingDraft.novel_id == novel_uuid)
            )
            await db.execute(delete(AsyncTask).where(AsyncTask.novel_id == novel_uuid))
            await db.execute(delete(Project).where(Project.id == novel_uuid))


async def _async_noop(_db, *_args, **_kwargs) -> None:
    return None
