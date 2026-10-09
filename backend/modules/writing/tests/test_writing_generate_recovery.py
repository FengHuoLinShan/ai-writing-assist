"""写作生成恢复矩阵用例（BR-0b）。

交接 P0-4「模型返回但结果未提交」：已付费的模型输出必须在 worker checkpoint
冻结，重排复用；不得在一次生成意图上悄悄第二次调用付费模型。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest import mock

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from infrastructure.tasks.models import AsyncTask
from modules.evidence.compilation.models import ContextConfirmation
from modules.project.models import Project
from modules.writing.models import WritingDraft
from modules.writing.services import (
    _FROZEN_GENERATION_CANDIDATE_VERSION,
    WritingGenerationService,
    _frozen_candidate_for_plan,
)
from modules.writing.tasks import handle_writing_generate
from modules.writing.tests.test_writing_generate_task_transactions import (
    _GovernedFakeClientMixin,
    _snapshot,
)


def _plan(fingerprint: str):
    return SimpleNamespace(source_fingerprint=fingerprint)


def _frozen_payload(fingerprint: str) -> dict:
    return {
        "version": _FROZEN_GENERATION_CANDIDATE_VERSION,
        "attempt": 1,
        "source_fingerprint": fingerprint,
        "candidate": {
            "novel_id": "11111111-1111-1111-1111-111111111111",
            "chapter_index": 3,
            "title": "冻结候选",
            "content": "已付费输出",
            "provenance_json": {"source": "writing_generate"},
        },
    }


def test_frozen_candidate_reused_only_on_fingerprint_match() -> None:
    frozen = _frozen_payload("f" * 64)
    reused = _frozen_candidate_for_plan(frozen, _plan("f" * 64))
    assert reused is not None
    assert reused.content == "已付费输出"
    assert reused.provenance_json["source"] == "writing_generate"

    # 来源漂移：冻结输出作废，走正常重新生成（finalize 重验仍是门禁）
    assert _frozen_candidate_for_plan(frozen, _plan("e" * 64)) is None
    # 版本或负载损坏：同样不得复用
    assert _frozen_candidate_for_plan({"version": 0}, _plan("f" * 64)) is None
    broken = {**frozen, "candidate": {"chapter_index": "not-an-int"}}
    assert _frozen_candidate_for_plan(broken, _plan("f" * 64)) is None


class _CountingClient(_GovernedFakeClientMixin):
    model_name = "frozen-model"

    def __init__(self) -> None:
        self.generate_calls = 0
        self.close_calls = 0

    async def generate(self, _request):
        self.generate_calls += 1
        return SimpleNamespace(content="已付费的候选正文", model=self.model_name)

    async def close(self) -> None:
        self.close_calls += 1


def _worker(sessions):
    from infrastructure.tasks.registry import TaskRegistry
    from infrastructure.tasks.worker import TaskWorker
    from run_worker import (
        _guard_active_task_project_finalize,
        _require_active_task_project,
    )

    class _Manager:
        def __init__(self) -> None:
            self.engine = sessions.kw["bind"]
            self.session_factory = sessions

    registry = TaskRegistry()
    if registry.get_handler("writing_generate") is None:
        registry.register(
            "writing_generate",
            handle_writing_generate,
            recovery_policy="auto_requeue",
            max_attempts=2,
        )

    return TaskWorker(
        db_manager=_Manager(),
        heartbeat_interval=60.0,
        task_preflight=_require_active_task_project,
        task_commit_guard=_guard_active_task_project_finalize,
    )


@pytest.mark.asyncio
async def test_requeued_generation_reuses_frozen_paid_output(test_engine, monkeypatch):
    """finalize 前崩溃 → 重排必须复用已付费输出，不得第二次调用模型。"""
    sessions = async_sessionmaker(
        test_engine,
        expire_on_commit=False,
        autoflush=False,
    )
    novel_uuid = uuid.uuid4()
    novel_id = str(novel_uuid)
    task_id = uuid.uuid4()
    confirmation_id: str | None = None
    client = _CountingClient()

    original_finalize = WritingGenerationService._finalize_generation_task
    finalize_calls = 0

    async def _crash_before_first_finalize(self, db, *, plan, candidate):
        nonlocal finalize_calls
        finalize_calls += 1
        if finalize_calls == 1:
            raise RuntimeError("simulated worker crash before finalize commit")
        return await original_finalize(self, db, plan=plan, candidate=candidate)

    monkeypatch.setattr(
        WritingGenerationService,
        "_finalize_generation_task",
        _crash_before_first_finalize,
    )

    try:
        async with sessions() as setup_db:
            setup_db.add(
                Project(
                    id=novel_uuid,
                    title="writing recovery",
                    language="zh",
                    default_reveal_policy="author_safe",
                    settings={},
                )
            )
            await setup_db.flush()
            from modules.evidence.contracts import ContextConfirmationRequest
            from modules.evidence.facade import (
                bind_confirmed_action_result,
                confirm_context,
            )

            confirmation = await confirm_context(
                setup_db,
                ContextConfirmationRequest(
                    novel_id=novel_id,
                    action="writing.generate",
                    task="recovery freeze reuse",
                    scope="project",
                    chapter_index=3,
                ),
            )
            confirmation_id = confirmation.id
            setup_db.add(
                AsyncTask(
                    id=task_id,
                    task_type="writing_generate",
                    status="pending",
                    recovery_policy="auto_requeue",
                    max_attempts=2,
                    meta={
                        "novel_id": novel_id,
                        "chapter_index": 3,
                        "context_confirmation_id": str(confirmation.id),
                        "llm_execution_snapshot": _snapshot(),
                    },
                )
            )
            await bind_confirmed_action_result(
                setup_db,
                novel_id=novel_id,
                confirmation_id=confirmation.id,
                result_type="task",
                result_id=str(task_id),
                status="running",
            )
            await setup_db.commit()

        with (
            mock.patch(
                "modules.project.llm_runtime.restore_project_llm_execution_settings",
                autospec=True,
                return_value={"llm": {"model": "frozen-model"}},
            ),
            mock.patch(
                "modules.project.facade.restore_project_llm_execution_settings",
                autospec=True,
                return_value={"llm": {"model": "frozen-model"}},
            ),
            mock.patch(
                "modules.project.llm_runtime.create_project_snapshot_llm_client",
                autospec=True,
                return_value=client,
            ),
        ):
            worker = _worker(sessions)
            first = await worker.run_once()
            assert first is not None and first.id == task_id

            async with sessions() as check_db:
                requeued = await check_db.get(AsyncTask, task_id)
                assert requeued is not None
                assert requeued.status == "pending"
                assert requeued.attempt == 1
                # 崩溃发生在 finalize 前：不得留下任何候选
                drafts = list(
                    (
                        await check_db.execute(
                            select(WritingDraft).where(
                                WritingDraft.novel_id == novel_uuid
                            )
                        )
                    ).scalars()
                )
                assert drafts == []
                # 跳过 handler 重试退避（_AUTO_REQUEUE_DELAYS_SECONDS 首档 1s）
                from datetime import UTC, datetime, timedelta

                requeued.updated_at = datetime.now(UTC) - timedelta(seconds=5)
                await check_db.commit()

            second = await worker.run_once()
            assert second is not None and second.id == task_id

        # 重排复用冻结输出：模型只被调用一次，恰好落一个候选
        assert client.generate_calls == 1
        assert finalize_calls == 2
        async with sessions() as verify_db:
            stored = await verify_db.get(AsyncTask, task_id)
            assert stored is not None
            assert stored.status == "done"
            drafts = list(
                (
                    await verify_db.execute(
                        select(WritingDraft).where(WritingDraft.novel_id == novel_uuid)
                    )
                ).scalars()
            )
            assert len(drafts) == 1
            assert "已付费的候选正文" in (drafts[0].content or "")
            assert drafts[0].status == "candidate"
            confirmation_row = await verify_db.get(
                ContextConfirmation,
                uuid.UUID(str(confirmation_id)),
            )
            assert confirmation_row is not None
            assert confirmation_row.result_status == "done"
    finally:
        async with sessions.begin() as cleanup_db:
            await cleanup_db.execute(
                delete(WritingDraft).where(WritingDraft.novel_id == novel_uuid)
            )
            if confirmation_id is not None:
                await cleanup_db.execute(
                    delete(ContextConfirmation).where(
                        ContextConfirmation.id == uuid.UUID(str(confirmation_id))
                    )
                )
            await cleanup_db.execute(delete(AsyncTask).where(AsyncTask.id == task_id))
            await cleanup_db.execute(delete(Project).where(Project.id == novel_uuid))
