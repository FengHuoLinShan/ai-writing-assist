"""
Infrastructure: Tasks 模块单元测试

覆盖:
- tasks/enqueuer.py — enqueue_task (纯逻辑)
- tasks/api.py — submit_task / get_task_status / cancel_task (FastAPI 路由)
- tasks/worker.py — TaskWorker (通过 mock 隔离 DB 和 Registry)

注意: api.py 使用 FastAPI 路由, 通过 mock 外部依赖直接调用路由函数。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from core.container import override


@pytest.fixture
def active_project_guard():
    """Keep direct endpoint unit tests focused below the project boundary."""
    guard = AsyncMock()
    with override("project.require_active", guard):
        yield guard


def _compiled_execute_statement(db: AsyncMock) -> str:
    statement = db.execute.call_args[0][0]
    return str(statement.compile(compile_kwargs={"literal_binds": True}))


# ============================================================
# enqueuer.py
# ============================================================


class TestEnqueueTask:
    """enqueue_task 单元测试"""

    def test_create_task_with_defaults(self) -> None:
        """GREEN: 使用默认参数创建任务"""
        from infrastructure.tasks.enqueuer import enqueue_task

        db = MagicMock()
        db.add = MagicMock()

        task_id = enqueue_task(db, task_type="test_type")

        # 验证返回 task_id
        assert isinstance(task_id, str)
        uuid.UUID(hex=task_id)  # 不会抛出异常 = 有效 UUID

        # 验证 db.add 被调用
        db.add.assert_called_once()
        task = db.add.call_args[0][0]
        assert task.task_type == "test_type"
        assert task.status == "pending"
        assert task.progress == 0.0
        assert task.meta == {}

    def test_create_task_with_custom_params(self) -> None:
        """GREEN: 使用自定义参数创建任务"""
        from infrastructure.tasks.enqueuer import enqueue_task

        db = MagicMock()
        db.add = MagicMock()

        task_id = enqueue_task(
            db,
            task_type="embedding_build",
            meta={"novel_id": "abc-123"},
            status="running",
            progress=0.5,
        )

        assert isinstance(task_id, str)
        task = db.add.call_args[0][0]
        assert task.task_type == "embedding_build"
        assert task.status == "running"
        assert task.progress == 0.5
        assert task.meta == {"novel_id": "abc-123"}

    def test_create_task_meta_none_becomes_empty_dict(self) -> None:
        """GREEN: meta=None 时转为空 dict"""
        from infrastructure.tasks.enqueuer import enqueue_task

        db = MagicMock()
        db.add = MagicMock()

        enqueue_task(db, task_type="test", meta=None)

        task = db.add.call_args[0][0]
        assert task.meta == {}


# ============================================================
# api.py
# ============================================================


class TestSubmitTask:
    """submit_task API endpoint 单元测试"""

    @pytest.mark.asyncio
    async def test_submit_known_task_type(self) -> None:
        """GREEN: 提交已注册的任务类型，返回 201 和 task_id"""
        from infrastructure.tasks.api import TaskSubmitRequest, submit_task

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        request = TaskSubmitRequest(task_type="test_type", meta={"key": "val"})

        with patch(
            "infrastructure.tasks.api.TaskRegistry",
        ) as mock_registry:
            registry_instance = mock_registry.return_value
            registry_instance.__contains__ = MagicMock(return_value=True)

            response = await submit_task(request, db=db)

        assert response.task_id is not None
        _ = uuid.UUID(hex=response.task_id)  # valid UUID
        assert response.status == "pending"
        db.add.assert_called_once()
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_submit_unknown_task_type_raises_400(self) -> None:
        """RED: 提交未知任务类型时抛出 400 HTTPException"""
        from infrastructure.tasks.api import TaskSubmitRequest, submit_task

        db = AsyncMock()

        request = TaskSubmitRequest(task_type="unknown_type")

        with patch(
            "infrastructure.tasks.api.TaskRegistry",
        ) as mock_registry:
            registry_instance = mock_registry.return_value
            registry_instance.__contains__ = MagicMock(return_value=False)
            registry_instance.registered_types = ["type_a", "type_b"]

            with pytest.raises(HTTPException) as exc_info:
                await submit_task(request, db=db)

        assert exc_info.value.status_code == 400
        assert "unknown_type" in exc_info.value.detail
        assert "type_a" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_submit_empty_meta(self) -> None:
        """GREEN: 提交空 meta 的任务"""
        from infrastructure.tasks.api import TaskSubmitRequest, submit_task

        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()

        request = TaskSubmitRequest(task_type="test_type")

        with patch(
            "infrastructure.tasks.api.TaskRegistry",
        ) as mock_registry:
            registry_instance = mock_registry.return_value
            registry_instance.__contains__ = MagicMock(return_value=True)

            _ = await submit_task(request, db=db)

        task = db.add.call_args[0][0]
        assert task.meta == {}


class TestGetTaskStatus:
    """get_task_status API endpoint 单元测试"""

    @pytest.mark.asyncio
    async def test_task_exists(self, active_project_guard: AsyncMock) -> None:
        """GREEN: 查询存在的任务返回完整状态"""
        from infrastructure.tasks.api import get_task_status

        task_id = uuid.uuid4()
        now = datetime.now(UTC)

        task_mock = MagicMock()
        task_mock.id = task_id
        task_mock.task_type = "test_type"
        task_mock.status = "done"
        task_mock.progress = 1.0
        task_mock.meta = {"novel_id": "abc"}
        task_mock.result = {"output": "ok"}
        task_mock.error_message = None
        task_mock.created_at = now
        task_mock.started_at = now
        task_mock.finished_at = now

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = task_mock
        db.execute = AsyncMock(return_value=result_mock)

        response = await get_task_status(task_id, db=db, novel_id="abc")

        assert response.task_id == str(task_id)
        assert response.task_type == "test_type"
        assert response.status == "done"
        assert response.progress == 1.0
        assert response.meta == {"novel_id": "abc"}
        assert response.result == {"output": "ok"}
        assert response.error_message is None
        active_project_guard.assert_awaited_once_with(db, "abc")
        sql = _compiled_execute_statement(db)
        assert "async_tasks.id" in sql
        assert "novel_id" in sql

    @pytest.mark.asyncio
    async def test_task_not_found_raises_404(
        self,
        active_project_guard: AsyncMock,
    ) -> None:
        """RED: 任务不存在时抛出 404"""
        from infrastructure.tasks.api import get_task_status

        task_id = uuid.uuid4()

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(HTTPException) as exc_info:
            await get_task_status(task_id, db=db, novel_id="abc")

        assert exc_info.value.status_code == 404
        active_project_guard.assert_awaited_once_with(db, "abc")

    @pytest.mark.asyncio
    async def test_status_fallback_when_none(
        self,
        active_project_guard: AsyncMock,
    ) -> None:
        """GREEN: status 为 None 时回退到 'pending'"""
        from infrastructure.tasks.api import get_task_status

        task_id = uuid.uuid4()

        task_mock = MagicMock()
        task_mock.id = task_id
        task_mock.task_type = "test"
        task_mock.status = None  # <-- None
        task_mock.progress = None
        task_mock.meta = {"novel_id": "abc"}
        task_mock.result = None
        task_mock.error_message = None
        task_mock.created_at = None
        task_mock.started_at = None
        task_mock.finished_at = None

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = task_mock
        db.execute = AsyncMock(return_value=result_mock)

        response = await get_task_status(task_id, db=db, novel_id="abc")

        assert response.status == "pending"
        assert response.meta == {"novel_id": "abc"}
        assert response.result == {}
        assert response.created_at is None
        active_project_guard.assert_awaited_once_with(db, "abc")


class TestCancelTask:
    """cancel_task API endpoint 单元测试"""

    @pytest.mark.asyncio
    async def test_cancel_pending_task(
        self,
        active_project_guard: AsyncMock,
    ) -> None:
        """GREEN: 取消 pending 状态的任务"""
        from infrastructure.tasks.api import cancel_task

        task_id = uuid.uuid4()

        task_mock = MagicMock()
        task_mock.id = task_id
        task_mock.status = "pending"
        task_mock.meta = {"novel_id": "abc"}
        task_mock.mark_cancelled = MagicMock()

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = task_mock
        db.execute = AsyncMock(return_value=result_mock)
        db.flush = AsyncMock()

        response = await cancel_task(task_id, db=db, novel_id="abc")

        assert response.task_id == str(task_id)
        assert response.cancelled is True
        task_mock.mark_cancelled.assert_called_once()
        active_project_guard.assert_awaited_once_with(db, "abc")
        sql = _compiled_execute_statement(db)
        assert "async_tasks.id" in sql
        assert "novel_id" in sql

    @pytest.mark.asyncio
    async def test_cancel_running_task(
        self,
        active_project_guard: AsyncMock,
    ) -> None:
        """GREEN: 取消 running 状态的任务"""
        from infrastructure.tasks.api import cancel_task

        task_id = uuid.uuid4()

        task_mock = MagicMock()
        task_mock.id = task_id
        task_mock.status = "running"
        task_mock.meta = {"novel_id": "abc"}
        task_mock.mark_cancelled = MagicMock()

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = task_mock
        db.execute = AsyncMock(return_value=result_mock)
        db.flush = AsyncMock()

        response = await cancel_task(task_id, db=db, novel_id="abc")
        assert response.cancelled is True
        task_mock.mark_cancelled.assert_called_once()
        active_project_guard.assert_awaited_once_with(db, "abc")

    @pytest.mark.asyncio
    async def test_cancel_done_task_raises_400(
        self,
        active_project_guard: AsyncMock,
    ) -> None:
        """RED: 取消已完成的任务抛出 400"""
        from infrastructure.tasks.api import cancel_task

        task_id = uuid.uuid4()

        task_mock = MagicMock()
        task_mock.id = task_id
        task_mock.status = "done"
        task_mock.meta = {"novel_id": "abc"}

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = task_mock
        db.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(HTTPException) as exc_info:
            await cancel_task(task_id, db=db, novel_id="abc")

        assert exc_info.value.status_code == 400
        assert "done" in exc_info.value.detail
        active_project_guard.assert_awaited_once_with(db, "abc")

    @pytest.mark.asyncio
    async def test_cancel_failed_task_raises_400(
        self,
        active_project_guard: AsyncMock,
    ) -> None:
        """RED: 取消已失败的任务抛出 400"""
        from infrastructure.tasks.api import cancel_task

        task_id = uuid.uuid4()

        task_mock = MagicMock()
        task_mock.id = task_id
        task_mock.status = "failed"
        task_mock.meta = {"novel_id": "abc"}

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = task_mock
        db.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(HTTPException) as exc_info:
            await cancel_task(task_id, db=db, novel_id="abc")

        assert exc_info.value.status_code == 400
        active_project_guard.assert_awaited_once_with(db, "abc")

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_task_raises_404(
        self,
        active_project_guard: AsyncMock,
    ) -> None:
        """RED: 取消不存在的任务抛出 404"""
        from infrastructure.tasks.api import cancel_task

        task_id = uuid.uuid4()

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)

        with pytest.raises(HTTPException) as exc_info:
            await cancel_task(task_id, db=db, novel_id="abc")

        assert exc_info.value.status_code == 404
        active_project_guard.assert_awaited_once_with(db, "abc")


# ============================================================
# worker.py
# ============================================================


class TestTaskWorkerInitAndProps:
    """TaskWorker 初始化和属性"""

    def test_init_defaults(self) -> None:
        """GREEN: 默认初始化使用全局常量"""
        from infrastructure.tasks.worker import TaskWorker
        from shared.constants import (
            TASK_HEARTBEAT_INTERVAL,
            TASK_MAX_HEARTBEAT_GAP,
            TASK_POLL_INTERVAL,
        )

        with patch("infrastructure.tasks.worker.get_manager", autospec=True):
            worker = TaskWorker()

        assert worker._poll_interval == TASK_POLL_INTERVAL
        assert worker._heartbeat_interval == TASK_HEARTBEAT_INTERVAL
        assert worker._max_heartbeat_gap == TASK_MAX_HEARTBEAT_GAP
        assert worker._max_concurrent_tasks >= 1
        assert worker._running is False
        assert worker._running_task_ids == set()
        assert worker._heartbeat_tasks == {}
        assert worker._stats == {
            "processed": 0,
            "succeeded": 0,
            "failed": 0,
            "cancelled": 0,
        }

    def test_custom_parameters(self) -> None:
        """GREEN: 自定义参数"""
        from infrastructure.tasks.worker import TaskWorker

        with patch("infrastructure.tasks.worker.get_manager"):
            worker = TaskWorker(
                poll_interval=0.5,
                heartbeat_interval=5.0,
                max_heartbeat_gap=30.0,
            )

        assert worker._poll_interval == 0.5
        assert worker._heartbeat_interval == 5.0
        assert worker._max_heartbeat_gap == 30.0

    def test_custom_task_preflight(self) -> None:
        """Worker keeps project policy behind an injected async preflight."""
        from infrastructure.tasks.worker import TaskWorker

        preflight = AsyncMock()
        with patch("infrastructure.tasks.worker.get_manager", autospec=True):
            worker = TaskWorker(task_preflight=preflight)

        assert worker._task_preflight is preflight

    def test_stats_property(self) -> None:
        """GREEN: stats 返回副本而非引用"""
        from infrastructure.tasks.worker import TaskWorker

        with patch("infrastructure.tasks.worker.get_manager"):
            worker = TaskWorker()

        stats = worker.stats
        assert stats == {"processed": 0, "succeeded": 0, "failed": 0, "cancelled": 0}
        # 验证是副本
        stats["processed"] = 999
        assert worker._stats["processed"] == 0

    def test_stop_sets_running_false(self) -> None:
        """GREEN: stop() 设置 _running = False"""
        from infrastructure.tasks.worker import TaskWorker

        with patch("infrastructure.tasks.worker.get_manager"):
            worker = TaskWorker()

        worker._running = True
        worker.stop()
        assert worker._running is False


class TestTaskWorkerClaimTask:
    """TaskWorker._claim_task 单元测试"""

    @pytest.mark.asyncio
    async def test_claim_pending_task(self) -> None:
        """GREEN: 成功领取 pending 任务"""
        from infrastructure.tasks.worker import TaskWorker

        task_mock = MagicMock()
        task_mock.id = uuid.uuid4()
        task_mock.status = "pending"
        task_mock.task_type = "test_type"
        task_mock.mark_running = MagicMock()

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = task_mock

        db_session = AsyncMock()
        db_session.execute = AsyncMock(return_value=result_mock)
        db_session.commit = AsyncMock()

        with patch("infrastructure.tasks.worker.get_manager"):
            worker = TaskWorker()

        claimed = await worker._claim_task(db_session)

        assert claimed is task_mock
        task_mock.mark_running.assert_called_once()
        db_session.commit.assert_awaited_once()
        assert task_mock.id in worker._running_task_ids

    @pytest.mark.asyncio
    async def test_claim_no_pending_task(self) -> None:
        """GREEN: 无 pending 任务时返回 None"""
        from infrastructure.tasks.worker import TaskWorker

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None

        db_session = AsyncMock()
        db_session.execute = AsyncMock(return_value=result_mock)

        with patch("infrastructure.tasks.worker.get_manager"):
            worker = TaskWorker()

        claimed = await worker._claim_task(db_session)

        assert claimed is None
        assert worker._running_task_ids == set()

    @pytest.mark.asyncio
    async def test_claim_uses_skip_locked(self) -> None:
        """GREEN: _claim_task 使用 FOR UPDATE SKIP LOCKED"""
        from infrastructure.tasks.worker import TaskWorker

        task_mock = MagicMock()
        task_mock.mark_running = MagicMock()

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = task_mock

        db_session = AsyncMock()
        db_session.execute = AsyncMock(return_value=result_mock)
        db_session.commit = AsyncMock()

        with patch("infrastructure.tasks.worker.get_manager"):
            worker = TaskWorker()

        await worker._claim_task(db_session)

        # 验证 SELECT 语句使用了 with_for_update(skip_locked=True)
        call_stmt = db_session.execute.call_args[0][0]
        assert call_stmt._for_update_arg is not None
        assert call_stmt._for_update_arg.skip_locked is True


class TestTaskWorkerExecuteTask:
    """TaskWorker._execute_task 单元测试"""

    @pytest.mark.asyncio
    async def test_execute_success(self) -> None:
        """GREEN: 任务执行成功更新状态为 done"""
        from infrastructure.tasks.worker import TaskWorker

        task_mock = MagicMock()
        task_mock.id = uuid.uuid4()
        task_mock.task_type = "test_type"
        task_mock.mark_done = MagicMock()

        db_session = AsyncMock()
        db_session.commit = AsyncMock()

        handler = AsyncMock(return_value={"output": "success"})

        with (
            patch("infrastructure.tasks.worker.get_manager", autospec=True),
            patch.object(
                TaskWorker,
                "_heartbeat_loop",
                autospec=True,
                return_value=None,
            ),
        ):
            worker = TaskWorker()
            worker._lifecycle.finalize = AsyncMock(return_value=True)
            worker._registry.get_handler = MagicMock(return_value=handler)

            await worker._execute_task(task_mock, db_session)

        handler.assert_awaited_once_with(task=task_mock, db=db_session)
        worker._lifecycle.finalize.assert_awaited_once_with(
            db_session,
            task_id=task_mock.id,
            lease_id=str(task_mock.lease_id or ""),
            status="done",
            result_data={"output": "success"},
        )
        assert worker._stats["succeeded"] == 1
        assert worker._stats["processed"] == 1
        assert task_mock.id not in worker._running_task_ids

    @pytest.mark.asyncio
    async def test_preflight_rejects_task_before_handler_runs(self) -> None:
        """A recycled-project preflight failure must prevent business writes."""
        from core.errors import NotFoundError
        from infrastructure.tasks.worker import TaskWorker

        task_mock = MagicMock()
        task_mock.id = uuid.uuid4()
        task_mock.task_type = "test_type"
        task_mock.meta = {"novel_id": str(uuid.uuid4())}
        task_mock.result = {}
        db_session = AsyncMock()
        handler = AsyncMock()
        preflight = AsyncMock(side_effect=NotFoundError("Project not found"))

        with (
            patch("infrastructure.tasks.worker.get_manager", autospec=True),
            patch.object(
                TaskWorker,
                "_heartbeat_loop",
                autospec=True,
                return_value=None,
            ),
        ):
            worker = TaskWorker(task_preflight=preflight)
            worker._lifecycle.finalize = AsyncMock(return_value=False)
            worker._registry.get_handler = MagicMock(return_value=handler)

            await worker._execute_task(task_mock, db_session)

        preflight.assert_awaited_once_with(db_session, task_mock)
        handler.assert_not_awaited()
        db_session.rollback.assert_awaited_once()
        assert worker._lifecycle.finalize.await_args.kwargs["status"] == "failed"

    @pytest.mark.asyncio
    async def test_execute_success_persists_deduplicated_llm_provenance(
        self,
    ) -> None:
        import json

        from infrastructure.llm.agent_step_harness import (
            MANAGED_LLM_PROVENANCE_KEY,
            run_managed_generate,
        )
        from infrastructure.llm.schemas import LLMCallRequest, LLMCallResponse
        from infrastructure.tasks.worker import TaskWorker

        class FakeClient:
            profile_summary = {
                "model": "default-model",
                "base_url_host": ("https://api.example.test/v1?api_key=query-secret"),
                "api_key": "sk-task-secret",
                "prompt": "private prompt",
            }
            runtime_scope = {
                "novel_id": "novel-task",
                "profile_source": "project",
            }

            async def generate(self, request):
                return LLMCallResponse(content="ok", model=request.model)

        client = FakeClient()

        async def handler(**kwargs):
            request = LLMCallRequest(model="phase-model", messages=[])
            await run_managed_generate(client, request, step_name="test.phase")
            await run_managed_generate(client, request, step_name="test.phase")
            await run_managed_generate(client, request, step_name="test.other")
            return {"output": "success"}

        task_mock = MagicMock()
        task_mock.id = uuid.uuid4()
        task_mock.task_type = "test_type"
        task_mock.result = {}
        task_mock.mark_done = MagicMock()
        db_session = AsyncMock()

        with (
            patch("infrastructure.tasks.worker.get_manager"),
            patch.object(TaskWorker, "_heartbeat_loop", return_value=None),
        ):
            worker = TaskWorker()
            worker._lifecycle.finalize = AsyncMock(return_value=True)
            worker._registry.get_handler = MagicMock(return_value=handler)
            await worker._execute_task(task_mock, db_session)

        result_data = worker._lifecycle.finalize.await_args.kwargs["result_data"]
        assert result_data["output"] == "success"
        records = result_data[MANAGED_LLM_PROVENANCE_KEY]
        assert [record["step_name"] for record in records] == [
            "test.phase",
            "test.other",
        ]
        assert records[0]["profile_summary"]["model"] == "phase-model"
        assert records[0]["profile_summary"]["default_model"] == "default-model"
        serialized = json.dumps(records, ensure_ascii=False)
        assert "query-secret" not in serialized
        assert "sk-task-secret" not in serialized
        assert "private prompt" not in serialized

    @pytest.mark.asyncio
    async def test_execute_handler_returns_non_dict(self) -> None:
        """GREEN: handler 返回非 dict 时包装为 {'result': ...}"""
        from infrastructure.tasks.worker import TaskWorker

        task_mock = MagicMock()
        task_mock.id = uuid.uuid4()
        task_mock.task_type = "test_type"
        task_mock.mark_done = MagicMock()

        db_session = AsyncMock()
        db_session.commit = AsyncMock()

        handler = AsyncMock(return_value="simple_string_result")

        with (
            patch("infrastructure.tasks.worker.get_manager"),
            patch.object(TaskWorker, "_heartbeat_loop", return_value=None),
        ):
            worker = TaskWorker()
            worker._lifecycle.finalize = AsyncMock(return_value=True)
            worker._registry.get_handler = MagicMock(return_value=handler)

            await worker._execute_task(task_mock, db_session)

        assert worker._lifecycle.finalize.await_args.kwargs == {
            "task_id": task_mock.id,
            "lease_id": str(task_mock.lease_id or ""),
            "status": "done",
            "result_data": {"result": "simple_string_result"},
        }

    @pytest.mark.asyncio
    async def test_execute_handler_none_registered(self) -> None:
        """RED: 未注册 handler 时标记为 failed"""
        from unittest.mock import PropertyMock

        from infrastructure.tasks.registry import TaskRegistry
        from infrastructure.tasks.worker import TaskWorker

        task_mock = MagicMock()
        task_mock.id = uuid.uuid4()
        task_mock.task_type = "unknown_type"
        task_mock.mark_failed = MagicMock()

        db_session = AsyncMock()
        db_session.rollback = AsyncMock()
        db_session.commit = AsyncMock()

        with (
            patch("infrastructure.tasks.worker.get_manager"),
            patch.object(TaskWorker, "_heartbeat_loop", return_value=None),
            patch.object(
                TaskRegistry,
                "registered_types",
                new_callable=PropertyMock,
                return_value=["known_type"],
            ),
        ):
            worker = TaskWorker()
            worker._lifecycle.finalize = AsyncMock(return_value=True)
            worker._registry.get_handler = MagicMock(return_value=None)

            await worker._execute_task(task_mock, db_session)

        db_session.rollback.assert_awaited_once()
        finalized = worker._lifecycle.finalize.await_args.kwargs
        assert finalized["status"] == "failed"
        assert "No handler" in finalized["error_message"]
        assert worker._stats["failed"] == 1
        assert worker._stats["processed"] == 1

    @pytest.mark.asyncio
    async def test_execute_handler_raises_exception(self) -> None:
        """RED: handler 抛出异常时标记为 failed"""
        from infrastructure.tasks.worker import TaskWorker

        task_mock = MagicMock()
        task_mock.id = uuid.uuid4()
        task_mock.task_type = "test_type"
        task_mock.mark_failed = MagicMock()

        db_session = AsyncMock()
        db_session.rollback = AsyncMock()
        db_session.commit = AsyncMock()

        async def failing_handler(**kwargs):
            raise ValueError("processing error")

        with (
            patch("infrastructure.tasks.worker.get_manager"),
            patch.object(TaskWorker, "_heartbeat_loop", return_value=None),
        ):
            worker = TaskWorker()
            worker._lifecycle.finalize = AsyncMock(return_value=True)
            worker._registry.get_handler = MagicMock(return_value=failing_handler)

            await worker._execute_task(task_mock, db_session)

        db_session.rollback.assert_awaited_once()
        finalized = worker._lifecycle.finalize.await_args.kwargs
        assert finalized["status"] == "failed"
        assert "ValueError: processing error" in finalized["error_message"]
        assert worker._stats["failed"] == 1

    @pytest.mark.asyncio
    async def test_execute_failure_persists_managed_llm_provenance(self) -> None:
        from infrastructure.llm.agent_step_harness import (
            MANAGED_LLM_PROVENANCE_KEY,
            run_managed_generate,
        )
        from infrastructure.llm.schemas import LLMCallRequest
        from infrastructure.tasks.worker import TaskWorker

        class FailingClient:
            profile_summary = {"model": "default-model"}
            runtime_scope = {
                "novel_id": "novel-failed",
                "profile_source": "project",
            }

            async def generate(self, request):
                raise RuntimeError("provider failed")

        async def failing_handler(**kwargs):
            await run_managed_generate(
                FailingClient(),
                LLMCallRequest(model="failed-phase-model", messages=[]),
                step_name="test.failed",
            )

        task_mock = MagicMock()
        task_mock.id = uuid.uuid4()
        task_mock.task_type = "test_type"
        task_mock.result = {"checkpoint": 2}
        task_mock.mark_failed = MagicMock()
        db_session = AsyncMock()

        with (
            patch("infrastructure.tasks.worker.get_manager"),
            patch.object(TaskWorker, "_heartbeat_loop", return_value=None),
        ):
            worker = TaskWorker()
            worker._lifecycle.finalize = AsyncMock(return_value=True)
            worker._registry.get_handler = MagicMock(return_value=failing_handler)
            await worker._execute_task(task_mock, db_session)

        result_data = worker._lifecycle.finalize.await_args.kwargs["result_data"]
        assert result_data["checkpoint"] == 2
        record = result_data[MANAGED_LLM_PROVENANCE_KEY][0]
        assert record["step_name"] == "test.failed"
        assert record["profile_summary"]["model"] == "failed-phase-model"
        assert worker._lifecycle.finalize.await_args.kwargs["status"] == "failed"

    def test_public_task_error_message_sanitizes_dbapi_details(self) -> None:
        """DB/SQL internals must not be exposed through task status."""
        from infrastructure.tasks.worker import _public_task_error_message

        message = _public_task_error_message(
            RuntimeError(
                "DBAPIError: asyncpg.exceptions.InFailedSQLTransactionError: "
                "current transaction is aborted [SQL: UPDATE async_tasks SET progress=$1]"
            )
        )

        assert message == "后台任务遇到数据库临时错误，请稍后重试。"
        assert "DBAPIError" not in message
        assert "UPDATE async_tasks" not in message

    def test_public_task_error_message_redacts_credentials_and_url_query(self) -> None:
        """Provider diagnostics exposed by the task API must be secret-free."""
        from infrastructure.tasks.worker import _public_task_error_message

        message = _public_task_error_message(
            RuntimeError(
                "request https://user:pass@gateway.example.test/v1/chat?opaque=hidden "
                "failed with Authorization: Bearer sk-task-secret"
            )
        )

        assert "hidden" not in message
        assert "user:pass" not in message
        assert "sk-task-secret" not in message
        assert "gateway.example.test/v1/chat" in message
        assert "REDACTED" in message

    @pytest.mark.asyncio
    async def test_execute_task_never_logs_chained_secret_cause(
        self,
        caplog,
    ) -> None:
        """A provider cause chain must not escape through worker traceback logging."""
        from infrastructure.tasks.worker import TaskWorker

        async def failing_handler(**_kwargs):
            try:
                raise RuntimeError(
                    "transport https://gateway.example.test/v1?opaque=hidden-cause "
                    "Bearer sk-hidden-cause"
                )
            except RuntimeError as cause:
                raise RuntimeError("provider request failed") from cause

        task_mock = MagicMock()
        task_mock.id = uuid.uuid4()
        task_mock.task_type = "test_type"
        task_mock.result = {}
        task_mock.mark_failed = MagicMock()
        db_session = AsyncMock()

        with (
            patch("infrastructure.tasks.worker.get_manager"),
            patch.object(TaskWorker, "_heartbeat_loop", return_value=None),
            caplog.at_level("ERROR", logger="infrastructure.tasks.worker"),
        ):
            worker = TaskWorker()
            worker._lifecycle.finalize = AsyncMock(return_value=True)
            worker._registry.get_handler = MagicMock(return_value=failing_handler)
            await worker._execute_task(task_mock, db_session)

        logged = "\n".join(caplog.messages)
        assert "provider request failed" in logged
        assert "hidden-cause" not in logged
        assert "sk-hidden-cause" not in logged
        finalized = worker._lifecycle.finalize.await_args.kwargs
        assert finalized["status"] == "failed"
        assert finalized["error_message"] == "RuntimeError: provider request failed"

    @pytest.mark.asyncio
    async def test_execute_cancelled_error(self) -> None:
        """GREEN: 捕获 CancelledError 并标记为 cancelled"""
        from infrastructure.tasks.worker import TaskWorker

        task_mock = MagicMock()
        task_mock.id = uuid.uuid4()
        task_mock.task_type = "test_type"
        task_mock.mark_cancelled = MagicMock()

        db_session = AsyncMock()
        db_session.rollback = AsyncMock()
        db_session.commit = AsyncMock()

        async def cancelling_handler(**kwargs):
            raise asyncio.CancelledError()

        with (
            patch("infrastructure.tasks.worker.get_manager"),
            patch.object(TaskWorker, "_heartbeat_loop", return_value=None),
        ):
            worker = TaskWorker()
            worker._lifecycle.finalize = AsyncMock(return_value=True)
            worker._registry.get_handler = MagicMock(return_value=cancelling_handler)

            await worker._execute_task(task_mock, db_session)

        db_session.rollback.assert_awaited_once()
        assert worker._lifecycle.finalize.await_args.kwargs["status"] == "cancelled"
        assert worker._stats["cancelled"] == 1

    @pytest.mark.asyncio
    async def test_execute_cancelled_persists_managed_llm_provenance(self) -> None:
        from infrastructure.llm.agent_step_harness import (
            MANAGED_LLM_PROVENANCE_KEY,
            run_managed_generate,
        )
        from infrastructure.llm.schemas import LLMCallRequest
        from infrastructure.tasks.worker import TaskWorker

        class CancellingClient:
            profile_summary = {"model": "default-model"}
            runtime_scope = {
                "novel_id": "novel-cancelled",
                "profile_source": "project",
            }

            async def generate(self, request):
                raise asyncio.CancelledError()

        async def cancelling_handler(**kwargs):
            await run_managed_generate(
                CancellingClient(),
                LLMCallRequest(model="cancelled-phase-model", messages=[]),
                step_name="test.cancelled",
            )

        task_mock = MagicMock()
        task_mock.id = uuid.uuid4()
        task_mock.task_type = "test_type"
        task_mock.result = {}
        task_mock.mark_cancelled = MagicMock()
        db_session = AsyncMock()

        with (
            patch("infrastructure.tasks.worker.get_manager"),
            patch.object(TaskWorker, "_heartbeat_loop", return_value=None),
        ):
            worker = TaskWorker()
            worker._lifecycle.finalize = AsyncMock(return_value=True)
            worker._registry.get_handler = MagicMock(return_value=cancelling_handler)
            await worker._execute_task(task_mock, db_session)

        result_data = worker._lifecycle.finalize.await_args.kwargs["result_data"]
        record = result_data[MANAGED_LLM_PROVENANCE_KEY][0]
        assert record["step_name"] == "test.cancelled"
        assert record["profile_summary"]["model"] == "cancelled-phase-model"
        assert worker._lifecycle.finalize.await_args.kwargs["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_heartbeat_task_cancelled_in_finally(self) -> None:
        """GREEN: finally 中取消心跳协程"""
        import asyncio

        from infrastructure.tasks.worker import TaskWorker

        task_mock = MagicMock()
        task_mock.id = uuid.uuid4()
        task_mock.task_type = "test_type"
        task_mock.mark_done = MagicMock()

        db_session = AsyncMock()
        db_session.commit = AsyncMock()

        handler = AsyncMock(return_value={"ok": True})

        # 创建一个真实的心跳协程用于测试
        async def dummy_heartbeat(task_id):
            try:
                while True:
                    await asyncio.sleep(100)
            except asyncio.CancelledError:
                pass

        with (
            patch("infrastructure.tasks.worker.get_manager"),
            patch.object(
                TaskWorker,
                "_heartbeat_loop",
                side_effect=dummy_heartbeat,
            ),
        ):
            worker = TaskWorker()
            worker._registry.get_handler = MagicMock(return_value=handler)

            await worker._execute_task(task_mock, db_session)

        # 心跳任务应在 finally 中从集合移除
        assert worker._heartbeat_tasks == {}


class TestTaskWorkerHeartbeat:
    """TaskWorker._heartbeat_loop 单元测试"""

    @pytest.mark.asyncio
    async def test_heartbeat_updates_heartbeat_at(self) -> None:
        """GREEN: 心跳更新任务的 heartbeat_at"""
        from infrastructure.tasks.worker import TaskWorker

        task_id = uuid.uuid4()

        # Mock db_manager 返回的 session
        hb_session = AsyncMock()
        hb_session.execute = AsyncMock()
        hb_session.commit = AsyncMock()

        db_manager = MagicMock()
        db_manager.session_factory = MagicMock(return_value=AsyncMock())
        db_manager.session_factory.return_value.__aenter__ = AsyncMock(
            return_value=hb_session
        )
        db_manager.session_factory.return_value.__aexit__ = AsyncMock()

        worker = TaskWorker(db_manager=db_manager, heartbeat_interval=0.01)

        # 运行心跳循环，让它更新一次后通过外边取消
        heartbeat_task = asyncio.create_task(worker._heartbeat_loop(task_id))
        await asyncio.sleep(0.05)
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass

        # 验证 execute 被调用（至少一次）
        hb_session.execute.assert_called()
        hb_session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_heartbeat_logs_error_on_failure(self) -> None:
        """GREEN: 心跳更新失败时记录 warning 不崩溃"""
        from infrastructure.tasks.worker import TaskWorker

        task_id = uuid.uuid4()

        # 模拟 session.execute 抛出异常
        hb_session = AsyncMock()
        hb_session.execute = AsyncMock(side_effect=Exception("DB gone"))

        db_manager = MagicMock()
        db_manager.session_factory = MagicMock(return_value=AsyncMock())
        db_manager.session_factory.return_value.__aenter__ = AsyncMock(
            return_value=hb_session
        )
        db_manager.session_factory.return_value.__aexit__ = AsyncMock()

        worker = TaskWorker(db_manager=db_manager, heartbeat_interval=0.01)

        heartbeat_task = asyncio.create_task(worker._heartbeat_loop(task_id))
        await asyncio.sleep(0.05)
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass

        # 即使失败也不应崩溃, 循环应继续直到取消
        # 没有断言异常就是成功

    @pytest.mark.asyncio
    async def test_rejected_heartbeat_cancels_runner(self) -> None:
        """Clearing a deleted project's lease cancels and rolls back its runner."""
        from infrastructure.tasks.worker import TaskWorker

        task_id = uuid.uuid4()
        hb_session = AsyncMock()
        db_manager = MagicMock()
        db_manager.session_factory = MagicMock(return_value=AsyncMock())
        db_manager.session_factory.return_value.__aenter__ = AsyncMock(
            return_value=hb_session
        )
        db_manager.session_factory.return_value.__aexit__ = AsyncMock()
        runner = MagicMock()
        runner.done.return_value = False

        worker = TaskWorker(db_manager=db_manager, heartbeat_interval=0.001)
        worker._lifecycle.heartbeat = AsyncMock(return_value=False)
        worker._runner_tasks[task_id] = runner

        await worker._heartbeat_loop(task_id, "stale-lease")

        worker._lifecycle.heartbeat.assert_awaited_once_with(
            hb_session,
            task_id=task_id,
            lease_id="stale-lease",
        )
        runner.cancel.assert_called_once_with()


class TestTaskWorkerRecoverStale:
    """TaskWorker.recover_stale_tasks 单元测试"""

    @pytest.mark.asyncio
    async def test_recover_stale_tasks_marks_deep_import_recovery_required(
        self,
    ) -> None:
        """GREEN: stale deep_import 只标记可恢复，不自动改回 pending"""
        from infrastructure.tasks.worker import TaskWorker

        heartbeat_at = datetime(2026, 6, 30, 10, 0, tzinfo=UTC)
        task_mock = MagicMock()
        task_mock.task_type = "deep_import"
        task_mock.status = "running"
        task_mock.heartbeat_at = heartbeat_at
        task_mock.started_at = heartbeat_at
        task_mock.recovery_policy = "manual_resume"
        task_mock.attempt = 1
        task_mock.max_attempts = 1
        task_mock.lease_id = str(uuid.uuid4())
        task_mock.result = {
            "current_phase": "entity_extraction",
            "current_chapter": 7,
            "current_chapter_range": "1-12",
            "quality_stats": {
                "scene_commit": {"created_count": 9},
                "phase2": {"total_created": 14},
            },
            "checkpoints": {
                "phase2": {
                    "scenes": [
                        {"scene_id": "s1", "status": "succeeded"},
                        {"scene_id": "s2", "status": "failed"},
                        {"scene_id": "s3", "status": "running"},
                    ]
                }
            },
        }
        task_mock.meta = {"novel_id": "novel-1"}

        deep_import_result = MagicMock()
        deep_import_result.scalars.return_value.all.return_value = [task_mock]

        result_mock = MagicMock()
        result_mock.rowcount = 0

        db_session = AsyncMock()
        db_session.execute = AsyncMock(side_effect=[deep_import_result, result_mock])
        db_session.commit = AsyncMock()

        db_manager = MagicMock()
        db_manager.session_factory = MagicMock(return_value=AsyncMock())
        db_manager.session_factory.return_value.__aenter__ = AsyncMock(
            return_value=db_session
        )
        db_manager.session_factory.return_value.__aexit__ = AsyncMock()

        worker = TaskWorker(db_manager=db_manager)

        recovered = await worker.recover_stale_tasks()

        assert recovered == 0
        assert task_mock.status == "failed"
        assert task_mock.result["interrupted"] is True
        assert task_mock.result["recoverable"] is True
        assert task_mock.result["recovery_required"] is True
        assert task_mock.result["last_heartbeat_at"] == heartbeat_at.isoformat()
        assert task_mock.result["interrupted_at"]
        assert task_mock.result["lifecycle"]["reason"] == "heartbeat_timeout"
        assert task_mock.meta["interrupted"] is True
        assert task_mock.meta["recoverable"] is True
        assert task_mock.meta["recovery_required"] is True
        assert "interrupted" in task_mock.error_message.lower()
        db_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_recover_stale_tasks_keeps_non_deep_import_auto_recovery(
        self,
    ) -> None:
        """GREEN: 非 deep_import stale task 仍自动恢复为 pending"""
        from infrastructure.tasks.worker import TaskWorker

        deep_import_result = MagicMock()
        task_mock = MagicMock()
        task_mock.task_type = "rag_reindex_novel"
        task_mock.status = "running"
        task_mock.started_at = datetime(2026, 6, 30, 10, 0, tzinfo=UTC)
        task_mock.heartbeat_at = task_mock.started_at
        task_mock.recovery_policy = "auto_requeue"
        task_mock.attempt = 1
        task_mock.max_attempts = 2
        task_mock.lease_id = str(uuid.uuid4())
        task_mock.result = {}
        task_mock.meta = {"novel_id": "novel-1"}
        deep_import_result.scalars.return_value.all.return_value = [task_mock]

        result_mock = MagicMock()
        result_mock.rowcount = 1

        db_session = AsyncMock()
        db_session.execute = AsyncMock(side_effect=[deep_import_result, result_mock])
        db_session.commit = AsyncMock()

        db_manager = MagicMock()
        db_manager.session_factory = MagicMock(return_value=AsyncMock())
        db_manager.session_factory.return_value.__aenter__ = AsyncMock(
            return_value=db_session
        )
        db_manager.session_factory.return_value.__aexit__ = AsyncMock()

        worker = TaskWorker(db_manager=db_manager)

        recovered = await worker.recover_stale_tasks()
        assert recovered == 1
        assert task_mock.status == "pending"
        assert db_session.execute.await_count == 1

    @pytest.mark.asyncio
    async def test_recover_stale_tasks_rowcount_none(self) -> None:
        """GREEN: non-deep update rowcount 为 None 时返回 0"""
        from infrastructure.tasks.worker import TaskWorker

        deep_import_result = MagicMock()
        deep_import_result.scalars.return_value.all.return_value = []

        result_mock = MagicMock()
        result_mock.rowcount = None

        db_session = AsyncMock()
        db_session.execute = AsyncMock(side_effect=[deep_import_result, result_mock])
        db_session.commit = AsyncMock()

        db_manager = MagicMock()
        db_manager.session_factory = MagicMock(return_value=AsyncMock())
        db_manager.session_factory.return_value.__aenter__ = AsyncMock(
            return_value=db_session
        )
        db_manager.session_factory.return_value.__aexit__ = AsyncMock()

        worker = TaskWorker(db_manager=db_manager)

        recovered = await worker.recover_stale_tasks()
        assert recovered == 0

    @pytest.mark.asyncio
    async def test_recover_non_deep_import_update_excludes_deep_import(self) -> None:
        """GREEN: 自动 pending 恢复语句排除 deep_import"""
        from infrastructure.tasks.worker import TaskWorker

        deep_import_result = MagicMock()
        deep_import_result.scalars.return_value.all.return_value = []

        result_mock = MagicMock()
        result_mock.rowcount = 0

        db_session = AsyncMock()
        db_session.execute = AsyncMock(side_effect=[deep_import_result, result_mock])
        db_session.commit = AsyncMock()

        db_manager = MagicMock()
        db_manager.session_factory = MagicMock(return_value=AsyncMock())
        db_manager.session_factory.return_value.__aenter__ = AsyncMock(
            return_value=db_session
        )
        db_manager.session_factory.return_value.__aexit__ = AsyncMock()

        worker = TaskWorker(db_manager=db_manager)

        await worker.recover_stale_tasks()

        scan_stmt = db_session.execute.await_args_list[0].args[0]
        stmt_text = str(scan_stmt)
        assert "async_tasks.status = :status_1" in stmt_text
        assert "async_tasks.heartbeat_at" in stmt_text

    @pytest.mark.asyncio
    async def test_maybe_recover_stale_tasks_force_and_idle_interval(self) -> None:
        """GREEN: startup force 触发扫描，idle 未到间隔不重复，到间隔再扫描"""
        from infrastructure.tasks.worker import TaskWorker

        db_manager = MagicMock()
        worker = TaskWorker(db_manager=db_manager, poll_interval=2.0)
        worker.recover_stale_tasks = AsyncMock(return_value=0)

        with patch("infrastructure.tasks.worker.monotonic", return_value=10.0):
            await worker._maybe_recover_stale_tasks(force=True)

        with patch("infrastructure.tasks.worker.monotonic", return_value=11.0):
            await worker._maybe_recover_stale_tasks()

        with patch("infrastructure.tasks.worker.monotonic", return_value=12.1):
            await worker._maybe_recover_stale_tasks()

        assert worker.recover_stale_tasks.await_count == 2


class TestTaskWorkerRunOnce:
    """TaskWorker.run_once 单元测试"""

    @pytest.mark.asyncio
    async def test_run_once_with_task(self) -> None:
        """GREEN: run_once 正常领取并执行任务"""
        from infrastructure.tasks.worker import TaskWorker

        task_mock = MagicMock()
        task_mock.id = uuid.uuid4()
        task_mock.task_type = "test_type"
        task_mock.mark_running = MagicMock()
        task_mock.mark_done = MagicMock()

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = task_mock

        db_session = AsyncMock()
        db_session.execute = AsyncMock(return_value=result_mock)
        db_session.commit = AsyncMock()

        handler = AsyncMock(return_value={"ok": True})

        db_manager = MagicMock()
        db_manager.session_factory = MagicMock(return_value=AsyncMock())
        db_manager.session_factory.return_value.__aenter__ = AsyncMock(
            return_value=db_session
        )
        db_manager.session_factory.return_value.__aexit__ = AsyncMock()

        with patch.object(TaskWorker, "_heartbeat_loop", return_value=None):
            worker = TaskWorker(db_manager=db_manager)
            worker._registry.get_handler = MagicMock(return_value=handler)

            result = await worker.run_once()

        assert result is task_mock
        handler.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_once_no_task(self) -> None:
        """GREEN: 无 pending 任务时返回 None"""
        from infrastructure.tasks.worker import TaskWorker

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None

        db_session = AsyncMock()
        db_session.execute = AsyncMock(return_value=result_mock)

        db_manager = MagicMock()
        db_manager.session_factory = MagicMock(return_value=AsyncMock())
        db_manager.session_factory.return_value.__aenter__ = AsyncMock(
            return_value=db_session
        )
        db_manager.session_factory.return_value.__aexit__ = AsyncMock()

        worker = TaskWorker(db_manager=db_manager)

        result = await worker.run_once()
        assert result is None


class TestTaskWorkerRunForever:
    """TaskWorker.run_forever 并发调度测试"""

    @pytest.mark.asyncio
    async def test_run_forever_fills_concurrency_slots_and_waits_on_stop(self) -> None:
        """run_forever 按配置填满 in-flight 槽，stop 后等待任务自然完成。"""
        from infrastructure.tasks.worker import TaskWorker

        db_manager = MagicMock()
        worker = TaskWorker(db_manager=db_manager, poll_interval=0.01)
        worker._max_concurrent_tasks = 2

        created = 0
        active = 0
        max_active = 0
        both_started = asyncio.Event()
        release = asyncio.Event()

        async def fake_claim_task_runner():
            nonlocal created
            if created >= 2:
                return None
            created += 1

            async def runner() -> None:
                nonlocal active, max_active
                active += 1
                max_active = max(max_active, active)
                if active == 2:
                    both_started.set()
                    worker.stop()
                await release.wait()
                active -= 1

            return asyncio.create_task(runner())

        worker._claim_task_runner = AsyncMock(side_effect=fake_claim_task_runner)
        worker._maybe_recover_stale_tasks = AsyncMock(return_value=0)

        run_task = asyncio.create_task(worker.run_forever())
        await asyncio.wait_for(both_started.wait(), timeout=1.0)

        assert created == 2
        assert max_active == 2
        assert not run_task.done()

        release.set()
        await asyncio.wait_for(run_task, timeout=1.0)

        assert active == 0
